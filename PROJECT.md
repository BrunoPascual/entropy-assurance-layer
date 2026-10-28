# Entropy Assurance Layer (EAL) — Brief do projeto

- **Versão do documento:** 1.0
- **Data:** 27/10/2026
- **Autor:** Bruno Pascual
- **Status:** Dia 1 de 9 (fase de fundação)
- **Documento irmão:** `THREAT_MODEL.md` (modelo de ameaça)

> Este arquivo é a fonte de verdade do projeto. Cole-o no início de cada sessão com a IA.
> Se algo no código contradizer este documento, o documento vence, ou ele é atualizado primeiro.

---

## 1. Resumo em uma frase

A EAL é uma camada de software que coleta bits aleatórios de várias fontes (sistema operacional, simulador de QPU e QPU real da IBM), testa a qualidade de cada lote, mistura apenas as fontes aprovadas, deriva chaves pós-quânticas (ML-KEM-768 e ML-DSA-65) a partir da semente resultante e emite um **recibo assinado** que registra de onde a aleatoriedade veio e quais testes ela passou.

É um **protótipo de pesquisa**, não um produto de produção.

---

## 2. Problema

1. Toda chave criptográfica nasce de números aleatórios. Se eles forem previsíveis, a criptografia é quebrada mesmo que o algoritmo esteja correto.
2. Falhas históricas de aleatoriedade foram de **fonte ou semeadura**, não de algoritmo: o bug do OpenSSL no Debian (2008), chaves RSA repetidas em dispositivos de rede (2012) e o gerador Dual_EC_DRBG com suspeita de backdoor.
3. Equipes de segurança raramente conseguem **provar** de onde veio a aleatoriedade usada numa chave e que ela foi testada. Auditorias (FIPS 140-3, NIST SP 800-90B) pedem essa evidência.
4. A migração para criptografia pós-quântica **não resolve** o problema: ML-KEM e ML-DSA também consomem aleatoriedade, e se ela for previsível, o segredo também é.
5. Fontes quânticas (QRNG) existem, mas confiar nelas exige método: viés de hardware, ruído, deriva e, no caso de nuvem, a confiança no provedor.

---

## 3. Posicionamento e concorrência

**O que a EAL é:** uma **camada de garantia neutra**, que aceita qualquer fonte de bits, mais um **estudo aberto e reproduzível** de quão boas são QPUs públicas como fonte de entropia.

**O que a EAL não é:** um "serviço de bits quânticos". Esse mercado já existe:

- **Quantinuum Quantum Origin:** QRNG em software, com semente gerada em computador quântico e refino local da entropia; validado no NIST SP 800-90B (abril de 2025).
- **ID Quantique (controlada pela IonQ desde maio de 2025):** chips e dispositivos QRNG, incluindo os usados nos celulares Samsung Galaxy Quantum.
- **Outros fornecedores:** Quside, QuintessenceLabs, Crypta Labs, KETS, Qrypt, Quantum eMotion.

**Diferencial da EAL:**

1. Neutra em relação à fonte (qualquer fonte entra por um adaptador).
2. Recibo de auditoria por chave gerada.
3. Dados abertos sobre QPUs públicas (viés, correlação, deriva).
4. Integração direta com geração de chaves PQC.
5. Arquitetura pronta para evoluir para chip QRNG local (roadmap).

---

## 4. Escopo

### 4.1 Entra nos 9 dias

- Fontes: sistema operacional, simulador de QPU com ruído (Qiskit Aer), QPU real IBM e 5 fontes defeituosas simuladas.
- Testes de saúde contínuos do NIST SP 800-90B: Repetition Count Test (RCT) e Adaptive Proportion Test (APT).
- Estimativa conservadora de min-entropia.
- 3 testes estatísticos do NIST SP 800-22: frequência (monobit), frequência por bloco e sequências (runs).
- Extrator Toeplitz e mistura por hash (SHA3-512).
- Derivação determinística de ML-KEM-768 e ML-DSA-65 a partir da semente.
- Recibo JSON assinado com ML-DSA-65, encadeado por hash.
- Linha de comando (CLI) e painel Streamlit de uma página.
- 5 experimentos (E1 a E5) e relatório final.

### 4.2 Fica fora (roadmap futuro)

- Certificação NIST, FIPS 140-3, Common Criteria ou AIS 31.
- Chip QRNG local, porte para C ou Rust, firmware embarcado.
- Segurança de produção: as bibliotecas PQC em Python puro servem para protótipo.
- Outros provedores de QPU (AWS Braket só se sobrar tempo).
- Login, banco de dados, deploy, API pública (FastAPI é opcional e o primeiro corte).
- QKD, inventário criptográfico, risco por dependências.

---

## 5. Arquitetura

```
                 ┌──────────────────────────┐
                 │       Fontes de bits      │
                 │  os │ qpu_sim │ qpu_ibm   │
                 │  faulty (só em testes)    │
                 └────────────┬─────────────┘
                              │ RawBatch (bits + metadados)
                              ▼
                 ┌──────────────────────────┐
                 │     Testes de saúde       │  RCT, APT, min-entropia,
                 │   (por fonte, por lote)   │  3 testes SP 800-22
                 └──────┬─────────────┬─────┘
                aprovada│             │reprovada
                        ▼             ▼
       ┌──────────────────────┐   excluída e registrada
       │  Extrator Toeplitz   │   (entra no recibo como reprovada)
       │  (por fonte)         │
       └──────────┬───────────┘
                  ▼
       ┌──────────────────────┐
       │  Mixer SHA3-512      │  política: ≥ 1 fonte local aprovada
       │  (fail-closed)       │  senão: nenhuma semente é gerada
       └──────────┬───────────┘
                  ▼ semente de 64 bytes (nunca sai do processo)
       ┌──────────────────────┐
       │  Derivação PQC       │  ML-KEM-768, ML-DSA-65
       └──────────┬───────────┘
                  ▼
       ┌──────────────────────┐
       │  Recibo assinado     │  só hashes; assinado com ML-DSA-65;
       │  + cadeia de hashes  │  encadeado ao recibo anterior
       └──────────────────────┘
```

---

## 6. Componentes e contratos

### 6.1 Interface de fonte (`eal/sources/base.py`)

Toda fonte implementa o mesmo contrato. O resto do sistema não sabe se os bits vieram do sistema operacional, de um simulador ou de um chip.

```python
from abc import ABC, abstractmethod

class Source(ABC):
    source_id: str        # ex.: "os", "qpu_sim", "ibm_kingston", "faulty_biased"
    source_type: str      # "os" | "qpu_sim" | "qpu_ibm" | "faulty"
    is_local: bool        # True se os bits nunca saíram da máquina
    is_simulated: bool    # True para simulador e fontes defeituosas

    @abstractmethod
    def read(self, n_bits: int) -> "RawBatch":
        """Retorna exatamente n_bits bits crus, com metadados."""
```

### 6.2 Lote cru (`RawBatch`)

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `batch_id` | str | UUID do lote |
| `source_id` | str | Identificador da fonte |
| `source_type` | str | Tipo da fonte |
| `source_version` | str | Versão do adaptador e, se houver, do SDK |
| `is_local` / `is_simulated` | bool | Copiados da fonte |
| `bits` | `numpy.ndarray[uint8]` | Valores 0/1, um por posição |
| `n_bits` | int | Quantidade de bits |
| `created_at` | str | ISO 8601 em UTC |
| `params` | dict | Ex.: backend, qubits, shots, job_id, modelo de ruído |
| `batch_hash` | str | SHA3-256 de `n_bits` (8 bytes, big-endian) seguido dos bits empacotados com `numpy.packbits` (detecção de replay e de alteração) |

### 6.3 Fontes

| `source_id` | Tipo | Local? | Simulada? | Uso |
| --- | --- | --- | --- | --- |
| `os` | os | sim | não | Fonte de referência (`os.urandom` / `secrets`) |
| `qpu_sim` | qpu_sim | sim | **sim** | Desenvolvimento e experimentos; Hadamard em N qubits no Qiskit Aer com modelo de ruído |
| `ibm_<backend>` | qpu_ibm | **não** | não | QPU real; só via script de coleta com limite de orçamento |
| `faulty_biased` | faulty | sim | sim | Probabilidade de 1 ≠ 0,5 (parâmetro `p`) |
| `faulty_stuck` | faulty | sim | sim | Trechos de bits travados (parâmetro `run_length`) |
| `faulty_replay` | faulty | sim | sim | Repete um lote anterior |
| `faulty_prng` | faulty | sim | sim | Mersenne Twister com semente fixa, disfarçado de QPU |
| `faulty_correlated` | faulty | sim | sim | Bit depende do anterior com probabilidade `rho` |

**Atenção:** o simulador Qiskit Aer gera resultados com um gerador pseudoaleatório **clássico**. A fonte `qpu_sim` **nunca** conta como entropia real para gerar chaves. Ela existe para desenvolver e para os experimentos.

### 6.4 Testes de saúde contínuos (`eal/health/continuous.py`)

Seguem a seção 4.4 do NIST SP 800-90B, aplicados a cada lote.

**Parâmetros fixos:**

- Taxa de falso alarme por teste: `α = 2^-20`.
- `H` = min-entropia por bit declarada ou estimada para a fonte (≤ 1).

**Repetition Count Test (RCT):** detecta bits travados.

- Limite: `C = 1 + ceil(-log2(α) / H)`.
- Exemplo: com `H = 1`, `C = 21`; com `H = 0,9`, `C = 24`.
- Falha se algum valor se repetir `C` ou mais vezes seguidas.

**Adaptive Proportion Test (APT):** detecta viés persistente.

- Janela para dados binários: `W = 1024`.
- Limite: `C = 1 + CRITBINOM(W, 2^-H, 1 - α)`, calculado com `scipy.stats.binom.ppf(1 - α, W, 2**-H)` + 1.
- Para cada janela: toma o primeiro bit e conta quantas vezes ele aparece na janela; falha se a contagem ≥ `C`.

**Detecção de replay (complementar, não faz parte do SP 800-90B):** guarda o `batch_hash` de cada lote e de blocos de 4096 bits; falha se algum se repetir.

### 6.5 Estimativa de min-entropia (`eal/health/min_entropy.py`)

Usa o **mínimo** de dois estimadores, para ser conservadora:

1. **Valor mais comum (MCV), por bit** (SP 800-90B, seção 6.3.1):
   - `p̂ = contagem_máxima / L`
   - `p_u = min(1, p̂ + 2,576 · sqrt(p̂ · (1 - p̂) / (L - 1)))`
   - `H_bit = -log2(p_u)`
2. **MCV em símbolos de 8 bits**, dividido por 8. Captura correlação entre bits vizinhos que o estimador por bit não vê.

`H_estimada = min(H_bit, H_byte / 8)`.

Esta é uma estimativa simplificada. O projeto **não alega conformidade** com o SP 800-90B. Se houver tempo, compare com a ferramenta oficial de avaliação de entropia do NIST (confirmar disponibilidade no GitHub do NIST antes de usar).

### 6.6 Testes estatísticos (`eal/health/stats_tests.py`)

Do NIST SP 800-22, aplicados em lotes de pelo menos 1.000.000 de bits quando houver dados suficientes:

| Teste | O que detecta | Aprovado se |
| --- | --- | --- |
| Frequência (monobit) | Excesso de 0 ou de 1 | p-valor ≥ 0,01 |
| Frequência por bloco (M = 128) | Viés local | p-valor ≥ 0,01 |
| Sequências (runs) | Alternância anormal | p-valor ≥ 0,01 |

Esses testes **não provam** aleatoriedade: um bom gerador pseudoaleatório passa em todos.

### 6.7 Relatório de lote (`HealthReport`)

| Campo | Descrição |
| --- | --- |
| `batch_id`, `source_id` | Referências |
| `rct_pass`, `rct_cutoff`, `rct_max_run` | Resultado do RCT |
| `apt_pass`, `apt_cutoff`, `apt_max_count` | Resultado do APT |
| `replay_pass` | Sem repetição de lote ou bloco |
| `h_bit`, `h_byte`, `h_estimated` | Estimativas de min-entropia |
| `stats` | p-valores dos 3 testes |
| `approved` | `True` somente se todos os testes passaram |
| `reasons` | Lista de motivos de reprovação |

### 6.8 Extrator Toeplitz (`eal/extract/toeplitz.py`)

- Entrada por bloco: `n = 2048` bits crus.
- Min-entropia do bloco: `k = n · H_estimada`.
- Erro do extrator: `ε = 2^-64`.
- Saída por bloco (lema do hash residual): `m = floor(k) - 2 · log2(1/ε) = floor(k) - 128`.
  - Exemplo: `H = 0,9` → `k = 1843` → `m = 1715` bits.
- Se `m ≤ 0`, o bloco é descartado.
- Matriz Toeplitz `m × n` definida por uma semente de `n + m - 1` bits **uniformes e independentes da fonte**, tirada da fonte `os` no início de cada execução. O SHA3-256 dessa semente vai para o recibo.
- Operação: `saída = (T · x) mod 2`. Com `n = 2048`, a matriz cabe em memória (`scipy.linalg.toeplitz` + NumPy).
- Alternativa para comparação (opcional, primeiro corte): condicionamento com SHA3-512.

### 6.9 Mixer (`eal/mix/mixer.py`)

**Política (fail-closed):**

1. Só entram fontes com `approved = True`.
2. É obrigatório **pelo menos 1 fonte local aprovada e não simulada** (na prática, `os`). Motivo: o provedor da QPU conhece os bits que gerou.
3. Fontes simuladas só entram em modo experimento, nunca em modo de geração de chave real.
4. Se a política não for satisfeita, **nenhuma semente é gerada** e o erro é registrado.

**Combinação:**

```
semente = SHA3-512(
    "EAL-v1-mix" ||
    para cada fonte aprovada, em ordem alfabética de source_id:
        len(source_id) || source_id || len(saida) || saida_extraida
)
```

- Saída: 64 bytes.
- Por que hash e não XOR: no XOR, uma fonte adversária que vê as outras pode cancelar a entropia. A combinação por hash resiste melhor (testado no E4).

### 6.10 Derivação de chaves (`eal/pqc/keygen.py`)

Determinística a partir da semente, com separação de domínio:

| Algoritmo | Entrada interna (padrão) | Derivação |
| --- | --- | --- |
| ML-KEM-768 (FIPS 203) | `d` e `z`, 32 bytes cada | `d‖z = SHAKE256("EAL-v1|ML-KEM-768|" ‖ semente, 64 bytes)` |
| ML-DSA-65 (FIPS 204) | `ξ`, 32 bytes | `ξ = SHAKE256("EAL-v1|ML-DSA-65|" ‖ semente, 32 bytes)` |

- Biblioteca preferida para o protótipo: `kyber-py` e `dilithium-py` (Python puro, instalação fácil). **Confirmar** se expõem derivação a partir de semente (`key_derive` ou equivalente) antes de escrever o código.
- Alternativa: `liboqs-python` (mais difícil de instalar no Windows).
- Teste obrigatório: encapsular e decapsular (ML-KEM), assinar e verificar (ML-DSA), e a mesma semente gerar sempre as mesmas chaves.
- Chaves privadas derivadas **não são gravadas em disco**, exceto com a opção explícita `--export-demo`, apenas para demonstração.

### 6.11 Recibo (`eal/receipt/`)

**Chave do emissor:** um par ML-DSA-65 separado, gerado uma vez a partir da fonte `os`. A chave privada fica em `keys/issuer_ml_dsa_65.sk` (no `.gitignore`); a pública em `keys/issuer_ml_dsa_65.pk`.

**Exemplo de recibo:**

```json
{
  "eal_version": "0.1.0",
  "receipt_id": "3f2b1c9e-0000-0000-0000-000000000000",
  "created_at": "2026-10-28T14:03:12Z",
  "mode": "keygen",
  "prev_receipt_hash": "sha3-256 do recibo anterior, ou 64 zeros no primeiro",
  "sources": [
    {
      "source_id": "os",
      "source_type": "os",
      "is_local": true,
      "is_simulated": false,
      "batch_hash": "…",
      "n_bits": 1048576,
      "health": {"rct_pass": true, "apt_pass": true, "replay_pass": true, "h_estimated": 0.998, "stats": {"monobit": 0.41, "block": 0.73, "runs": 0.22}},
      "approved": true
    },
    {
      "source_id": "ibm_kingston",
      "source_type": "qpu_ibm",
      "is_local": false,
      "is_simulated": false,
      "params": {"job_id": "…", "qubits": 156, "shots": 4096},
      "batch_hash": "…",
      "health": {"…": "…"},
      "approved": true
    }
  ],
  "extractor": {"type": "toeplitz", "n": 2048, "epsilon_log2": -64, "seed_hash": "…"},
  "mixer": {"type": "sha3-512", "inputs": ["ibm_kingston", "os"], "policy": "min_local_non_simulated=1"},
  "seed_hash": "sha3-256 da semente",
  "keys": {"ml_kem_768_pk_hash": "…", "ml_dsa_65_pk_hash": "…"},
  "limitations": ["prototype", "no_sp800_90b_claim", "chsh_is_sanity_check_only"],
  "signature": {"alg": "ML-DSA-65", "issuer_pk_hash": "…", "value": "base64…"}
}
```

**Regras:**

1. O recibo contém **somente hashes**, nunca a semente nem chaves privadas.
2. A assinatura cobre o JSON canônico de todos os campos exceto `signature` (chaves ordenadas, sem espaços, UTF-8).
3. `prev_receipt_hash` encadeia os recibos; o log fica em `data/receipts/chain.jsonl`.
4. Verificação (`eal verify`): recalcula o JSON canônico, confere a assinatura com a chave pública do emissor e confere o encadeamento.

### 6.12 Linha de comando (`eal/cli.py`)

| Comando | Faz |
| --- | --- |
| `py -3.12 -m eal run --sources os,qpu_sim --bits 1048576` | Pipeline completo, gera chaves e recibo |
| `py -3.12 -m eal verify data/receipts/<id>.json` | Verifica assinatura e cadeia |
| `py -3.12 -m eal collect-ibm --qubits 156 --shots 4096 --budget-seconds 30` | Coleta na QPU real com limite duro |
| `py -3.12 -m eal health data/raw/<arquivo>.npy` | Roda só os testes num arquivo |
| `py -3.12 -m eal experiment e2` | Roda um experimento |

### 6.13 Painel (`dashboard/app.py`)

Uma página em Streamlit: fontes e status, saúde por lote, min-entropia por fonte, viés por qubit, último recibo (com botão de verificação) e gráficos dos experimentos. Rodar com `py -3.12 -m streamlit run dashboard/app.py`.

---

## 7. Estrutura de pastas

```
EntropyAssuranceLayer/
├── PROJECT.md
├── THREAT_MODEL.md
├── README.md
├── requirements.txt
├── .env                    # token IBM (nunca no Git)
├── .gitignore
├── eal/
│   ├── __init__.py
│   ├── __main__.py         # permite "py -3.12 -m eal"
│   ├── cli.py
│   ├── config.py           # constantes: α, W, n, ε, orçamento
│   ├── storage.py          # gravação e leitura de lotes em data/raw/
│   ├── sources/            # base.py, os_source.py, qpu_sim.py, qpu_ibm.py, faulty.py
│   ├── health/             # continuous.py, min_entropy.py, stats_tests.py, report.py
│   ├── extract/            # toeplitz.py, sha3.py
│   ├── mix/                # mixer.py
│   ├── pqc/                # keygen.py
│   └── receipt/            # schema.py, sign.py, verify.py, chain.py
├── experiments/            # e1_quality.py … e5_chsh.py
├── dashboard/
│   └── app.py
├── tests/                  # test_sources.py, test_health.py, test_extract.py, …
├── data/
│   ├── raw/                # bits crus (.npy) + metadados (.json)
│   ├── results/            # CSVs dos experimentos
│   ├── receipts/           # recibos e chain.jsonl
│   └── logs/               # qpu_usage.csv
├── keys/                   # chave do emissor (.sk no .gitignore)
└── scratch/                # testes soltos: teste_qiskit.py, teste_ibm.py
```

**`.gitignore` mínimo:**

```
.env
.venv/
__pycache__/
keys/*.sk
data/raw/
*.pyc
```

---

## 8. Ambiente

### 8.1 Situação confirmada no Dia 1

- Sistema: Windows 11, PowerShell.
- Python do projeto: **3.12.10**, instalado pelo Python Install Manager, chamado sempre com **`py -3.12`**.
- Também existe o Python 3.15.2 como padrão da máquina. **Nunca** use `python` ou `py` sem `-3.12`.
- **Sem ambiente virtual:** a criação do `.venv` falhou com `WinError 2` (causa não resolvida). As bibliotecas estão instaladas direto no Python 3.12.
- VS Code: interpretador selecionado = Python 3.12.10.

### 8.2 Versões instaladas e confirmadas

| Pacote | Versão |
| --- | --- |
| qiskit | 2.6.1 |
| qiskit-aer | 0.18.2 |
| qiskit-ibm-runtime | 0.51.0 |
| python-dotenv | 1.2.4 |
| numpy | 2.5.4 |
| scipy | 1.18.1 |
| cryptography | 50.0.2 |

### 8.3 `requirements.txt`

```
qiskit==2.6.1
qiskit-aer==0.18.2
qiskit-ibm-runtime==0.51.0
python-dotenv==1.2.4
numpy==2.5.4
scipy==1.18.1
# a adicionar e fixar a versão depois de instalar:
# pandas, matplotlib, streamlit, pytest, kyber-py, dilithium-py
```

Instalação: `py -3.12 -m pip install -r requirements.txt`. Sempre que instalar algo novo, fixe a versão aqui.

---

## 9. QPU IBM e orçamento

### 9.1 Conta

- Plano: Open Plan (gratuito).
- Canal: `ibm_quantum_platform`.
- Instância: `open-instance` (passar explicitamente para evitar o aviso).
- Token: em `.env`, variável `IBM_QUANTUM_TOKEN`.
- Limite: cerca de 10 minutos de execução por janela móvel de 28 dias; só conta o tempo no chip, não a fila. Plano pago: US$ 96 por minuto. **Conferir o saldo no painel da IBM antes de cada coleta.**

### 9.2 Primeiro job (Dia 1)

| Campo | Valor |
| --- | --- |
| Backend | ibm_kingston |
| Circuito | 1 qubit, Hadamard + medição |
| Shots | 128 |
| Job ID | dbgiga4dgr2s73crj1h0 |
| Resultado | `{'0': 31, '1': 97}` |

**Primeiro achado:** 97 de 128 é cerca de 76% de "1". Para uma moeda justa, isso fica a cerca de 5,8 desvios-padrão de 64, então não é acaso: há viés real nesse qubit físico, provavelmente erro de leitura. É exatamente o que o E1 vai medir em escala.

### 9.3 Orçamento planejado

| Uso | Dia | Minutos |
| --- | --- | --- |
| Teste de acesso (feito) | 1 | 0,2 |
| Calibração do consumo real por job | 6 | 0,5 |
| Coleta 1 (principal) | 6 | 3,0 |
| Coleta 2 (outro horário) | 6 | 2,0 |
| Coleta 3 (deriva entre dias) | 7 | 1,5 |
| CHSH no hardware | 7 | 0,5 |
| Reserva | — | 2,3 |

### 9.4 Regras

1. Nunca depurar na QPU real. Tudo roda antes no simulador e num backend falso.
2. Todo envio passa por `qpu_ibm.py`, que tem **limite duro**: recusa o job se o consumo acumulado do dia passar do orçamento.
3. Cada job é registrado em `data/logs/qpu_usage.csv`: data, backend, qubits, shots, job_id, tempo de QPU (campo de uso informado pelo Runtime; confirmar o nome na documentação), arquivo de saída.
4. Dados crus de QPU são salvos **antes** de qualquer processamento.
5. `SamplerV2` está marcado como obsoleto desde o qiskit-ibm-runtime 0.50. Decisão: manter no protótipo enquanto funcionar, isolado em `qpu_ibm.py`, para trocar pelo novo `Sampler` num só arquivo.
6. Cada shot de N qubits gera N bits. Com 156 qubits e 4.096 shots: cerca de 639 mil bits por job. Guardar também o **mapa qubit → posição do bit**, para analisar viés por qubit.

---

## 10. Experimentos

| # | Pergunta | Método | Métricas | Saída |
| --- | --- | --- | --- | --- |
| E1 | Quão boa é a QPU como fonte? | `qpu_sim` com ruído vs QPU real vs `os`, em 3 sessões | Viés por qubit, correlação entre vizinhos, `h_estimated`, deriva entre sessões | `data/results/e1_*.csv` |
| E2 | O sistema detecta fontes ruins? | 5 fontes defeituosas × intensidades × tamanhos de lote, centenas de lotes | Taxa de detecção, falsos positivos (na `os`) | `data/results/e2_*.csv` |
| E3 | Quanto custa e rende? | Bits por job e por segundo de QPU | Bits/s de QPU, custo por megabit a US$ 96/min | `data/results/e3_*.csv` |
| E4 | A mistura resiste? | Falha ou viés de uma fonte; fonte adversária que vê as outras; XOR vs hash | Saída aprovada por cenário | `data/results/e4_*.csv` |
| E5 | CHSH ajuda? | S no simulador sem ruído, com ruído, QPU real e gerador clássico | S (limite clássico 2; máximo quântico 2√2 ≈ 2,83) | `data/results/e5_*.csv` |

**Ângulos do CHSH:** Alice mede em 0 e π/2; Bob em π/4 e −π/4. `S = E(a0,b0) + E(a0,b1) + E(a1,b0) − E(a1,b1)`.

**Hipóteses** (a medir, não provadas):

- E1: viés pequeno mas mensurável na QPU real; `h_estimated` abaixo de 1.
- E2: viés, travamento e replay detectados; gerador clássico disfarçado **passa** (limitação fundamental de testar saída).
- E3: muito mais caro que a fonte `os`.
- E4: com 1 fonte boa e independente, saída boa; XOR frágil contra fonte adversária.
- E5: simulador sem ruído ≈ 2,83; QPU real entre 2 e 2,83; clássico ≤ 2. Serve só como verificação de sanidade.

---

## 11. Convenções de dados

- **Bits crus:** `numpy.packbits` em `.npy`, com arquivo `.json` irmão de metadados (campos do `RawBatch` exceto `bits`).
- **Nomes:** `AAAA-MM-DD_<source_id>_<sessao>_<n>.npy`, por exemplo `2026-11-02_ibm_kingston_s1_003.npy`.
- **Resultados:** CSV com cabeçalho, uma linha por lote ou cenário.
- **Reprodutibilidade:** fontes simuladas e defeituosas usam semente fixa registrada no CSV. A fonte `os` e a QPU real, por natureza, não são reprodutíveis; por isso os dados crus são guardados.
- **Todo número do relatório sai de um arquivo em `data/results/` gerado por script.** Nada digitado à mão.

---

## 12. Regras de código

1. Python 3.12, rodado sempre com `py -3.12`.
2. Código e nomes em inglês; comentários e mensagens podem ser em português.
3. Tipos nos parâmetros e retornos; docstring curta em toda função pública.
4. Funções curtas (alvo: até 50 linhas); sem estado global; constantes em `eal/config.py`.
5. Aleatoriedade **somente** através das fontes. Proibido `random` do Python fora de `faulty.py`.
6. Todo módulo vem com testes `pytest`. Nada está pronto sem teste verde.
7. Testes com **respostas conhecidas** nos pontos críticos: limites RCT/APT, estimador MCV, extrator (dimensões e linearidade), derivação de chaves (mesma semente, mesmas chaves), assinatura do recibo.
8. Um módulo por tarefa; commit a cada passo verde.
9. Nenhum `print` de semente, chave privada ou token, nem em modo de depuração.

---

## 13. Regras de segurança

1. Token IBM só no `.env`; `.env` no `.gitignore`. Se o token aparecer em chat, print ou arquivo público, gerar outro na IBM.
2. Chave privada do emissor só em `keys/*.sk`, no `.gitignore`.
3. Semente e chaves derivadas vivem só em memória; recibo só com hashes.
4. A QPU nunca é a única fonte de uma semente usada como chave.
5. Fontes simuladas nunca entram em modo `keygen`.
6. Linguagem honesta em todos os resultados (ver seção 9 do `THREAT_MODEL.md`).

---

## 14. Como trabalhar com a IA

**Papéis:** a IA escreve; eu decido, rodo, leio a saída e faço commit.

**Ciclo por tarefa:**

1. Pedir plano antes de código (até 5 linhas, arquivos afetados, como testar).
2. Código junto com testes, um módulo por vez.
3. Rodar `py -3.12 -m pytest`; só avançar com verde.
4. Erro: colar a mensagem inteira e pedir diagnóstico antes da correção.
5. Pedir resumo em português do que mudou e do que pode estar errado.
6. Commit.

**Nos pontos críticos** (testes de saúde, min-entropia, extrator, derivação de chaves, CHSH): pedir que a IA cite a especificação e a seção, e fazer revisão adversarial no fim do módulo.

**Abertura de cada sessão:**

```
Leia o PROJECT.md e o THREAT_MODEL.md. Hoje é o Dia N. Tarefa: <tarefa>.
Não escreva código ainda. Proponha o plano em até 5 linhas, os arquivos que vai criar ou mudar e como vamos testar.
Lembre: Windows, PowerShell, sempre "py -3.12", sem ambiente virtual.
```

---

## 15. Definição de pronto

Uma tarefa está pronta quando:

1. O código roda com `py -3.12`.
2. Os testes passam (`py -3.12 -m pytest`).
3. Nenhum segredo aparece em saída, log ou arquivo versionado.
4. O que foi medido está salvo em `data/`.
5. Há commit com mensagem descritiva.
6. Limitações novas foram anotadas na seção 17.

---

## 16. Plano dos 9 dias (resumo)

| Dia | Foco | Gate |
| --- | --- | --- |
| 1 | Fundação: ambiente, conta IBM, brief, modelo de ameaça, estrutura | `pytest` verde, job de 1 qubit rodou, brief pronto |
| 2 | Fontes de bits e simulador com ruído | 5 fontes geram 1 milhão de bits cada em menos de 5 min |
| 3 | Testes de saúde e min-entropia | Reprova viesada, travada e replay; aprova `os` |
| 4 | Extrator, mixer, semente | Pipeline completo no simulador até a semente |
| 5 | Chaves PQC e recibo | Um comando gera chaves e recibo; outro verifica |
| 6 | Coleta na QPU real | 2 a 3 milhões de bits reais salvos, se o orçamento permitir |
| 7 | Experimentos E1 a E5 | Tabela com os 5 resultados |
| 8 | Painel e relatório | Painel abre com dados reais; relatório completo |
| 9 | Entrega: one-pager, demo, README, roadmap | Outra pessoa roda tudo só com o README |

**Ordem de cortes, se atrasar:** FastAPI → log encadeado → alternativa SHA3 → coleta 3 e CHSH no hardware → painel vira relatório estático.

**Nunca cortar:** fontes, testes de saúde, mixer, chaves PQC, recibo e dados reais da QPU.

---

## 17. Limitações conhecidas

1. Protótipo de pesquisa; não usar para proteger dados reais.
2. Estimativa de min-entropia simplificada; sem alegação de conformidade com SP 800-90B.
3. Bibliotecas PQC em Python puro: sem tempo constante, sem auditoria.
4. O provedor da QPU conhece os bits que gerou.
5. CHSH numa QPU em nuvem não é teste de Bell sem brechas.
6. O simulador é um gerador clássico.
7. Ambiente sem `.venv` (problema não resolvido no Windows).
8. Orçamento de QPU limita o tamanho das amostras reais.

---

## 18. Glossário

| Termo | Significado |
| --- | --- |
| Entropia | Medida de imprevisibilidade |
| Min-entropia | Entropia do pior caso: quanto vale o palpite mais provável; é a medida usada em criptografia |
| Viés | Desvio de 50/50 entre 0 e 1 |
| Extrator | Função que transforma bits imperfeitos em menos bits quase uniformes |
| Semente | Valor de 64 bytes que alimenta a derivação de chaves |
| Fail-closed | Na dúvida, o sistema não gera nada |
| QPU | Processador quântico |
| Shot | Uma execução do circuito; gera 1 bit por qubit medido |
| Backend | Máquina (real ou simulada) que roda o circuito |
| KEM | Mecanismo de encapsulamento de chave (ML-KEM) |
| CHSH | Teste de Bell com dois qubits; mede correlações que nenhum modelo clássico local passa de 2 |
| Recibo | Registro assinado de como uma semente e suas chaves foram produzidas |
| RCT / APT | Testes contínuos de saúde do SP 800-90B |

---

## 19. Referências

- NIST FIPS 203 (ML-KEM): https://csrc.nist.gov/pubs/fips/203/final
- NIST FIPS 204 (ML-DSA): https://csrc.nist.gov/pubs/fips/204/final
- NIST SP 800-90B (fontes de entropia): https://csrc.nist.gov/pubs/sp/800/90/b/final
- NIST SP 800-22 Rev. 1a (testes estatísticos): https://csrc.nist.gov/pubs/sp/800/22/r1/upd1/final
- IBM Quantum Platform, planos: https://quantum.cloud.ibm.com/docs/guides/plans-overview
- IBM Quantum, preços: https://www.ibm.com/quantum/pricing
- Quantinuum Quantum Origin: https://docs.quantinuum.com/origin/user_guides/introduction/how-quantum-origin-works.html
- NCSC, tecnologias de segurança quântica: https://www.ncsc.gov.uk/paper/quantum-security-technologies

Confirme os links e as versões de API antes de depender deles; planos, preços e APIs mudam.
+-- scripts/                # plot_bias.py (gr�fico de vi�s por qubit, Dia 2)
