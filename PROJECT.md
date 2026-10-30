# Entropy Assurance Layer (EAL) — Brief do projeto

- **Versão do documento:** 1.0
- **Data:** 27/10/2026
- **Autor:** Bruno Pascual
- **Status:** Dia 4 de 9 (concluído; gate do Dia 4 aprovado, ver seção 16.2)
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

Medido em 2026-10-30T13:52:03.537145+00:00 (commit `d98e8bb`). Tabela: `data/results/dia4_resilience_2026-10-30_135203.csv`, SHA3-256 `e8b23bb9f44ab1995063420eb7cf6b57dfa8499a6e74b1f7ec8e70ea4c0c5dc6`. Parâmetros: 5 repetições por cenário, lotes de 1.000.000 bits, backend de ruído `FakeKingston`; 60 execuções. Gerado por `scripts/gerar_docs_dia4.py`; resumo, gate e contagem de falsos alarmes foram recalculados do CSV.

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
- A `os` não entrou na mistura em 2 de 45 execuções fora dos cenários em que ela falha de propósito (reprovação pelos testes de saúde ou falha de leitura). Referência da seção 16.1: cerca de 3% por lote. Esta contagem não inclui reprovações do stand-in remoto (ver a tabela de atenção).
- Em 19 execuções com fontes defeituosas ou indisponíveis e a `os` aprovada (`C1_stuck`, `C2_biased_correlated`, `C3_replay/second`, `C4_remote_down`), nenhuma fonte defeituosa entrou na mistura.
- A `faulty_prng` entrou na mistura em 5 de 5 execuções com a `os` aprovada (C6): testes de saída não distinguem um gerador clássico bom (limitação T4).
- Em `keygen`, com a `os` fora (leitura falha ou lote adulterado) e a remota no ar, a semente foi gerada em 0 de 10 execuções (esperado: 0; G2).
- K1: semente utilizável em 5 de 5 execuções; 1 com UNEXPECTED (ver a tabela de atenção).
- C5c: em `experiment`, com a `os` fora, a `qpu_sim` sozinha gerou semente marcada como inutilizável em 5 de 5 execuções.
- Execuções com VIOLATION (política ou isolamento do pipeline quebrados): 0.

**O que este gate não mostra.** A fonte "remota" dos cenários `keygen` é um stand-in (bits da `os` com rótulo de fonte remota não simulada), não a QPU da IBM. O gate verifica política, isolamento e fail-closed; não mede a qualidade estatística da semente (o SHA3-512 de lixo também parece uniforme) nem a taxa de detecção de fontes defeituosas, com 5 repetições por cenário (isso é o E2). O CSV guarda só o SHA3-256 da semente; nenhuma semente nem bit é gravado.
<!-- dia4-gate:end -->

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
+-- scripts/                # plot_bias.py (gr fico de vi s por qubit, Dia 2)
