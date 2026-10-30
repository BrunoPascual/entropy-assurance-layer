"""Dia 4, etapa 3 (passo 4): como a H estimada depende do tamanho do lote.

Uso (a partir da raiz do projeto):
    py -3.12 -m scripts.estimator_vs_size [--reads 10]

Lê lotes da fonte `os` em cinco tamanhos, estima a min-entropia de cada um e
registra qual dos dois estimadores (por bit ou por byte) limitou o resultado,
o m do extrator, a saída e se o lote passaria no teste de saúde pela H (limiar
0,9, escolha de projeto fixada antes dos dados).

Isto mede o ESTIMADOR, não a fonte: a premissa P3 diz que a `os` tem H real
próxima de 1, e o que se vê aqui é quanto o estimador conservador subestima.
Lotes menores que 1M bits não passariam no gate (estatísticos inconclusivos);
esta medição não os aprova, só observa o estimador.

Grava data/results/dia4_estimator_<ts>.csv (uma linha por leitura),
dia4_estimator_summary_<ts>.csv (uma linha por tamanho) e .meta.json.
Nunca sobrescreve. Os bits NÃO são gravados: a `os` não é reprodutível, então
o CSV guarda as estimativas e o hash de cada lote, não os bits.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from eal.config import H_DECLARED_DEFAULT, H_MIN_HEALTH, MCV_Z, STATS_MIN_BITS
from eal.extract.budget import loss_breakdown
from eal.health.min_entropy import entropy_health_ok, estimate_min_entropy, extractor_entropy

RESULTS_DIR = Path("data/results")
DEFAULT_SIZES = (2**16, 2**18, 2**20, 1_000_000, 2**22)
DEFAULT_READS = 10
CONSISTENCY_TOLERANCE = 1e-12


class BitSource(Protocol):
    """O que a medição precisa de uma fonte (OsSource serve)."""

    def read(self, n_bits: int) -> Any: ...


def h_bit_reference(n_bits: int, z: float = MCV_Z) -> float:
    """H do estimador por bit para uma fonte perfeita (p̂ = 0,5): -log2(0,5 + z·0,5/sqrt(L-1))."""
    if n_bits < 2:
        raise ValueError("n_bits deve ser pelo menos 2")
    p_upper = 0.5 + z * 0.5 / math.sqrt(n_bits - 1)
    return 0.0 if p_upper >= 1.0 else -math.log2(p_upper)


def limited_by(h_bit: float, h_byte: float) -> str:
    """Estimador que limitou o mínimo; em empate, 'bit' (como em estimate_min_entropy)."""
    return "byte" if h_byte < h_bit else "bit"


def measure_batch(batch: Any, reading: int) -> dict[str, Any]:
    """Estima a H de um lote e deriva m, saída e a decisão do teste de saúde pela H."""
    bits = batch.bits
    est = estimate_min_entropy(bits)
    h_bit, h_byte, h_est = float(est.bit.h), float(est.byte.h), float(est.h_estimated)
    if abs(h_est - min(h_bit, h_byte)) > CONSISTENCY_TOLERANCE:
        raise ValueError("estimador inconsistente: h_estimated difere de min(h_bit, h_byte)")
    h_used = extractor_entropy(H_DECLARED_DEFAULT, h_est)
    b = loss_breakdown(int(bits.size), h_used)  # m vem de block_output_bits, a mesma função do extrator
    return {
        "size_bits": int(bits.size), "reading": reading, "h_bit": h_bit, "h_byte": h_byte,
        "h_estimated": h_est, "limited_by": limited_by(h_bit, h_byte), "h_used": h_used,
        "h_health_ok": bool(entropy_health_ok(h_est)), "stats_conclusive": bits.size >= STATS_MIN_BITS,
        "m": b.m, "n_blocks": b.n_blocks, "output_bits": b.output_bits, "total_yield": b.total_yield,
        "batch_hash": batch.batch_hash,
    }


def measure(source: BitSource, sizes: tuple[int, ...] = DEFAULT_SIZES, reads: int = DEFAULT_READS) -> list[dict[str, Any]]:
    """Lê `reads` lotes de cada tamanho e mede cada um."""
    if reads < 1:
        raise ValueError("reads deve ser pelo menos 1")
    if not sizes or any(not isinstance(s, int) or s < 16 for s in sizes):
        raise ValueError("sizes deve ser lista de inteiros >= 16")
    rows = []
    for size in sizes:
        for reading in range(1, reads + 1):
            rows.append(measure_batch(source.read(size), reading))
    return rows


def _sd(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) > 1 else None


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Uma linha por tamanho, na ordem em que os tamanhos aparecem."""
    out = []
    for size in dict.fromkeys(r["size_bits"] for r in rows):
        grp = [r for r in rows if r["size_bits"] == size]
        h = [r["h_estimated"] for r in grp]
        n = len(grp)
        out.append({
            "size_bits": size, "n_reads": n,
            "h_est_mean": statistics.fmean(h), "h_est_sd": _sd(h), "h_est_min": min(h), "h_est_max": max(h),
            "h_bit_mean": statistics.fmean(r["h_bit"] for r in grp),
            "h_byte_mean": statistics.fmean(r["h_byte"] for r in grp),
            "h_bit_reference": h_bit_reference(size),
            "frac_limited_by_byte": sum(r["limited_by"] == "byte" for r in grp) / n,
            "frac_h_health_ok": sum(r["h_health_ok"] for r in grp) / n,
            "stats_conclusive": size >= STATS_MIN_BITS,
            "mean_output_bits": statistics.fmean(r["output_bits"] for r in grp),
            "mean_total_yield": statistics.fmean(r["total_yield"] for r in grp),
        })
    return out


def _sha3(data: bytes) -> str:
    return hashlib.sha3_256(data).hexdigest()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> str:
    with path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return _sha3(path.read_bytes())


def output_names(tag: str) -> dict[str, str]:
    """Nomes dos três arquivos de uma execução."""
    return {
        "readings": f"dia4_estimator_{tag}.csv",
        "summary": f"dia4_estimator_summary_{tag}.csv",
        "meta": f"dia4_estimator_{tag}.meta.json",
    }


def unique_tag(directory: Path, stamp: str) -> str:
    """Etiqueta que não colide com nenhum arquivo existente (nunca sobrescreve)."""
    n = 1
    while True:
        tag = stamp if n == 1 else f"{stamp}_{n}"
        if not any((directory / name).exists() for name in output_names(tag).values()):
            return tag
        n += 1


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run(source: BitSource, source_id: str, sizes: tuple[int, ...] = DEFAULT_SIZES,
        reads: int = DEFAULT_READS, out_dir: Path = RESULTS_DIR) -> dict[str, Any]:
    """Mede, grava os CSVs e o meta, e devolve o meta (com `summary` em memória)."""
    rows = measure(source, sizes, reads)  # mede tudo antes de gravar qualquer arquivo
    summary = summarize(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    names = output_names(unique_tag(out_dir, stamp))
    outputs = {
        key: {"path": (out_dir / names[key]).as_posix(), "sha3_256": _write_csv(out_dir / names[key], data)}
        for key, data in (("readings", rows), ("summary", summary))
    }
    meta = {
        "script": "scripts/estimator_vs_size.py",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "python": platform.python_version(),
        "source_id": source_id,
        "params": {"sizes": list(sizes), "reads": reads, "h_declared": H_DECLARED_DEFAULT,
                   "h_min_health": H_MIN_HEALTH, "mcv_z": MCV_Z},
        "outputs": outputs,
        "notes": [
            "mede o estimador de min-entropia sobre a fonte os, não a entropia real da fonte (premissa P3)",
            "lotes menores que 1M bits não passariam no gate (estatísticos inconclusivos)",
            "h_bit_reference é a H do estimador por bit para p̂ = 0,5; a diferença para h_est vem do ramo por byte",
            "a fonte os não é reprodutível e os bits não foram gravados; só estimativas e hashes de lote",
            "o limiar de H 0,9 foi fixado antes dos dados e não foi ajustado",
        ],
    }
    meta_path = out_dir / names["meta"]
    with meta_path.open("x", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return {**meta, "meta_path": meta_path.as_posix(), "summary": summary}


def main() -> None:
    from eal.sources.os_source import OsSource  # importado aqui para os testes usarem fontes falsas

    parser = argparse.ArgumentParser(description="H estimada x tamanho do lote (Dia 4, etapa 3)")
    parser.add_argument("--reads", type=int, default=DEFAULT_READS)
    args = parser.parse_args()
    source = OsSource()
    result = run(source, source.source_id, reads=args.reads)
    print(f"{'bits':>9} {'H_est média':>12} {'dp':>7} {'min':>7} {'máx':>7} {'H_bit':>7} {'H_byte':>7} "
          f"{'ref_bit':>8} {'limita(byte)':>12} {'passa H>=0,9':>12} {'saída':>9}")
    for s in result["summary"]:
        sd = "-" if s["h_est_sd"] is None else f"{s['h_est_sd']:.4f}"
        print(f"{s['size_bits']:>9} {s['h_est_mean']:>12.4f} {sd:>7} {s['h_est_min']:>7.4f} {s['h_est_max']:>7.4f} "
              f"{s['h_bit_mean']:>7.4f} {s['h_byte_mean']:>7.4f} {s['h_bit_reference']:>8.4f} "
              f"{s['frac_limited_by_byte']:>12.2f} {s['frac_h_health_ok']:>12.2f} {s['mean_output_bits']:>9.0f}")
    for key, info in result["outputs"].items():
        print(f"{key}: {info['path']}")
    print(f"Meta: {result['meta_path']}")


if __name__ == "__main__":
    main()
