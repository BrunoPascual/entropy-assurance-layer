"""Roda RCT e APT nas fontes reais do projeto (1 milhão de bits cada).

Usa H = 1,0 para todas, porque o estimador de min-entropia ainda não existe.
Rodar com: py -3.12 scratch\\check_continuous_sources.py
"""
from eal.health.continuous import run_apt, run_rct
from eal.sources.faulty import FAULTY_SOURCES
from eal.sources.os_source import OsSource

N = 1_000_000
H = 1.0

fontes = [("os", OsSource)] + sorted(FAULTY_SOURCES.items())
print(f"{'fonte':18} {'RCT':5} {'run/C':>8}   {'APT':5} {'max/C':>9} {'janelas ruins':>14}")
for nome, fabrica in fontes:
    try:
        lote = fabrica().read(N)
    except Exception as exc:  # assinatura diferente da esperada: mostrar e seguir
        print(f"{nome:18} ERRO ao criar/ler: {type(exc).__name__}: {exc}")
        continue
    r = run_rct(lote.bits, H)
    a = run_apt(lote.bits, H)
    print(
        f"{lote.source_id:18} {'ok' if r.passed else 'FALHA':5} {r.max_run:>3}/{r.cutoff:<4}"
        f"   {'ok' if a.passed else 'FALHA':5} {a.max_count:>4}/{a.cutoff:<4}"
        f" {a.n_failed_windows:>6}/{a.n_windows}"
    )
