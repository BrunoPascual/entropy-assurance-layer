"""Dia 4, etapa 1: compara o extrator Toeplitz com a alternativa SHA3.

Uso (a partir da raiz do projeto):
    py -3.12 -m scripts.compare_extractors --noise-backend <nome>

Fontes: os, qpu_sim ideal e qpu_sim com ruído; 2 leituras de 1M bits por fonte.
Grava data/results/dia4_extract_<timestamp>.csv e .meta.json (nunca sobrescreve).

Os p-valores da SAÍDA são diagnóstico, não aprovação: a saída tem menos de
1M bits, e estatística boa na saída não prova nada (o SHA3 de bits travados
também parece perfeito). O extrator é dimensionado pela H medida na ENTRADA.
Nenhum bit de saída nem de semente é gravado ou impresso; só hashes e contagens.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from eal.config import H_DECLARED_DEFAULT
from eal.extract.sha3 import extract_sha3
from eal.extract.toeplitz import extract_toeplitz
from eal.health.min_entropy import estimate_min_entropy, extractor_entropy
from eal.health.stats_tests import block_frequency_p, monobit_p, runs_p
from eal.sources.os_source import OsSource
from eal.sources.qpu_sim import QpuSim

RESULTS_DIR = Path("data/results")
SEED_READ_BITS = 4096  # >= n + m - 1 = 3967 no pior caso (H = 1)

# Exemplos do NIST SP 800-22 Rev. 1a (seções 2.1.8, 2.2.8 e 2.3.8).
_SP800_22_EXAMPLES: list[tuple[str, Callable[..., Any], str, dict[str, int], float]] = [
    ("monobit", monobit_p, "1011010101", {}, 0.527089),
    ("block", block_frequency_p, "0110011010", {"m": 3}, 0.801252),
    ("runs", runs_p, "1001101011", {}, 0.147232),
]

CSV_FIELDS = [
    "source_id", "reading", "extractor", "guarantee", "n_input_bits",
    "h_estimated_input", "h_used", "n", "m", "n_blocks", "discarded_bits",
    "n_output_bits", "epsilon_total_log2", "seconds", "frac_ones_out",
    "h_estimated_out", "monobit_p_out", "block_p_out", "runs_p_out",
    "seed_hash", "input_batch_hash",
]


def _bits(text: str) -> np.ndarray:
    return np.array([int(c) for c in text], dtype=np.uint8)


def find_p_positions() -> dict[str, int]:
    """Descobre em que posição da tupla cada função devolve o p-valor."""
    positions: dict[str, int] = {}
    for name, fn, seq, kwargs, expected in _SP800_22_EXAMPLES:
        values = fn(_bits(seq), **kwargs)
        hits = [i for i, v in enumerate(values) if isinstance(v, float) and abs(v - expected) < 1e-5]
        if len(hits) != 1:
            raise RuntimeError(f"{name}: p-valor do exemplo SP 800-22 não encontrado em {values}")
        positions[name] = hits[0]
    return positions


def output_diagnostics(bits: np.ndarray, pos: dict[str, int]) -> dict[str, Any]:
    """Fração de 1, H estimada e p-valores da saída (diagnóstico)."""
    if bits.size == 0:
        return dict.fromkeys(["frac_ones_out", "h_estimated_out", "monobit_p_out", "block_p_out", "runs_p_out"])
    return {
        "frac_ones_out": float(bits.mean()),
        "h_estimated_out": float(estimate_min_entropy(bits).h_estimated),
        "monobit_p_out": float(monobit_p(bits)[pos["monobit"]]),
        "block_p_out": float(block_frequency_p(bits)[pos["block"]]),
        "runs_p_out": float(runs_p(bits)[pos["runs"]]),
    }


def compare_batch(batch: Any, reading: int, seed_source: OsSource, pos: dict[str, int]) -> list[dict[str, Any]]:
    """Roda os dois extratores sobre um lote e devolve uma linha do CSV para cada."""
    h_est = float(estimate_min_entropy(batch.bits).h_estimated)
    h_used = extractor_entropy(H_DECLARED_DEFAULT, h_est)
    seed_batch = seed_source.read(SEED_READ_BITS)
    runs = [
        lambda: extract_toeplitz(batch.bits, h_used, seed_batch, input_batch_id=batch.batch_id),
        lambda: extract_sha3(batch.bits, h_used),
    ]
    rows = []
    for run in runs:
        t0 = time.perf_counter()
        res = run()
        seconds = time.perf_counter() - t0
        d = res.to_dict()
        row = {k: d.get(k) for k in CSV_FIELDS if k in d}
        row.update(
            source_id=batch.source_id, reading=reading, extractor=d["extractor_type"],
            h_estimated_input=h_est, seconds=round(seconds, 4), input_batch_hash=batch.batch_hash,
        )
        row.update(output_diagnostics(res.bits, pos))
        rows.append(row)
    return rows


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _sources(noise_backend: str, sim_seed: int) -> list[tuple[str, Any]]:
    return [
        ("os", OsSource()),
        ("qpu_sim_ideal", QpuSim(seed=sim_seed)),
        ("qpu_sim_noise", QpuSim(seed=sim_seed, noise_backend=noise_backend)),
    ]


def write_outputs(rows: list[dict[str, Any]], meta: dict[str, Any]) -> tuple[Path, Path]:
    """Grava CSV e meta com modo 'x': falha se o arquivo já existir."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    csv_path = RESULTS_DIR / f"dia4_extract_{stamp}.csv"
    suffix = 2
    while csv_path.exists():  # mesmo segundo: novo nome, nunca sobrescreve
        csv_path = RESULTS_DIR / f"dia4_extract_{stamp}_{suffix}.csv"
        suffix += 1
    meta_path = csv_path.with_suffix(".meta.json")
    with csv_path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["label"] + CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    meta["csv"] = csv_path.as_posix()
    meta["csv_sha3_256"] = hashlib.sha3_256(csv_path.read_bytes()).hexdigest()
    with meta_path.open("x", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return csv_path, meta_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Compara Toeplitz e SHA3 (Dia 4, etapa 1)")
    parser.add_argument("--noise-backend", required=True, help="nome do backend usado no gate do Dia 3")
    parser.add_argument("--bits", type=int, default=1_000_000)
    parser.add_argument("--readings", type=int, default=2)
    parser.add_argument("--sim-seed", type=int, default=12345)
    args = parser.parse_args()

    pos = find_p_positions()
    seed_source = OsSource()
    rows: list[dict[str, Any]] = []
    for label, source in _sources(args.noise_backend, args.sim_seed):
        for reading in range(1, args.readings + 1):
            batch = source.read(args.bits)
            for row in compare_batch(batch, reading, seed_source, pos):
                rows.append({"label": label, **row})

    meta = {
        "script": "scripts/compare_extractors.py",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "params": vars(args) | {"h_declared": H_DECLARED_DEFAULT, "seed_read_bits": SEED_READ_BITS},
        "p_value_positions": pos,
        "notes": [
            "p-valores da saída são diagnóstico, não aprovação (saída < 1M bits)",
            "SHA3: garantia heurística; Toeplitz: lema do hash residual sob P4",
            "qpu_sim: semente efetiva por execução = semente base + contador",
            "tempos medidos nesta máquina, nesta execução",
        ],
    }
    csv_path, meta_path = write_outputs(rows, meta)
    for r in rows:
        print(f"{r['label']:<15} leitura {r['reading']}  {r['extractor']:<8} "
              f"H_in={r['h_estimated_input']:.3f} m={r['m']} saída={r['n_output_bits']} "
              f"t={r['seconds']:.3f}s monobit_p={r['monobit_p_out']}")
    print(f"CSV:  {csv_path}\nMeta: {meta_path}")


if __name__ == "__main__":
    main()
