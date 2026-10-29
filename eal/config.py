"""Constantes do projeto. Todo número "mágico" mora aqui, nunca espalhado pelo código.

Os valores seguem o PROJECT.md (seções 6 e 9).
"""

# --- Testes de saúde (NIST SP 800-90B, seção 4.4) ---
# α = 2**-X: falso alarme por amostra (RCT) ou por janela (APT). Faixa do SP 800-90B: 20 a 40.
RCT_ALPHA_NEG_LOG2 = 40   # 2**-40 por amostra: ~5e-7 de falso alarme por lote de 1M bits
APT_ALPHA_NEG_LOG2 = 20   # 2**-20 por janela: ~8e-4 de falso alarme por lote de 1M bits
APT_WINDOW_BITS = 1024    # janela do Adaptive Proportion Test para dados binários
# --- Extrator Toeplitz ---
EXTRACTOR_INPUT_BITS = 2048   # bits crus por bloco
EXTRACTOR_EPSILON_LOG2 = -64  # erro do extrator: 2**-64

# --- Mixer e semente ---
SEED_BYTES = 64
MIX_DOMAIN = b"EAL-v1-mix"
MIN_LOCAL_NON_SIMULATED_SOURCES = 1  # política fail-closed

# --- Orçamento de QPU (segundos de execução no chip) ---
QPU_TOTAL_BUDGET_SECONDS = 600  # 10 minutos por janela de 28 dias (confira no painel da IBM)

# --- Dia 3: estimador de min-entropia (PROJECT.md 6.5) ---
MCV_Z = 2.576          # quantil normal do limite superior de 99% (SP 800-90B 6.3.1)
MCV_SYMBOL_BITS = 8    # tamanho do simbolo do segundo estimador
