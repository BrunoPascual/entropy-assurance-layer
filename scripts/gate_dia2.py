"""Gate do Dia 2: cada fonte gera 1 milhão de bits, salva em data/raw e relê.

Uso (na raiz do projeto):
    py -3.12 -m scripts.gate_dia2

Gate: as 5 fontes defeituosas geram 1 milhão de bits cada em menos de 5 minutos
(no total). `os` e `qpu_sim` (com ruído) entram como referência e não contam.
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from eal import storage
from eal.sources.faulty import FAULTY_SOURCES
from eal.sources.os_source import OsSource
from eal.sources.qpu_sim import QpuSim

N_BITS = 1_000_000
LIMIT_SECONDS = 300
RESULTS_DIR = Path("data/results")


def bias_chart_path(day: str | None = None) -> Path:
    """Caminho esperado do gráfico de viés gerado por scripts.plot_bias no dia."""
    return RESULTS_DIR / f"{day or date.today().isoformat()}_bias_por_qubit.png"


def check(source, session: str = "gate") -> tuple[float, str]:
    """Gera, salva e relê um lote; devolve (segundos para gerar, nome do arquivo)."""
    t = time.perf_counter()
    batch = source.read(N_BITS)
    elapsed = time.perf_counter() - t
    path = storage.save_batch(batch, session)
    back = storage.load_batch(path)
    assert back.batch_hash == batch.batch_hash and back.n_bits == N_BITS
    return elapsed, path.name


def main() -> None:
    """Roda o gate e imprime uma tabela."""
    total = 0.0
    print(f"{'fonte':<20}{'segundos':>10}  arquivo")
    for cls in FAULTY_SOURCES.values():
        sec, name = check(cls())
        total += sec
        print(f"{cls.source_id:<20}{sec:>10.3f}  {name}")
    print(f"{'total (5 defeituosas)':<20}{total:>9.3f}")
    for ref in (OsSource(), QpuSim(noise_backend="FakeKingston")):
        sec, name = check(ref)
        print(f"{ref.source_id + ' (ref.)':<20}{sec:>10.3f}  {name}")
    chart = bias_chart_path()
    chart_ok = chart.exists() and chart.stat().st_size > 5_000
    ok_time = total < LIMIT_SECONDS
    print(f"\nFontes: {'OK' if ok_time else 'FORA DO TEMPO'} "
          f"({total:.1f} s de {LIMIT_SECONDS} s); todos os lotes relidos com hash conferido")
    print(f"Gráfico: {'OK' if chart_ok else 'AUSENTE'} ({chart})"
          + ("" if chart_ok else "  -> rode: py -3.12 -m scripts.plot_bias"))
    ok = ok_time and chart_ok
    print(f"\nGATE DIA 2: {'APROVADO' if ok else 'REPROVADO'}")


if __name__ == "__main__":
    main()
