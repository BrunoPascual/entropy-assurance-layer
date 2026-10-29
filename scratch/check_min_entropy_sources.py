"""Estima a min-entropia das fontes reais e mostra o efeito de usar H estimada
nos limites do RCT e do APT, comparado com H declarada = 1,0.

Rodar na raiz do projeto: py -3.12 -m scratch.check_min_entropy_sources
"""
from eal.health.continuous import run_apt, run_rct
from eal.health.min_entropy import estimate_min_entropy
from eal.sources.faulty import FAULTY_SOURCES
from eal.sources.os_source import OsSource

N = 1_000_000


def verdict(rct, apt) -> str:
    """Resumo curto: 'ok' ou quais testes falharam."""
    falhas = [nome for nome, r in (("RCT", rct), ("APT", apt)) if not r.passed]
    return "ok" if not falhas else "FALHA " + "+".join(falhas)


fontes = [("os", OsSource)] + sorted(FAULTY_SOURCES.items())
print(f"{'fonte':18} {'H_bit':>6} {'H_byte':>6} {'H_est':>6} {'limita':>6}"
      f"   {'com H=1,0':14} {'com H_est':14}")
for nome, fabrica in fontes:
    try:
        bits = fabrica().read(N).bits
    except Exception as exc:
        print(f"{nome:18} ERRO: {type(exc).__name__}: {exc}")
        continue
    e = estimate_min_entropy(bits)
    h_est = max(e.h_estimated, 0.05)  # H = 0 não tem limite definido
    declarada = verdict(run_rct(bits, 1.0), run_apt(bits, 1.0))
    estimada = verdict(run_rct(bits, h_est), run_apt(bits, h_est))
    print(f"{nome:18} {e.h_bit:6.3f} {e.h_byte:6.3f} {e.h_estimated:6.3f} {e.limited_by:>6}"
          f"   {declarada:14} {estimada:14}")
