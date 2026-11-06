# Entropy Assurance Layer (EAL)

Protótipo de pesquisa que coleta bits aleatórios de várias fontes (sistema operacional, simulador de QPU e QPU real da IBM), testa cada lote, mistura só as fontes que não mostraram defeito na saída, deriva chaves pós-quânticas (ML-KEM-768 e ML-DSA-65) e emite um **recibo assinado e encadeado por hash** que registra de onde veio a aleatoriedade e quais testes ela passou.

**Isto não é um produto.** Não use para proteger dados reais. Não há certificação (NIST SP 800-90B, FIPS 140-3, Common Criteria) nem alegação de "origem quântica". As bibliotecas PQC estão em Python puro, sem tempo constante e sem auditoria. Leia o [relatório](relatorio/RELATORIO.md) e o [modelo de ameaça](THREAT_MODEL.md) antes de tirar qualquer conclusão.

## O que há aqui

| O quê | Onde |
|---|---|
| Biblioteca e CLI | `eal/` |
| Relatório com gráficos, análise e limitações | [relatorio/RELATORIO.md](relatorio/RELATORIO.md) |
| Painel (Streamlit, uma página) | `dashboard/app.py` |
| One-pager e roadmap | [docs/ONE_PAGER.md](docs/ONE_PAGER.md), [docs/ROADMAP.md](docs/ROADMAP.md) |
| Cadeia de recibos de demonstração | `demo/` |
| Resultados dos 5 experimentos (CSV) | `data/results/` |
| Brief do projeto e decisões | [PROJECT.md](PROJECT.md), [THREAT_MODEL.md](THREAT_MODEL.md) |

Os bits crus (`data/raw/`), os recibos reais, as chaves do emissor, o `.env` e os logs **não** estão no repositório. Os CSVs de `data/results/` estão, e é deles que saem o painel e o relatório.

## Requisitos

- Python **3.12**. O projeto foi desenvolvido e testado só no **Windows 11**, chamando `py -3.12`. Em outro sistema, troque `py -3.12` por `python3.12`; isso não foi testado.
- Não há ambiente virtual no desenvolvimento original (a criação falhou na máquina do autor). Você pode usar um `.venv` normalmente.
- Conta IBM Quantum **só** se quiser coletar bits novos da QPU. Para rodar testes, painel e relatório não precisa de conta nem de rede.

## Instalação

```
py -3.12 -m pip install -r requirements.txt
```

## Rodar os testes

```
py -3.12 -m pytest
```

São mais de 3.200 testes e levam alguns minutos. Os que dependem de dados que ficam fora do Git (bits crus, cadeia real) são pulados num clone limpo.

## Ver o painel

```
py -3.12 -m streamlit run dashboard/app.py
```

Abre em http://localhost:8501. Mostra fontes, saúde por lote, min-entropia, viés por qubit, o último recibo (com botão de verificação) e os experimentos E1 a E5. Num clone limpo não há cadeia real, e o painel usa a cadeia de demonstração de `demo/`, avisando na tela.

## Demo ao vivo (apresentação)

Envia um job real à QPU da IBM (Hadamard em 156 qubits, 9.616 disparos, cerca de 5 s de QPU), espera o tempo que a fila exigir, roda os testes de saúde da EAL sobre os bits (e, para comparar, sobre a mesma quantidade de bits da fonte `os`) e abre uma página no navegador com o mosaico de bits, o mapa do chip e o veredito:

```
py -3.12 -m scripts.demo_ao_vivo                 # mostra o plano, pede SIM, envia, espera e abre
py -3.12 -m scripts.demo_ao_vivo --job JOB_ID    # se a espera for interrompida, retoma sem reenviar
py -3.12 -m scripts.demo_ao_vivo --arquivo data\raw\<lote>.npy   # ensaio sem QPU, com um lote já salvo
```

Precisa do token no `.env` (ver abaixo) e usa as mesmas travas de orçamento e o mesmo log da coleta. A página fica em `ao_vivo/` (fora do Git) e diz "gravado (ensaio)" quando vem de `--arquivo`. Para conferir a página sem animação, abra-a com `#estatico` no fim do endereço.

## Gerar chaves e recibo (CLI)

```
py -3.12 -m eal init-issuer          # cria o par ML-DSA-65 do emissor (uma vez); a chave privada fica em keys/ e não vai para o Git
py -3.12 -m eal run                  # lê bits da fonte os, testa, extrai, mistura, deriva as chaves e grava o recibo
py -3.12 -m eal verify data\receipts\<receipt_id>.json
```

Códigos de saída: 0 ok; 1 falha esperada (recusa, recibo reprovado); 2 erro de uso. A semente e as chaves privadas nunca vão para a saída, para o log nem para o recibo.

### Verificar a cadeia de demonstração

A pasta `demo/` traz 3 recibos encadeados e a chave pública do emissor da demo (a privada não foi publicada):

```
py -3.12 -m eal verify demo\receipts\72843d53-2fcc-593d-8365-2aca3d35a095.json --keys-dir demo\keys
```

Saída esperada: `recibo válido` e `cadeia: posição 3 de 3`. A cabeça da cadeia (SHA3-256 da última linha de `chain.jsonl`) é `82bdfd93ff040d2c66d9a686ab61db44e6f55812534937af4cc7790df8d56926`; para conferir contra ela, passe `--expected-head`.

## Reproduzir os números do relatório

Todo número do relatório sai de um CSV de `data/results/`:

```
py -3.12 -m scripts.incerteza_dia8      # faixas de incerteza -> data/results/dia8_incerteza.csv
py -3.12 -m scripts.gerar_relatorio     # relatorio/RELATORIO.md e relatorio/figuras/
```

O gerador recusa gravar uma frase se os CSVs deixarem de sustentá-la. Refazer a coleta na QPU real exige conta IBM e consome o plano de uso; as coletas feitas estão registradas em `data/results/dia6_*_inventario.csv`, com o identificador de cada job.

## Coletar bits da QPU real (opcional)

Coloque o token no arquivo `.env` na raiz (nunca versionado):

```
IBM_QUANTUM_TOKEN=<seu token>
```

e use `py -3.12 scripts\coletar_ibm.py` com `status`, `calibrar`, `enviar` ou `recuperar` (`--help` mostra as opções). O `enviar` mostra o plano e só gasta QPU depois de você digitar `SIM`, e o código recusa passar do orçamento do plano gratuito (600 s por janela de 28 dias, com margem), configurado em `eal/config.py`. Se o token aparecer em chat, print ou arquivo público, gere outro na IBM.

## Estrutura

```
eal/            sources/ health/ extract/ mix/ pqc/ receipt/ pipeline.py cli.py ibm_cli.py
dashboard/      app.py (página) e data.py (carga de dados, testada)
scripts/        experimentos E1 a E5, registros, análises, incerteza_dia8.py, gerar_relatorio.py
tests/          pytest
data/results/   CSVs dos resultados (versionados)
demo/           cadeia de recibos de demonstração e chave pública da demo
relatorio/      relatório e figuras
docs/           one-pager e roadmap
```

## Limitações principais

- Uma QPU (`ibm_kingston`), 3 coletas em 2 dias, 6 lotes: nada aqui permite falar de "as QPUs".
- Os lotes da QPU real **não passaram** na porta de saúde; nenhum bit dela entrou numa semente. O resultado diz respeito ao tamanho do lote e ao critério escolhido, não à qualidade da QPU.
- Os testes olham só a saída: um gerador pseudoaleatório disfarçado passa.
- O provedor da QPU conhece os bits que gerou.
- Lista completa no relatório (seção 5) e na seção 17 do `PROJECT.md`.

## Licença

Nenhuma licença foi definida ainda. Sem licença, o código não é de uso livre por terceiros; defina uma antes de publicar.
