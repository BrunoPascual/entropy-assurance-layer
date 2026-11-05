# Entropy Assurance Layer: one-pager

*Protótipo de pesquisa de 9 dias (Bruno Pascual, novembro de 2026). Não é um produto e não tem certificação.*

## Problema

Toda chave criptográfica nasce de números aleatórios. As falhas históricas de aleatoriedade foram de **fonte ou de semeadura**, não de algoritmo: o bug do OpenSSL no Debian (2008), chaves RSA repetidas em dispositivos de rede (2012), o gerador Dual_EC_DRBG sob suspeita de backdoor. Equipes de segurança raramente conseguem **mostrar** de onde veio a aleatoriedade de uma chave e que ela foi testada, e as auditorias (FIPS 140-3, NIST SP 800-90B) pedem essa evidência. A migração para criptografia pós-quântica não resolve isto: ML-KEM e ML-DSA também consomem aleatoriedade.

## Solução

Uma camada de software **neutra em relação à fonte**:

1. aceita bits de qualquer fonte (sistema operacional, simulador, QPU real da IBM, ou um chip no futuro) por um adaptador;
2. testa cada lote (RCT e APT do SP 800-90B, estimativa conservadora de min-entropia, três testes do SP 800-22, detector de replay);
3. extrai (Toeplitz) e mistura (SHA3-512) só as fontes sem defeito visível, e **recusa gerar semente** se não houver ao menos uma fonte local aprovada;
4. deriva ML-KEM-768 e ML-DSA-65 a partir da semente;
5. emite um **recibo assinado (ML-DSA-65) e encadeado por hash**, só com hashes, que registra as fontes, os testes e o resultado de cada uma.

Mais um **estudo aberto e reproduzível** de como QPUs públicas se comportam como fonte de bits: dados e CSVs versionados, e cada número do relatório rastreável a um arquivo.

## O que os 9 dias mostraram

- Uma QPU real (`ibm_kingston`, 3 coletas, 6 lotes de 1,5 milhão de bits) **não passou** na porta de saúde: o viés é pequeno (0,4964 a 0,5048 de uns), mas com esse tamanho de lote ele é medível, e o sinal mudou entre coletas. Isso diz respeito ao tamanho do lote e ao critério, não prova má qualidade da QPU.
- O sistema detecta viés, correlação, travamento e replay; um gerador pseudoaleatório disfarçado **passa**, porque os testes olham só a saída. O falso positivo na fonte `os` é de 2,6% a 3,6%.
- Com XOR um adversário que vê a outra fonte escolhe a semente final e os testes não percebem; com hash isso não acontece, mas quem testa candidatos força k bits com 2^k tentativas.
- Em tempo, a QPU gasta da ordem de 10 vezes mais segundos por megabit que a fonte `os`. Não é uma razão de dinheiro.
- O CHSH foi só conferido em simulação e **não diz nada sobre a QPU real**.

## Mercado e concorrentes

O mercado de geração quântica de números aleatórios já existe e é de hardware ou serviço próprio: **Quantinuum Quantum Origin** (semente gerada em computador quântico, com refino local da entropia; validado no NIST SP 800-90B em abril de 2025), **ID Quantique** (chips e dispositivos QRNG, controlada pela IonQ desde maio de 2025, presente nos celulares Samsung Galaxy Quantum), Quside, QuintessenceLabs, Crypta Labs, KETS, Qrypt e Quantum eMotion. A EAL **não compete como fonte de bits quânticos**: um serviço em nuvem de QPU, como o testado aqui, mostrou-se lento, caro em tempo e sujeito à confiança no provedor.

**Onde a EAL pode ter espaço (hipóteses a validar com clientes, sem números de mercado levantados):** equipes que precisam de **evidência por chave** da origem e do teste da aleatoriedade, que misturam várias fontes (inclusive de fornecedores de QRNG) e querem uma camada de verificação independente do fornecedor, e quem se prepara para a migração pós-quântica e para auditorias.

| Diferencial | Observação honesta |
|---|---|
| Neutra em relação à fonte | Qualquer QRNG pode entrar como fonte; não substitui o QRNG |
| Recibo de auditoria por chave | Integridade e ordem; **não** garante a entropia |
| Dados abertos sobre QPUs públicas | Uma QPU, 3 coletas: pequeno, mas reproduzível |
| Derivação PQC integrada | Python puro, sem tempo constante |

## Roadmap (resumo)

Chip QRNG local como fonte de primeira classe; estimadores completos do SP 800-90B e testes de saúde na linha de produção; porte do núcleo para C ou Rust com bibliotecas PQC auditadas; certificação só depois de definir o caminho (SP 800-90B, FIPS 140-3); mais QPUs e mais coletas. Detalhes e ordem em [ROADMAP.md](ROADMAP.md).

Relatório completo, com limitações e faixas de incerteza: [../relatorio/RELATORIO.md](../relatorio/RELATORIO.md).
