"""Gate do Dia 2: cada fonte gera 1 milhão de bits, salva em data/raw e relê.

Uso (na raiz do projeto):
    py -3.12 -m scripts.gate_dia2

Gate: as 5 fontes defeituosas geram 1 milhão de bits cada em menos de 5 minutos
(no total). `os` e `qpu_sim` (com ruído) entram como referência e não contam.
"""
from __future__ import annotations

import time

from eal import storage
from eal.sources.faulty import FAULTY_SOURCES
from eal.sources.os_source import OsSource
from eal.sources.qpu_sim import QpuSim

N_BITS = 1_000_000
LIMIT_SECONDS = 300


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
    ok = total < LIMIT_SECONDS
    print(f"\nGATE DIA 2 (fontes): {'APROVADO' if ok else 'REPROVADO'} "
          f"({total:.1f} s de {LIMIT_SECONDS} s); todos os lotes relidos com hash conferido")


if __name__ == "__main__":
    main()
