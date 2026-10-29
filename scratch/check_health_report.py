"""Passa as fontes reais pelo HealthReport (1 milhão de bits por leitura).

Cada fonte é lida duas vezes com a MESMA instância, para o teste de replay ter
histórico. A faulty_replay ganha uma 3ª leitura menor (prefixo do lote guardado).

Rodar na raiz do projeto: py -3.12 -m scratch.check_health_report
"""
from eal.health.replay import ReplayDetector
from eal.health.report import build_health_report
from eal.sources.faulty import FAULTY_SOURCES
from eal.sources.os_source import OsSource

N = 1_000_000
N_PREFIX = 4096 * 100  # 409.600 bits: menor que o lote guardado, múltiplo de bloco

detector = ReplayDetector()  # um por execução; vale entre todas as fontes
origem: dict[str, str] = {}  # batch_id -> nome da fonte, só para legibilidade
fontes = [("os", OsSource)] + sorted(FAULTY_SOURCES.items())

for nome, fabrica in fontes:
    try:
        fonte = fabrica()
    except Exception as exc:
        print(f"{nome}: ERRO ao criar: {type(exc).__name__}: {exc}")
        continue
    tamanhos = [N, N] + ([N_PREFIX] if nome == "faulty_replay" else [])
    for i, n in enumerate(tamanhos, start=1):
        try:
            lote = fonte.read(n)
            r = build_health_report(lote, detector)
            origem[lote.batch_id] = f"{r.source_id}, leitura {i}"
        except Exception as exc:
            print(f"{nome} (leitura {i}): ERRO: {type(exc).__name__}: {exc}")
            continue
        h = "-" if r.h_estimated is None else f"{r.h_estimated:.3f}"
        p = r.stats
        print(f"{r.source_id} (leitura {i}, {n} bits): {'APROVADO' if r.approved else 'REPROVADO'}"
              f"   H_est={h}  p(mono,bloco,runs)=({p['monobit']:.2g}, {p['block']:.2g}, {p['runs']:.2g})")
        for motivo in r.reasons:
            for bid, de_onde in origem.items():
                motivo = motivo.replace(bid, f"[{de_onde}]")
            print(f"    - {motivo}")
