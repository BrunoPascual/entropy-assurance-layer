"""Gate do Dia 3: roda todas as fontes pelo HealthReport e grava a primeira tabela.

Protocolo (fixado antes de olhar resultados):
  - cada fonte é criada uma vez e lida READS vezes com N bits;
  - a faulty_replay ganha uma leitura extra de N_PREFIX bits (prefixo);
  - qpu_sim (ideal e com ruído) entra como controle, sem regra de gate;
  - a QPU real entra como linha "pendente" (coleta no Dia 6);
  - os bits crus de cada lote são salvos em data/raw/ ANTES da análise;
  - um único ReplayDetector vale para a execução inteira, na ordem abaixo.

Saídas (nunca sobrescreve):
  data/results/dia3_health_<data>_<hora>.csv        uma linha por lote, sem filtro
  data/results/dia3_health_<data>_<hora>.meta.json  versão, parâmetros, gate, SHA3 do CSV

O gate é avaliado LENDO O CSV DE VOLTA: o que aprova é o que está gravado.

Rodar na raiz do projeto: py -3.12 -m scripts.gate_dia3
"""
from __future__ import annotations

import csv
import hashlib
import inspect
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import scipy

from eal import config
from eal.health.replay import ReplayDetector
from eal.health.report import build_health_report

READS = 2
N = 1_000_000
N_PREFIX = 4096 * 100  # 409.600 bits: prefixo do lote guardado, múltiplo de bloco
SESSION = "dia3"
RESULTS_DIR = Path("data") / "results"

META_COLS = [
    "run_index", "status", "source_id", "variant", "read_index", "n_bits_requested",
    "is_local", "is_simulated", "seed", "raw_file", "read_seconds", "error",
]
REPORT_COLS = [
    "schema", "batch_id", "n_bits", "h_declared",
    "rct_pass", "rct_cutoff", "rct_max_run", "rct_max_run_start", "rct_alpha_neg_log2",
    "apt_pass", "apt_inconclusive", "apt_cutoff", "apt_max_count", "apt_n_windows",
    "apt_n_failed_windows", "apt_discarded_bits", "apt_alpha_neg_log2",
    "replay_pass", "replay_history_batches", "replay_n_blocks", "replay_repeated_blocks",
    "replay_batch_repeated",
    "h_bit", "h_byte", "h_estimated", "h_limited_by", "h_threshold", "h_health_pass",
    "stats_monobit", "stats_block", "stats_runs", "stats_pass", "stats_inconclusive",
    "approved", "reasons", "notes",
]
COLUMNS = META_COLS + REPORT_COLS
CONFIG_NAMES = [
    "RCT_ALPHA_NEG_LOG2", "APT_ALPHA_NEG_LOG2", "APT_WINDOW_BITS", "MCV_Z",
    "MCV_SYMBOL_BITS", "H_MIN_HEALTH", "STATS_P_MIN", "STATS_BLOCK_M",
    "STATS_MIN_BITS", "REPLAY_BLOCK_BITS", "H_DECLARED_DEFAULT",
]


# ---------- linhas da tabela (funções puras, testadas) ----------

def _cell(value: Any) -> str:
    """Converte para texto de CSV: None vira vazio; float com precisão total."""
    if value is None:
        return ""
    return repr(value) if isinstance(value, float) else str(value)


def report_row(meta: dict[str, Any], report_dict: dict[str, Any]) -> dict[str, str]:
    """Linha de um lote avaliado. Falha se o relatório tiver campo sem coluna."""
    d = dict(report_dict)
    stats = d.pop("stats")
    source_id = d.pop("source_id")
    d["stats_monobit"] = stats["monobit"]
    d["stats_block"] = stats["block"]
    d["stats_runs"] = stats["runs"]
    d["reasons"] = " | ".join(d["reasons"])
    d["notes"] = " | ".join(d["notes"])
    unknown = set(d) - set(REPORT_COLS)
    if unknown:
        raise ValueError(f"campos do HealthReport sem coluna na tabela: {sorted(unknown)}")
    row = {c: "" for c in COLUMNS}
    row.update({k: _cell(v) for k, v in meta.items()})
    row.update({k: _cell(v) for k, v in d.items()})
    row["status"] = "avaliado"
    row["source_id"] = source_id
    return row


def other_row(meta: dict[str, Any], status: str, error: str = "") -> dict[str, str]:
    """Linha sem relatório: 'pendente' (não coletada) ou 'erro'."""
    if status not in ("pendente", "erro"):
        raise ValueError("status deve ser 'pendente' ou 'erro'")
    row = {c: "" for c in COLUMNS}
    row.update({k: _cell(v) for k, v in meta.items()})
    row["status"] = status
    row["error"] = error
    return row


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Grava a tabela; nunca sobrescreve (modo 'x')."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    """Lê a tabela de volta, como texto."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------- gate (lido do CSV) ----------

@dataclass(frozen=True)
class GateCheck:
    rule: str
    ok: bool
    detail: str


def _rows(rows: list[dict[str, str]], source_id: str) -> list[dict[str, str]]:
    return [r for r in rows if r["source_id"] == source_id and r["variant"] == ""]


def _all_evaluated(rs: list[dict[str, str]], minimum: int) -> str | None:
    """Motivo de falha se faltam linhas ou há erro; None se ok."""
    if any(r["status"] != "avaliado" for r in rs):
        return "há linha com erro ou não avaliada"
    if len(rs) < minimum:
        return f"esperadas ao menos {minimum} leituras, encontradas {len(rs)}"
    return None


def evaluate_gate(rows: list[dict[str, str]], reads: int = READS) -> list[GateCheck]:
    """Regras do gate do Dia 3. Falta de evidência conta como falha (fail-closed)."""
    t = "True"
    checks: list[GateCheck] = []

    def rule(name: str, source: str, minimum: int, cond: Callable[[list], bool], expect: str):
        rs = _rows(rows, source)
        problem = _all_evaluated(rs, minimum)
        if problem:
            checks.append(GateCheck(name, False, problem))
        else:
            ok = cond(rs)
            checks.append(GateCheck(name, ok, expect if ok else f"NÃO ocorreu: {expect}"))

    rule("os aprovada", "os", reads,
         lambda rs: all(r["approved"] == t for r in rs),
         "todas as leituras aprovadas")
    rule("faulty_biased reprovada", "faulty_biased", reads,
         lambda rs: all(r["approved"] != t and r["apt_pass"] != t and r["h_health_pass"] != t
                        for r in rs),
         "todas reprovadas, com APT e limiar de H falhando")
    rule("faulty_stuck reprovada", "faulty_stuck", reads,
         lambda rs: all(r["approved"] != t and r["rct_pass"] != t for r in rs),
         "todas reprovadas, com RCT falhando")
    rule("faulty_correlated reprovada", "faulty_correlated", reads,
         lambda rs: all(r["approved"] != t and r["h_health_pass"] != t for r in rs),
         "todas reprovadas, com limiar de H falhando")

    def replay_ok(rs: list) -> bool:
        first, later = rs[0], rs[1:]
        only_replay = all(
            r["replay_pass"] != t and r["approved"] != t for r in later
        ) and all(
            r["rct_pass"] == t and r["apt_pass"] == t and r["h_health_pass"] == t
            and r["stats_pass"] == t
            for r in later if r["n_bits_requested"] == str(N)
        )
        return first["approved"] == t and first["replay_pass"] == t and only_replay

    rule("faulty_replay pega por replay", "faulty_replay", reads + 1, replay_ok,
         "1ª leitura aprovada; seguintes reprovadas por replay (só por replay se tiverem N bits)")
    rule("faulty_prng passa (limitação T4)", "faulty_prng", reads,
         lambda rs: all(r["approved"] == t for r in rs),
         "todas aprovadas: testes de saída não detectam gerador clássico")
    return checks


# ---------- execução (depende das fontes do projeto) ----------

def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else "desconhecido"
    except Exception:
        return "desconhecido"


def _preflight() -> tuple[Callable, Callable]:
    """Confere a assinatura do storage antes de gravar qualquer coisa."""
    from eal import storage

    for name in ("save_batch", "load_batch"):
        if not hasattr(storage, name):
            sys.exit(f"PARADO: eal.storage não tem {name}. Cole o conteúdo de eal\\storage.py.")
    sig = inspect.signature(storage.save_batch)
    params = list(sig.parameters.values())
    required = [p.name for p in params[1:]
                if p.default is inspect.Parameter.empty
                and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
    if "session" not in sig.parameters or set(required) - {"session"}:
        sys.exit(f"PARADO antes de gravar: assinatura inesperada save_batch{sig}. "
                 "Cole esta linha na conversa para ajustar o script.")
    return storage.save_batch, storage.load_batch


def _save_raw(save: Callable, load: Callable, batch: Any) -> str:
    """Salva os bits crus e relê, conferindo o hash. Devolve o caminho do .npy."""
    result = save(batch, session=SESSION)
    candidates = list(result) if isinstance(result, (tuple, list)) else [result]
    paths = [Path(str(c)) for c in candidates if str(c).endswith(".npy")]
    if not paths:
        raise RuntimeError(f"save_batch não devolveu um caminho .npy: {result!r}")
    reloaded = load(paths[0])
    if getattr(reloaded, "batch_hash", None) != batch.batch_hash:
        raise RuntimeError("lote relido do disco com hash diferente")
    return str(paths[0])


def _sources() -> list[tuple[str, str, Callable[[], Any]]]:
    """(source_id, variante, fábrica) na ordem do protocolo."""
    from eal.sources.faulty import FAULTY_SOURCES
    from eal.sources.os_source import OsSource

    out: list[tuple[str, str, Callable[[], Any]]] = [("os", "", OsSource)]
    try:
        from eal.sources.qpu_sim import QpuSim

        out.append(("qpu_sim", "ideal (controle)", QpuSim))
        if "noise_backend" in inspect.signature(QpuSim).parameters:
            from eal.sources.noise import load_fake_backend

            out.append(("qpu_sim", "ruído FakeKingston (controle)",
                        lambda: QpuSim(noise_backend="FakeKingston")))
    except ImportError as exc:
        print(f"aviso: qpu_sim não importado ({exc}); segue sem ele")
    out += [(name, "", fabrica) for name, fabrica in sorted(FAULTY_SOURCES.items())]
    return out


def main() -> int:
    save, load = _preflight()
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y-%m-%d_%H%M%S")
    csv_path = RESULTS_DIR / f"dia3_health_{stamp}.csv"
    meta_path = RESULTS_DIR / f"dia3_health_{stamp}.meta.json"
    if csv_path.exists() or meta_path.exists():
        sys.exit(f"PARADO: {csv_path} já existe")

    detector = ReplayDetector()
    rows: list[dict[str, str]] = []
    run_index = 0
    for source_id, variant, factory in _sources():
        sizes = [N] * READS + ([N_PREFIX] if source_id == "faulty_replay" else [])
        try:
            source = factory()
        except Exception as exc:
            run_index += 1
            rows.append(other_row({"run_index": run_index, "source_id": source_id,
                                   "variant": variant}, "erro", f"{type(exc).__name__}: {exc}"))
            continue
        for read_index, n in enumerate(sizes, start=1):
            run_index += 1
            meta = {"run_index": run_index, "source_id": source_id, "variant": variant,
                    "read_index": read_index, "n_bits_requested": n}
            try:
                t0 = time.perf_counter()
                batch = source.read(n)
                meta["read_seconds"] = round(time.perf_counter() - t0, 3)
                meta["is_local"] = getattr(batch, "is_local", None)
                meta["is_simulated"] = getattr(batch, "is_simulated", None)
                meta["seed"] = (getattr(batch, "params", None) or {}).get("seed")
                meta["raw_file"] = _save_raw(save, load, batch)  # salvo ANTES da análise
                report = build_health_report(batch, detector)
                rows.append(report_row(meta, report.to_dict()))
                verdict = "APROVADO" if report.approved else "REPROVADO"
                label = f"{source_id}" + (f" [{variant}]" if variant else "")
                print(f"{run_index:>2}. {label} leitura {read_index}: {verdict}"
                      f" ({len(report.reasons)} motivo(s))")
            except Exception as exc:
                rows.append(other_row(meta, "erro", f"{type(exc).__name__}: {exc}"))
                print(f"{run_index:>2}. {source_id} leitura {read_index}: ERRO {exc}")

    run_index += 1
    rows.append(other_row({"run_index": run_index, "source_id": "ibm_<backend>",
                           "variant": "QPU real"}, "pendente",
                          "não coletada no Dia 3; coleta prevista para o Dia 6"))

    write_csv(csv_path, rows)
    back = read_csv(csv_path)  # o gate usa o que foi gravado
    checks = evaluate_gate(back)
    gate_ok = all(c.ok for c in checks)
    controls_failed = [
        (r["source_id"] + " " + r.get("variant", "")).strip()
        for r in rows
        if r.get("source_id") == "qpu_sim" and r.get("status") != "avaliado"
    ]
    if controls_failed:
        gate_ok = False
        print("CONTROLE FALHOU (gate reprovado): " + "; ".join(controls_failed))

    meta = {
        "format": "eal-dia3-health-table-v1",
        "created_at": started.isoformat().replace("+00:00", "Z"),
        "csv_file": csv_path.name,
        "csv_sha3_256": hashlib.sha3_256(csv_path.read_bytes()).hexdigest(),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_dirty": _git("status", "--porcelain", "--untracked-files=no") not in ("", "desconhecido"),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "config": {name: getattr(config, name, None) for name in CONFIG_NAMES},
        "protocol": {"reads": READS, "n_bits": N, "n_prefix_replay": N_PREFIX,
                     "session": SESSION, "replay_detector": "um por execução",
                     "order": [f"{s}{' [' + v + ']' if v else ''}" for s, v, _ in _sources()]},
        "gate": {"approved": gate_ok,
                 "checks": [{"rule": c.rule, "ok": c.ok, "detail": c.detail} for c in checks]},
        "limitations": ["prototype", "no_sp800_90b_claim", "faulty_prng_passes_T4",
                        "os_false_alarm_about_3pct_per_batch", "qpu_real_not_collected"],
    }
    with open(meta_path, "x", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("\nGate do Dia 3 (lido do CSV):")
    for c in checks:
        print(f"  [{'ok' if c.ok else 'FALHA'}] {c.rule}: {c.detail}")
    print(f"\nGATE DIA 3: {'APROVADO' if gate_ok else 'NÃO APROVADO'}")
    print(f"Tabela: {csv_path}\nMetadados: {meta_path}")
    if meta["git_dirty"]:
        print("Aviso: havia mudanças sem commit; o git_commit não descreve o código exato.")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
