"""Dia 4, etapa 3 (passos 2 e 3): rendimento do extrator.

Uso (a partir da raiz do projeto):
    py -3.12 -m scripts.yield_analysis data\\results\\dia4_extract_<timestamp>.csv

1. Lê o CSV de `compare_extractors`, confere o SHA3-256 dele contra o .meta.json
   e usa só as linhas do Toeplitz (a SHA3 tem o mesmo m e o mesmo número de blocos,
   o que também é conferido).
2. Para cada linha, recalcula m, blocos, saída, resto e ε com o modelo de
   `eal.extract.budget` e EXIGE igualdade com o que foi gravado. Se algo divergir,
   para com erro: nada é analisado sobre dados que não batem.
3. Decompõe cada lote em déficit, arredondamento, margem, saída e resto.
4. Gera duas curvas CALCULADAS (não medidas): rendimento em função de H e em função
   de n.

Grava data/results/dia4_yield_<ts>.csv, dia4_yield_curve_h_<ts>.csv,
dia4_yield_curve_n_<ts>.csv e dia4_yield_<ts>.meta.json (com o SHA3-256 de cada
um). Nunca sobrescreve. Só hashes e contagens: nenhum bit é lido ou gravado.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import subprocess
import sys
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from eal.config import EXTRACTOR_EPSILON_LOG2, EXTRACTOR_INPUT_BITS
from eal.extract.blocks import block_min_entropy_bits
from eal.extract.budget import LossBreakdown, loss_breakdown, yield_ratio

RESULTS_DIR = Path("data/results")
REQUIRED_COLUMNS = (
    "label", "source_id", "reading", "extractor", "n_input_bits", "h_estimated_input",
    "h_used", "n", "m", "n_blocks", "discarded_bits", "n_output_bits", "epsilon_total_log2",
)
SAME_IN_BOTH = ("n_input_bits", "h_used", "n", "m", "n_blocks", "discarded_bits", "n_output_bits")
CURVE_H_STEPS = 1000  # H = 0,001 ... 1,000
CURVE_N_VALUES = (512, 1024, 2048, 4096, 8192)
CURVE_N_H_VALUES = (0.9, 0.954, 1.0)
CURVE_N_INPUT_BITS = 1_000_000
EPS_TOLERANCE = 1e-9


def _sha3(data: bytes) -> str:
    return hashlib.sha3_256(data).hexdigest()


def read_verified_csv(csv_path: Path) -> list[dict[str, str]]:
    """Lê o CSV só depois de conferir o SHA3-256 dele contra o meta. Qualquer falha: ValueError."""
    meta_path = csv_path.with_suffix(".meta.json")
    try:
        data = csv_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"não consegui ler {csv_path} ou o meta dele: {exc}") from exc
    expected = meta.get("csv_sha3_256")
    if not isinstance(expected, str):
        raise ValueError("o meta não traz csv_sha3_256")
    if _sha3(data) != expected:
        raise ValueError(f"SHA3-256 de {csv_path.name} não confere com o meta")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))
    if not rows:
        raise ValueError("CSV sem linhas")
    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    if missing:
        raise ValueError(f"colunas ausentes no CSV: {missing}")
    return rows


def split_extractors(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Devolve as linhas do Toeplitz, exigindo uma linha SHA3 equivalente para cada uma."""
    toeplitz: dict[tuple[str, str], dict[str, str]] = {}
    sha3: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row["label"], row["reading"])
        target = {"toeplitz": toeplitz, "sha3": sha3}.get(row["extractor"])
        if target is None:
            raise ValueError(f"extrator desconhecido no CSV: {row['extractor']!r}")
        if key in target:
            raise ValueError(f"linha repetida para {key} / {row['extractor']}")
        target[key] = row
    if toeplitz.keys() != sha3.keys():
        raise ValueError("Toeplitz e SHA3 não cobrem as mesmas leituras")
    for key, row in toeplitz.items():
        for col in SAME_IN_BOTH:
            if row[col] != sha3[key][col]:
                raise ValueError(f"{key}: Toeplitz e SHA3 divergem em {col}")
    return [r for r in rows if r["extractor"] == "toeplitz"]


def check_row(row: dict[str, str]) -> LossBreakdown:
    """Recalcula a linha pelo modelo e exige igualdade com o que foi gravado."""
    key = (row["label"], row["reading"])
    try:
        n_in, n = int(row["n_input_bits"]), int(row["n"])
        h = float(row["h_used"])
        b = loss_breakdown(n_in, h, n=n)
        recorded = {
            "m": int(row["m"]), "n_blocks": int(row["n_blocks"]),
            "n_output_bits": int(row["n_output_bits"]), "discarded_bits": int(row["discarded_bits"]),
        }
    except ValueError as exc:
        raise ValueError(f"{key}: valor inválido na linha: {exc}") from exc
    expected = {
        "m": b.m, "n_blocks": b.n_blocks, "n_output_bits": b.output_bits,
        "discarded_bits": b.tail_bits + b.low_entropy_discard_bits,
    }
    for name, value in expected.items():
        if recorded[name] != value:
            raise ValueError(f"{key}: {name} gravado {recorded[name]} difere do recalculado {value}")
    _check_epsilon(row, b, key)
    return b


def _check_epsilon(row: dict[str, str], b: LossBreakdown, key: tuple[str, str]) -> None:
    text = row["epsilon_total_log2"]
    if b.n_blocks == 0:
        if text != "":
            raise ValueError(f"{key}: sem blocos, mas epsilon_total_log2 = {text!r}")
        return
    expected = EXTRACTOR_EPSILON_LOG2 + math.log2(b.n_blocks)
    if abs(float(text) - expected) > EPS_TOLERANCE:
        raise ValueError(f"{key}: epsilon_total_log2 gravado {text} difere de {expected}")


def analyze(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Uma linha de saída por leitura (linhas do Toeplitz), com a decomposição de perdas."""
    out: list[dict[str, Any]] = []
    for row in split_extractors(rows):
        b = check_row(row)
        total = Fraction(b.n_input_bits)

        def frac(x: Fraction | int) -> float:
            return float(Fraction(x) / total)

        out.append({
            "label": row["label"], "source_id": row["source_id"], "reading": int(row["reading"]),
            "n_input_bits": b.n_input_bits, "h_estimated_input": float(row["h_estimated_input"]),
            "h_used": b.h_used, "n": b.n, "m": b.m, "n_blocks": b.n_blocks,
            "deficit_bits": float(b.deficit_bits), "rounding_bits": float(b.rounding_bits),
            "margin_bits": b.margin_bits, "output_bits": b.output_bits, "tail_bits": b.tail_bits,
            "low_entropy_discard_bits": b.low_entropy_discard_bits,
            "yield_block": b.m / b.n, "total_yield": b.total_yield,
            "frac_deficit": frac(b.deficit_bits), "frac_rounding": frac(b.rounding_bits),
            "frac_margin": frac(b.margin_bits), "frac_output": frac(b.output_bits),
            "frac_tail": frac(b.tail_bits), "frac_low_entropy_discard": frac(b.low_entropy_discard_bits),
        })
    return out


def curve_h() -> list[dict[str, Any]]:
    """Rendimento por bloco em função de H (n e ε de config). Calculado, não medido."""
    n = EXTRACTOR_INPUT_BITS
    rows = []
    for i in range(1, CURVE_H_STEPS + 1):
        h = i / CURVE_H_STEPS
        b = loss_breakdown(n, h)  # um bloco
        rows.append({
            "h": h, "k_floor": block_min_entropy_bits(h), "m": b.m, "yield_block": yield_ratio(h),
            "deficit_per_block": float(b.deficit_bits), "rounding_per_block": float(b.rounding_bits),
            "margin_per_block": b.margin_bits, "low_entropy_discard": b.low_entropy_discard_bits,
        })
    return rows


def curve_n() -> list[dict[str, Any]]:
    """Rendimento em função de n, com H constante, para um lote de 1M bits. Calculado, não medido."""
    rows = []
    for n in CURVE_N_VALUES:
        for h in CURVE_N_H_VALUES:
            b = loss_breakdown(CURVE_N_INPUT_BITS, h, n=n)
            rows.append({
                "n": n, "h": h, "m": b.m, "n_blocks": b.n_blocks, "tail_bits": b.tail_bits,
                "output_bits": b.output_bits, "yield_block": b.m / n, "total_yield": b.total_yield,
                "margin_frac_of_block": -2 * EXTRACTOR_EPSILON_LOG2 / n,
                "batch_epsilon_log2": (
                    EXTRACTOR_EPSILON_LOG2 + math.log2(b.n_blocks) if b.n_blocks else None
                ),
            })
    return rows


def output_names(tag: str) -> dict[str, str]:
    """Nomes dos quatro arquivos de uma execução."""
    return {
        "analysis": f"dia4_yield_{tag}.csv",
        "curve_h": f"dia4_yield_curve_h_{tag}.csv",
        "curve_n": f"dia4_yield_curve_n_{tag}.csv",
        "meta": f"dia4_yield_{tag}.meta.json",
    }


def unique_tag(directory: Path, stamp: str) -> str:
    """Etiqueta que não colide com nenhum arquivo existente (nunca sobrescreve)."""
    n = 1
    while True:
        tag = stamp if n == 1 else f"{stamp}_{n}"
        if not any((directory / name).exists() for name in output_names(tag).values()):
            return tag
        n += 1


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> str:
    with path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return _sha3(path.read_bytes())


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run(source_csv: Path, out_dir: Path = RESULTS_DIR) -> dict[str, Any]:
    """Executa a análise completa e grava os arquivos. Devolve o meta."""
    rows = read_verified_csv(source_csv)
    per_reading = analyze(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    names = output_names(unique_tag(out_dir, stamp))
    paths = {k: out_dir / names[k] for k in ("analysis", "curve_h", "curve_n")}
    data = {"analysis": per_reading, "curve_h": curve_h(), "curve_n": curve_n()}
    outputs = {k: {"path": paths[k].as_posix(), "sha3_256": _write_csv(paths[k], data[k])} for k in paths}
    meta = {
        "script": "scripts/yield_analysis.py",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "python": platform.python_version(),
        "source_csv": source_csv.as_posix(),
        "source_csv_sha3_256": _sha3(source_csv.read_bytes()),
        "params": {"n": EXTRACTOR_INPUT_BITS, "epsilon_log2": EXTRACTOR_EPSILON_LOG2,
                   "curve_h_steps": CURVE_H_STEPS, "curve_n_values": list(CURVE_N_VALUES),
                   "curve_n_h_values": list(CURVE_N_H_VALUES), "curve_n_input_bits": CURVE_N_INPUT_BITS},
        "outputs": outputs,
        "notes": [
            "analysis: cada linha foi recalculada pelo modelo e confere com o CSV de origem",
            "curve_h e curve_n são contas do modelo, não medidas",
            "curve_n supõe a mesma H para todo n; a H estimada real não depende de n, mas pode variar entre lotes",
            "a H usada continua sendo uma estimativa conservadora (T8): o modelo não valida a estimativa",
        ],
    }
    meta_path = out_dir / names["meta"]
    with meta_path.open("x", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    meta["meta_path"] = meta_path.as_posix()
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Rendimento do extrator (Dia 4, etapa 3)")
    parser.add_argument("source_csv", type=Path, help="CSV dia4_extract_*.csv (com .meta.json ao lado)")
    args = parser.parse_args()
    try:
        meta = run(args.source_csv)
    except ValueError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)
    with open(meta["outputs"]["analysis"]["path"], encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        print(f"{r['label']:<15} leitura {r['reading']}  H={float(r['h_used']):.3f} m={r['m']:>4} "
              f"rendimento/bloco={float(r['yield_block']):.4f}  do lote: saída={float(r['frac_output']):.4f} "
              f"déficit={float(r['frac_deficit']):.4f} margem={float(r['frac_margin']):.4f} "
              f"resto={float(r['frac_tail']):.4f}")
    for k, v in meta["outputs"].items():
        print(f"{k}: {v['path']}")
    print(f"Meta: {meta['meta_path']}")


if __name__ == "__main__":
    main()
