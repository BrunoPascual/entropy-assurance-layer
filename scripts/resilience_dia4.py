"""Dia 4, etapa 4: teste de resiliência e gate do Dia 4.

Uso (a partir da raiz do projeto):
    py -3.12 -m scripts.resilience_dia4 [--reps 5] [--bits 1000000] [--noise-backend FakeKingston]

Roda o pipeline (eal/pipeline.py) com as fontes reais em nove cenários e grava
data/results/dia4_resilience_<ts>.csv (uma linha por execução) e .meta.json.
Nunca sobrescreve. Nenhum bit e nenhuma semente são gravados ou impressos; só o
SHA3-256 da semente (`seed_hash`), como no recibo.

Cenários. Em `experiment` (as faulty_* são simuladas e o mixer as recusa em keygen):
  BASE, BASE_NOISE   os + qpu_sim (ideal / com ruído): o gate do Dia 4
  C1                 os + faulty_stuck
  C2                 os + faulty_biased + faulty_correlated
  C3                 os + faulty_replay, duas passagens com o mesmo detector
  C5c                a os falha, sobra só a qpu_sim: em experiment sai semente, marcada inutilizável
  C6                 os + faulty_prng (passa nos testes: limitação T4)
Em `keygen` (chave real; "remota" é um STAND-IN: bits da os com rótulo de fonte remota não
simulada, no papel da QPU da IBM; não é a QPU):
  K1                 os + remota no ar: as duas entram, semente utilizável
  C4                 os + remota fora do ar: semente só da os (T16)
  C5a, C5b           a própria os falha (leitura / adulterada) e a remota está no ar:
                     nenhuma semente (G2: o provedor sozinho nunca gera chave)

Vereditos por execução:
  ok                  os mista, semente gerada, fontes ruins fora, semente = semente sem elas
  ok_fail_closed      a os não entrou (falha ou reprovação) e nenhuma semente foi gerada
  ok_experiment_only  a os não entrou, mas em `experiment` uma fonte local simulada bastou: semente
                      gerada e marcada usable_for_key = False (permitido pelo mixer)
  DETECTION_MISS      uma fonte defeituosa passou nos testes e entrou (assunto do E2, não do pipeline)
  UNEXPECTED          uma fonte que deveria entrar (ex.: faulty_prng, 1ª leitura do replay) não entrou
  VIOLATION           política ou isolamento do pipeline quebrados (semente em keygen sem fonte local
                      não simulada aprovada, semente que difere da semente sem as fontes ruins,
                      usable_for_key incoerente com o modo)

Gate do Dia 4: nenhuma VIOLATION em nenhuma execução E, nas execuções BASE em que a os foi
aprovada, semente de 64 bytes gerada com usable_for_key = False (e pelo menos uma assim).
Falso alarme da os (~3% por lote) aparece como ok_fail_closed e é contado à parte.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from eal.mix.mixer import mix
from eal.pipeline import DEFAULT_N_BITS, PipelineResult, run_pipeline

RESULTS_DIR = Path("data/results")
DEFAULT_REPS = 5
DEFAULT_NOISE_BACKEND = "FakeKingston"
TAMPER_START, TAMPER_LENGTH = 1000, 100  # trecho de zeros no lote da os do C5b (RCT pega 41+)
REASON_LIMIT = 200
Factory = Callable[[int], Any]

CSV_FIELDS = [
    "scenario", "rep", "mode", "n_bits", "os_status", "os_expected_to_fail", "seed_generated",
    "usable_for_key", "statuses", "mixed", "not_mixed_reasons", "must_exclude", "seed_equals_without_bad",
    "seed_hash", "error", "verdict",
]


# ------------------------------------------------------------ catálogo e cenários


@dataclass(frozen=True)
class Catalog:
    """Fábricas de fontes: cada uma recebe o número da repetição. `detector` cria um ReplayDetector."""

    os: Factory
    qpu_ideal: Factory
    qpu_noise: Factory
    biased: Factory
    stuck: Factory
    correlated: Factory
    replay: Factory
    prng: Factory
    os_down: Factory
    os_tampered: Factory
    remote_up: Factory
    remote_down: Factory
    detector: Callable[[], Any]


@dataclass(frozen=True)
class PassSpec:
    """O que se espera de uma passagem do pipeline."""

    label: str = ""
    must_exclude: tuple[str, ...] = ()
    expect_mixed: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    name: str
    mode: str
    build: Callable[[Catalog, int], list[Any]]
    passes: tuple[PassSpec, ...] = (PassSpec(),)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("BASE", "experiment", lambda c, r: [c.os(r), c.qpu_ideal(r)]),
    Scenario("BASE_NOISE", "experiment", lambda c, r: [c.os(r), c.qpu_noise(r)]),
    Scenario("C1_stuck", "experiment", lambda c, r: [c.os(r), c.stuck(r)],
             (PassSpec(must_exclude=("faulty_stuck",)),)),
    Scenario("C2_biased_correlated", "experiment", lambda c, r: [c.os(r), c.biased(r), c.correlated(r)],
             (PassSpec(must_exclude=("faulty_biased", "faulty_correlated")),)),
    Scenario("C3_replay", "experiment", lambda c, r: [c.os(r), c.replay(r)],
             (PassSpec("first", expect_mixed=("faulty_replay",)), PassSpec("second", must_exclude=("faulty_replay",)))),
    Scenario("C5c_os_down_experiment", "experiment", lambda c, r: [c.os_down(r), c.qpu_ideal(r)],
             (PassSpec(must_exclude=("os",)),)),
    Scenario("C6_prng", "experiment", lambda c, r: [c.os(r), c.prng(r)],
             (PassSpec(expect_mixed=("faulty_prng",)),)),
    Scenario("K1_keygen_standin", "keygen", lambda c, r: [c.os(r), c.remote_up(r)],
             (PassSpec(expect_mixed=("ibm_standin",)),)),
    Scenario("C4_remote_down", "keygen", lambda c, r: [c.os(r), c.remote_down(r)],
             (PassSpec(must_exclude=("ibm_down",)),)),
    Scenario("C5a_os_down", "keygen", lambda c, r: [c.os_down(r), c.remote_up(r)],
             (PassSpec(must_exclude=("os",)),)),
    Scenario("C5b_os_tampered", "keygen", lambda c, r: [c.os_tampered(r), c.remote_up(r)],
             (PassSpec(must_exclude=("os",)),)),
)


# ------------------------------------------------------------------ veredito


@dataclass(frozen=True)
class Judgment:
    verdict: str
    os_status: str
    seed_generated: bool
    usable_for_key: bool | None
    mixed: tuple[str, ...]
    equals_without_bad: bool | None


def judge(result: PipelineResult, spec: PassSpec) -> Judgment:
    """Aplica as regras do docstring do módulo a UMA execução do pipeline."""
    status = {o.source_id: o.status for o in result.outcomes}
    os_status = status.get("os", "absent")
    generated = result.seed_generated
    mixed = result.mix.included_ids if result.mix is not None else ()
    usable = result.mix.usable_for_key if result.mix is not None else None
    equals: bool | None = None

    def done(verdict: str) -> Judgment:
        return Judgment(verdict, os_status, generated, usable, tuple(mixed), equals)

    if os_status != "mixed":
        if not generated:
            return done("ok_fail_closed")
        if result.mode == "keygen":
            return done("VIOLATION: semente gerada sem a fonte local aprovada")
        if usable is not False:
            return done("VIOLATION: semente de experiment marcada como utilizável")
        return done("ok_experiment_only")
    if not generated:
        return done("VIOLATION: fonte local aprovada, mas nenhuma semente")
    if usable != (result.mode == "keygen"):
        return done("VIOLATION: usable_for_key incoerente com o modo")
    missed = [sid for sid in spec.must_exclude if status.get(sid) == "mixed"]
    if missed:
        return done("DETECTION_MISS: " + ",".join(missed))
    if spec.must_exclude:
        good = [mi for mi in result.inputs if mi.source_id not in spec.must_exclude]
        equals = mix(good, result.mode).seed == result.mix.seed  # type: ignore[union-attr]
        if not equals:
            return done("VIOLATION: semente difere da semente sem as fontes ruins")
    absent = [sid for sid in spec.expect_mixed if status.get(sid) != "mixed"]
    if absent:
        return done("UNEXPECTED: não entrou na mistura: " + ",".join(absent))
    return done("ok")


def _reasons_text(result: PipelineResult) -> str:
    parts = []
    for o in result.outcomes:
        if o.status != "mixed" and o.reasons:
            parts.append(f"{o.source_id}: " + " | ".join(o.reasons)[:REASON_LIMIT])
    return " ; ".join(parts)


def make_row(name: str, rep: int, n_bits: int, result: PipelineResult, spec: PassSpec) -> dict[str, Any]:
    j = judge(result, spec)
    return {
        "scenario": f"{name}/{spec.label}" if spec.label else name, "rep": rep, "mode": result.mode,
        "n_bits": n_bits, "os_status": j.os_status, "os_expected_to_fail": "os" in spec.must_exclude,
        "seed_generated": j.seed_generated, "usable_for_key": j.usable_for_key,
        "statuses": ";".join(f"{o.source_id}:{o.status}" for o in result.outcomes),
        "mixed": ";".join(j.mixed), "not_mixed_reasons": _reasons_text(result),
        "must_exclude": ";".join(spec.must_exclude), "seed_equals_without_bad": j.equals_without_bad,
        "seed_hash": result.mix.seed_hash if result.mix is not None else "",
        "error": result.error or "", "verdict": j.verdict,
    }


# --------------------------------------------------------------- execução


def run_scenario(catalog: Catalog, scenario: Scenario, rep: int, n_bits: int, seed_source: Any,
                 health_fn: Callable[..., Any] | None = None) -> list[dict[str, Any]]:
    """Uma repetição de um cenário: fontes novas, um detector, uma linha por passagem."""
    sources, detector, rows = scenario.build(catalog, rep), catalog.detector(), []
    for spec in scenario.passes:
        result = run_pipeline(sources, seed_source, mode=scenario.mode, n_bits=n_bits,
                              detector=detector, health_fn=health_fn)
        rows.append(make_row(scenario.name, rep, n_bits, result, spec))
    return rows


def run_all(catalog: Catalog, seed_source: Any, *, reps: int = DEFAULT_REPS, n_bits: int = DEFAULT_N_BITS,
            scenarios: tuple[Scenario, ...] = SCENARIOS, health_fn: Callable[..., Any] | None = None,
            progress: Callable[[str], None] | None = None) -> list[dict[str, Any]]:
    """Todos os cenários, `reps` repetições cada, com fontes novas a cada repetição."""
    if isinstance(reps, bool) or not isinstance(reps, int) or reps < 1:
        raise ValueError("reps deve ser inteiro >= 1")
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        for rep in range(1, reps + 1):
            if progress:
                progress(f"{scenario.name} repetição {rep}/{reps}")
            rows += run_scenario(catalog, scenario, rep, n_bits, seed_source, health_fn)
    return rows


def kind(verdict: str) -> str:
    """'DETECTION_MISS: x' -> 'DETECTION_MISS'."""
    return verdict.split(":")[0]


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Contagem de vereditos por cenário (com a passagem, quando houver)."""
    out: dict[str, Counter[str]] = {}
    for r in rows:
        out.setdefault(r["scenario"], Counter())[kind(r["verdict"])] += 1
    return {k: dict(v) for k, v in out.items()}


def os_false_alarms(rows: list[dict[str, Any]]) -> int:
    """Execuções em que a os NÃO deveria falhar e não entrou na mistura (falso alarme ou falha real)."""
    return sum(1 for r in rows if r["os_status"] != "mixed" and not r["os_expected_to_fail"])


def gate(rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Gate do Dia 4 (ver docstring do módulo). Devolve (cumprido, motivos de falha)."""
    problems = [f"{r['scenario']} rep {r['rep']}: {r['verdict']}" for r in rows if kind(r["verdict"]) == "VIOLATION"]
    base = [r for r in rows if r["scenario"] == "BASE"]
    with_os = [r for r in base if r["os_status"] == "mixed"]
    if not with_os:
        problems.append("BASE: nenhuma execução com a os aprovada; sem evidência")
    for r in with_os:
        if not r["seed_generated"]:
            problems.append(f"BASE rep {r['rep']}: os aprovada, mas sem semente")
        elif r["usable_for_key"] is not False:
            problems.append(f"BASE rep {r['rep']}: semente marcada como utilizável para chave em experiment")
    return (not problems), problems


# ----------------------------------------------------- catálogo real e arquivos


class FailingSource:
    """Fonte cuja leitura sempre levanta exceção (fila ou queda do provedor, ou a própria os)."""

    def __init__(self, source_id: str, *, local: bool, simulated: bool = False) -> None:
        self.source_id, self.is_local, self.is_simulated = source_id, local, simulated

    def read(self, n_bits: int) -> Any:
        raise ConnectionError(f"{self.source_id}: fonte indisponível")


class RemoteStandIn:
    """STAND-IN da QPU remota: bits da fonte interna com rótulo de fonte remota, não local, não simulada.

    Serve para exercitar o `keygen` com uma fonte remota aprovada; não é a QPU real e não tem
    nenhuma das suas propriedades (viés, ruído, independência do provedor)."""

    source_id = "ibm_standin"

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def read(self, n_bits: int) -> Any:
        batch = self._inner.read(n_bits)
        return dataclasses.replace(batch, source_id=self.source_id, is_local=False, is_simulated=False)


class TamperedSource:
    """Envolve uma fonte e zera um trecho de cada lote (RCT deve reprovar). Não muda o resto do lote."""

    def __init__(self, inner: Any) -> None:
        self._inner, self.source_id = inner, inner.source_id

    def read(self, n_bits: int) -> Any:
        batch = self._inner.read(n_bits)
        bits = batch.bits.copy()
        bits[TAMPER_START:TAMPER_START + TAMPER_LENGTH] = 0
        return dataclasses.replace(batch, bits=bits)


def real_catalog(noise_backend: str) -> Catalog:
    """Catálogo com as fontes reais do projeto. Importa os módulos só aqui."""
    from eal.health.replay import ReplayDetector
    from eal.sources.faulty import BiasedSource, CorrelatedSource, PrngSource, ReplaySource, StuckSource
    from eal.sources.os_source import OsSource
    from eal.sources.qpu_sim import QpuSim

    return Catalog(
        os=lambda rep: OsSource(),
        qpu_ideal=lambda rep: QpuSim(seed=12345 + rep),
        qpu_noise=lambda rep: QpuSim(seed=12345 + rep, noise_backend=noise_backend),
        biased=lambda rep: BiasedSource(seed=2026 + rep),
        stuck=lambda rep: StuckSource(seed=2026 + rep),
        correlated=lambda rep: CorrelatedSource(seed=2026 + rep),
        replay=lambda rep: ReplaySource(seed=2026 + rep),
        prng=lambda rep: PrngSource(seed=2026 + rep),
        os_down=lambda rep: FailingSource("os", local=True),
        os_tampered=lambda rep: TamperedSource(OsSource()),
        remote_up=lambda rep: RemoteStandIn(OsSource()),
        remote_down=lambda rep: FailingSource("ibm_down", local=False),
        detector=ReplayDetector,
    )


def _sha3(data: bytes) -> str:
    return hashlib.sha3_256(data).hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def unique_tag(directory: Path, stamp: str) -> str:
    """Etiqueta sem colisão com arquivos existentes (nunca sobrescreve)."""
    n = 1
    while True:
        tag = stamp if n == 1 else f"{stamp}_{n}"
        if not any((directory / f"dia4_resilience_{tag}{ext}").exists() for ext in (".csv", ".meta.json")):
            return tag
        n += 1


def write_outputs(rows: list[dict[str, Any]], params: dict[str, Any], out_dir: Path = RESULTS_DIR) -> dict[str, Any]:
    """Grava o CSV e o meta (modo 'x') e devolve o meta."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = unique_tag(out_dir, datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S"))
    csv_path, meta_path = out_dir / f"dia4_resilience_{tag}.csv", out_dir / f"dia4_resilience_{tag}.meta.json"
    with csv_path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    ok, problems = gate(rows)
    meta = {
        "script": "scripts/resilience_dia4.py",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "python": platform.python_version(), "numpy": np.__version__,
        "params": params, "csv": csv_path.as_posix(), "csv_sha3_256": _sha3(csv_path.read_bytes()),
        "n_rows": len(rows), "verdicts_by_scenario": summarize(rows),
        "os_false_alarms": os_false_alarms(rows),
        "gate": {"ok": ok, "problems": problems},
        "notes": [
            "experiment: as faulty_* são simuladas e o mixer as recusa em keygen; K1, C4, C5a e C5b rodam em keygen",
            "ok_experiment_only: em experiment, uma fonte local simulada basta e a semente sai marcada como inutilizável",
            "a fonte remota dos cenários keygen é um stand-in (bits da os com rótulo remoto), não a QPU da IBM",
            "DETECTION_MISS não é falha do pipeline: é uma fonte defeituosa que passou nos testes (medida do E2)",
            "a os pode ser reprovada por falso alarme (~3% por lote); isso aparece como ok_fail_closed e em os_false_alarms",
            "C5b usa uma os adulterada (trecho de zeros); se o RawBatch não puder ser copiado com bits novos, o cenário aparece como read_failed",
            "o CSV guarda só o SHA3-256 da semente (seed_hash); nenhuma semente nem bit é gravado",
        ],
    }
    with meta_path.open("x", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    meta["meta_path"] = meta_path.as_posix()
    return meta


def main() -> None:
    from eal.sources.os_source import OsSource

    parser = argparse.ArgumentParser(description="Resiliência do pipeline e gate do Dia 4")
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    parser.add_argument("--bits", type=int, default=DEFAULT_N_BITS)
    parser.add_argument("--noise-backend", default=DEFAULT_NOISE_BACKEND)
    args = parser.parse_args()
    rows = run_all(real_catalog(args.noise_backend), OsSource(), reps=args.reps, n_bits=args.bits,
                   progress=lambda msg: print(msg, flush=True))
    meta = write_outputs(rows, {"reps": args.reps, "n_bits": args.bits, "noise_backend": args.noise_backend})
    print(f"\n{'cenário':<26} vereditos")
    for name, counts in meta["verdicts_by_scenario"].items():
        print(f"{name:<26} " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"\nFalsos alarmes da os (fora dos cenários C5): {meta['os_false_alarms']} de {len(rows)} execuções")
    print("GATE DO DIA 4: " + ("CUMPRIDO" if meta["gate"]["ok"] else "NÃO CUMPRIDO"))
    for p in meta["gate"]["problems"]:
        print(f"  - {p}")
    print(f"CSV:  {meta['csv']}\nMeta: {meta['meta_path']}")
    sys.exit(0 if meta["gate"]["ok"] else 1)


if __name__ == "__main__":
    main()
