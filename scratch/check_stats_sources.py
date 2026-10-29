"""Roda os três testes do SP 800-22 nas fontes reais (1 milhão de bits cada).

Rodar na raiz do projeto: py -3.12 -m scratch.check_stats_sources
"""
from eal.health.stats_tests import run_stats_tests
from eal.sources.faulty import FAULTY_SOURCES
from eal.sources.os_source import OsSource

N = 1_000_000

fontes = [("os", OsSource)] + sorted(FAULTY_SOURCES.items())
print(f"{'fonte':18} {'monobit':>10} {'bloco':>10} {'runs':>10}   veredito")
for nome, fabrica in fontes:
    try:
        bits = fabrica().read(N).bits
    except Exception as exc:
        print(f"{nome:18} ERRO: {type(exc).__name__}: {exc}")
        continue
    r = run_stats_tests(bits)
    falhas = [t.name for t in r.results if not t.passed]
    veredito = "ok" if r.passed else "FALHA " + "+".join(falhas)
    p = r.p_values()
    print(f"{nome:18} {p['monobit']:10.3g} {p['block']:10.3g} {p['runs']:10.3g}   {veredito}")
