# Entropy Assurance Layer (EAL) — Brief do projeto

- **Versão do documento:** 1.0
- **Data:** 27/10/2026
- **Autor:** Bruno Pascual
- **Status:** Dia 5 de 9 (concluído; gate do Dia 5 aprovado, ver seção 16.3; revisão adversarial na seção 16.4)
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
| `params` | dict | Ex.: backend, qubits, shots, job_id, modelo de ruído. Só as chaves da lista fechada de `eal/config.py` (`RECEIPT_BATCH_PARAM_*`) chegam ao recibo (G6) |
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

- Taxa de falso alarme (α) por amostra no RCT e por janela no APT. Valores separados: RCT `α = 2^-40`, APT `α = 2^-20`.
- `H` = min-entropia por bit declarada ou estimada para a fonte (≤ 1).

**Repetition Count Test (RCT):** detecta bits travados.

- Limite: `C = 1 + ceil(-log2(α) / H)`.
- Exemplo: com `H = 1`, `C = 41`; com `H = 0,9`, `C = 46` (α = 2^-40).
- Falha se algum valor se repetir `C` ou mais vezes seguidas.

**Adaptive Proportion Test (APT):** detecta viés persistente.

- Janela para dados binários: `W = 1024`.
- Limite: `C = 1 + CRITBINOM(W, 2^-H, 1 - α)`, calculado com `scipy.stats.binom.ppf(1 - α, W, 2**-H)` + 1.
- Para cada janela: toma o primeiro bit e conta quantas vezes ele aparece na janela; falha se a contagem ≥ `C`.

**Detecção de replay (complementar, não faz parte do SP 800-90B):** guarda o `batch_hash` de cada lote e de blocos de 4096 bits; falha se algum se repetir.

**Justificativa dos α (medida, não suposta).** Num lote de 1.000.000 de bits há cerca de 500 mil sequências testadas pelo RCT. Com `α = 2^-20` e `H = 1` (`C = 21`), o falso alarme por lote fica perto de 38% mesmo para fonte justa, o que inviabiliza o gate. Com `α = 2^-40` (`C = 41`), fica perto de 5 × 10^-7 por lote e o RCT ainda pega o trecho travado de 64 bits. No APT, `α = 2^-20` dá cerca de 8 × 10^-4 de falso alarme por lote (976 janelas) e pega viés p = 0,55. Os dois valores ficam dentro da faixa 2^-40 a 2^-20 do SP 800-90B. Valores em `eal/config.py`.

**Limitação do lote.** O APT só testa janelas completas de 1024 bits. Em 1.000.000 de bits, 576 bits ficam de fora e são registrados em `discarded_bits`.

### 6.5 Estimativa de min-entropia (`eal/health/min_entropy.py`)

Usa o **mínimo** de dois estimadores, para ser conservadora:

1. **Valor mais comum (MCV), por bit** (SP 800-90B, seção 6.3.1):
   - `p̂ = contagem_máxima / L`
   - `p_u = min(1, p̂ + 2,576 · sqrt(p̂ · (1 - p̂) / (L - 1)))`
   - `H_bit = -log2(p_u)`
2. **MCV em símbolos de 8 bits**, dividido por 8. Captura correlação entre bits vizinhos que o estimador por bit não vê.

`H_estimada = min(H_bit, H_byte / 8)`.

Esta é uma estimativa simplificada. O projeto **não alega conformidade** com o SP 800-90B. Se houver tempo, compare com a ferramenta oficial de avaliação de entropia do NIST (confirmar disponibilidade no GitHub do NIST antes de usar).

**Uso da min-entropia nos testes (decisão do Dia 3).**

- Os testes RCT e APT usam a **H declarada** da fonte, não a estimada. Usar a estimada afrouxa os limites justamente nas fontes ruins (medido: com H estimada, o travamento de 64 bits passava no RCT).
- O **teste de saúde pela H estimada** reprova a fonte se `H_estimada < 0,9`. O limiar 0,9 é **escolha de projeto**, não valor derivado: separa a fonte `os` (0,954 a 0,963 em 25 lotes de 1 milhão de bits) das fontes defeituosas medidas (`faulty_correlated` 0,752, `faulty_biased` 0,844, `faulty_stuck` 0,609). Foi fixado antes de existirem dados reais da QPU e não será ajustado depois para aprovar uma fonte.
- O **extrator** usa `min(H declarada, H estimada)`.
- O limiar reprova a QPU real se os bits dela tiverem H estimada abaixo de 0,9. Esse é o comportamento esperado (fail-closed), e o relatório deve registrar o resultado, mesmo que seja reprovação.

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

<!-- dia4-rendimento:start -->
### 6.8.1 Rendimento do extrator (Dia 4, etapa 3)

Gerado por `scripts/gerar_secao_rendimento.py` a partir dos arquivos listados abaixo, com o SHA3-256 conferido contra o meta. Nenhum número foi digitado à mão. As tabelas A, B e C vêm do modelo de perdas (`eal/extract/budget.py`) e valem para qualquer H; a tabela A parte das leituras do CSV de comparação e a D mede o estimador.

**Contabilidade.** Por bloco de n = 2048 bits, com k = floor(n·H) e margem 2·log2(1/ε) = 128: cada bit de entrada vai para o déficit de entropia (n − n·H), o arredondamento (n·H − k), a margem, a saída m = k − margem ou o resto (bits que não completam um bloco). A soma é exatamente a entrada. Se m = 0, o lote inteiro é descartado por entropia insuficiente.

**Origem dos dados.**
- Comparação de extratores: `data/results/dia4_extract_2026-10-30_120623.csv`, SHA3-256 `bb6fde627dcd1f38e2a802931396a074436d77d670191893fddb91ce005ca6b8`.
- Análise de rendimento: `data/results/dia4_yield_2026-10-30_131212.csv` (`4dddce9eb49d03d847e784e73329cc3181650af9aee409d7df3a86f198bc72d6`), `data/results/dia4_yield_curve_h_2026-10-30_131212.csv` (`038b0783c49c025b17547c53d2467af5290cc4fcb0e6d0ad08226d5c962af7a9`), `data/results/dia4_yield_curve_n_2026-10-30_131212.csv` (`e8e51d143247e5fe8c2c52058e9d2ba6b6cb2ef1ab5b3604188834aba90986ea`); medida em 2026-10-30T13:12:12.370978+00:00.
- Estimador × tamanho: `data/results/dia4_estimator_2026-10-30_131219.csv` (`27ca56e46a0d61776899cf843c7aa9cdf5b849cec59970e4f3f22c099bc3ac87`), `data/results/dia4_estimator_summary_2026-10-30_131219.csv` (`bf2b01b7a6a15b2491a40d074f11acd30ccd96a41af553644e1315976d9b283b`); medida em 2026-10-30T13:12:19.117430+00:00; 50 leituras da fonte `os`.

**Tabela A: para onde foi cada bit de entrada (leituras do CSV de comparação, lote de 1.000.000 bits).** As fontes `qpu_sim_*` são simuladas (gerador clássico) e não representam entropia real.

| Fonte | Leitura | H usada | m | Saída | Déficit | Arredondamento | Margem | Resto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `os` | 1 | 0,961 | 1840 | 89,79% | 3,89% | 0,01% | 6,25% | 0,06% |
| `os` | 2 | 0,961 | 1840 | 89,79% | 3,86% | 0,04% | 6,25% | 0,06% |
| `qpu_sim_ideal` | 1 | 0,958 | 1833 | 89,45% | 4,24% | 0,01% | 6,25% | 0,06% |
| `qpu_sim_ideal` | 2 | 0,957 | 1831 | 89,35% | 4,30% | 0,05% | 6,25% | 0,06% |
| `qpu_sim_noise` | 1 | 0,955 | 1828 | 89,21% | 4,45% | 0,04% | 6,25% | 0,06% |
| `qpu_sim_noise` | 2 | 0,953 | 1824 | 89,01% | 4,66% | 0,02% | 6,25% | 0,06% |

**Tabela B: rendimento por bloco em função de H (n = 2048).** Primeiro H da grade (passo 0,001) com saída positiva: 0,063.

| H | k = floor(n·H) | m | m/n | Déficit/bloco | Arredond./bloco | Margem/bloco |
| --- | --- | --- | --- | --- | --- | --- |
| 0,500 | 1024 | 896 | 0,4375 | 1024,0 | 0,000 | 128 |
| 0,900 | 1843 | 1715 | 0,8374 | 204,8 | 0,200 | 128 |
| 0,954 | 1953 | 1825 | 0,8911 | 94,2 | 0,792 | 128 |
| 1,000 | 2048 | 1920 | 0,9375 | 0,0 | 0,000 | 128 |

**Tabela C: rendimento em função de n, com H = 0,954 e lote de 1.000.000 bits** (a H é suposta a mesma para todo n; o CSV traz também H = 0,9 e 1,0).

| n | m | Blocos em 1M bits | m/n | Margem/bloco | log2(ε do lote) |
| --- | --- | --- | --- | --- | --- |
| 512 | 360 | 1953 | 0,7031 | 25,00% | -53,07 |
| 1024 | 848 | 976 | 0,8281 | 12,50% | -54,07 |
| 2048 | 1825 | 488 | 0,8911 | 6,25% | -55,07 |
| 4096 | 3779 | 244 | 0,9226 | 3,13% | -56,07 |
| 8192 | 7687 | 122 | 0,9384 | 1,56% | -57,07 |

**Tabela D: H estimada da fonte `os` em função do tamanho do lote.** Mede o estimador, não a fonte. Lotes menores que 1.000.000 bits não passariam no gate (estatísticos inconclusivos).

| Bits | Leituras | H estimada | dp | Mín a máx | H_bit | H_byte | Ref. bit (p̂=0,5) | Limitou (byte) | Passa H ≥ 0,9 | Saída média |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 65.536 | 10 | 0,8652 | 0,0102 | 0,8516 a 0,8835 | 0,9811 | 0,8652 | 0,9856 | 100% | 0% | 52.589 |
| 262.144 | 10 | 0,9249 | 0,0037 | 0,9193 a 0,9306 | 0,9905 | 0,9249 | 0,9928 | 100% | 100% | 225.997 |
| 1.000.000 | 10 | 0,9585 | 0,0027 | 0,9534 a 0,9617 | 0,9948 | 0,9585 | 0,9963 | 100% | 100% | 895.187 |
| 1.048.576 | 10 | 0,9586 | 0,0027 | 0,9520 a 0,9619 | 0,9950 | 0,9586 | 0,9964 | 100% | 100% | 939.366 |
| 4.194.304 | 10 | 0,9791 | 0,0016 | 0,9767 a 0,9815 | 0,9976 | 0,9791 | 0,9982 | 100% | 100% | 3.843.277 |

**Leitura dos resultados** (frases geradas dos CSVs):
- A margem de segurança é fixa: 128 bits por bloco de 2048 bits (6,25% da entrada), qualquer que seja H.
- Nas 6 leituras do CSV de comparação, a H usada ficou entre 0,953 e 0,961 e a saída ficou entre 89,01% e 89,79% da entrada.
- A H estimada média vai de 0,865 com 65.536 bits a 0,979 com 4.194.304 bits.
- A média cresce com o tamanho do lote em todos os tamanhos medidos.
- O teste de saúde pela H (limiar 0,9) reprovou parte ou todas as leituras com: 65.536 bits (0% das leituras passou).
- Em todos os tamanhos, o ramo por byte limitou a H em 100% das leituras.
- Com 4.194.304 bits, a referência analítica do ramo por bit (p̂ = 0,5) é 0,9982 e o H_bit médio medido é 0,9976; a H estimada (0,9791) fica abaixo disso por causa do ramo por byte.
- A amplitude da H entre as 6 leituras do CSV de comparação (0,953 a 0,961, diferença 0,0080) deve ser lida contra o desvio entre leituras da `os` com 1.000.000 bits (0,0027, 10 leituras). A amplitude é de no máximo 4 desvios: essa comparação, com poucas leituras por fonte, não distingue uma fonte da outra.

**Interpretação (não medida).** O estimador usa um limite superior de 99% e, no ramo por byte, o máximo entre 256 contagens de símbolos; por construção ele fica abaixo de 1 mesmo para uma fonte uniforme. Esta medição não separa entropia real de conservadorismo do estimador. Pela premissa P3 a `os` tem H próxima de 1, mas isso é premissa, não resultado. O rendimento do extrator herda esse conservadorismo.
<!-- dia4-rendimento:end -->

### 6.9 Mixer (`eal/mix/mixer.py`)

**Política (fail-closed):**

1. Só entram fontes com `approved = True`.
2. Em modo `keygen` é obrigatório **pelo menos 1 fonte local aprovada e não simulada** (na prática, `os`), cujas saídas extraídas somem pelo menos 512 bits (o tamanho da semente). Motivo: o provedor da QPU conhece os bits que gerou.
3. Fontes simuladas só entram em modo `experiment`, nunca em `keygen`: em `keygen`, uma fonte simulada na lista é erro de configuração, mesmo reprovada. Em `experiment` basta 1 fonte local aprovada (simulada ou não), com o mesmo piso de 512 bits, e a semente sai marcada `usable_for_key = False`.
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

<!-- dia4-mixer:start -->
### 6.9.1 Mixer: o que o código fixa (Dia 4)

Texto escrito a partir de `eal/mix/mixer.py`; complementa o 6.9, que não dizia como codificar os tamanhos.

**Modos.** `keygen`: fonte simulada na lista é erro (mesmo reprovada); exige pelo menos 1 fonte local, não simulada e aprovada, e a parte local deve somar 512 bits extraídos; a semente sai com `usable_for_key = True`. `experiment`: aceita fontes simuladas; exige pelo menos 1 fonte local aprovada (simulada ou não) com o mesmo piso de 512 bits; a semente sai sempre com `usable_for_key = False`.

**Codificação.** `SHA3-512( MIX_DOMAIN || para cada fonte incluída, em ordem de código Unicode do source_id: len(id em UTF-8) [8 bytes, big-endian] || id || n_bits [8 bytes, big-endian] || packbits(saída) )`. O contador é de BITS, não de bytes: `packbits` preenche o último byte com zeros, e sem o contador `[1]` e `[1,0,0,0,0,0,0,0]` dariam a mesma semente.

**Pareamento.** `make_mix_input` amarra o relatório de saúde e a extração aos bits do lote pelo `input_hash` (`hash_bits` dos bits do lote), pelo `batch_id`, pelo `source_id` e pelo tamanho. `source_id`, `batch_id` e `input_hash` repetidos entre as contribuições são recusados.

**Flags.** `is_local` só vale se for booleano verdadeiro; `is_simulated`, só se for booleano falso; `approved`, só se for booleano verdadeiro (`bool` ou `numpy.bool_`). Qualquer outro valor conta como o pior caso.

**Registro.** Fonte reprovada ou sem saída é excluída e registrada com `source_id`, `batch_id` e os motivos, em ordem de `source_id`. `MixResult.to_dict()` traz modo, `usable_for_key`, texto da política, `seed_hash` e, por fonte incluída, `source_id`, `batch_id`, `input_hash`, flags e bits misturados; nenhum byte de semente.
<!-- dia4-mixer:end -->

### 6.10 Derivação de chaves (`eal/pqc/keygen.py`)

Determinística a partir da semente, com separação de domínio:

| Algoritmo | Entrada interna (padrão) | Derivação |
| --- | --- | --- |
| ML-KEM-768 (FIPS 203) | `d` e `z`, 32 bytes cada | `d‖z = SHAKE256("EAL-v1|ML-KEM-768|" ‖ semente, 64 bytes)` |
| ML-DSA-65 (FIPS 204) | `ξ`, 32 bytes | `ξ = SHAKE256("EAL-v1|ML-DSA-65|" ‖ semente, 32 bytes)` |
- Biblioteca usada: `kyber-py` 1.2.0 e `dilithium-py` 1.5.1 (Python puro). Confirmado na etapa 1 do Dia 5: ambas expõem `key_derive` a partir de semente, e o projeto não usa `keygen()`. Os dois `key_derive` reproduzem os vetores de keyGen do NIST ACVP (25 de 25 por algoritmo); ver `tests/data/kat/SOURCE.json`.
- Alternativa: `liboqs-python` (mais difícil de instalar no Windows).
- Teste obrigatório: encapsular e decapsular (ML-KEM), assinar e verificar (ML-DSA), e a mesma semente gerar sempre as mesmas chaves.
- Chaves privadas derivadas **não são gravadas em disco**, exceto com a opção explícita `--export-demo`, apenas para demonstração. A opção ainda não existe na CLI (etapa 4); fica para a demo do Dia 9.

### 6.11 Recibo (`eal/receipt/`)

**Chave do emissor:** um par ML-DSA-65 separado, gerado uma vez a partir da fonte `os`. A chave privada fica em `keys/issuer_ml_dsa_65.sk` (no `.gitignore`); a pública em `keys/issuer_ml_dsa_65.pk`.

**Exemplo de recibo** (ilustrativo e abreviado: "…" marca o que foi omitido; a forma exata do corpo vem de `build_receipt_body` e é validada por `validate_body`). Uma fonte simulada nunca aparece num recibo, nem excluída: o `validate_body` recusa.

```json
{
  "eal_version": "0.1.0",
  "receipt_id": "uuid5 do seed_hash, canônico, em minúsculas",
  "created_at": "2026-10-28T14:03:12+00:00",
  "mode": "keygen",
  "prev_receipt_hash": "sha3-256 do recibo anterior (com assinatura), ou 64 zeros no primeiro",
  "software": {"python": "3.12.10", "kyber-py": "1.2.0", "dilithium-py": "1.5.1", "numpy": "…", "scipy": "…"},
  "sources": [
    {
      "source_id": "os",
      "source_type": "os",
      "source_version": "0.1.0",
      "status": "mixed",
      "batch_id": "…",
      "batch_hash": "…",
      "is_local": true,
      "is_simulated": false,
      "approved": true,
      "reasons": [],
      "health": {"…": "HealthReport.to_dict() (seção 6.7)"},
      "extraction": {"seed_hash": "sha3-256 da semente Toeplitz DESTA fonte", "…": "ExtractionResult.to_dict()"}
    },
    {
      "source_id": "ibm_kingston",
      "source_type": "qpu_ibm",
      "source_version": "…",
      "status": "excluded",
      "batch_id": "…",
      "batch_hash": "…",
      "is_local": false,
      "is_simulated": false,
      "approved": false,
      "reasons": ["motivo da reprovação"],
      "health": {"…": "…"},
      "extraction": null
    }
  ],
  "extractor": {"type": "toeplitz", "n": 2048, "epsilon_log2": -64},
  "mixer": {"…": "MixResult.to_dict(): modo, usable_for_key, política, seed_hash, fontes incluídas e excluídas; nenhum byte de semente"},
  "seed_hash": "sha3-256 da semente",
  "keys": {"ml_kem_768_pk_hash": "…", "ml_dsa_65_pk_hash": "…"},
  "limitations": ["prototype", "no_sp800_90b_claim", "no_quantum_origin_claim", "chsh_is_sanity_check_only", "pqc_pure_python_not_constant_time", "issuer_key_unencrypted_on_disk"],
  "signature": {"alg": "ML-DSA-65", "issuer_pk_hash": "…", "value": "base64…"}
}
```

**Regras:**

1. O recibo contém **somente hashes**, nunca a semente nem chaves privadas.
2. A assinatura cobre o JSON canônico de todos os campos exceto `signature` (chaves ordenadas, sem espaços, UTF-8).
3. `prev_receipt_hash` encadeia os recibos (hash do recibo anterior COMPLETO, com assinatura); o log fica em `data/receipts/chain.jsonl` e é descrito logo abaixo.
4. Verificação (`eal verify`): recalcula o JSON canônico, confere a assinatura com a chave pública do emissor e confere o encadeamento.
5. Params do lote (G6, Dia 6): só as chaves da lista fechada em `eal/config.py` entram no bloco `batch_params` de cada fonte; token, semente e demais campos ficam de fora. Fonte `qpu_ibm` com lote exige `job_id` (recusa o recibo). Recibos anteriores ao G6 não têm o bloco e continuam válidos.

**Construtor do recibo (Dia 5, etapa 2B, `eal/receipt/builder.py`).** Monta o corpo do recibo a partir do `PipelineResult`, das `DerivedKeys` e dos objetos `Source`. Cada fonte traz `source_type`, `source_version`, `status`, `batch_id`, `batch_hash` (o `input_hash` do lote), flags, `approved`, motivos, o `HealthReport` e os metadados da extração, incluindo o `seed_hash` da semente Toeplitz daquela fonte. O bloco `extractor` de topo traz só tipo, `n` e `epsilon_log2`. O `receipt_id` é UUID5 do `seed_hash`. As chaves são re-derivadas da semente e conferidas. Fontes que falharam entram com `approved: false` e o motivo, sem mensagem de exceção.

**Chave do emissor.** `xi = SHAKE256("EAL-v1|issuer|ML-DSA-65|" ‖ semente, 32 bytes)`, a partir de uma execução `keygen` validada pelo mixer.

**Log encadeado (Dia 5, etapa 3, `eal/receipt/chain.py`).** API: `append_receipt(receipt, issuer_pk, directory) -> Path`, `verify_chain(directory, issuer_pk, *, expected_head=None) -> ChainResult(ok, reasons, length, head)`, `chain_head(directory, issuer_pk)` e `ChainError`. O nome do log é `RECEIPT_CHAIN_NAME = "chain.jsonl"` em `eal/config.py`.

*Formato.* `<pasta>/chain.jsonl` tem uma linha por recibo; cada linha é o JSON canônico do recibo completo seguido de `\n`, gravada em modo binário (sem `\r\n`, o que importa no Windows com `core.autocrlf`). Cada recibo também vai para `<pasta>/<receipt_id>.json`, com os mesmos bytes da linha, para o `eal verify` receber um arquivo só. O log é o registro oficial; o arquivo individual é uma cópia conferida contra ele.

*Gravação.* `append_receipt` recusa com `ChainError`, sem gravar nada, se: a chave pública do emissor for inválida; a cadeia existente for inválida (fail-closed: log corrompido também recusa novas gravações); o recibo for inválido; o `prev_receipt_hash` não for a cabeça da cadeia (`GENESIS_PREV_HASH` com o log vazio); o `receipt_id` não for o `uuid5` do `seed_hash`; o `receipt_id` já estiver no log; ou o `<receipt_id>.json` já existir. A pasta só é criada depois que o recibo passa em todas as conferências. A ordem é: primeiro a linha (modo `ab`, `flush` e `fsync`), depois o `<receipt_id>.json` (modo `xb`, que nunca sobrescreve, com `fsync`). Se a segunda gravação falhar, a linha fica no log, `append_receipt` levanta `ChainError` e o `verify_chain` acusa "arquivo individual ausente" (a linha vence o arquivo).

*Verificação.* `verify_chain` não levanta exceção por causa do conteúdo dos arquivos. Confere, por linha: linha vazia; JSON inválido (inclui chave repetida, NaN, valor que não é objeto e UTF-8 inválido); forma canônica; `verify_receipt` com a MESMA chave pública do emissor para a cadeia toda (uma chave por cadeia); `receipt_id` único e igual ao `uuid5` do `seed_hash`; e o elo (`prev_receipt_hash` igual ao hash da linha anterior). Depois confere o arquivo individual de cada linha (ausente ou diferente), arquivos `.json` sem linha no log, última linha sem `\n` e, se `expected_head` for informado, a cabeça da cadeia. Depois de uma linha ilegível, o elo da linha seguinte não é verificável e não gera acusação extra. Outros arquivos da pasta (como `.gitkeep`) são ignorados. As mensagens trazem só números de linha e contagens, nunca o conteúdo do recibo.

*Testes.* `tests/test_receipt_chain.py` (79 testes, em pasta temporária), `tests/test_receipt_chain_pipeline.py` (4 testes, com duas execuções reais do pipeline e uma fonte determinística de teste) e `scripts/mutacoes_chain.py` (55 mutações manuais do `chain.py`, 55 mortas). Isso mostra que os testes pegam esses erros, não que o módulo esteja correto.

### 6.12 Linha de comando (`eal/cli.py`)

Uso: `py -3.12 -m eal <comando>`. Não há executável `eal` (o projeto não tem `pyproject.toml`). É um protótipo de pesquisa; a ajuda gerada pelo `argparse` tem partes em inglês.

| Comando | Faz | Estado |
| --- | --- | --- |
| `init-issuer [--bits N] [--keys-dir D] [--logs-dir D]` | Execução `keygen` só com a fonte `os`; deriva o par ML-DSA-65 do emissor (`issuer_seed_from_mix`) e grava `keys/issuer_ml_dsa_65.sk` e `.pk`. Recusa se qualquer um dos dois já existir | Etapa 4 |
| `run [--sources os] [--bits N] [--keys-dir D] [--receipts-dir D] [--public-keys-dir D] [--logs-dir D]` | Pipeline `keygen` com a fonte `os`, chaves ML-KEM-768 e ML-DSA-65 derivadas e recibo assinado gravado no log encadeado | Etapa 4 |
| `verify <arquivo> [--keys-dir D] [--chain-dir D] [--sem-cadeia] [--expected-head HASH]` | Verifica o recibo, a cadeia e a posição do recibo nela | Etapa 4 |
| `collect-ibm --qubits 156 --shots 4096 --budget-seconds 30` | Coleta na QPU real com limite duro | Ainda não existe (Dia 6) |
| `health data/raw/<arquivo>.npy` | Roda só os testes de saúde num arquivo | Ainda não existe |
| `experiment e2` | Roda um experimento | Ainda não existe (Dia 7) |

**Códigos de saída.** 0: ok. 1: falha esperada (fail-closed, recusa, recibo ou cadeia reprovados) ou erro inesperado, que é capturado e mostra só o nome da classe da exceção. 2: erro de uso (opção ou comando inválido).

**`init-issuer`.** O par do emissor vem de uma execução `keygen` própria, nunca da semente das chaves do usuário. Sem semente (fail-closed), nada é criado.

**`run`.** A ordem é: (1) carrega a chave do emissor (sem ela: "rode `init-issuer`"); (2) confere a cadeia existente, e um log corrompido recusa ANTES do pipeline; (3) roda o pipeline `keygen` uma única vez (sem semente: fail-closed, sem repetição automática; a `os` pode ser reprovada por acaso, como mostra o gate do Dia 4, e rodar de novo é legítimo); (4) deriva as chaves, monta e assina o recibo e grava no log; (5) grava SÓ as chaves públicas derivadas em `data/public_keys/<receipt_id>/` (`ml_kem_768.ek.hex` e `ml_dsa_65.pk.hex`, em hex com `\n` final, modo binário, sem sobrescrever). Se o passo 5 falhar, o recibo já está no log, e a mensagem diz isso (código 1). A saída traz `receipt_id`, o caminho do recibo, o hash da semente, os hashes das chaves públicas, o estado de cada fonte e a `cabeça da cadeia`; guardá-la fora do log permite usar `--expected-head` depois. `--sources` só aceita `os`: fonte simulada ou defeituosa é erro de uso (T13) e a fonte da IBM ainda não existe.

**`verify`.** Confere, nesta ordem: a chave pública do emissor (`--keys-dir`); o arquivo; o formato e a assinatura do recibo; e, a menos que haja `--sem-cadeia`, a cadeia da pasta do arquivo (ou de `--chain-dir`), com `--expected-head` se informada. O recibo precisa estar no log, o que é conferido pelo conteúdo canônico e não pelo nome do arquivo. Sem `chain.jsonl` na pasta, o erro manda usar `--chain-dir` ou `--sem-cadeia`. Com `--sem-cadeia` a saída traz "AVISO: cadeia não conferida". Em caso de sucesso imprime "recibo válido: <id>", "cadeia: posição X de N" e, com `--expected-head`, "cabeça conferida".

**Pastas padrão** (relativas ao diretório atual, cada uma com opção própria): `keys/`, `data/receipts/`, `data/public_keys/` e `data/logs/`.

**Log de falhas (T14).** `init-issuer` e `run` acrescentam uma linha JSON a `data/logs/eal_runs.jsonl` a cada falha, com `ts`, `command`, `stage` (`issuer_key`, `chain`, `pipeline`, `public_keys` ou `unexpected`), `ok: false`, `reason` e `pipeline` (`PipelineResult.to_dict()` ou `null`). O `verify` não grava log.

**O que a saída nunca traz.** Semente, chaves privadas (derivadas ou do emissor) e o texto de exceções, só o nome da classe. Há testes para isso (T10).

**Testes.** `tests/test_cli.py` (63 testes, em pastas temporárias; as fontes de teste entram por um parâmetro interno de `main`, nunca por opção da CLI; uma barreira automática impede os testes de gravar no `data/logs` real) e `scripts/mutacoes_chain_cli.py` (58 mutações manuais, 58 mortas). Isso mostra que os testes pegam esses erros, não que a CLI esteja correta.

### 6.13 Painel (`dashboard/app.py`)

Uma página em Streamlit: fontes e status, saúde por lote, min-entropia por fonte, viés por qubit, último recibo (com botão de verificação) e gráficos dos experimentos. Rodar com `py -3.12 -m streamlit run dashboard/app.py`.

<!-- dia4-pipeline:start -->
### 6.14 Pipeline (`eal/pipeline.py`, Dia 4)

`run_pipeline(sources, seed_source, mode, n_bits, h_declared, detector, health_fn)` devolve um `PipelineResult`. `health_fn` e `detector` são opcionais: sem eles, o pipeline importa `build_health_report` e `ReplayDetector` (os testes de política injetam versões falsas).

**Fluxo por fonte.** (1) lê um lote; (2) roda o teste de saúde, com o mesmo detector de replay para todas as fontes; (3) se aprovada, extrai com Toeplitz usando uma semente de uma leitura SEPARADA de `seed_source` (uma leitura nova por fonte aprovada); se reprovada, cria uma extração vazia ligada ao lote pelo hash, sem gastar semente; (4) monta o `MixInput`. No fim chama `mix`.

**Princípio.** A falha de uma fonte nunca derruba o pipeline; só a política do mixer derruba a semente. Sem política satisfeita, `mix = None`, o motivo vai em `error` e nenhuma semente é gerada (fail-closed).

**Estados de cada fonte** (`SourceOutcome.status`):

| Estado | Significado |
| --- | --- |
| `mixed` | entrou na mistura |
| `excluded` | reprovada ou sem saída; registrada com o motivo |
| `not_mixed` | aprovada, mas a política falhou e nenhuma semente saiu |
| `read_failed` | a leitura levantou exceção |
| `health_failed` | o teste de saúde levantou exceção |
| `extraction_failed` | semente de extração indisponível ou recusada, ou H estimada ausente |

**Regras.** Só `Exception` é capturada (`KeyboardInterrupt` passa). A mensagem de uma exceção de fonte ou de teste não é gravada, só o nome da classe, porque pode conter dados do provedor; a única mensagem gravada é a do `ValueError` do próprio extrator. `to_dict()` não traz bit nem byte de semente. O detector de replay vale por execução; para detectar replay entre execuções seguidas, o chamador passa o mesmo `detector`.
<!-- dia4-pipeline:end -->

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
│   ├── pipeline.py         # fontes -> saúde -> extração -> mixer -> semente (Dia 4)
│   ├── sources/            # base.py, os_source.py, qpu_sim.py, qpu_ibm.py, faulty.py
│   ├── health/             # continuous.py, min_entropy.py, stats_tests.py, report.py
│   ├── extract/            # blocks.py, budget.py, toeplitz.py, sha3.py
│   ├── mix/                # mixer.py
│   ├── pqc/                # keygen.py
│   └── receipt/            # schema.py, sign.py, verify.py, builder.py, chain.py
├── experiments/            # e1_quality.py … e5_chsh.py
├── dashboard/
│   └── app.py
├── tests/                  # test_sources.py, test_health.py, test_extract.py, …
├── data/
│   ├── raw/                # bits crus (.npy) + metadados (.json)
│   ├── results/            # CSVs dos experimentos
│   ├── receipts/           # recibos reais (chain.jsonl + <id>.json), fora do Git
│   ├── public_keys/        # chaves públicas derivadas, uma pasta por recibo, fora do Git
│   └── logs/               # qpu_usage.csv e eal_runs.jsonl (falhas da CLI), fora do Git
├── keys/                   # chave do emissor (.sk e .pk fora do Git)
├── scripts/                # geração de documentos e análises (gerar_docs_dia4.py, resilience_dia4.py, plot_bias.py, …)
└── scratch/                # testes soltos: teste_qiskit.py, teste_ibm.py
```

**`.gitignore` (conteúdo atual do arquivo):**

```
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
keys/*.sk
data/raw/
data/results/*.png
data/receipts/*
!data/receipts/.gitkeep
data/public_keys/
data/logs/*
!data/logs/.gitkeep
keys/*.pk
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
| matplotlib | 3.11.2 |
| pytest | 9.2.0 |
| kyber-py | 1.2.0 |
| dilithium-py | 1.5.1 |

### 8.3 `requirements.txt`

```
qiskit==2.6.1
qiskit-aer==0.18.2
qiskit-ibm-runtime==0.51.0
python-dotenv==1.2.4
numpy==2.5.4
scipy==1.18.1
cryptography==50.0.2
matplotlib==3.11.2
pytest==9.2.0
kyber-py==1.2.0
dilithium-py==1.5.1
# a adicionar e fixar depois de instalar: pandas, streamlit

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
7. Recibos reais, chaves públicas derivadas, a `.pk` do emissor e os logs ficam fora do Git. Só a demo do Dia 9 publica uma cadeia de demonstração, numa pasta própria.

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
| 2 | Fontes de bits e simulador com ruído | 5 fontes geram 1 milhão de bits cada em menos de 5 min e o gráfico de viés existe |
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

<!-- dia3-gate:start -->
### 16.1 Resultado do gate do Dia 3

Gate oficial: `dia3_health_2026-10-30_112209.csv`, commit `ac7637b`, criado em `2026-10-30T11:22:09.143096Z`, SHA3-256 `3b322c4d73d2da52bd4c8ae317f4ca363aea2d7aa5bad20e4893ad0bcd0867af`. Resultado: **APROVADO**. O meta marca git_dirty=true por arquivos não rastreados; o código rastreado é o do commit indicado.

Rodadas anteriores, não citar como resultado: `dia3_health_2026-10-29_200210` (controles quebrados, commit 11c6d4c), `dia3_health_2026-10-29_200513` e `dia3_health_2026-10-30_112016` (anteriores às correções do commit ac7637b).

| Fonte | Leituras | Aprovadas | Reprovadas | Erro ou pendente |
|---|---|---|---|---|
| `os` | 2 | 2 | 0 | 0 |
| `qpu_sim [ideal (controle)]` | 2 | 2 | 0 | 0 |
| `qpu_sim [ruído FakeKingston (controle)]` | 2 | 1 | 1 | 0 |
| `faulty_biased` | 2 | 0 | 2 | 0 |
| `faulty_correlated` | 2 | 0 | 2 | 0 |
| `faulty_prng` | 2 | 2 | 0 | 0 |
| `faulty_replay` | 3 | 1 | 2 | 0 |
| `faulty_stuck` | 2 | 0 | 2 | 0 |
| `ibm_<backend> [QPU real]` | 0 | 0 | 0 | 1 |

Controles (o veredito deles não entra no gate, que só exige que tenham rodado):
- qpu_sim [ideal (controle)], leitura 1: aprovada; monobit p = 0.7840846216576349; motivos: sem motivos
- qpu_sim [ideal (controle)], leitura 2: aprovada; monobit p = 0.7565609563559614; motivos: sem motivos
- qpu_sim [ruído FakeKingston (controle)], leitura 1: aprovada; monobit p = 0.056650205654175154; motivos: sem motivos
- qpu_sim [ruído FakeKingston (controle)], leitura 2: reprovada; monobit p = 0.00044474799901887707; motivos: monobit: p = 0.000445 (< 0.01)

Regras do gate:
- [ok] os aprovada: todas as leituras aprovadas
- [ok] faulty_biased reprovada: todas reprovadas, com APT e limiar de H falhando
- [ok] faulty_stuck reprovada: todas reprovadas, com RCT falhando
- [ok] faulty_correlated reprovada: todas reprovadas, com limiar de H falhando
- [ok] faulty_replay pega por replay: 1ª leitura aprovada; seguintes reprovadas por replay (só por replay se tiverem N bits)
- [ok] faulty_prng passa (limitação T4): todas aprovadas: testes de saída não detectam gerador clássico

**Decisão do Dia 3 (A):** o critério de aprovação continua o da seção 6.6 (monobit, bloco e runs com p ≥ 0,01 em lotes de 1 milhão de bits). Essa regra não foi ajustada depois de ver dados da QPU real. Consequência prevista: uma QPU com viés da ordem do ruído simulado (cerca de 0,15 ponto percentual, previsto pela calibração do chip) pode ser reprovada em parte das leituras. O E1 deve reportar a fração de leituras aprovadas, e não só o veredito de cada uma.

Limitações desta medição:
- O controle com ruído é simulado. A reprovação dele é um achado sobre a calibração do FakeKingston, não sobre uma QPU real.
- O `faulty_prng` é reproduzível só como fluxo sequencial da instância: o metadado registra a semente, não o deslocamento do fluxo.
- O `qpu_sim` registra a semente base no metadado; a semente efetiva de cada execução é a base mais o contador de execuções.
- Com 1 milhão de bits, o monobit detecta desvios da ordem de 0,1 ponto percentual. Viés menor que isso não aparece no gate.
<!-- dia3-gate:end -->

<!-- dia4-gate:start -->
### 16.2 Resultado do gate do Dia 4 (resiliência do pipeline)

Medido em 2026-10-30T13:52:03.537145+00:00 (commit `d98e8bb`). Tabela: `data/results/dia4_resilience_2026-10-30_135203.csv`, SHA3-256 `e8b23bb9f44ab1995063420eb7cf6b57dfa8499a6e74b1f7ec8e70ea4c0c5dc6`. CSV versionado em `2996df2`. Parâmetros: 5 repetições por cenário, lotes de 1.000.000 bits, backend de ruído `FakeKingston`; 60 execuções. Gerado por `scripts/gerar_docs_dia4.py`; resumo, gate e contagem de falsos alarmes foram recalculados do CSV.

**Regras do gate.**
- Nenhuma execução com VIOLATION em nenhum cenário.
- No cenário BASE, em toda execução com a `os` aprovada: semente de 64 bytes gerada e `usable_for_key = False` (modo `experiment`), e pelo menos uma execução assim.

**Resultado do gate: CUMPRIDO.**

**Vereditos por cenário.** `DETECTION_MISS` é uma fonte defeituosa que passou nos testes (medida do E2, não falha do pipeline); `UNEXPECTED`, uma fonte que deveria entrar e não entrou; `VIOLATION`, política ou isolamento quebrados.

| Cenário | Modo | Execuções | ok | ok_experiment_only | ok_fail_closed | DETECTION_MISS | UNEXPECTED | VIOLATION |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `BASE` | experiment | 5 | 4 | 1 | - | - | - | - |
| `BASE_NOISE` | experiment | 5 | 5 | - | - | - | - | - |
| `C1_stuck` | experiment | 5 | 5 | - | - | - | - | - |
| `C2_biased_correlated` | experiment | 5 | 4 | - | 1 | - | - | - |
| `C3_replay/first` | experiment | 5 | 5 | - | - | - | - | - |
| `C3_replay/second` | experiment | 5 | 5 | - | - | - | - | - |
| `C5c_os_down_experiment` | experiment | 5 | - | 5 | - | - | - | - |
| `C6_prng` | experiment | 5 | 5 | - | - | - | - | - |
| `K1_keygen_standin` | keygen | 5 | 4 | - | - | - | 1 | - |
| `C4_remote_down` | keygen | 5 | 5 | - | - | - | - | - |
| `C5a_os_down` | keygen | 5 | - | - | 5 | - | - | - |
| `C5b_os_tampered` | keygen | 5 | - | - | 5 | - | - | - |

**Execuções fora do esperado** (tudo que não é `ok`, exceto o fail-closed previsto dos cenários C5):

| Cenário | Rep. | Estados | Veredito | Motivo registrado |
| --- | --- | --- | --- | --- |
| `BASE` | 2 | `os:excluded;qpu_sim:mixed` | ok_experiment_only | os: reprovada pelo teste de saúde: block: p = 0.00924 (< 0.01) / sem saída de extração (lote curto ou entropia... |
| `C2_biased_correlated` | 2 | `os:excluded;faulty_biased:excluded;faulty_correlated:excluded` | ok_fail_closed | os: runs: p = 0.00129 (< 0.01) ; faulty_biased: APT: 20 de 976 janelas no limite 589 ou acima (máximo 611) / m... |
| `K1_keygen_standin` | 2 | `os:mixed;ibm_standin:excluded` | UNEXPECTED: não entrou na mistura: ibm_standin | ibm_standin: reprovada pelo teste de saúde: block: p = 0.00881 (< 0.01) / sem saída de extração (lote curto ou... |

**Leitura dos resultados** (frases geradas do CSV):
- A `os` não entrou na mistura em 2 de 45 execuções fora dos cenários em que ela falha de propósito (reprovação pelos testes de saúde ou falha de leitura). Referência da seção 16.1: cerca de 3% por lote. Esta contagem não inclui reprovações do stand-in remoto (ver a tabela «Execuções fora do esperado»).
- Em 19 execuções com fontes defeituosas ou indisponíveis e a `os` aprovada (`C1_stuck`, `C2_biased_correlated`, `C3_replay/second`, `C4_remote_down`), nenhuma fonte defeituosa entrou na mistura.
- A `faulty_prng` entrou na mistura em 5 de 5 execuções com a `os` aprovada (C6): testes de saída não distinguem um gerador clássico bom (limitação T4).
- Em `keygen`, com a `os` fora (leitura falha ou lote adulterado) e a remota no ar, a semente foi gerada em 0 de 10 execuções (esperado: 0; G2).
- K1: semente utilizável em 5 de 5 execuções; 1 com UNEXPECTED (ver a tabela «Execuções fora do esperado»). Na execução, o motivo registrado é reprovação pelo teste de saúde com p < 0,01 (critério da seção 6.6). Como o stand-in usa bits da `os` (premissa P3), o resultado é compatível com o falso alarme que esse limiar produz por acaso (cerca de 1% por teste em fonte boa), não com defeito do pipeline.
- C5c: em `experiment`, com a `os` fora, a `qpu_sim` sozinha gerou semente marcada como inutilizável em 5 de 5 execuções.
- Execuções com VIOLATION (política ou isolamento do pipeline quebrados): 0.

**O que este gate não mostra.** A fonte "remota" dos cenários `keygen` é um stand-in (bits da `os` com rótulo de fonte remota não simulada), não a QPU da IBM. O gate verifica política, isolamento e fail-closed; não mede a qualidade estatística da semente (o SHA3-512 de lixo também parece uniforme) nem a taxa de detecção de fontes defeituosas, com 5 repetições por cenário (isso é o E2). O CSV guarda só o SHA3-256 da semente; nenhuma semente nem bit é gravado.
<!-- dia4-gate:end -->

<!-- dia5-gate:start -->
### 16.3 Gate manual do Dia 5 (execução real na máquina do autor)

Gerado por `scripts/registrar_gate_dia5.py` a partir de `data/results/dia5_gate_manual_2026-10-31.json` (SHA3-256 `00a967715daef34d650310018f47e386f0a3b55632e2c8b08a9c8dec1924ec15`). Nenhum número foi digitado à mão. Antes de gravar, o script conferiu cada recibo, cabeça e chave pública contra o log e os arquivos em `data/receipts/`, e confirmou no Git que as chaves e o log ficam fora do controle de versão. O JSON veio do bloco `gate_manual_dia5_resultado` do handoff (SHA3-256 `906ee784e14b24812c3db84f62d1eb5afd7add1d5644307033645fdbe11f7c2d`).

**Origem.** 2026-10-31, máquina do usuário, fonte os real, comandos py -3.12 -m eal.

**Execuções.**

| Tentativa | Código | receipt_id | seed_hash | ML-KEM-768 (pk_hash) | ML-DSA-65 (pk_hash) | Fontes | Cabeça após a execução |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 20388d1d-5896-5efe-9e16-67c964db7f60 | 4d42873eb3a99f077fc16a4c09f01d8a175f66482a119b2f500c1eabb477a6e8 | b82cf0c2d6f57a71139f5032cda011060ef1a0adf5281eee3fae0d17838c7bd9 | 2a473104b7b98a5d8daa8f58b1a1e96bfef146cb6091aa958d04e22e159db808 | os=mixed | 9f3cf4dcf3d3e6acb4bb53aad3391a6611269d9cdce1af096a3f425377f27001 |
| 2 | 0 | 8efb7176-2edd-5b97-bb5f-4e11709b5d92 | b0e5106433359e629777d198829c1396f40c123f5c70864c79732f9488911aed | 983cf9ed4a2649236396d38265ba3abfdea7d2b2d63cf0ba4303a3f108e4a509 | 22229e42df74a7242bea251aa1a1fc5ab72e103e64017752e1b02434ddeda587 | os=mixed | ae6b331a3db5d81b43a1ebbbe8c2661b21ac8d4761fb8938a6e089b691d1687a |

**Chave do emissor.** código 0; pk_hash 729e5cfbd664fafc6b444050f6cae2863b7a6fdf4bf20e2369b5e52dd14d57d0; .sk e .pk ignoradas pelo Git (.gitignore:6 keys/*.sk e :14 keys/*.pk).

**Checagens.**

- verify do último recibo + --expected-head (posição 2 de 2, cabeça conferida): código 0
- verify do penúltimo recibo (posição 1 de 2): código 0
- verify de cópia igual com outro nome e --chain-dir: código 0
- verify de cópia ADULTERADA ('mode':'keygen' -> 'keygex', cópia em %TEMP%): código 1, 'recibo reprovado'
- verify com cabeça errada ('a'*64): código 1, 'cadeia reprovada'

**Outras conferências na data do gate.** Chaves públicas com 2369 e 3905 bytes (2 x tamanho + 1, sem \r). git status sem nada de keys/ nem data/. Nenhuma falha registrada. Duas execuções só: não generalizar (ex.: não afirmar taxa de fail-closed).

**O que este gate mostra e o que não mostra.**

- 2 execução(ões) com a fonte `os`. São dados de um dia, não uma taxa: com elas não dá para estimar a frequência de falhas por acaso.
- A fonte é a `os`, cuja imprevisibilidade é premissa (P3). A QPU da IBM não entrou nesta execução, e a CLI ainda não tem coleta de QPU.
- O gate confere fluxo, cadeia e chaves no disco. Não mede a qualidade estatística da semente nem a taxa de detecção de fontes defeituosas (isso é o E2).
<!-- dia5-gate:end -->

<!-- dia5-nota:start -->
**Nota sobre o gate do Dia 5.** O gate cumpre o fluxo abaixo. Não é um comando único que faz tudo:

- `py -3.12 -m eal init-issuer` cria a chave do emissor de recibos. Precisa existir antes do primeiro `run`.
- `py -3.12 -m eal run` deriva as chaves ML-KEM-768 e ML-DSA-65 da semente e grava no log encadeado o recibo assinado com ML-DSA-65. Ele não cria a chave do emissor.
- `py -3.12 -m eal verify <recibo>` confere a assinatura, o formato e a posição do recibo na cadeia.

As chaves privadas derivadas ficam só em memória (AT2 do THREAT_MODEL). A exceção `--export-demo` não faz parte deste gate.
<!-- dia5-nota:end -->

<!-- dia5-revisao:start -->
### 16.4 Revisão adversarial do Dia 5

Feita por leitura do código, em partes, a partir do arquivo que o coletor gera (`revisao_parteN_*.txt`), com o commit lido e o SHA-256 de cada arquivo. O que foi confirmado por execução está dito em cada achado; o resto é leitura e não prova ausência de defeitos.

**Parte 1 (31/10/2026), commit `90d15b8`.** `eal/cli.py` (SHA-256 `0ADAC6167E0A570F56BA1D0C4A220AFB6F2A96F1BEBFFD9F564FBC076040DFA5`); `eal/receipt/chain.py` (SHA-256 `779BE0DA09A47EAC1F39AF65A7F9C89977FE67669D7FA7409DDBC1132D2685FE`); `eal/receipt/verify.py` (SHA-256 `371DD71FFA5B99078EB044008AFE7AB0D997FF070763D3D9C0956DAF5F598733`).

**Parte 2 (31/10/2026), commit `20e7055`.** `eal/pqc/keygen.py` (SHA-256 `005C589DF037D54ACE97863BCA3B4CE5EAFE5723896D2BCE31A82B50AD6B4F81`); `eal/receipt/builder.py` (SHA-256 `313F49039BD338A7C0635FE3FF3C274945982CC8367FB04B16F0C9A47A31E7EA`); `eal/receipt/sign.py` (SHA-256 `496646F61566563C5F1DE6F3F715B6ACCF035D3E658E55C6CA111D71D923A3FB`); `eal/receipt/schema.py` (SHA-256 `731FCC7D8B52F54C8B603E51D21FFB722990B4C05939B1BA44B724AA9AE87AC3`).

**Parte 3 (31/10/2026), commit `20e7055`.** `eal/mix/mixer.py` (SHA-256 `4B0D47C93C2F41152BCE47C834E01F085D7635214DA98CA7AE7B293A1B929807`); `eal/pipeline.py` (SHA-256 `5B6D4DFD862D81B390ACA90A41521ABC82057C7465D23A260A8F230628296A80`); `eal/config.py` (SHA-256 `98DB40E62374FB4A6458C730CCFDC97C4D453B2353C57DE98C9082D06093BD74`); `eal/health/report.py` (SHA-256 `FCAD8168F5AF5C34443C4CE4475EF44D31AAA53651DC5210BC69A1BDE12F8095`); `eal/extract/toeplitz.py` (SHA-256 `6930DFACEE5F36C3395CF849E6A22EA6044F4E0CC48B4C9E8B2F85AFA317D9AC`); `eal/extract/budget.py` (SHA-256 `AB3EE27C0E810A593381985BB344B70ED10F4B95BCAE445B5ADDF62F28FD4765`); `eal/extract/blocks.py` (SHA-256 `CF19EF4E795026914019626FC414AE75E0FCBCB3F0CD96170676E54AD04C64FA`); `eal/extract/sha3.py` (SHA-256 `1DD58535A853B1E2816E097F2E088D9186DADF83AD4F963611FD7125DEF416EC`).

| ID | Gravidade | Onde | Achado | Decisão |
| --- | --- | --- | --- | --- |
| F1 | Baixa | `cli.py`, `verify` | `--sem-cadeia` com `--expected-head` ignorava a cabeça em silêncio; só aparecia o aviso de cadeia não conferida. Confirmado por execução. | Corrigido: juntas, as duas opções são erro de uso (código 2), antes de ler o arquivo. Testes em `tests/test_cli_revisao_parte1.py`. |
| F2 | Baixa (disponibilidade) | `chain.py`, `append_receipt` | Uma linha no log sem o arquivo individual deixa a cadeia inválida, e o `run` recusa antes do pipeline. Confirmado por execução, numa cópia. | Já estava documentado (seção 17, etapa 3). A limitação ganhou o procedimento de reparo manual. |
| F3 | Baixa | `chain.py` | Sem trava contra duas gravações simultâneas: a cadeia é acusada como quebrada e para; não aceita o recibo errado. | Já estava documentado; sem mudança. |
| F4 | Baixa (latente) | `cli.py`, `run` | `--sources` era validado e nunca lido. | Corrigido: a lista que valida o argumento é a mesma que cria as fontes (`_SOURCE_FACTORIES`). Testes no mesmo arquivo de F1. |
| F5 | Informativa | `verify.py`, `verify_receipt_text` | O motivo "JSON inválido" inclui o texto do erro do parser de JSON. | Aceito sem mudança: o texto traz só a posição e mensagens fixas, nunca conteúdo do recibo, e ajuda a diagnosticar. |
| F6 | Informativa | `cli.py` e `chain.py` | O `run` verifica a cadeia inteira duas vezes (uma verificação ML-DSA por linha). | A medir quando a cadeia crescer. A primeira passada é a que evita gastar entropia com log ruim. |
| F7 | Baixa (disponibilidade) | `sign.py`, `cli.py` | A `.pk` é gravada antes da `.sk`; se a segunda falhar, `init-issuer` recusa ("já existe") e `run` manda rodar `init-issuer`: um beco sem saída. Confirmado por execução no `sign.py`; o efeito na CLI é pela leitura. | Corrigido: `init-issuer` e `run` detectam o par incompleto e dizem qual arquivo falta e o que fazer. |
| F8 | Baixa (mensagem) | `schema.py`, `chain.py`, `cli.py` | `--expected-head` em maiúsculas (como o `Get-FileHash` imprime) era recusado como cabeça diferente. Confirmado por execução. | Corrigido: o argumento é normalizado para minúsculas e sem espaços; a comparação continua exata. |
| F9 | Baixa (endurecimento) | `schema.py`, `report.py`, `builder.py` | O validador não olha dentro de `mixer`, `sources[i]` etc., e `HealthReport.to_dict()` usa `asdict`: um campo novo iria para o recibo assinado sem alarme. Hoje nenhum desses objetos leva material secreto. Confirmado por execução: a aceitação de campo extra; o resto é leitura. | Corrigido no construtor: lista fechada de campos nos objetos aninhados, recusa de texto hexadecimal longo e de lista longa de bits, e testes que travam os 35 campos do `HealthReport`. A verificação não mudou: recibos antigos continuam válidos. |
| F10 | Informativa | `pipeline.py` | O `except ValueError` gravava o texto de qualquer `ValueError` do `try`, inclusive o da leitura da semente. | Corrigido: a leitura da semente tem `try` próprio, e só a mensagem do extrator (texto fixo e tamanhos) é gravada. |
| F11 | Baixa (latente) | `toeplitz.py` | A checagem da semente usava veracidade: `is_simulated=None`, `''` ou `0` e `is_local='não'` passavam. Confirmado por execução. | Corrigido: booleano estrito, como no mixer e no construtor do recibo. |
| F12 | Média para o Dia 6, baixa hoje | `pipeline.py`, `report.py` | O detector de replay é criado a cada `eal run`: replay entre execuções não é detectado. Já estava na seção 17; o THREAT_MODEL (T3) dizia "baixo para replay exato". | Resolvido no Dia 6 (passos 1 e 2, commits e25e8dd e e4b9f1d): o histórico é salvo em `data/logs/replay_history.json` e carregado antes de qualquer leitura de fonte; T3 e N14 atualizados no THREAT_MODEL v1.3. |

**Resolvido sem mudança de código:** `save_issuer_key` grava em modo exclusivo; os quatro prefixos de domínio da semente (`EAL-v1|ML-KEM-768|`, `EAL-v1|ML-DSA-65|`, `EAL-v1|issuer|ML-DSA-65|` e `EAL-v1-mix`) são distintos e nenhum é prefixo de outro (executado); `PipelineResult.to_dict()` e `MixResult.to_dict()` são listas fixas de campos; um `--bits` abaixo de 1.000.000 não aprova a fonte, porque o teste estatístico fica inconclusivo (leitura).

**F12 resolvido no Dia 6** (passos 1 e 2, commits e25e8dd e e4b9f1d): o histórico do detector de replay é salvo entre execuções e carregado antes de qualquer leitura de fonte; a gravação acontece antes de qualquer recibo. Falha de leitura ou de gravação recusa a execução (fail-closed). Limitações na seção 17.
**G6 (Dia 6, resolvido):** params do lote no recibo. Passo 1 (`df231d7`): `SourceOutcome` carrega os params, fora do `to_dict()`. Passo 2 (`e0b4dd4`): lista fechada em `config.py`, bloco `batch_params` no builder e no esquema, `job_id` obrigatório em `qpu_ibm`. Verificação: suíte com 1623 passed e 1 skipped; cadeia real válida (posição 2 de 2, cabeça conferida); recibos antigos sem o bloco continuam válidos.

<!-- dia5-revisao:end -->

## 17. Limitações conhecidas

1. Protótipo de pesquisa; não usar para proteger dados reais.
2. Estimativa de min-entropia simplificada; sem alegação de conformidade com SP 800-90B.
3. Bibliotecas PQC em Python puro: sem tempo constante, sem auditoria.
4. O provedor da QPU conhece os bits que gerou.
5. CHSH numa QPU em nuvem não é teste de Bell sem brechas.
6. O simulador é um gerador clássico.
7. Ambiente sem `.venv` (problema não resolvido no Windows).
8. Orçamento de QPU limita o tamanho das amostras reais.
9. O simulador trata os qubits como independentes (cada um é simulado separadamente): não reproduz correlação entre vizinhos (crosstalk) que um chip real pode ter.
10. O ruído do `qpu_sim` vem de uma calibração fixa do `FakeKingston` (15/04/2026), que pode não refletir o chip hoje; a comparação com o chip real é o E1.
11. O `NoiseModel.from_backend` do Aer monta o erro de leitura simétrico, o que apaga o viés de um qubit em 50/50; o projeto remonta o erro de forma assimétrica a partir da calibração (`eal/sources/noise.py`).

---

### Limitações do Dia 3

- Testes de saúde e estatísticos não detectam gerador clássico de boa qualidade (T4). A defesa é estrutural (fonte local obrigatória na mistura).
- O replay detecta blocos de 4096 bits idênticos. Não detecta replay transformado (um bit alterado por bloco), replay deslocado para fora de múltiplos de 4096 bits, nem replay menor que um bloco, a menos que o lote inteiro seja idêntico.
- O estado do detector de replay existe só em memória, durante uma execução. Replay entre execuções não é detectado.
- O teste de saúde pela H estimada usa limiar 0,9, que é escolha de projeto, não valor derivado de dados.
- O APT e os estatísticos testam só janelas e blocos completos; bits finais são descartados e registrados em `notes`.
- Lote menor que 1.000.000 bits: estatísticos inconclusivos, e o lote não é aprovado.

### Limitações do Dia 4 (etapa 1: extrator)

- O ε = 2^-64 do Toeplitz vale por bloco. Sobre um lote, o limite é n_blocos · ε (≈ 2^-55 para 488 blocos) e só vale se cada bloco tiver a min-entropia estimada condicionada aos blocos anteriores; correlação entre blocos quebra essa premissa.
- A garantia do Toeplitz (lema do hash residual) depende da premissa P4: semente uniforme e independente da fonte. O código recusa semente simulada, não local ou idêntica ao lote, mas não prova independência estatística.
- O extrator SHA3 tem garantia só heurística (modelo de oráculo aleatório); serve para comparação, não para o pipeline.
- Estatística boa na saída do extrator não prova nada: o SHA3 de bits travados também parece uniforme. O extrator é dimensionado pela H medida na entrada.
- Os p-valores de saída no CSV de comparação são diagnóstico, não aprovação (saída < 1M bits).

### Limitações do Dia 5 (etapa 1: derivação PQC)

- Os vetores oficiais (NIST ACVP) cobrem o `key_derive` das bibliotecas, não a derivação da EAL (SHAKE256 com prefixo de domínio sobre a semente), que não tem vetor oficial e é verificada contra `hashlib` no teste.
- Os vetores são o subconjunto de ML-KEM-768 e ML-DSA-65 do branch master do ACVP-Server, baixado em 30/10/2026; o commit de cada arquivo foi verificado pelo SHA3-256 do conteúdo original: ML-KEM-768 `15c0f3deeefbfa8cb6cd32a99e1ca3b738c66bf0`, ML-DSA-65 `2972def23bf9f3680c2c531561ed9bdd0f1086ad` (ver `tests/data/kat/SOURCE.json`).
- Os vetores cobrem geração de chave. Encapsulamento, decapsulamento, assinatura e verificação são testados por ida e volta e adulteração, sem vetores oficiais.
- O teste de sigilo procura trechos secretos definidos pelo formato FIPS 203/204. O início da chave privada do ML-DSA (`ρ`) é público, então o teste procura `K`; se uma versão futura da biblioteca mudar o formato, o teste `test_sk_do_ml_dsa_comeca_com_rho_publico` avisa.
- Bibliotecas em Python puro: sem tempo constante e sem auditoria (T15, N5). A semente fica em `bytes`, que o Python não apaga da memória (P1).
- Mutações: 14 mutações manuais da derivação, da política do mix e do sigilo foram todas detectadas (`scripts/mutacoes_pqc.py`); isso mostra que os testes pegam esses erros, não que o módulo esteja correto.


<!-- dia4-limitacoes:start -->
### Limitações do Dia 4 (etapa 3: rendimento do extrator)

- O modelo de perdas é conta, não medida: ele diz o que o extrator faz com a H que recebe, e não se essa H está certa (T8).
- A curva em função de n supõe a mesma H para todo n; o ε do lote (n_blocos · ε) vale sob a premissa de independência entre blocos.
- A H estimada da `os` fica abaixo de 1 por construção do estimador, e o teste de saúde pela H (limiar 0,9) reprova lotes pequenos mesmo vindos de uma fonte que a premissa P3 considera boa; ver a tabela D para os tamanhos afetados.
- A tabela D tem 10 leituras por tamanho: o desvio entre leituras é reportado, mas não há intervalo de confiança.
- A fonte `os` não é reprodutível e os bits dessa medição não foram guardados; só estimativas e hashes de lote.
- Com poucas leituras por fonte, diferenças de H entre `os`, `qpu_sim` ideal e `qpu_sim` com ruído não são conclusivas; a comparação entre fontes é do E1.
<!-- dia4-limitacoes:end -->

<!-- dia4-limitacoes-pipeline:start -->
### Limitações do Dia 4 (etapas 2 e 4: mixer, pipeline e resiliência)

- Um `MixInput` montado à mão, sem `make_mix_input`, pode declarar um `input_hash` falso: o pareamento só vale para quem usa o ponto de entrada normal.
- A semente fica em `bytes`, que o Python não consegue apagar da memória; é aceitável no protótipo e coberto pela premissa P1 (host íntegro).
- O piso de 512 bits conta bits extraídos, não entropia provada; vale sob as mesmas premissas do extrator (P4 e independência entre blocos).
- Em `experiment`, o mixer não exige fonte local não simulada (ver o 6.9); a semente sai inutilizável para chave, mas uma execução sem a `os` ainda gera semente.
- Os testes de política do pipeline usam funções de saúde falsas; o comportamento com os testes estatísticos reais só aparece na execução do script de resiliência.
- A fonte remota dos cenários `keygen` é um stand-in (bits da `os` com rótulo remoto), não a QPU: o gate não diz nada sobre a QPU real nem sobre a independência do provedor (N7).
- O cenário C5b adultera o lote da `os` com um trecho de zeros, que só exercita o RCT; não cobre viés nem correlação na `os`.
- O teste com fonte adaptativa mostra que o SHA3-512 resiste a cancelar a entropia da `os` (cancelar exigiria colisões), mas não protege quem vê a saída da `os` (G3 vale só para quem não a conhece), e uma fonte adaptativa pode "moer" candidatos, a um custo de 2^k para fixar k bits da semente.
- Poucas repetições por cenário: as contagens do 16.2 não estimam taxas (nem a de falso alarme da `os`, nem a de detecção); isso é o E2.
<!-- dia4-limitacoes-pipeline:end -->

### Limitações do Dia 5 (etapa 2: recibo)

- Os `params` do lote (ex.: `job_id` da IBM) não chegavam ao recibo. Resolvido no Dia 6 (G6): ver a seção "Limitações do Dia 6 (G6)" abaixo.
- O recibo é verificável por este código em Python; o JSON canônico com números de ponto flutuante não foi testado contra um verificador em outra linguagem.
- O teste de integração usa uma fonte determinística (SHAKE256) no lugar da `os`, para não falhar por acaso; ela não é fonte de entropia e só existe nos testes.
- A chave do emissor depende só da fonte `os` (P3) e fica em disco sem cifragem (N11).

### Limitações do Dia 6 (G6: params do lote)

- Recibos anteriores ao G6 não têm o bloco `batch_params`; a verificação aceita a ausência, então eles continuam válidos, mas não provam o `job_id` de nenhuma coleta.
- Os nomes das chaves (`backend`, `job_id`, `shots`, `qubits`) e os formatos (texto de até 64 caracteres, inteiros de 1 a 10⁹) são as premissas deste protótipo. O adaptador da IBM ainda não existe: os nomes e os formatos reais do `job_id` e do número de qubits precisam ser conferidos na documentação do qiskit-ibm-runtime antes da coleta. Se o provedor usar outro formato, o recibo é recusado (fail-closed).
- O `job_id` é guardado em claro no recibo. Ele não é segredo, mas revela que o job existiu na conta.
- O recibo prova os params que o código entregou ao builder, não que a API da IBM devolveu esses valores.

### Limitações do Dia 6 (F12: histórico de replay)

- O histórico começa no primeiro `eal run` depois do commit `e4b9f1d`. Lotes de execuções anteriores não estão nele, então o replay de um lote antigo não é detectado.
- O `state_hash` detecta corrupção acidental, não adulteração: quem tem acesso ao disco pode refazer o arquivo, e apagá-lo zera a proteção sem alarme. A cabeça da cadeia anotada fora do repositório não cobre este arquivo.
- Não há trava para dois `eal run` simultâneos (como a F3): a última gravação vence.
- O arquivo cresce com os lotes; acima de 64 MiB o `run` recusa, até que alguém o arquive à mão.
- Replay transformado e replay deslocado para fora de múltiplos de 4096 bits continuam não detectados (ver as limitações do Dia 3).

### Limitações do Dia 5 (etapa 3: log encadeado)

- Não há trava contra duas gravações simultâneas: dois processos podem ler a mesma cabeça e gravar dois recibos com o mesmo `prev_receipt_hash`. O `verify_chain` acusa isso depois, mas a gravação não é impedida. O escopo do protótipo é um usuário (THREAT_MODEL, seção 1).
- Apagar o ÚLTIMO recibo (ou truncar o fim do log) deixa uma cadeia válida. Só a cabeça guardada fora do log (`expected_head`) denuncia, e o protótipo ainda não guarda essa cabeça em lugar nenhum.
- Quem tem a chave privada do emissor e acesso ao disco pode refazer a cadeia inteira com assinaturas válidas (N11, resíduo de T9).
- Uma chave de emissor por cadeia, sem rotação: trocar a chave exige começar outra cadeia.
- A gravação em dois arquivos não é atômica. Se o processo cair entre a linha e o `<receipt_id>.json`, o log fica com uma linha sem arquivo e passa a recusar novas gravações (fail-closed) até uma intervenção manual; não há comando de reparo. O reparo é recriar `<receipt_id>.json` com os mesmos bytes da linha do log seguidos de `\n`, gravado em modo binário (um editor pode trocar `\n` por `\r\n`), e conferir com `eal verify`. Se a queda deixar uma linha incompleta no fim do log, o reparo é outro (remover essa linha) e não foi testado. Ver achado F2 na seção 16.4.
- O `fsync` pede ao sistema operacional que grave no disco; o comportamento em queda de energia não foi testado.
- O `created_at` é informado por quem emite o recibo e não é conferido (nem a ordem entre recibos).
- O teste de integração da cadeia usa a mesma fonte determinística de teste da etapa 2 no lugar da `os`; ela não é fonte de entropia.
- Mutações: 55 mutações manuais do `chain.py` foram todas detectadas (`scripts/mutacoes_chain.py`); isso mostra que os testes pegam esses erros, não que o módulo esteja correto.

### Limitações do Dia 5 (etapa 4: linha de comando)

- O `run` só aceita a fonte `os`. A coleta da IBM (Dia 6) ainda não existe, então a CLI não mistura a `os` com outra fonte.
- Só com a `os`, um fail-closed por acaso é possível (o teste de bloco já reprovou a `os` num dos cenários do gate do Dia 4). O comando não repete sozinho; rodar de novo é decisão de quem usa.
- A `cabeça da cadeia` é impressa pelo `run`, mas o protótipo não a guarda em lugar nenhum: o `--expected-head` só serve a quem a anotou. Sem isso, apagar o último recibo continua indetectável (limitação da etapa 3).
- Recibos reais, chaves públicas derivadas, a `.pk` do emissor e os logs ficam fora do Git. Perder `data/receipts/` apaga a evidência, e não há cópia de segurança. A cadeia de demonstração do Dia 9 irá numa pasta própria, com uma cópia da `.pk` do emissor.
- A `.sk` do emissor fica em hex, sem cifragem, em `keys/` (N11). O `init-issuer` não sobrescreve; não há rotação nem recuperação da chave.
- O `--export-demo` citado na 6.10 não existe: nenhuma chave privada derivada vai a disco.
- O `run` grava as chaves públicas derivadas, mas nenhum comando as confere depois contra os hashes do recibo.
- O log de falhas não tem rotação nem proteção contra adulteração, e o campo `reason` pode conter caminhos de pastas do usuário.
- As pastas padrão são relativas ao diretório atual: rodar de outra pasta cria `keys/` e `data/` ali.
- Dois `run` ao mesmo tempo seguem sem trava (herdado da etapa 3).
- Caracteres que o console não escreve viram `?` (o console do Windows usa ibm850), e partes da ajuda do `argparse` ficam em inglês.
- Os testes da CLI usam a fonte determinística (SHAKE256) no lugar da `os`, com o pipeline real. A CLI com a `os` real só roda no gate manual.
- Mutações: 58 mutações manuais do `cli.py` foram todas detectadas (`scripts/mutacoes_chain_cli.py`); isso mostra que os testes pegam esses erros, não que a CLI esteja correta. Uma delas, "não cria a pasta das chaves", era equivalente, porque o `save_issuer_key` já cria a pasta; ficou coberta por um teste que fixa o `mkdir` do comando.

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


## 18. Dia 6: calibração na QPU real e pendências (registro)
Job de calibração: dbji1pgnceqs73ak2c8g, backend ibm_kingston, 156 qubits, 1000 shots, reserva de 20 s, SamplerV2 (qiskit 2.6.1, qiskit-ibm-runtime 0.51.0).
Estado: DONE. Uso cobrado: 2 s de QPU (usage() e qpu_charge_time_seconds). Criado às 08:22 (horário de São Paulo) e já concluído na inspeção das 11:26.
Conversão validada com resultado real: BitArray com 156 bits e 1000 shots; a conversão do adaptador é igual a to_bool_array(order='little'). 156000 bits uint8. Fração geral de 1: 0,4971.
Colunas mais afastadas de 0,5 (posição, qubit físico, fração de 1): 121, 0,3450; 46, 0,4080; 112, 0,5740. Amostra de um job: não é conclusão sobre viés.
Calibração: properties() no início da execução tem data 2026-11-01 11:09:06 (-03:00); o retrato gravado no envio tem 07:36:54 (-03:00). A data mudou, mas o erro de leitura dos 156 qubits não mudou (diferença máxima 0,00000). Não se sabe ainda qual propriedade mudou.
Confirmado no ibm_kingston: 156 qubits operacionais; max_shots 100000; default_rep_delay 0,00025 s; erro de leitura (31/10/2026) mínimo 0,00134, mediana 0,00989, máximo 0,49451.
Janela do orçamento: 28 dias rolantes (usage_period de 03/10 a 31/10 na sonda de 31/10). Limite do Open Plan: 600 s.
Dry-run indisponível para o ibm_kingston no Open Plan (QiskitBackendNotFoundError: não há backend mock_). O custo real só se mede com job real. Mensagem de falha corrigida no commit ab11bc5.
SamplerV2 obsoleto desde qiskit-ibm-runtime 0.50.0 (DeprecationWarning, remoção não antes de 3 meses após o lançamento). Versão fixada em 0.51.0; a troca para executor_sampler fica depois da coleta 1.
Estimativa com um único ponto (limite superior, não medida): 2 milhões de bits cabem em um job de cerca de 12.821 shots com reserva de ~41 s; 3 milhões em cerca de 19.231 shots com reserva de ~60 s. Um segundo job de calibração confirma ou derruba isso.
Pendências antes da coleta 1: (1) recuperar o job de calibração, que fecha a conta no log; (2) segundo job de calibração; (3) registrar aqui o plano congelado da coleta 1 antes do primeiro envio; (4) P1: copiar data/logs/replay_history.json após o primeiro eal run real; (5) gate do Dia 6 (2 a 3 milhões de bits reais salvos), ainda não avaliado.
Limitação nova (seção 17): o adaptador lê o uso primeiro em metrics()['usage']['quantum_seconds'], chave que a IBM não devolveu neste job; a IBM expõe qpu_charge_time_seconds. A leitura caiu em usage(), que devolveu o mesmo valor. Corrigir antes da coleta 1.
Limitações novas (seção 17), ainda não listadas: janela de queda entre a checagem do lote e a gravação (o lote fica consumido e não registrado); leituras de semente Toeplitz não passam pelo detector de replay (premissa P3); limite de 64 MiB do histórico de replay.

<!-- coleta1-plano:start -->
### Plano congelado da coleta 1 (Dia 6, registrado antes do primeiro envio)

Registrado em 01/11/2026 sobre o commit dca8fb6. Nenhum parâmetro abaixo muda depois do primeiro envio da coleta 1 (seção 6.5).

- **Backend:** ibm_kingston.
- **Qubits:** os 156 operacionais, todos, sem exclusão. A decisão foi tomada quando já existia saída da QPU nos jobs de calibração; excluir algum qubit agora seria escolher olhando os dados.
- **Circuito:** Hadamard em todos os qubits e medição (`hadamard_all_measure`), SamplerV2, `rep_delay` padrão do backend (0,00025 s).
- **Sessão:** `coleta1`.
- **Jobs:** 2, enviados um de cada vez. O segundo só é enviado depois que o primeiro for recuperado e inspecionado.
- **Shots por job:** 9.616, o que dá 1.500.096 bits por job e 3.000.192 no total.
- **Reserva por job:** 20 s.
- **Base do custo:** dois jobs de calibração (1.000 shots: 2 s; 4.000 shots: 3 s). O modelo é 1,667 s fixos + 0,333 ms por shot, com estimativa central de 4,9 s por job. A IBM cobra em segundos inteiros; com ±0,5 s em cada ponto, o pior caso é cerca de 7,2 s por job.
- **Critérios de parada:** a coleta encerra quando os 2 jobs estiverem salvos. Ela para antes se acontecer qualquer uma destas situações:
  - recusa do orçamento;
  - job com status diferente de DONE;
  - falha de conversão, ou params do lote diferentes de OK no `inspecionar`;
  - aviso de lote duplicado;
  - primeiro job usando mais de 15 s (3 vezes a estimativa central, sinal de que o modelo de custo está errado).

  Ao parar: documentar e não reenviar sem uma nova decisão registrada aqui.
- **O que não é critério de parada:** a estatística dos bits (viés, H estimada). Reprovação no limiar 0,9 é resultado válido.
- **Bits de calibração:** os da sessão `cal` (`cal_001` e `cal_002`, 780.000 bits) não contam para o gate.
- **Gate do Dia 6:** 3.000.192 bits reais salvos em `data/raw`, na sessão `coleta1`.
<!-- coleta1-plano:end -->

<!-- dia6-gate:start -->
### Resultado do gate do Dia 6 (coleta 1)

Gerado por `scripts/atualizar_docs_gate6.py` a partir de `data/results/dia6_coleta1_inventario.csv` (SHA-256 `9f01c43147013f6da2de009f010899bfd46d775ac8dac2b908f9b010746d5b81`), que sai de `scripts/inventario_coleta1.py`. Os números abaixo vêm desse arquivo.

- **Resultado:** ATINGIDO. 3.000.192 bits reais da QPU salvos em `data/raw`, sessão `coleta1`; a meta do plano congelado era 3.000.192.
- **Lotes:** 2, backend ibm_kingston, 156 qubits.
  - `2026-11-01_ibm_kingston_coleta1_001.json`: job `dbjlg80nceqs73ak89g0`, 9.616 shots, 1.500.096 bits, uso 5 s, SHA-256 do `.npy` `0b8d5b04482331f1eb7b8a356963fde7155126a033d0f66daf2e0d68a3652412`.
  - `2026-11-01_ibm_kingston_coleta1_002.json`: job `dbjlkahffo6c73b9t1u0`, 9.616 shots, 1.500.096 bits, uso 5 s, SHA-256 do `.npy` `c8a9ca348727ecda02f79b67b052cc3b1f3517d31ec88646cc269e0780054cc9`.
- **Uso de QPU da coleta 1:** 10 s no total.
- **Critérios de parada:** nenhum disparou; status DONE, conversão e params do lote OK e nenhum aviso de duplicata, conferidos com `inspecionar_job_ibm.py` em cada job.
- **Cópia dos dados crus:** `C:\projeto\ancoras\coleta1_2026-11-01`, com SHA-256 conferido arquivo a arquivo. `data/raw` não é versionado.
- **Fica para depois:** reorganizar as seções 6.12, 9.3, 9.4 e 17 (R11), mudar o campo Status (R12) e analisar os dados no E1.
<!-- dia6-gate:end -->

<!-- dia6-e1parcial:start -->
### E1 parcial (Dia 6): QPU real, simulador e fonte os; jobs cal

Gerado por `scripts/atualizar_docs_e1parcial.py`. Todo número abaixo vem dos CSVs de `data/results` (SHA-256 com fim de linha normalizado para LF):

- `dia6_qpu_vs_sim_lotes.csv`: `5023a1a6df5473f2be955d66681d732127f6d29714424d0060b9b13cefbb6e14`
- `dia6_qpu_vs_sim_resumo.csv`: `dd6f7375d0947e8cd0030eddf9552330468964dcbee860d51a1a47e4790ef7ba`
- `dia6_qpu_excesso_leitura.csv`: `d3fe3fad35fa33c3fd50d5b861903dc9a56cb70c16cfbb7bf789b41c1f4f40a6`
- `dia6_qpu_vs_sim_por_qubit.csv`: `9af7321c7c7e5423a1e6337de05f29455f6c2a529962f5220f2177951df05895`
- `dia6_deriva_dia_lotes.csv`: `3078d678a7beb06409d8a804de88e3327ddf7b65276f146283d588ebe0bcdcf2`
- `dia6_deriva_dia_conjunto_fixo.csv`: `543627875f9bfa2c64d0c642ab338b6e9375e25e391b26d008836f439ad63e9e`
- `dia6_deriva_dia_estabilidade.csv`: `0051ad524090bf8a20563f2bce7118aabb03feb58693869d10a38f12de9638e2`

Entrada: 2 lotes por fonte, de 1500096 bits cada, da sessão `coleta1`. O simulador é o `qpu_sim` com ruído do FakeKingston; a fonte `os` tem o mesmo formato.

#### Testes de saúde por lote

Limiar de H estimada: 0,90 (seção 6.5, fixado antes dos dados reais e não ajustado).

| Fonte | Lote | Aprovado | RCT, APT e replay | H estimada | H >= limiar | p monobit | p blocos | p runs | Bits extraídos | Rendimento |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qpu_real (ibm_kingston) | 1 | não | ok | 0,9623 | sim | 2,91e-18 | 0,359 | 0 | 0 | 0,000 |
| qpu_real (ibm_kingston) | 2 | não | ok | 0,9555 | sim | 6,62e-07 | 0,839 | 0 | 0 | 0,000 |
| simulador (qpu_sim) | 1 | não | ok | 0,9592 | sim | 6,78e-17 | 0,699 | 0 | 0 | 0,000 |
| simulador (qpu_sim) | 2 | não | ok | 0,9618 | sim | 7,29e-20 | 0,715 | 0 | 0 | 0,000 |
| os (os) | 1 | sim | ok | 0,9695 | sim | 4,76e-01 | 0,742 | 9,37e-01 | 1359324 | 0,906 |
| os (os) | 2 | sim | ok | 0,9665 | sim | 8,23e-02 | 0,029 | 7,40e-01 | 1354932 | 0,903 |

- qpu_real lote 1 reprovado: monobit: p = 2.91e-18 (< 0.01); runs: p = 0 (< 0.01) (pré-teste de frequência falhou; p = 0 (SP 800-22 2.3.4))
- qpu_real lote 2 reprovado: monobit: p = 6.62e-07 (< 0.01); runs: p = 0 (< 0.01) (pré-teste de frequência falhou; p = 0 (SP 800-22 2.3.4))
- simulador lote 1 reprovado: monobit: p = 6.78e-17 (< 0.01); runs: p = 0 (< 0.01) (pré-teste de frequência falhou; p = 0 (SP 800-22 2.3.4))
- simulador lote 2 reprovado: monobit: p = 7.29e-20 (< 0.01); runs: p = 0 (< 0.01) (pré-teste de frequência falhou; p = 0 (SP 800-22 2.3.4))

O `p = 0` do teste de runs, quando aparece, vem do pré-teste de frequência que falhou (SP 800-22, 2.3.4); não é evidência independente do monobit.

#### Viés, correlação e estabilidade entre os dois lotes da coleta 1

156 qubits, 9616 shots por lote. Em cada célula de dois valores: lote 1 / lote 2. O z de p1 é em relação a 0,5.

| Fonte | Fração de 1 | \|z\| máx. de p1 | Qubits com \|z\| > 3 | Correlação com o vizinho, \|z\| > 3 | Correlação com o shot seguinte, \|z\| > 3 | Desvio-padrão do zdiff | \|zdiff\| > 3 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qpu_real | 0,4964 / 0,4980 | 33,1 / 36,1 | 28 / 27 | 3 / 2 | 1 / 0 | 1,14 | 3 |
| simulador | 0,5034 / 0,5037 | 96,1 / 96,3 | 26 / 26 | 0 / 0 | 0 / 0 | 1,00 | 0 |
| os | 0,5003 / 0,5007 | 2,9 / 3,5 | 0 / 1 | 0 / 0 | 0 / 0 | 1,04 | 0 |

O zdiff compara o p1 de cada qubit entre os lotes 1 e 2; sem deriva e sem estrutura, o desvio-padrão esperado é perto de 1. As fontes `simulador` e `os` servem de controle.

#### QPU real: desvio de 0,5 acima do erro de leitura do retrato

- Lote 1: 5 de 156 qubits acima do limite (posições: 14, 21, 105, 138, 144).
- Lote 2: 7 de 156 qubits acima do limite (posições: 14, 21, 87, 106, 135, 138, 142).
- Acima do limite em todos os lotes: 14, 21, 138.
- Esperado ao acaso, sem viés além do erro de leitura: cerca de 0,42 por lote.

O limite é 3 erros-padrão de p1 (0,5 / raiz do número de shots) e o excesso é \|p1 - 0,5\| menos o erro de leitura do retrato gravado no envio.

#### Correlação com a posição vizinha

- qpu_real lote 1: pares acima do limite de Bonferroni (|z| > 3,60, 155 pares): 112-113 (z = -6,65).
- qpu_real lote 2: pares acima do limite de Bonferroni (|z| > 3,60, 155 pares): 112-113 (z = -5,59).
- simulador lote 1: pares acima do limite de Bonferroni (|z| > 3,60, 155 pares): nenhum.
- simulador lote 2: pares acima do limite de Bonferroni (|z| > 3,60, 155 pares): nenhum.
- os lote 1: pares acima do limite de Bonferroni (|z| > 3,60, 155 pares): nenhum.
- os lote 2: pares acima do limite de Bonferroni (|z| > 3,60, 155 pares): nenhum.
- QPU real, acima do limite em todos os lotes: 112-113.

z = r vezes a raiz do número de shots (aproximação). "Vizinho" é a posição i + 1 do índice físico, não necessariamente um par acoplado no chip.

#### Maior erro de leitura do retrato

Posição 146: erro de leitura 0,4912 (lote 1: p1 = 0,5057, z = 1,12; lote 2: p1 = 0,4926, z = -1,45). Com erro de leitura perto de 0,5, a saída tende a não depender do estado preparado e pode parecer sem viés. Isso é inferência a partir do retrato gravado, não medida desta coleta, e mostra que teste de saída não certifica a origem (hipótese do E2).

#### Jobs cal contra a coleta 1 (persistência dentro do dia)

| Lote | criado_em (UTC) | Calibração no envio | Shots | Fração de 1 | Conferência |
| --- | --- | --- | --- | --- | --- |
| cal_001 | 2026-11-01T14:30:25Z | 2026-11-01 07:36:54-03:00 | 1000 | 0,4971 | batch_hash |
| cal_002 | 2026-11-01T15:09:16Z | 2026-11-01 11:57:51-03:00 | 4000 | 0,4973 | batch_hash |
| coleta1_001 | 2026-11-01T15:24:23Z | 2026-11-01 11:57:51-03:00 | 9616 | 0,4964 | inventario+batch_hash |
| coleta1_002 | 2026-11-01T15:28:12Z | 2026-11-01 11:57:51-03:00 | 9616 | 0,4980 | inventario+batch_hash |

Intervalos pelo campo `criado_em`, que é o momento em que o lote foi salvo, não o da execução na QPU: cal_001 → cal_002: 39 min; cal_002 → coleta1_001: 15 min; cal_001 → coleta1_001: 54 min.

| Item | Grupo | Lote | Estimativa | z | z esperado | Testável | Replica | Magnitude compatível |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| par 112-113 | par_replicado_coleta1 | cal_001 | -0,0223 | -0,70 | 1,97 | não | — | — |
| par 112-113 | par_replicado_coleta1 | cal_002 | -0,0473 | -2,99 | 3,95 | sim | sim | sim |
| par 130-131 | par_replicado_coleta1 | cal_001 | -0,0712 | -2,25 | 1,07 | não | — | — |
| par 130-131 | par_replicado_coleta1 | cal_002 | -0,0286 | -1,81 | 2,14 | não | — | — |
| qubit 121 | controle_leitura | cal_001 | 0,3450 | -9,80 | 11,17 | sim | sim | sim |
| qubit 121 | controle_leitura | cal_002 | 0,3232 | -22,36 | 22,34 | sim | sim | sim |
| qubit 131 | controle_leitura | cal_001 | 0,5540 | 3,42 | 9,03 | sim | sim | não |
| qubit 131 | controle_leitura | cal_002 | 0,6475 | 18,66 | 18,07 | sim | sim | sim |
| qubit 138 | vies_alem_da_leitura | cal_001 | 0,4940 | -0,38 | 8,78 | sim | não | não |
| qubit 138 | vies_alem_da_leitura | cal_002 | 0,3887 | -14,07 | 17,55 | sim | sim | não |
| qubit 14 | vies_alem_da_leitura | cal_001 | 0,5070 | 0,44 | 9,29 | sim | não | não |
| qubit 14 | vies_alem_da_leitura | cal_002 | 0,4035 | -12,21 | 18,59 | sim | sim | não |
| qubit 21 | vies_alem_da_leitura | cal_001 | 0,5070 | 0,44 | 1,47 | não | — | — |
| qubit 21 | vies_alem_da_leitura | cal_002 | 0,5220 | 2,78 | 2,95 | sim | sim | sim |

- qubit 14: replica em cal_002; não replica em cal_001; não testável em nenhum lote.
- qubit 21: replica em cal_002; não replica em nenhum lote; não testável em cal_001.
- qubit 138: replica em cal_002; não replica em cal_001; não testável em nenhum lote.
- qubit 121: replica em cal_001, cal_002; não replica em nenhum lote; não testável em nenhum lote.
- qubit 131: replica em cal_001, cal_002; não replica em nenhum lote; não testável em nenhum lote.
- par 112-113: replica em cal_002; não replica em nenhum lote; não testável em cal_001.
- par 130-131: replica em nenhum lote; não replica em nenhum lote; não testável em cal_001, cal_002.

Estabilidade do p1 dos qubits entre pares de lotes (zdiff, com shots diferentes):

| Par de lotes | zdiff médio | Desvio-padrão do zdiff | \|zdiff\| > 3 | \|zdiff\| máx. |
| --- | --- | --- | --- | --- |
| cal_001 x cal_002 | -0,01 | 1,45 | 6 | 6,05 |
| cal_001 x coleta1_001 | +0,05 | 1,62 | 5 | 10,33 |
| cal_001 x coleta1_002 | -0,05 | 1,57 | 6 | 8,90 |
| cal_002 x coleta1_001 | +0,10 | 1,26 | 2 | 6,76 |
| cal_002 x coleta1_002 | -0,07 | 1,13 | 2 | 4,37 |
| coleta1_001 x coleta1_002 | -0,21 | 1,14 | 3 | 4,36 |

#### Limites desta análise

- Uma sessão, num único dia, num único backend. O E1 completo pede sessões em outros horários e em outros dias (seção 9.3); nada aqui mede deriva entre dias.
- O conjunto fixo e os critérios (testável, replica, magnitude compatível) estão como constantes em `scripts/analisar_cal.py` e foram fixados antes da leitura dos lotes cal, só com base na coleta 1. Uma das posições do conjunto fixo (112, do par 112-113) já tinha aparecido entre as colunas mais afastadas de 0,5 do `cal_001` no registro da seção 18; a correlação do par não tinha sido vista.
- Os lotes cal não estão no inventário: a integridade deles é só o `batch_hash`. A coleta 1 é conferida também pelo SHA-256 do inventário.
- O retrato de erro de leitura e a data de calibração gravados são os do envio, não os da execução (R8). Os quatro lotes têm o mesmo retrato de erro de leitura.
- `criado_em` é o momento em que o lote foi salvo; os tempos de execução na QPU não estão nos dados e não entram nas conclusões.
- O simulador usa a calibração congelada do FakeKingston, não a do dia da coleta; ele serve de referência qualitativa. O limiar de H estimada e os limiares dos testes de saúde não foram alterados.
- Mais de um teste por qubit: os qubits e pares citados vêm de varreduras de 156 e 155 itens; só o que repete entre lotes independentes ou passa pelo limite de Bonferroni indicado tem peso.
- Isto é um registro de medições. A causa do viés (leitura, porta, relaxação, calibração ou crosstalk) não foi determinada.

<!-- dia6-e1parcial:end -->

<!-- dia6-estado:start -->
### Estado ao fim da etapa 5 do Dia 6 (registro)

Gerado por `scripts/atualizar_estado_dia6.py` a partir do git, dos CSVs de `data/results` e de `eal/config.py`. O campo Status deste documento não foi alterado (R12 depende do R11).

- Branch `master`; HEAD no momento do registro (antes do commit do próprio registro): `700cddd`; árvore limpa.
- Última execução completa da suíte, informada na hora do registro: 2500 passed, 1 skipped (`py -3.12 -m pytest -q`).
- Coleta 1: 2 jobs, 3000192 bits, 10 s de QPU (pelo inventário).
- Orçamento (`eal/config.py`): 600 s por janela de 28 dias; teto de 24 h 330 s; reserva máxima por job 60 s; margem 30 s. O saldo atual não está neste registro: conferir antes de qualquer envio.

#### Commits desde `23d328a`

| Commit | Título |
| --- | --- |
| `182c5a8` | Dia 6 etapa 0: script de reconhecimento da conta e do backend IBM (so leitura) |
| `2c911e8` | Dia 6 etapa 0b: sonda complementar (janela do orcamento, max_shots, erro de leitura por qubit, aviso do SamplerV2) |
| `aa8f385` | Dia 6 etapa 1 passo 1: guarda de orcamento de QPU e log de uso (qpu_budget), 107 testes, 34 mutacoes |
| `542fcbf` | Dia 6 etapa 1 passo 2: conversao do BitArray em bits e params do lote da IBM (ibm_bits), 82 testes, 33 mutacoes |
| `203a73f` | Dia 6 etapa 1 passo 3a: constantes da politica de QPU e do acesso a IBM no config.py (script tudo-ou-nada), 39 testes |
| `b6bd0cd` | Dia 6 etapa 1 passo 3b: adaptador da IBM (envio com limite duro, recuperacao, manifesto), 102 testes, 42 mutacoes; scripts de mutacao sem bytecode obsoleto |
| `f0e38a6` | Dia 6 etapa 1 passo 4a: modelo de custo de QPU e planejamento da coleta (qpu_calibration), 110 testes, 31 mutacoes |
| `655bf84` | Dia 6 etapa 1 passo 4b: ponto de entrada da coleta na IBM (status, calibrar, enviar com confirmacao, recuperar) e constantes de calibracao, 102 testes, 40 mutacoes |
| `8e6ba62` | Dia 6 P2: fecha as mutacoes do G6 (params do lote no recibo): 20 testes de lacunas, script de mutacoes com descoberta automatica, 19 mutacoes mortas |
| `ab11bc5` | Dia 6: mensagem do dry-run sem backend mock (nada foi gasto), inspecao so de leitura de um job da IBM (fila, estimativa, deriva de calibracao), 53 testes, mutacoes 46 e 28 |
| `2ce238c` | Dia 6: registro da calibracao na QPU real e pendencias em PROJECT.md e THREAT_MODEL.md (bloco acrescentado ao fim, sem editar secoes), 19 testes |
| `dca8fb6` | R2: uso lido primeiro em qpu_charge_time_seconds (formato real da IBM), depois usage() e quantum_seconds; 122 testes, 49 mutacoes; T11 conferido em 2ce238c e no stage |
| `80837a0` | R4: plano congelado da coleta 1 no PROJECT.md antes do primeiro envio (2 jobs x 9616 shots, reserva 20 s, 156 qubits, sessao coleta1), 18 testes |
| `deac699` | R6: gate do Dia 6 atingido (3.000.192 bits reais, sessao coleta1, 2 jobs, 10 s de QPU); inventario em data/results e registro no PROJECT.md, 48 testes |
| `c1d8210` | Dia 6 etapa 4: pipeline nos dados reais da coleta 1 vs simulador e os (script, 16 testes, 2 CSVs); QPU reprovada no monobit, H estimada 0,956-0,962; 2422 testes |
| `863fb14` | Dia 6 etapa 4b: resumo da coleta 1 (frac1, correlacoes, zdiff) e excesso sobre o erro de leitura; script, 15 testes, 2 CSVs; 2437 testes |
| `a3bfb8c` | Dia 6 etapa 5: E1 parcial registrado no PROJECT.md (gerado dos CSVs); jobs cal vs coleta 1 por qubit com conjunto fixo pre-registrado; viés de 14 e 138 presente em cal_002 e ausente em cal_001; intervalos entre lotes corrigidos (15 a 54 min, por criado_em); 2 scripts, 40 testes, 4 CSVs |
| `e0f7225` | Dia 6: docstring do analisar_cal.py corrigido (intervalo entre lotes vem de criado_em) |
| `700cddd` | Dia 6: script de estado (bloco no PROJECT.md e JSON para o proximo chat) e 23 testes |

#### Resultados deste estágio (SHA-256 com fim de linha normalizado para LF)

| Arquivo | SHA-256 |
| --- | --- |
| `dia6_coleta1_inventario.csv` | `16b4c2b5bd5ba94479c8b26b9a4830cfb0da82662adb939adaf68bacee37acf5` |
| `dia6_deriva_dia_conjunto_fixo.csv` | `543627875f9bfa2c64d0c642ab338b6e9375e25e391b26d008836f439ad63e9e` |
| `dia6_deriva_dia_estabilidade.csv` | `0051ad524090bf8a20563f2bce7118aabb03feb58693869d10a38f12de9638e2` |
| `dia6_deriva_dia_lotes.csv` | `3078d678a7beb06409d8a804de88e3327ddf7b65276f146283d588ebe0bcdcf2` |
| `dia6_deriva_dia_por_qubit.csv` | `fc4a986065fcbf1c07cc06c79a5860e967946ce1ac94b10b6af234878bbe1075` |
| `dia6_qpu_excesso_leitura.csv` | `d3fe3fad35fa33c3fd50d5b861903dc9a56cb70c16cfbb7bf789b41c1f4f40a6` |
| `dia6_qpu_vs_sim_lotes.csv` | `5023a1a6df5473f2be955d66681d732127f6d29714424d0060b9b13cefbb6e14` |
| `dia6_qpu_vs_sim_por_qubit.csv` | `9af7321c7c7e5423a1e6337de05f29455f6c2a529962f5220f2177951df05895` |
| `dia6_qpu_vs_sim_resumo.csv` | `dd6f7375d0947e8cd0030eddf9552330468964dcbee860d51a1a47e4790ef7ba` |

A análise está no bloco `dia6-e1parcial`, logo acima.

#### O que resta

| Id | Pendência | Quando |
| --- | --- | --- |
| T11 | checagem de segredos (T11) sobre todos os commits da lista acima; o usuário ainda não confirmou a saída dela nos commits feitos nesta fase | antes de qualquer novo commit |
| COLETA2 | coleta 2 em outro horário do dia, para medir deriva (seção 9.3): plano congelado no PROJECT.md antes do primeiro envio; só o usuário envia, com comando explícito e SIM | próxima etapa |
| DEP_SESSAO | inventario_coleta1.py, analisar_coleta1.py e analisar_cal.py fixam a sessão coleta1 (e o prefixo coleta1_); parametrizar a sessão antes de analisar a coleta 2 (muda código: precisa de plano e aprovação) | antes de analisar a coleta 2 |
| R8 | gravar o retrato da calibração da execução em cada lote; sem isso a deriva por tempo e por calibração não se separa (o registro da seção 18 diz que o cal_001 rodou sob uma calibração diferente da data gravada no lote) | antes da coleta 2 |
| CRITERIO_REPLICA | o critério 'replica' (mesmo sinal e \|z\| > 2) é fraco: onde a magnitude é incompatível, relatar 'direção reproduzida, magnitude não' | ao escrever o relatório |
| R11 | reorganizar as seções 6.12, 9.3, 9.4 e 17 do PROJECT.md com o conteúdo dos blocos acrescentados ao fim (dia6-e1parcial e dia6-estado incluídos) | antes de mudar o Status |
| R12 | campo Status do PROJECT.md ainda diz Dia 5 de 9; atualizar depois do R11 | depois do R11 |
| BACKUP_RESULTADOS | copiar data/results para C:\projeto\ancoras (os dados crus já têm cópia em coleta1_2026-11-01) | baixa |
| COLETA3 | coleta 3 (deriva entre dias), seção 9.3: decisão do usuário; vem antes da coleta 2 na ordem de cortes da seção 16 | decidir antes do Dia 7 |
| R7 | copiar data\logs\replay_history.json para C:\projeto\ancoras após o primeiro eal run real | depois do primeiro eal run real |
| R9 | trocar SamplerV2 pelo executor_sampler.Sampler antes de qualquer atualização do pacote | baixa, versão fixada |
| R10 | limpeza: texto 'disponível para um job' do status ignora o limite de 60 s; RuntimeJobNotFound aparece como erro inesperado; entrada de log do dry-run recusado | baixa |
| T_TEMPO | test_noisy_million_bits_fast depende da velocidade da máquina; registrar como limitação na seção 17 | junto com o R11 |

#### Próxima etapa

Sessão de coleta 2 em outro horário do dia, para medir deriva (seção 9.3). Primeiro o plano congelado neste documento, sem enviar nada; o envio é só do usuário.

<!-- dia6-estado:end -->

<!-- coleta2-plano:start -->
### Plano congelado da coleta 2 (Dia 6, registrado antes do primeiro envio)

Registrado em 01/11/2026 sobre o commit e82e081. Nenhum parâmetro abaixo muda depois do primeiro envio da coleta 2 (seção 6.5).

- **Objetivo:** medir a deriva no mesmo dia (seção 9.3), comparando com a coleta 1.
- **Backend, qubits, circuito e `rep_delay`:** iguais aos da coleta 1 (ibm_kingston; os 156 operacionais, sem exclusão; `hadamard_all_measure` com SamplerV2; 0,00025 s).
- **Sessão:** `coleta2`.
- **Jobs:** 2, enviados um de cada vez. O segundo só é enviado depois que o primeiro for recuperado e inspecionado.
- **Shots por job:** 9.616, o que dá 1.500.096 bits por job e 3.000.192 no total.
- **Reserva por job:** 20 s.
- **Horário:** o primeiro envio não acontece antes das 17:00 (-03:00) de 01/11/2026, cerca de 5 h depois da coleta 1.
- **Custo:** a coleta 1 usou 5 s por job. Saldo antes do envio: 583 s.
- **Calibração:** cada lote grava o retrato do envio (`calibration_date`, `readout_error_by_position`) e, pelo R8 (commit e82e081), o da execução (`calibration_date_run`, `readout_error_run_by_position`).
- **Critérios de parada e o que não é critério de parada:** iguais aos da coleta 1, inclusive parar se o primeiro job usar mais de 15 s. Ao parar: documentar e não reenviar sem uma nova decisão registrada aqui.
- **Critérios de análise, fixados antes de ver os dados:**
  - saúde e H estimada por lote, pelo mesmo pipeline da coleta 1, com limiar 0,9;
  - conjunto fixo: viés além da leitura nos qubits 14, 21 e 138; controles 121 e 131; pares 112-113 e 130-131. Nenhum item entra ou sai depois de ver a coleta 2;
  - réplica contra a coleta 1: mesmo sinal e |z| > 2. Onde a direção se reproduz e a magnitude não (`magnitude_compativel`), o resultado é "direção reproduzida, magnitude não";
  - cada comparação registra se a calibração da execução é a mesma da coleta 1 ou não.
- **Análise:** só depois da parametrização da sessão nos scripts de análise (DEP_SESSAO).
<!-- coleta2-plano:end -->

<!-- dia6-coleta2:start -->
### Coleta 2 e deriva no mesmo dia (Dia 6, registro gerado dos CSVs)

Gerado por `scripts/registrar_deriva_coleta2.py` a partir dos CSVs listados no fim deste bloco. Nenhum número foi digitado à mão. Os critérios são os do plano congelado da coleta 2, registrado antes do primeiro envio.

**Lotes da coleta 2 (inventário):** 2 lotes, 3.000.192 bits, 10 s de QPU.

| Arquivo | Job | Bits | Uso (s) |
|---|---|---|---|
| 2026-11-01_ibm_kingston_coleta2_001.json | dbjq01pffo6c73ba4lo0 | 1.500.096 | 5 |
| 2026-11-01_ibm_kingston_coleta2_002.json | dbjq4ehkdqps73912u30 | 1.500.096 | 5 |

**Saúde por lote (mesmo pipeline da coleta 1, limiar 0,9):**

| Fonte | Lote | Aprovado | H estimada | Bits extraídos |
|---|---|---|---|---|
| qpu_real | 1 | não | 0,959769 | 0 |
| qpu_real | 2 | não | 0,955301 | 0 |
| simulador | 1 | não | 0,959153 | 0 |
| simulador | 2 | não | 0,961837 | 0 |
| os | 1 | sim | 0,966476 | 1.354.932 |
| os | 2 | sim | 0,966476 | 1.354.932 |

**Calibração e fração de 1 por lote:**

| Lote | Sessão | Calibração em vigor | Retrato de leitura | Igual à coleta 1 | Fração de 1 |
|---|---|---|---|---|---|
| coleta1_001 | coleta1 | 2026-11-01 11:57:51-03:00 | envio | sim | 0,4964 |
| coleta1_002 | coleta1 | 2026-11-01 11:57:51-03:00 | envio | sim | 0,4980 |
| coleta2_001 | coleta2 | 2026-11-01 16:56:51-03:00 | execucao | não | 0,5025 |
| coleta2_002 | coleta2 | 2026-11-01 16:56:51-03:00 | execucao | não | 0,5011 |

**Conjunto fixo, coleta 2 contra a coleta 1:**

| Item | Grupo | Lote | Estimativa | z | z esperado | Resultado |
|---|---|---|---|---|---|---|
| qubit 14 | vies_alem_da_leitura | coleta2_001 | 0,5017 | 0,33 | 28,82 | não replica |
| qubit 14 | vies_alem_da_leitura | coleta2_002 | 0,4997 | -0,06 | 28,82 | não replica |
| qubit 21 | vies_alem_da_leitura | coleta2_001 | 0,5232 | 4,55 | 4,57 | replica |
| qubit 21 | vies_alem_da_leitura | coleta2_002 | 0,5236 | 4,63 | 4,57 | replica |
| qubit 138 | vies_alem_da_leitura | coleta2_001 | 0,4875 | -2,45 | 27,22 | direção reproduzida, magnitude não |
| qubit 138 | vies_alem_da_leitura | coleta2_002 | 0,4844 | -3,06 | 27,22 | direção reproduzida, magnitude não |
| qubit 121 | controle_leitura | coleta2_001 | 0,3514 | -29,15 | 34,63 | direção reproduzida, magnitude não |
| qubit 121 | controle_leitura | coleta2_002 | 0,3481 | -29,80 | 34,63 | direção reproduzida, magnitude não |
| qubit 131 | controle_leitura | coleta2_001 | 0,6856 | 36,41 | 28,01 | direção reproduzida, magnitude não |
| qubit 131 | controle_leitura | coleta2_002 | 0,6736 | 34,04 | 28,01 | direção reproduzida, magnitude não |
| par 112-113 | par_replicado_coleta1 | coleta2_001 | -0,0726 | -7,12 | 6,12 | replica |
| par 112-113 | par_replicado_coleta1 | coleta2_002 | -0,0742 | -7,28 | 6,12 | replica |
| par 130-131 | par_replicado_coleta1 | coleta2_001 | -0,0528 | -5,18 | 3,32 | replica |
| par 130-131 | par_replicado_coleta1 | coleta2_002 | -0,0396 | -3,88 | 3,32 | replica |

Contagem: direção reproduzida, magnitude não: 6; não replica: 2; replica: 6.

**Estabilidade entre pares de lotes (zdiff dos qubits):**

| Lote A | Lote B | Média | Desvio-padrão | Qubits acima de 3 |
|---|---|---|---|---|
| coleta1_001 | coleta1_002 | -0,212 | 1,145 | 3 |
| coleta1_001 | coleta2_001 | -0,845 | 3,274 | 12 |
| coleta1_001 | coleta2_002 | -0,649 | 3,377 | 9 |
| coleta1_002 | coleta2_001 | -0,633 | 3,111 | 10 |
| coleta1_002 | coleta2_002 | -0,437 | 3,313 | 11 |
| coleta2_001 | coleta2_002 | 0,196 | 1,133 | 2 |

**Limites:**

- A coleta 2 rodou sob outra calibração (2026-11-01 16:56:51-03:00) que a coleta 1 (2026-11-01 11:57:51-03:00). A diferença entre as coletas mistura o tempo decorrido e a troca de calibração, e estes dados não separam os dois.
- O critério de réplica (mesmo sinal e |z| > 2) é fraco; por isso a magnitude é relatada à parte.
- Isto é um registro de medições. A causa de qualquer diferença (leitura, porta, relaxação, calibração ou outra) não é afirmada aqui.

**CSVs (SHA-256 dos bytes em disco):**

- `dia6_coleta2_inventario.csv`: `d2d1fc799f0f1360e910c21cd9899ab188cb673d8fb76702e78291a015be1901`
- `dia6_coleta2_qpu_vs_sim_lotes.csv`: `0a30e43ae33ad62b8cbef7cea034beb3c0199c95beebab3ba3a23c7e36930edf`
- `dia6_deriva_coleta2_conjunto_fixo.csv`: `6f823feef65d7b593a99f4e723f5a0150e88beaedbb93bd4475b0f09c74a4032`
- `dia6_deriva_coleta2_estabilidade.csv`: `efdba5aedc83b95ba23a88135415facadd3a2f5697fb5537b62270d813fc5b99`
- `dia6_deriva_coleta2_lotes.csv`: `24d3ba1bd8b02b6d1b775baee773260e7f6bfc06589c7fdd01af0cf78ffb628b`
<!-- dia6-coleta2:end -->

<!-- dia7-e2:start -->
### E2, ataques: taxa de detecção e falsos positivos (Dia 7, registro gerado dos CSVs)

Gerado por `scripts/registrar_e2.py` a partir de `e2_lotes.csv` e `e2_resumo.csv`. Nenhum número foi digitado à mão. As frases da seção de leitura só são gravadas se cada uma for confirmada pelos CSVs; o script recusa se alguma falhar.

**Protocolo (pré-registrado):** rodada sobre o commit `f5b35166ff9550357d0dc30cc14c4ed7fd975130`, conferido na coluna `commit` das 7.900 linhas. 36 células, lotes de 1.000.000 e 4.000.000 bits. Cada lote usa uma instância nova da fonte, semente própria gravada e um detector de replay novo; no replay, as duas leituras de cada par vêm da mesma instância. Detecção é o lote com `approved` falso; no replay só a 2ª leitura conta, e a 1ª entra como referência. Falso positivo é um lote da `os` reprovado. IC 95% de Clopper-Pearson.

**Resultados por célula** (RCT, APT, Replay, H e Estat. contam os lotes em que o respectivo teste falhou; um lote pode falhar em mais de um):

| Grupo | Fonte | Valor | Bits | Reprovados | Lotes | Taxa | IC 95% | RCT | APT | Replay | H | Estat. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| detecção | faulty_biased | 0,501 | 1.000.000 | 60 | 200 | 0,3000 | 0,2374 a 0,3686 | 0 | 0 | 0 | 0 | 60 |
| detecção | faulty_biased | 0,502 | 1.000.000 | 185 | 200 | 0,9250 | 0,8793 a 0,9574 | 0 | 0 | 0 | 0 | 185 |
| detecção | faulty_biased | 0,505 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 0 | 1 | 0 | 0 | 200 |
| detecção | faulty_biased | 0,51 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 0 | 2 | 0 | 0 | 200 |
| detecção | faulty_biased | 0,55 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 0 | 200 | 0 | 200 | 200 |
| detecção | faulty_correlated | 0,501 | 1.000.000 | 64 | 200 | 0,3200 | 0,2560 a 0,3895 | 0 | 1 | 0 | 0 | 63 |
| detecção | faulty_correlated | 0,502 | 1.000.000 | 184 | 200 | 0,9200 | 0,8733 a 0,9536 | 0 | 0 | 0 | 0 | 184 |
| detecção | faulty_correlated | 0,505 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 0 | 1 | 0 | 0 | 200 |
| detecção | faulty_correlated | 0,51 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 0 | 1 | 0 | 0 | 200 |
| detecção | faulty_correlated | 0,6 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 0 | 10 | 0 | 200 | 200 |
| detecção | faulty_stuck | 8 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 0 | 0 | 0 | 0 | 200 |
| detecção | faulty_stuck | 16 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 0 | 2 | 0 | 200 | 200 |
| detecção | faulty_stuck | 24 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 13 | 5 | 0 | 200 | 200 |
| detecção | faulty_stuck | 32 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 200 | 9 | 0 | 200 | 200 |
| detecção | faulty_stuck | 64 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 200 | 126 | 0 | 200 | 200 |
| detecção | faulty_prng | - | 1.000.000 | 6 | 200 | 0,0300 | 0,0111 a 0,0642 | 0 | 0 | 0 | 0 | 6 |
| referência (1ª leitura) | faulty_replay | - | 1.000.000 | 4 | 200 | 0,0200 | 0,0055 a 0,0504 | 0 | 0 | 0 | 0 | 4 |
| detecção (2ª leitura) | faulty_replay | - | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 a 1,0000 | 0 | 0 | 200 | 0 | 4 |
| falso positivo | os | - | 1.000.000 | 52 | 2.000 | 0,0260 | 0,0195 a 0,0340 | 0 | 0 | 0 | 0 | 52 |
| detecção | faulty_biased | 0,501 | 4.000.000 | 95 | 100 | 0,9500 | 0,8872 a 0,9836 | 0 | 0 | 0 | 0 | 95 |
| detecção | faulty_biased | 0,502 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 1 | 0 | 0 | 100 |
| detecção | faulty_biased | 0,505 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 0 | 0 | 0 | 100 |
| detecção | faulty_biased | 0,51 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 0 | 0 | 0 | 100 |
| detecção | faulty_biased | 0,55 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 100 | 0 | 100 | 100 |
| detecção | faulty_correlated | 0,501 | 4.000.000 | 89 | 100 | 0,8900 | 0,8117 a 0,9438 | 0 | 2 | 0 | 0 | 89 |
| detecção | faulty_correlated | 0,502 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 0 | 0 | 0 | 100 |
| detecção | faulty_correlated | 0,505 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 0 | 0 | 0 | 100 |
| detecção | faulty_correlated | 0,51 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 1 | 0 | 0 | 100 |
| detecção | faulty_correlated | 0,6 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 19 | 0 | 100 | 100 |
| detecção | faulty_stuck | 8 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 0 | 0 | 0 | 100 |
| detecção | faulty_stuck | 16 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 3 | 0 | 100 | 100 |
| detecção | faulty_stuck | 24 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 24 | 2 | 0 | 100 | 100 |
| detecção | faulty_stuck | 32 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 100 | 14 | 0 | 100 | 100 |
| detecção | faulty_stuck | 64 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 100 | 96 | 0 | 100 | 100 |
| detecção | faulty_prng | - | 4.000.000 | 4 | 100 | 0,0400 | 0,0110 a 0,0993 | 0 | 0 | 0 | 0 | 4 |
| referência (1ª leitura) | faulty_replay | - | 4.000.000 | 0 | 100 | 0,0000 | 0,0000 a 0,0362 | 0 | 0 | 0 | 0 | 0 |
| detecção (2ª leitura) | faulty_replay | - | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 a 1,0000 | 0 | 0 | 100 | 0 | 0 |
| falso positivo | os | - | 4.000.000 | 18 | 500 | 0,0360 | 0,0215 a 0,0563 | 0 | 1 | 0 | 0 | 17 |

**Falso positivo da `os`, por teste que reprovou o lote:**

| Bits | Lotes `os` | Reprovados | monobit | block | runs | APT |
|---|---|---|---|---|---|---|
| 1.000.000 | 2.000 | 52 | 13 | 18 | 21 | 0 |
| 4.000.000 | 500 | 18 | 6 | 6 | 5 | 1 |

Referência (conta, não medição): 3 testes estatísticos independentes com p mínimo 0,01 reprovariam 0,0297 dos lotes de uma fonte perfeita.

**Leitura (cada frase foi verificada contra os CSVs antes de ser gravada):**

- Viés e correlação (`faulty_biased`, `faulty_correlated`) com intensidade igual ou maior que 0,505 em lotes de 1.000.000 bits, ou 0,502 em lotes de 4.000.000 bits, foram reprovados em todos os lotes.
- Nos valores mais fracos da grade (0,501 nos dois tamanhos e 0,502 em 1.000.000 bits) a detecção é parcial: parte dos lotes passa.
- O RCT não reprovou nenhum lote de viés nem de correlação.
- Travamento (`faulty_stuck`): todos os lotes foram reprovados em todos os comprimentos da grade, inclusive no menor (8). O limite inferior de detecção do travamento não foi encontrado.
- No menor comprimento de travamento (8), o RCT e o teste de min-entropia não reprovaram nenhum lote e os testes estatísticos reprovaram todos.
- O RCT não reprova travamentos de 8 e 16 bits, reprova só parte dos lotes com 24 bits e reprova todos os lotes com 32 e 64 bits.
- O teste de min-entropia só reprovou lotes com viés de 0,55, correlação de 0,6 ou travamento de 16 bits ou mais; não reprovou nenhum lote das demais células, incluindo `os`, `faulty_prng` e `faulty_replay`.
- O teste de replay reprovou todas as 2ª leituras de `faulty_replay` e nenhum lote de qualquer outra célula (sem alarme falso de replay).
- Na fonte `os`, o RCT e o teste de min-entropia não reprovaram nenhum lote.
- Os IC 95% do falso positivo da `os` nos dois tamanhos se sobrepõem; estes dados não distinguem os dois tamanhos.
- A taxa de reprovação de `faulty_prng` não se distingue da da `os`: os IC 95% se sobrepõem nos dois tamanhos. O teste de saída não separa um PRNG de uma fonte boa (limitação T4 do modelo de ameaça).

**Ressalvas:**

- As fontes defeituosas são simuladas (`eal.sources.faulty`, geradas por numpy). As taxas valem para esses modelos de defeito, não para ataques reais. O E2 não usou QPU.
- As taxas das intensidades fracas incluem o ruído de fundo do falso positivo, que tem a ordem de grandeza da `os`; nada foi subtraído.
- Os testes estatísticos só concluem a partir de um tamanho mínimo de lote (`STATS_MIN_BITS`). O E2 mediu apenas lotes acima desse mínimo e não mediu lotes menores.
- Os testes estatísticos reprovam, por construção, uma fração das fontes perfeitas ligada ao p mínimo (referência acima). Mudar esse limiar mudaria também a sensibilidade nas intensidades fracas; isso só pode ser avaliado em um experimento novo, pré-registrado, e não foi feito aqui.
- Os lotes da `os` não têm semente e não são reproduzíveis. Os das fontes defeituosas são reproduzíveis pela semente gravada em `e2_lotes.csv`. Os bits crus não foram guardados.
- A grade, os tamanhos e as repetições foram fixados no commit indicado acima, antes da rodada. O aumento das repetições (10 vezes) foi decidido depois de medir o tempo e antes de ver qualquer taxa.

**CSVs (SHA-256 dos bytes em disco):**

- `e2_lotes.csv`: `f6d7cc87d3fa3fde9b7691307daa4a299628784fabd65ec4fc961510c94ad90a`
- `e2_resumo.csv`: `2fd202e9b3cc0dccf1dd52a6212de0f6296fb6d3e067ddff68a92e1a0de62a0c`
<!-- dia7-e2:end -->

<!-- coleta3-plano:start -->
### Plano congelado da coleta 3 (Dia 7, registrado antes do primeiro envio)

Registrado em 02/11/2026 sobre o commit 01666ec. Nenhum parâmetro abaixo muda depois do primeiro envio da coleta 3 (seção 6.5).

- **Objetivo:** medir a deriva entre dias (seção 9.3).
- **Backend, qubits, circuito e `rep_delay`:** iguais aos das coletas 1 e 2 (ibm_kingston; os 156 operacionais, sem exclusão; `hadamard_all_measure` com SamplerV2; 0,00025 s).
- **Sessão:** `coleta3`.
- **Jobs:** 2, enviados um de cada vez. O segundo só é enviado depois que o primeiro for recuperado e inspecionado.
- **Shots por job:** 9.616, o que dá 1.500.096 bits por job e 3.000.192 no total.
- **Reserva por job:** 20 s.
- **Horário:** o primeiro envio acontece entre 17:00 e 20:00 (-03:00) de 02/11/2026: o dia seguinte ao das coletas 1 e 2, na mesma faixa horária da coleta 2. Se o primeiro envio não acontecer nessa janela, este plano não vale e é refeito.
- **Custo:** as coletas 1 e 2 usaram 5 s por job. Saldo depois da coleta 2: 573 s; o saldo é conferido de novo com `coletar_ibm.py status` antes do primeiro envio.
- **Calibração:** cada lote grava o retrato do envio (`calibration_date`, `readout_error_by_position`) e o da execução (`calibration_date_run`, `readout_error_run_by_position`, R8).
- **Critérios de parada e o que não é critério de parada:** iguais aos das coletas 1 e 2, inclusive parar se o primeiro job usar mais de 15 s. Ao parar: documentar e não reenviar sem uma nova decisão registrada aqui.
- **Critérios de análise, fixados antes de ver os dados:**
  - saúde e H estimada por lote, pelo mesmo pipeline das coletas 1 e 2, com limiar 0,9;
  - conjunto fixo: viés além da leitura nos qubits 14, 21 e 138; controles 121 e 131; pares 112-113 e 130-131. Nenhum item entra ou sai depois de ver a coleta 3;
  - análise principal: contra a coleta 1, com `analisar_deriva.py --sessao coleta3`. Réplica: mesmo sinal e |z| > 2; onde a direção se reproduz e a magnitude não (`magnitude_compativel`), o resultado é "direção reproduzida, magnitude não". Esta comparação mistura o dia com a hora do dia (coleta 1 perto do meio-dia, coleta 3 depois das 17:00), e o registro diz isso;
  - análise secundária, opcional: contra a coleta 2 (mesma faixa horária, dia seguinte), com o mesmo conjunto fixo e a mesma regra de réplica, só se o `analisar_deriva.py` ganhar um parâmetro de referência, com testes. Se não for feita, o registro diz que não foi feita;
  - cada comparação registra se a calibração da execução é a mesma da referência ou não.
- **Análise:** com os comandos que já aceitam `--sessao` (inventário, saúde, resumo e deriva).
<!-- coleta3-plano:end -->

<!-- dia7-coleta3:start -->
### Coleta 3 e deriva entre dias (Dia 7, registro gerado dos CSVs)

Gerado por `scripts/registrar_deriva_coleta3.py` a partir dos CSVs listados no fim deste bloco. Nenhum número foi digitado à mão. Os critérios são os do plano congelado da coleta 3 (bloco `coleta3-plano`), registrado antes do primeiro envio. Análise principal: contra a coleta 1.

**Lotes da coleta 3 (inventário):** 2 lotes, 3.000.192 bits, 10 s de QPU.

| Arquivo | Job | Bits | Uso (s) |
|---|---|---|---|
| 2026-11-02_ibm_kingston_coleta3_001.json | dbkf24d6p51s73cmg7ng | 1.500.096 | 5 |
| 2026-11-02_ibm_kingston_coleta3_002.json | dbkf4f1ffo6c73bbc8m0 | 1.500.096 | 5 |

**Saúde por lote (mesmo pipeline das coletas 1 e 2, limiar 0,9):**

| Fonte | Lote | Aprovado | H estimada | Bits extraídos |
|---|---|---|---|---|
| qpu_real | 1 | não | 0,960593 | 0 |
| qpu_real | 2 | não | 0,955904 | 0 |
| simulador | 1 | não | 0,959153 | 0 |
| simulador | 2 | não | 0,961837 | 0 |
| os | 1 | sim | 0,962463 | 1.349.076 |
| os | 2 | sim | 0,968625 | 1.357.860 |

**Calibração e fração de 1 por lote:**

| Lote | Sessão | Calibração no envio | Calibração em vigor | Retrato de leitura | Igual à coleta 1 | Fração de 1 |
|---|---|---|---|---|---|---|
| coleta1_001 | coleta1 | 2026-11-01 11:57:51-03:00 | 2026-11-01 11:57:51-03:00 | envio | sim | 0,4964 |
| coleta1_002 | coleta1 | 2026-11-01 11:57:51-03:00 | 2026-11-01 11:57:51-03:00 | envio | sim | 0,4980 |
| coleta3_001 | coleta3 | 2026-11-02 16:36:41-03:00 | 2026-11-02 17:14:09-03:00 | execucao | não | 0,5028 |
| coleta3_002 | coleta3 | 2026-11-02 17:14:09-03:00 | 2026-11-02 17:14:09-03:00 | execucao | não | 0,5048 |

**Conjunto fixo, coleta 3 contra a coleta 1:**

| Item | Grupo | Lote | Estimativa | z | z esperado | Resultado |
|---|---|---|---|---|---|---|
| qubit 14 | vies_alem_da_leitura | coleta3_001 | 0,4882 | -2,30 | 28,82 | direção reproduzida, magnitude não |
| qubit 14 | vies_alem_da_leitura | coleta3_002 | 0,5006 | 0,12 | 28,82 | não replica |
| qubit 21 | vies_alem_da_leitura | coleta3_001 | 0,5147 | 2,88 | 4,57 | replica |
| qubit 21 | vies_alem_da_leitura | coleta3_002 | 0,5275 | 5,38 | 4,57 | replica |
| qubit 138 | vies_alem_da_leitura | coleta3_001 | 0,5101 | 1,98 | 27,22 | não replica |
| qubit 138 | vies_alem_da_leitura | coleta3_002 | 0,4992 | -0,16 | 27,22 | não replica |
| qubit 121 | controle_leitura | coleta3_001 | 0,4418 | -11,42 | 34,63 | direção reproduzida, magnitude não |
| qubit 121 | controle_leitura | coleta3_002 | 0,4457 | -10,65 | 34,63 | direção reproduzida, magnitude não |
| qubit 131 | controle_leitura | coleta3_001 | 0,6621 | 31,80 | 28,01 | direção reproduzida, magnitude não |
| qubit 131 | controle_leitura | coleta3_002 | 0,6581 | 31,00 | 28,01 | replica |
| par 112-113 | par_replicado_coleta1 | coleta3_001 | -0,0666 | -6,53 | 6,12 | replica |
| par 112-113 | par_replicado_coleta1 | coleta3_002 | -0,0628 | -6,16 | 6,12 | replica |
| par 130-131 | par_replicado_coleta1 | coleta3_001 | -0,0399 | -3,91 | 3,32 | replica |
| par 130-131 | par_replicado_coleta1 | coleta3_002 | -0,0288 | -2,82 | 3,32 | replica |

Contagem: direção reproduzida, magnitude não: 4; não replica: 3; replica: 7.

**Estabilidade entre pares de lotes (zdiff dos qubits):**

| Lote A | Lote B | Média | Desvio-padrão | Qubits acima de 3 |
|---|---|---|---|---|
| coleta1_001 | coleta1_002 | -0,212 | 1,145 | 3 |
| coleta1_001 | coleta3_001 | -0,882 | 3,063 | 12 |
| coleta1_001 | coleta3_002 | -1,171 | 3,067 | 14 |
| coleta1_002 | coleta3_001 | -0,670 | 2,965 | 11 |
| coleta1_002 | coleta3_002 | -0,959 | 2,983 | 11 |
| coleta3_001 | coleta3_002 | -0,288 | 1,089 | 1 |

Desvio-padrão do zdiff entre lotes da mesma sessão: de 1,089 a 1,145. Entre lotes de sessões diferentes: de 2,965 a 3,067.

**Limites:**

- A coleta 3 rodou sob outra calibração (2026-11-02 17:14:09-03:00) que a coleta 1 (2026-11-01 11:57:51-03:00), em outro dia e em outra hora do dia (plano congelado). A diferença entre as coletas mistura o dia, a hora do dia e a troca de calibração, e estes dados não separam os três.
- No lote coleta3_001, a calibração em vigor na execução (2026-11-02 17:14:09-03:00) difere da do envio (2026-11-02 16:36:41-03:00); a análise usa o retrato da execução (R8).
- A análise secundária prevista no plano (contra a coleta 2, mesma faixa horária em outro dia) não foi feita neste registro.
- O critério de réplica (mesmo sinal e |z| > 2) é fraco; por isso a magnitude é relatada à parte.
- Isto é um registro de medições. A causa de qualquer diferença (leitura, porta, relaxação, calibração ou outra) não é afirmada aqui.

**CSVs (SHA-256 dos bytes em disco):**

- `dia6_coleta3_inventario.csv`: `9de74bbe035c5d10ddfba06ed88ae42448ae108eaebf71b799012a21480d0ba2`
- `dia6_coleta3_qpu_vs_sim_lotes.csv`: `f7e6619f21370f48273dafeb96efa6206471dbf8f4037bb81723f7058a29c13f`
- `dia6_deriva_coleta3_conjunto_fixo.csv`: `aa5c3fbc07a5720c2922993134f52e7661575fdbab9429ecff2fcb5d88c12887`
- `dia6_deriva_coleta3_estabilidade.csv`: `1c8009100de560e6c6a4e98c14e93459263294690cb3687d6a4670e0914518a8`
- `dia6_deriva_coleta3_lotes.csv`: `ba97a9f9c21ac3736bff511e2d0d14bdac519408ce47419a0b2b98e3d056385a`
<!-- dia7-coleta3:end -->
