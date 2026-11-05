# Roadmap pós-9 dias

Estado de partida: protótipo de pesquisa em Python, com fontes `os`, simulador e QPU IBM; testes de saúde; extrator Toeplitz; mixer SHA3-512 fail-closed; derivação ML-KEM-768 e ML-DSA-65; recibo assinado e encadeado; painel e relatório. **Nada abaixo está feito.** A ordem reflete o que reduz mais risco por esforço, e as estimativas de duração são palpites a revisar.

## 1. Fechar o que ficou parcial (semanas)

- **E1:** comparar a coleta 3 com a coleta 2 e investigar a deriva (poucos qubits? troca de calibração?). Mais coletas em outro backend e em outros dias; com 3 coletas em 2 dias não há como falar de "as QPUs".
- **E5:** CHSH na QPU real (a etapa B), com o par de qubits escolhido por regra fixada antes da coleta. Continua sendo conferência, não certificação.
- **Estimadores:** implementar o conjunto completo do SP 800-90B (hoje há só os dois estimadores do tipo "valor mais comum") e tratar bits não independentes. O estimador atual supõe independência, e a garantia de extração dos recibos depende dele.
- **Poder dos experimentos:** E4 com mais sequências por célula (as células de `adv_forca` têm 10) e E3 com mais tamanhos de job para ajustar o custo marginal.

## 2. Chip QRNG local (alguns meses)

- Adaptador para um chip ou módulo QRNG real (por exemplo via USB ou SPI) implementando o contrato de `eal/sources/base.py`; os testes de saúde contínuos (RCT e APT) rodam sobre o fluxo do chip.
- Escolher o chip depois de ler a documentação de certificação do fornecedor, não antes. Medir viés, correlação e deriva por temperatura e por lote do chip, como foi feito com a QPU.
- Política da mistura: a fonte local de hardware passa a ser a primeira classe; a QPU em nuvem fica como fonte adicional, nunca única.

## 3. Porte para C ou Rust (alguns meses)

- Núcleo (testes de saúde, extrator, mixer, derivação) em C ou Rust, com **bibliotecas PQC auditadas e em tempo constante** no lugar de `kyber-py` e `dilithium-py`.
- Manter o Python como camada de análise. Reaproveitar os 3.200 testes e os vetores de teste conhecidos (KAT) como suíte de conformidade do porte.
- Gerenciar a chave do emissor fora do disco em texto claro (hoje ela fica sem criptografia em `keys/`).

## 4. Certificação (um a dois anos, depende de parceiros)

- Definir o alvo: SP 800-90B (fonte de entropia) e FIPS 140-3 (módulo criptográfico). Isso exige um laboratório acreditado, um módulo de fronteira definida e documentação formal; nada disso existe hoje.
- Antes de gastar nisso, validar com potenciais clientes se o recibo por chave é o que eles pedem, ou se querem só a camada de testes.
- Enquanto não houver certificação, manter a linguagem do `THREAT_MODEL.md`: sem alegação de conformidade e sem alegação de origem quântica.

## 5. Produto, se o problema se confirmar

- API (FastAPI) para pedir semente e recibo, e verificação pública de recibos. Cortada do prazo de 9 dias.
- Serviço de verificação de cadeia e publicação periódica da cabeça da cadeia fora do log (a verificação já aceita uma cabeça esperada).
- Integração com gerenciadores de chaves e com HSMs.

## Riscos que o roadmap precisa vigiar

- O provedor da QPU conhece os bits que gerou; por isso a QPU nunca é a única fonte de uma semente.
- Testar a saída não detecta um gerador pseudoaleatório disfarçado: a confiança na fonte tem que vir também do projeto físico e da cadeia de fornecimento.
- Concorrentes com validação formal já existem; o espaço da EAL é a camada neutra de evidência, não a fonte.
