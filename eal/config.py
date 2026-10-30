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
MIN_LOCAL_SOURCES_EXPERIMENT = 1     # experiment: fonte local aprovada, simulada permitida

# --- Orçamento de QPU (segundos de execução no chip) ---
QPU_TOTAL_BUDGET_SECONDS = 600  # 10 minutos por janela de 28 dias (confira no painel da IBM)

# --- Dia 3: estimador de min-entropia (PROJECT.md 6.5) ---
MCV_Z = 2.576          # quantil normal do limite superior de 99% (SP 800-90B 6.3.1)
MCV_SYMBOL_BITS = 8    # tamanho do simbolo do segundo estimador

# --- Dia 3: teste de saude pela H estimada (escolha de projeto, nao derivada) ---
H_MIN_HEALTH = 0.9

# --- Dia 3: testes estatisticos do SP 800-22 (PROJECT.md 6.6) ---
STATS_P_MIN = 0.01          # aprova se p-valor >= 0,01
STATS_BLOCK_M = 128         # bloco do teste por bloco (padrao do NIST STS)
STATS_MIN_BITS = 1_000_000  # abaixo disso: inconclusivo, nao aprovado

# --- Dia 3: replay e relatorio de lote ---
REPLAY_BLOCK_BITS = 4096       # blocos comparados na deteccao de replay
H_DECLARED_DEFAULT = 1.0     # H declarada usada por RCT e APT

# --- Dia 4: pipeline e mixer ---
MIN_LOCAL_OUTPUT_BITS = 8 * SEED_BYTES
DEFAULT_N_BITS = 1_000_000
SEED_READ_BITS = 2 * EXTRACTOR_INPUT_BITS

# --- Derivação de chaves PQC (Dia 5, PROJECT.md seção 6.10) ---
# Prefixos de separação de domínio: o mesmo seed gera material
# independente para cada algoritmo.
KEM_DOMAIN: bytes = b"EAL-v1|ML-KEM-768|"
DSA_DOMAIN: bytes = b"EAL-v1|ML-DSA-65|"

# Tamanhos do material interno exigido pelos padrões.
KEM_SEED_BYTES: int = 64  # d || z, FIPS 203
DSA_SEED_BYTES: int = 32  # xi, FIPS 204

# --- Recibo (Dia 5, PROJECT.md seção 6.11) ---
DSA_PK_BYTES: int = 1952
DSA_SIG_BYTES: int = 3309
RECEIPT_CTX: bytes = b"EAL-v1|receipt"  # contexto ML-DSA (FIPS 204) das assinaturas de recibo
RECEIPT_SIG_ALG: str = "ML-DSA-65"
GENESIS_PREV_HASH: str = "0" * 64  # prev_receipt_hash do primeiro recibo
RECEIPT_REQUIRED_LIMITATIONS: tuple[str, ...] = (
    "prototype",
    "no_sp800_90b_claim",
    "no_quantum_origin_claim",
    "chsh_is_sanity_check_only",
    "pqc_pure_python_not_constant_time",
    "issuer_key_unencrypted_on_disk",
)
ISSUER_SK_NAME: str = "issuer_ml_dsa_65.sk"
ISSUER_PK_NAME: str = "issuer_ml_dsa_65.pk"
