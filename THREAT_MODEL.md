# Entropy Assurance Layer (EAL) — Modelo de ameaça

- **Versão do documento:** 1.0
- **Data:** 27/10/2026
- **Autor:** Bruno Pascual
- **Documento irmão:** `PROJECT.md`

> Este documento diz **quem pode atacar**, **o que a EAL garante** e, com o mesmo peso, **o que ela não garante**.
> Toda afirmação nos resultados, no painel, no relatório e no one-pager deve caber dentro das garantias da seção 6.

---

## 1. Escopo

O modelo cobre o protótipo da EAL rodando na máquina do autor (Windows 11, Python 3.12), usando:

- a fonte local do sistema operacional (`os`);
- o simulador de QPU (`qpu_sim`, Qiskit Aer);
- a QPU real da IBM via nuvem (`ibm_<backend>`, Open Plan);
- as fontes defeituosas simuladas (`faulty_*`), usadas só em testes e experimentos.

O modelo **não** cobre uso em produção, múltiplos usuários, servidores públicos nem dispositivos embarcados.

---

## 2. Ativos

| ID | Ativo | Por que importa | Onde vive |
| --- | --- | --- | --- |
| AT1 | Semente de 64 bytes | Quem a conhece reconstrói todas as chaves derivadas | Só em memória |
| AT2 | Chaves privadas derivadas (ML-KEM-768, ML-DSA-65) | Decifram ou assinam em nome do dono | Só em memória (exceto `--export-demo`) |
| AT3 | Chave privada do emissor de recibos | Permite falsificar recibos | `keys/*.sk`, fora do Git |
| AT4 | Integridade dos recibos | É a evidência de auditoria do produto | `data/receipts/` |
| AT5 | Integridade dos dados crus e resultados | Os experimentos dependem deles | `data/raw/`, `data/results/` |
| AT6 | Token da IBM | Consome o orçamento e acessa a conta | `.env`, fora do Git |
| AT7 | Orçamento de QPU | Recurso escasso (cerca de 10 min por 28 dias) | Conta IBM |

---

## 3. Fronteiras de confiança

```
┌──────────────────────── Máquina local (confiável) ────────────────────────┐
│  fonte os  →  testes  →  extrator  →  mixer  →  chaves  →  recibo         │
│                 ▲                                                         │
│                 │ bits da QPU (dados não confiáveis)                       │
└─────────────────┼─────────────────────────────────────────────────────────┘
                  │  TLS (SDK qiskit-ibm-runtime)
┌─────────────────┴──────── Nuvem IBM (não confiável para sigilo) ──────────┐
│  fila de jobs  →  QPU (ibm_kingston etc.)  →  resultados                  │
└───────────────────────────────────────────────────────────────────────────┘

Bibliotecas de terceiros (qiskit, numpy, scipy, PQC em Python puro): confiadas, não auditadas.
```

**Regra central:** tudo que vem da nuvem é tratado como **dado não confiável**. Os bits da QPU passam pelos mesmos testes de qualquer fonte e **nunca** são a única origem de uma semente.

---

## 4. Adversários

| ID | Adversário | Capacidade | Objetivo | Em escopo? |
| --- | --- | --- | --- | --- |
| ADV1 | Fonte defeituosa (sem má intenção) | Viés, bits travados, correlação, deriva por ruído ou calibração | — (falha acidental) | **Sim** |
| ADV2 | Provedor de nuvem curioso | Vê todos os bits que a QPU gerou | Conhecer a semente | **Sim** |
| ADV3 | Provedor ou intermediário malicioso | Devolve bits escolhidos: gerador clássico disfarçado, replay, bits fabricados | Tornar a semente previsível | **Parcial** |
| ADV4 | Observador de rede | Lê ou altera tráfego | Ler ou trocar bits da QPU | **Sim**, mitigado pelo TLS do SDK |
| ADV5 | Falsificador de recibos | Edita ou cria recibos | Forjar evidência de auditoria | **Sim** |
| ADV6 | Fonte adversária adaptativa | Controla uma fonte e vê as saídas das outras | Cancelar a entropia na mistura | **Sim** (E4) |
| ADV7 | Atacante com acesso ao host | Malware, administrador, leitura de memória | Roubar semente, chaves, token | **Não** |
| ADV8 | Cadeia de suprimentos | Pacote pip malicioso ou comprometido | Qualquer coisa | **Não** (mitigação mínima: versões fixas) |
| ADV9 | Computador quântico futuro | Algoritmo de Shor | Quebrar RSA e ECC | **Sim**, para chaves e assinatura do recibo (por isso PQC) |
| ADV10 | Uso indevido pelo próprio autor | Tratar simulador como entropia real, exagerar resultados | — (erro humano) | **Sim** |

---

## 5. Ameaças e mitigações

| ID | Ameaça | Adversário | Mitigação | Como é testada | Risco residual |
| --- | --- | --- | --- | --- | --- |
| T1 | Viés ou correlação na fonte | ADV1 | APT, estimador MCV por bit e por byte, extrator dimensionado pela entropia estimada | E1, E2, testes unitários | Baixo para viés grosseiro; médio para correlações sutis |
| T2 | Bits travados | ADV1 | RCT | E2, testes com sequência conhecida | Baixo |
| T3 | Replay de lote ou de bloco | ADV3 | Hash de cada lote e de blocos de 4096 bits; reprova repetição | E2 | Baixo para replay exato; alto para replay transformado |
| T4 | Gerador clássico disfarçado de QPU | ADV3 | Não detectável por testes de saída. Mitigação estrutural: fonte local obrigatória na mistura; CHSH como verificação de sanidade | E2, E5 | **Alto**, declarado como limitação |
| T5 | Provedor conhece os bits | ADV2 | Política: ≥ 1 fonte local aprovada e não simulada em toda semente | Teste de política no mixer | Baixo, se o host for íntegro |
| T6 | Fonte adaptativa cancela a mistura | ADV6 | Combinação por SHA3-512 com separação de domínio (não XOR) | E4 | Baixo, sob a premissa P2 |
| T7 | Deriva da fonte ao longo do tempo | ADV1 | Testes contínuos em todo lote; comparação entre sessões | E1 | Médio |
| T8 | Superestimar a entropia | ADV1, ADV10 | Mínimo de dois estimadores; margem de 128 bits no extrator; nunca alegar conformidade com SP 800-90B | Revisão, comparação opcional com ferramenta do NIST | Médio |
| T9 | Recibo alterado ou forjado | ADV5 | Assinatura ML-DSA-65 sobre JSON canônico; cadeia de hashes; `eal verify` | Testes de adulteração | Baixo, se a chave do emissor estiver protegida |
| T10 | Vazamento da semente ou de chaves | ADV10 | Só em memória; recibo só com hashes; proibido `print`; teste que procura segredos nas saídas | Teste automatizado | Baixo (alto se ADV7) |
| T11 | Vazamento do token IBM | ADV10 | `.env` no `.gitignore`; nunca colar em chat; gerar outro se exposto | Checagem antes de cada commit | Baixo |
| T12 | Estouro do orçamento de QPU | ADV10 | Limite duro em `qpu_ibm.py`; log de uso por job | Teste do limite com valores simulados | Baixo |
| T13 | Simulador usado como entropia real | ADV10 | Flag `is_simulated`; política exclui fontes simuladas no modo `keygen` | Teste de política | Baixo |
| T14 | Falha de todas as fontes | ADV1 | Fail-closed: sem semente, sem chaves, erro registrado | Teste de política | Nenhum (o sistema só para) |
| T15 | Bugs ou canais laterais nas bibliotecas PQC | ADV8 | Uso declarado como protótipo; testes de ida e volta; versões fixas | Testes unitários | **Alto** fora do protótipo |
| T16 | Indisponibilidade da IBM ou fila longa | — | Pipeline funciona só com fontes locais; experimentos podem usar dados já coletados | Execução sem rede | Baixo para o pipeline; médio para os experimentos |

---

## 6. O que a EAL garante

Cada garantia vale **somente** sob as premissas da seção 8.

| ID | Garantia | Condição |
| --- | --- | --- |
| G1 | Falhas grosseiras de fonte (bits travados, viés persistente acima do limiar, repetição de lote) são detectadas por lote, com taxa de falso alarme `α = 2^-40` por amostra no RCT e `α = 2^-20` por janela no APT (cerca de 5 × 10^-7 e 8 × 10^-4 por lote de 1 milhão de bits), por desenho do teste | Entropia declarada `H` correta para a fonte |
| G2 | **Fail-closed:** sem ao menos uma fonte local aprovada e não simulada, nenhuma semente e nenhuma chave são geradas | Política do mixer não alterada |
| G3 | A semente é imprevisível para quem não conhece a saída da fonte local aprovada, **incluindo o provedor da QPU** | P1, P2, P3 |
| G4 | Todo recibo é assinado com ML-DSA-65 e encadeado ao anterior; qualquer alteração é detectada pelo `eal verify` | Chave do emissor não comprometida |
| G5 | Recibos não contêm segredos, somente hashes | Código conforme `PROJECT.md` |
| G6 | Cada semente tem proveniência registrada: fontes, versões, job IDs, resultados dos testes, estimativas e parâmetros do extrator | — |
| G7 | O consumo de QPU nunca passa do orçamento configurado | Todo envio passa por `qpu_ibm.py` |
| G8 | Assinaturas de recibo e chaves derivadas usam algoritmos pós-quânticos padronizados (FIPS 203 e 204) | Bibliotecas corretas |

---

## 7. O que a EAL não garante

| ID | Não garante | Por quê |
| --- | --- | --- |
| N1 | Que os bits tenham **origem quântica** | Numa QPU em nuvem você não controla o dispositivo; o CHSH desse cenário não é um teste de Bell sem brechas |
| N2 | Detectar um gerador pseudoaleatório bem feito ou uma fonte adversária que passa nos testes | Testes de saída não distinguem um bom gerador clássico de uma fonte verdadeira |
| N3 | Conformidade com NIST SP 800-90B, FIPS 140-3 ou qualquer certificação | Estimadores simplificados e nenhuma validação formal |
| N4 | Proteção contra host comprometido | Malware ou administrador lê memória, chaves e token |
| N5 | Implementações PQC seguras para produção | Python puro: sem tempo constante, sem auditoria |
| N6 | Proteção da criptografia clássica (RSA, ECC) contra Shor | A EAL melhora a qualidade das chaves; não substitui a migração para PQC |
| N7 | Que a IBM não veja os bits da QPU | Ela gera e transmite os resultados |
| N8 | Que as estimativas de entropia sejam exatas | São estimativas estatísticas com intervalo de confiança, não provas |
| N9 | Disponibilidade | Depende de fila, manutenção da IBM e orçamento |
| N10 | Que o simulador seja fonte de entropia | O Aer usa gerador pseudoaleatório clássico |
| N11 | Proteção da chave do emissor em disco | Arquivo local sem HSM nem cifragem |
| N12 | Resistência a ataques físicos ou de canal lateral | Fora do escopo do protótipo |

---

## 8. Premissas

| ID | Premissa |
| --- | --- |
| P1 | O host local é íntegro durante a execução (sem malware, sem acesso de terceiros) |
| P2 | As fontes combinadas são independentes entre si, e o SHA3-512 se comporta como função aleatória ideal para a mistura |
| P3 | A fonte `os` (`os.urandom` / `secrets`) do Windows fornece aleatoriedade criptograficamente forte |
| P4 | A semente do extrator Toeplitz é uniforme e independente da fonte extraída (tirada da fonte `os`) |
| P5 | O TLS usado pelo SDK da IBM protege a integridade dos resultados em trânsito |
| P6 | As bibliotecas (qiskit, numpy, scipy, PQC) fazem o que documentam nas versões fixadas em `requirements.txt` |
| P7 | A entropia `H` usada nos limites dos testes é uma estimativa conservadora para cada fonte |

Se uma premissa cair, as garantias que dependem dela caem junto, e isso deve ser dito no relatório.

---

## 9. Como comunicar os resultados

**Pode dizer:**

- "medido", "estimado", "observado", "detectado em X% dos casos simulados";
- "a QPU real apresentou viés de X no qubit Y nesta sessão";
- "verificação de sanidade" (para o CHSH);
- "protótipo de pesquisa".

**Não pode dizer:**

- "certificado", "provado", "validado pelo NIST", "conforme SP 800-90B";
- "aleatoriedade quântica garantida", "inquebrável", "100% seguro";
- "pronto para produção";
- "protege contra computadores quânticos" sem explicar que isso vale para as chaves PQC, não para a fonte de entropia.

**Toda limitação relevante aparece:** no relatório, no README, no one-pager e no campo `limitations` de cada recibo.

---

## 10. Riscos residuais principais

1. **T4 (gerador disfarçado):** é o limite fundamental do produto. A defesa é estrutural (fonte local obrigatória), não estatística. É também o achado mais importante do E2.
2. **T15 (bibliotecas PQC):** aceitável no protótipo; bloqueia qualquer uso real.
3. **T8 (entropia superestimada):** mitigado por margens, mas só uma avaliação formal resolveria.
4. **ADV7 (host comprometido):** fora do escopo; em produção exigiria HSM, enclave ou chip dedicado.

---

## 11. Quando revisar este documento

- Ao adicionar uma fonte nova (outro provedor, chip QRNG local).
- Ao mudar a política do mixer ou o extrator.
- Ao trocar a biblioteca PQC.
- Se um experimento contradisser uma hipótese ou uma garantia.
- Antes de qualquer uso fora do protótipo.
