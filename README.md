# Entropy Assurance Layer (EAL)

Research prototype that collects random bits from several sources (the operating system, a QPU simulator, and a real IBM QPU), tests each batch, mixes only the sources that showed no defect in their output, derives post-quantum keys (ML-KEM-768 and ML-DSA-65), and issues a **signed, hash-chained receipt** recording where the randomness came from and which tests it passed.

**This is not a product.** Do not use it to protect real data. There is no certification (NIST SP 800-90B, FIPS 140-3, Common Criteria) and no claim of "quantum origin." The PQC libraries are pure Python, not constant-time, and unaudited. Read the [report](relatorio/RELATORIO.md) and the [threat model](THREAT_MODEL.md) before drawing any conclusion.

## What's here

| What | Where |
|---|---|
| Library and CLI | `eal/` |
| Report with charts, analysis, and limitations | [relatorio/RELATORIO.md](relatorio/RELATORIO.md) |
| Dashboard (Streamlit, single page) | `dashboard/app.py` |
| One-pager and roadmap | [docs/ONE_PAGER.md](docs/ONE_PAGER.md), [docs/ROADMAP.md](docs/ROADMAP.md) |
| Demonstration receipt chain | `demo/` |
| Results of the 5 experiments (CSV) | `data/results/` |
| Project brief and decisions | [PROJECT.md](PROJECT.md), [THREAT_MODEL.md](THREAT_MODEL.md) |

Raw bits (`data/raw/`), real receipts, the issuer's keys, `.env`, and logs **are not** in the repository. The CSVs in `data/results/` are, and they are what feed the dashboard and the report.

## Requirements

- Python **3.12**. The project was developed and tested only on **Windows 11**, calling `py -3.12`. On another system, replace `py -3.12` with `python3.12`; this has not been tested.
- No virtual environment in the original development (creating one failed on the author's machine). You can use a `.venv` normally.
- An IBM Quantum account is needed **only** to collect new bits from the QPU. Running tests, the dashboard, and the report needs neither an account nor network access.

## Installation

```
py -3.12 -m pip install -r requirements.txt
```

## Running the tests

```
py -3.12 -m pytest
```

There are more than 3,200 tests and they take a few minutes. The ones that depend on data left out of Git (raw bits, the real chain) are skipped on a clean clone.

## Viewing the dashboard

```
py -3.12 -m streamlit run dashboard/app.py
```

Opens at http://localhost:8501. Shows sources, health per batch, min-entropy, bias per qubit, the latest receipt (with a verify button), and experiments E1 through E5. On a clean clone there is no real chain, and the dashboard uses the demonstration chain in `demo/`, with a warning on screen.

## Live demo (presentation)

Sends a real job to the IBM QPU (Hadamard on 156 qubits, 9,616 shots, about 5 s of QPU time), waits as long as the queue takes, runs the EAL's health tests on the bits (and, for comparison, on the same amount of bits from the `os` source), and opens a page in the browser with the bit mosaic, the chip map, and the verdict:

```
py -3.12 -m scripts.demo_ao_vivo                 # shows the plan, asks for SIM, sends, waits, and opens
py -3.12 -m scripts.demo_ao_vivo --job JOB_ID    # if the wait was interrupted, resumes without resending
py -3.12 -m scripts.demo_ao_vivo --arquivo data\raw\<batch>.npy   # rehearsal without the QPU, with an already-saved batch
```

Needs the token in `.env` (see below) and uses the same budget guardrails and the same log as the collection. The page lands in `ao_vivo/` (outside Git) and says "recorded (rehearsal)" when it comes from `--arquivo`. To check the page without the animation, open it with `#estatico` at the end of the address.

## Generating keys and a receipt (CLI)

```
py -3.12 -m eal init-issuer          # creates the issuer's ML-DSA-65 keypair (once); the private key stays in keys/ and does not go to Git
py -3.12 -m eal run                  # reads bits from the os source, tests, extracts, mixes, derives the keys, and writes the receipt
py -3.12 -m eal verify data\receipts\<receipt_id>.json
```

Exit codes: 0 ok; 1 expected failure (refusal, rejected receipt); 2 usage error. The seed and the private keys never go into the output, the log, or the receipt.

### Verifying the demonstration chain

The `demo/` folder carries 3 chained receipts and the demo issuer's public key (the private one was not published):

```
py -3.12 -m eal verify demo\receipts\72843d53-2fcc-593d-8365-2aca3d35a095.json --keys-dir demo\keys
```

Expected output: `recibo válido` ("valid receipt") and `cadeia: posição 3 de 3` ("chain: position 3 of 3"). The head of the chain (SHA3-256 of the last line of `chain.jsonl`) is `82bdfd93ff040d2c66d9a686ab61db44e6f55812534937af4cc7790df8d56926`; to check it against that, pass `--expected-head`.

## Reproducing the report's numbers

Every number in the report comes from a CSV in `data/results/`:

```
py -3.12 -m scripts.incerteza_dia8      # uncertainty ranges -> data/results/dia8_incerteza.csv
py -3.12 -m scripts.gerar_relatorio     # relatorio/RELATORIO.md and relatorio/figuras/
```

The generator refuses to write a sentence if the CSVs stop supporting it. Redoing the collection on the real QPU requires an IBM account and consumes the usage plan; the collections already done are recorded in `data/results/dia6_*_inventario.csv`, with each job's identifier.

Note: the report and its generation scripts (`eal/`, `scripts/`) work in Portuguese, since that is the language the original research session was run in. `relatorio/RELATORIO.md` in this repository is an English translation made for publication; re-running `scripts.gerar_relatorio` will overwrite it with a Portuguese version regenerated from the CSVs.

## Collecting bits from the real QPU (optional)

Put the token in a `.env` file at the project root (never versioned):

```
IBM_QUANTUM_TOKEN=<your token>
```

and use `py -3.12 scripts\coletar_ibm.py` with `status`, `calibrar`, `enviar`, or `recuperar` (`--help` shows the options; these subcommand names are in Portuguese: "calibrate," "send," "retrieve"). `enviar` shows the plan and only spends QPU time after you type `SIM` ("yes"), and the code refuses to go over the free plan's budget (600 s per 28-day window, with margin), configured in `eal/config.py`. If the token ever appears in a chat, a screenshot, or a public file, generate a new one on IBM.

## Structure

```
eal/            sources/ health/ extract/ mix/ pqc/ receipt/ pipeline.py cli.py ibm_cli.py
dashboard/      app.py (page) and data.py (data loading, tested)
scripts/        experiments E1 to E5, logging scripts, analyses, incerteza_dia8.py, gerar_relatorio.py
tests/          pytest
data/results/   result CSVs (versioned)
demo/           demonstration receipt chain and the demo's public key
relatorio/      report and figures
docs/           one-pager and roadmap
```

## Main limitations

- One QPU (`ibm_kingston`), 3 collections over 2 days, 6 batches: nothing here supports talking about "QPUs" in general.
- The real QPU's batches **did not pass** the health gate; none of its bits went into a seed. The result speaks to the batch size and the chosen criterion, not to the QPU's quality.
- The tests look only at the output: a disguised pseudorandom generator passes.
- The QPU provider knows the bits it generated.
- Full list in the report (section 5) and in section 17 of `PROJECT.md`.

## License

[MIT](LICENSE).
