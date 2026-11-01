"""Dia 6: pipeline nos dados reais da coleta 1, comparado ao simulador e à fonte os.

Só lê os dados. Não gasta QPU, não toca em data/logs, data/receipts nem keys, e nunca grava
bit nem semente. O detector de replay vive só em memória.

Passos (qualquer falha recusa e não grava nada):

1. Carrega os lotes da sessão ``coleta1`` listados no inventário. Confere o SHA-256 do ``.npy``
   e do ``.json`` (bytes do arquivo, a mesma conta de ``inventario_coleta1.py``), o
   ``batch_hash`` (via ``eal.storage.load_batch``) e a coerência com os params.
2. Gera, com a mesma forma (qubits, bits por lote, quantidade de lotes), lotes do ``qpu_sim``
   com ruído do FakeKingston e da fonte ``os``.
3. Para cada fonte: ``build_health_report`` com um detector novo por fonte (compartilhado entre
   os lotes dela) e ``run_pipeline(mode="experiment")`` com detector novo por lote, só para ler
   o rendimento do extrator (``ExtractionResult.to_dict()``, sem ``seed_hash``).
4. Por lote e por posição de qubit: fração de 1, z em relação a 0,5, correlação com a posição
   vizinha no mesmo shot e com o shot seguinte no mesmo qubit.

Saídas (não sobrescreve; recusa se qualquer uma já existir):
    data/results/dia6_qpu_vs_sim_lotes.csv       uma linha por fonte e lote
    data/results/dia6_qpu_vs_sim_por_qubit.csv   uma linha por fonte, lote e posição

Uso (na raiz do projeto):
    py -3.12 scripts\\analisar_coleta1.py
    py -3.12 scripts\\analisar_coleta1.py --sessao coleta2
Com ``--sessao`` diferente de ``coleta1``, o inventário padrão é
``data/results/dia6_<sessao>_inventario.csv`` e as saídas ganham o prefixo ``dia6_<sessao>_``.
Na QPU real, o erro de leitura é o retrato da execução (R8) quando o lote o tem; senão, o do
envio.
Código de saída: 0 gravado; 1 recusado ou erro (nada foi gravado); 2 erro de uso.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eal.config import H_DECLARED_DEFAULT  # noqa: E402
from eal.health.replay import ReplayDetector  # noqa: E402
from eal.health.report import build_health_report  # noqa: E402
from eal.pipeline import run_pipeline  # noqa: E402
from eal.sources.ibm_bits import BIT_ORDER  # noqa: E402
from eal.sources.os_source import OsSource  # noqa: E402
from eal.sources.qpu_sim import QpuSim  # noqa: E402
from eal.storage import load_batch  # noqa: E402

SESSION = "coleta1"
RAW_DIR = Path("data/raw")
INVENTORY_PATH = Path("data/results/dia6_coleta1_inventario.csv")
OUT_DIR = Path("data/results")
LOTS_NAME = "dia6_qpu_vs_sim_lotes.csv"
QUBIT_NAME = "dia6_qpu_vs_sim_por_qubit.csv"
SESSION_RE = re.compile(r"[A-Za-z0-9]+")
SIM_SEED = 12345
SIM_NOISE = "FakeKingston"
REAL, SIM, OS = "qpu_real", "simulador", "os"
INVENTORY_COLUMNS = ("arquivo", "job_id", "qubits", "shots", "n_bits", "npy_sha256", "json_sha256")


class AnalysisError(Exception):
    """Recusa: nada foi gravado."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_session(session: str) -> str:
    """Só letras e dígitos: entra num glob e em nomes de arquivo, e ``_`` separa o rótulo."""
    if not isinstance(session, str) or not SESSION_RE.fullmatch(session):
        raise AnalysisError(f"sessão inválida: {session!r}")
    return session


def session_file(name: str, session: str) -> str:
    """``coleta1`` mantém o nome de sempre; outra sessão ganha o prefixo ``dia6_<sessao>_``."""
    if session == SESSION:
        return name
    return name.replace("dia6_", f"dia6_{session}_", 1)


def inventory_for(session: str) -> Path:
    """Inventário de uma sessão (o mesmo nome que ``inventario_coleta1.py --sessao`` grava)."""
    return Path(f"data/results/dia6_{session}_inventario.csv")


def readout_of(params: dict[str, Any]) -> Any:
    """Erro de leitura por posição: o da execução (R8) se o lote tiver; senão, o do envio."""
    run = params.get("readout_error_run_by_position")
    return run if run is not None else params.get("readout_error_by_position")


# ---------------------------------------------------------------- carga e conferência

def _read_inventory(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise AnalysisError(f"inventário não encontrado: {path}")
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in INVENTORY_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise AnalysisError(f"inventário sem as colunas {missing}")
        rows = list(reader)
    if not rows:
        raise AnalysisError("inventário vazio")
    return rows


def _check_real(batch: Any, row: dict[str, str]) -> None:
    name = row["arquivo"]
    p = batch.params
    try:
        shots, qubits, n_bits = int(row["shots"]), int(row["qubits"]), int(row["n_bits"])
    except ValueError:
        raise AnalysisError(f"{name}: shots, qubits ou n_bits do inventário não são inteiros")
    if batch.is_local is not False or batch.is_simulated is not False:
        raise AnalysisError(f"{name}: lote não é real (is_local/is_simulated)")
    if p.get("job_id") != row["job_id"]:
        raise AnalysisError(f"{name}: job_id dos params difere do inventário")
    if (p.get("shots"), p.get("qubits")) != (shots, qubits):
        raise AnalysisError(f"{name}: shots ou qubits dos params diferem do inventário")
    if not (batch.n_bits == n_bits == shots * qubits):
        raise AnalysisError(f"{name}: n_bits diferente de shots x qubits")
    if len(p.get("physical_qubits") or []) != qubits:
        raise AnalysisError(f"{name}: mapa de qubits com tamanho diferente de qubits")
    if p.get("bit_order") != BIT_ORDER:
        raise AnalysisError(f"{name}: bit_order inesperado")
    if p.get("discarded_bits") != 0:
        raise AnalysisError(f"{name}: há bits descartados; a matriz shots x qubits não fecha")


def load_real(raw_dir: Path, inventory_path: Path, session: str = SESSION) -> list[Any]:
    """Carrega e confere os lotes reais do inventário; levanta AnalysisError."""
    rows = sorted(_read_inventory(inventory_path), key=lambda r: r["arquivo"])
    found = sorted(p.name for p in raw_dir.glob(f"*_{session}_*.json"))
    expected = [r["arquivo"] for r in rows]
    if found != expected:
        raise AnalysisError(f"lotes em {raw_dir} diferem do inventário: {found} != {expected}")
    batches = []
    for row in rows:
        meta = raw_dir / row["arquivo"]
        npy = meta.with_suffix(".npy")
        if not npy.exists():
            raise AnalysisError(f"{row['arquivo']}: falta o .npy")
        if _sha256(npy.read_bytes()) != row["npy_sha256"]:
            raise AnalysisError(f"{npy.name}: sha256 do .npy difere do inventário")
        if _sha256(meta.read_bytes()) != row["json_sha256"]:
            raise AnalysisError(f"{meta.name}: sha256 do .json difere do inventário")
        try:
            batch = load_batch(npy)
        except (ValueError, KeyError, OSError) as exc:
            raise AnalysisError(f"{npy.name}: {type(exc).__name__}: {exc}") from exc
        _check_real(batch, row)
        batches.append(batch)
    first = batches[0].params
    for b in batches[1:]:
        if (b.n_bits, b.params["qubits"], b.params["physical_qubits"]) != (
                batches[0].n_bits, first["qubits"], first["physical_qubits"]):
            raise AnalysisError("lotes reais com forma ou mapa de qubits diferentes entre si")
    _check_distinct(batches)
    return batches


def _check_distinct(batches: list[Any]) -> None:
    hashes = [b.batch_hash for b in batches]
    if len(set(hashes)) != len(hashes):
        raise AnalysisError("lote repetido (batch_hash igual)")


# ---------------------------------------------------------------- métricas por qubit

def qubit_metrics(bits: np.ndarray, n_qubits: int) -> dict[str, np.ndarray]:
    """Métricas por posição. ``bits`` é shot-major: posição i do shot = coluna i.

    ``corr_vizinho[i]`` correlaciona as colunas i e i+1 (a última fica NaN). ``corr_prox_shot[i]``
    correlaciona a coluna i com ela mesma no shot seguinte (média e desvio da coluna inteira).
    NaN onde o desvio é zero.
    """
    if n_qubits <= 0 or bits.size % n_qubits != 0:
        raise AnalysisError("n_bits não é múltiplo de qubits")
    shots = bits.size // n_qubits
    if shots < 3:
        raise AnalysisError("poucos shots para calcular correlação")
    x = bits.reshape(shots, n_qubits).astype(np.float64)
    p1 = x.mean(axis=0)
    xc = x - p1
    std = xc.std(axis=0)
    z = (p1 - 0.5) / math.sqrt(0.25 / shots)
    nb = np.full(n_qubits, np.nan)
    if n_qubits > 1:
        den = std[:-1] * std[1:]
        cov = (xc[:, :-1] * xc[:, 1:]).mean(axis=0)
        nb[:-1] = np.where(den > 0, cov / np.where(den > 0, den, 1.0), np.nan)
    den_s = std * std
    cov_s = (xc[:-1] * xc[1:]).mean(axis=0)
    sh = np.where(den_s > 0, cov_s / np.where(den_s > 0, den_s, 1.0), np.nan)
    return {"p1": p1, "z_p1": z, "corr_vizinho": nb, "corr_prox_shot": sh, "n_shots": shots}


# ---------------------------------------------------------------- achatamento e CSV

def flatten(prefix: str, value: Any) -> dict[str, Any]:
    """Achata dict/lista em colunas escalares ``prefixo_chave``; None vira texto vazio."""
    out: dict[str, Any] = {}

    def walk(key: str, v: Any) -> None:
        if isinstance(v, dict):
            for k, sub in v.items():
                walk(f"{key}_{k}", sub)
        elif isinstance(v, (list, tuple)):
            out[key] = " | ".join(str(x) for x in v)
        elif v is None:
            out[key] = ""
        elif isinstance(v, (bool, int, float, str)):
            out[key] = v
        elif isinstance(v, np.generic):
            out[key] = v.item()
        else:
            out[key] = str(v)

    walk(prefix, value)
    return out


def _cell(v: Any) -> str:
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        return "" if math.isnan(v) else f"{v:.12g}"
    return str(v)


def csv_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        raise AnalysisError("nenhuma linha para gravar")
    cols = list(rows[0])
    for r in rows:
        if set(r) != set(cols):
            raise AnalysisError("linhas com colunas diferentes")
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(cols)
    for r in rows:
        writer.writerow([_cell(r[c]) for c in cols])
    return buf.getvalue()


def _targets(out_dir: Path, session: str = SESSION) -> list[Path]:
    return [out_dir / session_file(LOTS_NAME, session),
            out_dir / session_file(QUBIT_NAME, session)]


def check_targets(out_dir: Path, session: str = SESSION) -> None:
    for t in _targets(out_dir, session):
        if t.exists() or t.with_name(t.name + ".tmp").exists():
            raise AnalysisError(f"já existe, não sobrescrevo: {t}")


def write_outputs(out_dir: Path, lots_text: str, qubit_text: str,
                  session: str = SESSION) -> list[Path]:
    """Grava os dois CSVs, tudo ou nada (temporário e depois o nome final)."""
    check_targets(out_dir, session)
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = _targets(out_dir, session)
    tmps = [t.with_name(t.name + ".tmp") for t in targets]
    try:
        for tmp, text in zip(tmps, (lots_text, qubit_text)):
            with open(tmp, "x", encoding="utf-8", newline="") as fh:
                fh.write(text)
    except BaseException:
        for tmp in tmps:
            tmp.unlink(missing_ok=True)
        raise
    for tmp, target in zip(tmps, targets):
        os.rename(tmp, target)
    return targets


# ---------------------------------------------------------------- análise por fonte

class _Fixed:
    """Fonte-envelope: devolve o lote já carregado, para o pipeline analisar os mesmos bits."""

    def __init__(self, batch: Any) -> None:
        self.batch = batch
        self.source_id = batch.source_id

    def read(self, n_bits: int) -> Any:
        if n_bits != self.batch.n_bits:
            raise ValueError("n_bits diferente do lote")
        return self.batch


def _pipeline_columns(batch: Any, seed_source: Any, pipeline_fn: Callable[..., Any]) -> dict[str, Any]:
    """Roda o pipeline (modo experiment) e devolve só metadados; a semente nunca é lida."""
    res = pipeline_fn([_Fixed(batch)], seed_source, mode="experiment", n_bits=batch.n_bits,
                      h_declared=H_DECLARED_DEFAULT, detector=ReplayDetector())
    if not res.inputs:
        reasons = "; ".join(r for o in res.outcomes for r in o.reasons)
        raise AnalysisError(f"pipeline sem extração para {batch.source_id}: {reasons}")
    outcome = res.outcomes[0]
    ext = res.inputs[0].extraction.to_dict()
    ext.pop("seed_hash", None)
    cols: dict[str, Any] = {
        "pipe_status": outcome.status,
        "pipe_reasons": " | ".join(outcome.reasons),
        "pipe_error": res.error or "",
        "pipe_seed_generated": bool(res.seed_generated),
    }
    cols.update(flatten("ext", ext))
    cols["ext_rendimento"] = ext["n_output_bits"] / batch.n_bits
    return cols


def analyze_source(label: str, batches: list[Any], *, physical: list[int], use_readout: bool,
                   os_factory: Callable[[], Any],
                   health_fn: Callable[..., Any] = build_health_report,
                   pipeline_fn: Callable[..., Any] = run_pipeline,
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Linhas por lote e por posição de qubit de uma fonte (2 ou mais lotes)."""
    n_qubits = len(physical)
    detector = ReplayDetector()
    seed_source = os_factory()
    lot_rows: list[dict[str, Any]] = []
    qubit_rows: list[dict[str, Any]] = []
    for i, b in enumerate(batches, 1):
        report = health_fn(b, detector, H_DECLARED_DEFAULT)
        row: dict[str, Any] = {
            "fonte": label, "lote": i, "source_id": b.source_id,
            "is_simulated": b.is_simulated, "n_bits": b.n_bits, "batch_hash": b.batch_hash,
        }
        row.update(flatten("saude", report.to_dict()))
        row.update(_pipeline_columns(b, seed_source, pipeline_fn))
        lot_rows.append(row)
        m = qubit_metrics(b.bits, n_qubits)
        readout = readout_of(b.params) if use_readout else None
        for pos in range(n_qubits):
            err = readout[pos] if readout else None
            qubit_rows.append({
                "fonte": label, "lote": i, "posicao": pos, "qubit_fisico": physical[pos],
                "n_shots": m["n_shots"], "p1": float(m["p1"][pos]), "z_p1": float(m["z_p1"][pos]),
                "corr_vizinho": float(m["corr_vizinho"][pos]),
                "corr_prox_shot": float(m["corr_prox_shot"][pos]),
                "erro_leitura": "" if err is None else float(err),
            })
    return lot_rows, qubit_rows


def _default_sim(n_qubits: int, seed: int, physical: list[int]) -> Any:
    return QpuSim(n_qubits=n_qubits, seed=seed, noise_backend=SIM_NOISE, physical_qubits=physical)


def run(raw_dir: Path, inventory: Path, out_dir: Path, sim_seed: int, *,
        sim_factory: Callable[..., Any] | None = None,
        os_factory: Callable[[], Any] | None = None,
        session: str = SESSION) -> list[dict[str, Any]]:
    session = check_session(session)
    sim_factory = sim_factory or _default_sim
    os_factory = os_factory or OsSource
    check_targets(out_dir, session)  # falha cedo, antes de simular
    real = load_real(raw_dir, inventory, session)
    physical = [int(q) for q in real[0].params["physical_qubits"]]
    n_qubits, n_bits = int(real[0].params["qubits"]), real[0].n_bits
    sim = sim_factory(n_qubits, sim_seed, physical)
    sim_batches = [sim.read(n_bits) for _ in real]
    os_src = os_factory()
    os_batches = [os_src.read(n_bits) for _ in real]
    for b in sim_batches + os_batches:
        if b.n_bits != n_bits:
            raise AnalysisError("lote de referência com n_bits diferente do real")
    _check_distinct(real + sim_batches + os_batches)
    lots: list[dict[str, Any]] = []
    qubits: list[dict[str, Any]] = []
    for label, batches, readout in ((REAL, real, True), (SIM, sim_batches, False),
                                    (OS, os_batches, False)):
        lr, qr = analyze_source(label, batches, physical=physical, use_readout=readout,
                                os_factory=os_factory)
        lots += lr
        qubits += qr
    lots_text, qubit_text = csv_text(lots), csv_text(qubits)
    paths = write_outputs(out_dir, lots_text, qubit_text, session)
    print(f"gravado: {paths[0]} ({len(lots)} linhas)")
    print(f"gravado: {paths[1]} ({len(qubits)} linhas)")
    return lots


def main(argv: list[str] | None = None, *, sim_factory: Callable[..., Any] | None = None,
         os_factory: Callable[[], Any] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dia 6: coleta 1 vs simulador vs os (só leitura)")
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--sessao", default=SESSION)
    ap.add_argument("--inventario", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--sim-seed", type=int, default=SIM_SEED)
    args = ap.parse_args(argv)
    try:
        session = check_session(args.sessao)
        inventory = args.inventario or inventory_for(session)
        lots = run(args.raw_dir, inventory, args.out_dir, args.sim_seed,
                   sim_factory=sim_factory, os_factory=os_factory, session=session)
    except AnalysisError as exc:
        print(f"RECUSADO: {exc}")
        return 1
    except Exception as exc:  # texto de exceção não é impresso, só a classe
        print(f"erro inesperado: {type(exc).__name__}")
        return 1
    for r in lots:
        print(f"{r['fonte']} lote {r['lote']}: aprovado={r.get('saude_approved', '?')} "
              f"h_estimada={r.get('saude_h_estimated', '?')} "
              f"bits_extraidos={r.get('ext_n_output_bits', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
