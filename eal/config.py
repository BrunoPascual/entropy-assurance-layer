"""Constantes do projeto. Todo número "mágico" mora aqui, nunca espalhado pelo código.

Os valores seguem o PROJECT.md (seções 6 e 9).
"""

# --- Testes de saúde (NIST SP 800-90B, seção 4.4) ---
ALPHA_LOG2 = -20          # taxa de falso alarme por teste: 2**-20
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
