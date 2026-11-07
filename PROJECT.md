# Entropy Assurance Layer (EAL) — Project Brief

- **Document version:** 1.0
- **Date:** 27/10/2026 (created); updated on 07/11/2026 (Day 9 state)
- **Author:** Bruno Pascual
- **Status:** Day 9 of 9 (delivery). Days 1 to 7 are recorded below; the dashboard, report and critical review from Day 8, and the README, one-pager, roadmap and demonstration chain from Day 9, are at the end of this file
- **Sibling document:** `THREAT_MODEL.md` (threat model)

> This file is the project's source of truth. Paste it at the start of every session with the AI.
> If anything in the code contradicts this document, the document wins, or it is updated first.

*Numbers in this document use the Brazilian convention: a period as the thousands separator and a comma as the decimal separator (e.g. `1.359.324` = 1,359,324; `0,9623` = 0.9623).*

---

## 1. One-sentence summary

EAL is a software layer that collects random bits from several sources (operating system, QPU simulator, and IBM's real QPU), tests the quality of each batch, mixes only the approved sources, derives post-quantum keys (ML-KEM-768 and ML-DSA-65) from the resulting seed, and issues a **signed receipt** that records where the randomness came from and which tests it passed.

It is a **research prototype**, not a production product.

---

## 2. Problem

1. Every cryptographic key is born from random numbers. If they are predictable, the cryptography is broken even if the algorithm is correct.
2. Historical randomness failures came from the **source or seeding**, not the algorithm: the Debian OpenSSL bug (2008), repeated RSA keys on network devices (2012), and the Dual_EC_DRBG generator with a suspected backdoor.
3. Security teams can rarely **prove** where the randomness used in a key came from and that it was tested. Audits (FIPS 140-3, NIST SP 800-90B) ask for this evidence.
4. The migration to post-quantum cryptography **does not solve** the problem: ML-KEM and ML-DSA also consume randomness, and if it is predictable, the secret is too.
5. Quantum sources (QRNG) exist, but trusting them requires method: hardware bias, noise, drift, and, in the case of the cloud, trust in the provider.

---

## 3. Positioning and competition

**What EAL is:** a **neutral assurance layer** that accepts any bit source, plus an **open and reproducible study** of how good public QPUs are as an entropy source.

**What EAL is not:** a "quantum bit service". That market already exists:

- **Quantinuum Quantum Origin:** software QRNG, with a seed generated on a quantum computer and local entropy refinement; validated under NIST SP 800-90B (April 2025).
- **ID Quantique (controlled by IonQ since May 2025):** QRNG chips and devices, including the ones used in Samsung Galaxy Quantum phones.
- **Other vendors:** Quside, QuintessenceLabs, Crypta Labs, KETS, Qrypt, Quantum eMotion.

**EAL's differentiator:**

1. Source-neutral (any source enters through an adapter).
2. Audit receipt per generated key.
3. Open data on public QPUs (bias, correlation, drift).
4. Direct integration with PQC key generation.
5. Architecture ready to evolve toward a local QRNG chip (roadmap).

---

## 4. Scope

### 4.1 In scope for the 9 days

- Sources: operating system, QPU simulator with noise (Qiskit Aer), real IBM QPU, and 5 simulated faulty sources.
- Continuous NIST SP 800-90B health tests: Repetition Count Test (RCT) and Adaptive Proportion Test (APT).
- Conservative min-entropy estimate.
- 3 statistical tests from NIST SP 800-22: frequency (monobit), block frequency, and runs.
- Toeplitz extractor and hash-based mixing (SHA3-512).
- Deterministic derivation of ML-KEM-768 and ML-DSA-65 from the seed.
- JSON receipt signed with ML-DSA-65, hash-chained.
- Command line (CLI) and a one-page Streamlit dashboard.
- 5 experiments (E1 to E5) and a final report.

### 4.2 Out of scope (future roadmap)

- NIST certification, FIPS 140-3, Common Criteria, or AIS 31.
- Local QRNG chip, port to C or Rust, embedded firmware.
- Production security: the pure-Python PQC libraries serve the prototype only.
- Other QPU providers (AWS Braket only if time allows).
- Login, database, deployment, public API (FastAPI is optional and the first thing to cut).
- QKD, cryptographic inventory, dependency risk.

---

## 5. Architecture

```
                 ┌──────────────────────────┐
                 │        Bit sources        │
                 │  os │ qpu_sim │ qpu_ibm   │
                 │  faulty (tests only)      │
                 └────────────┬─────────────┘
                              │ RawBatch (bits + metadata)
                              ▼
                 ┌──────────────────────────┐
                 │       Health tests        │  RCT, APT, min-entropy,
                 │  (per source, per batch)  │  3 SP 800-22 tests
                 └──────┬─────────────┬─────┘
                approved│             │rejected
                        ▼             ▼
       ┌──────────────────────┐   excluded and recorded
       │  Toeplitz Extractor  │   (enters the receipt as rejected)
       │  (per source)        │
       └──────────┬───────────┘
                  ▼
       ┌──────────────────────┐
       │  SHA3-512 Mixer      │  policy: ≥ 1 approved local source
       │  (fail-closed)       │  otherwise: no seed is generated
       └──────────┬───────────┘
                  ▼ 64-byte seed (never leaves the process)
       ┌──────────────────────┐
       │  PQC Derivation      │  ML-KEM-768, ML-DSA-65
       └──────────┬───────────┘
                  ▼
       ┌──────────────────────┐
       │  Signed receipt      │  only hashes; signed with ML-DSA-65;
       │  + hash chain        │  chained to the previous receipt
       └──────────────────────┘
```

---

## 6. Components and contracts

### 6.1 Source interface (`eal/sources/base.py`)

Every source implements the same contract. The rest of the system doesn't know whether the bits came from the operating system, a simulator, or a chip.

```python
from abc import ABC, abstractmethod

class Source(ABC):
    source_id: str        # e.g.: "os", "qpu_sim", "ibm_kingston", "faulty_biased"
    source_type: str      # "os" | "qpu_sim" | "qpu_ibm" | "faulty"
    is_local: bool        # True if the bits never left the machine
    is_simulated: bool    # True for the simulator and faulty sources

    @abstractmethod
    def read(self, n_bits: int) -> "RawBatch":
        """Returns exactly n_bits raw bits, with metadata."""
```

### 6.2 Raw batch (`RawBatch`)

| Field | Type | Description |
| --- | --- | --- |
| `batch_id` | str | Batch UUID |
| `source_id` | str | Source identifier |
| `source_type` | str | Source type |
| `source_version` | str | Adapter version and, if any, SDK version |
| `is_local` / `is_simulated` | bool | Copied from the source |
| `bits` | `numpy.ndarray[uint8]` | 0/1 values, one per position |
| `n_bits` | int | Number of bits |
| `created_at` | str | ISO 8601 in UTC |
| `params` | dict | E.g.: backend, qubits, shots, job_id, noise model. Only the keys from the closed list in `eal/config.py` (`RECEIPT_BATCH_PARAM_*`) reach the receipt (G6) |
| `batch_hash` | str | SHA3-256 of `n_bits` (8 bytes, big-endian) followed by the bits packed with `numpy.packbits` (replay and tampering detection) |

### 6.3 Sources

| `source_id` | Type | Local? | Simulated? | Use |
| --- | --- | --- | --- | --- |
| `os` | os | yes | no | Reference source (`os.urandom` / `secrets`) |
| `qpu_sim` | qpu_sim | yes | **yes** | Development and experiments; Hadamard on N qubits in Qiskit Aer with a noise model |
| `ibm_<backend>` | qpu_ibm | **no** | no | Real QPU; only via the collection script with a budget limit |
| `faulty_biased` | faulty | yes | yes | Probability of 1 ≠ 0,5 (parameter `p`) |
| `faulty_stuck` | faulty | yes | yes | Stuck bit runs (parameter `run_length`) |
| `faulty_replay` | faulty | yes | yes | Repeats a previous batch |
| `faulty_prng` | faulty | yes | yes | Mersenne Twister with a fixed seed, disguised as a QPU |
| `faulty_correlated` | faulty | yes | yes | Bit depends on the previous one with probability `rho` |

**Attention:** the Qiskit Aer simulator generates results with a **classical** pseudorandom generator. The `qpu_sim` source **never** counts as real entropy for generating keys. It exists for development and for the experiments.

### 6.4 Continuous health tests (`eal/health/continuous.py`)

Follow section 4.4 of NIST SP 800-90B, applied to each batch.

**Fixed parameters:**

- False-alarm rate (α) per sample in the RCT and per window in the APT. Separate values: RCT `α = 2^-40`, APT `α = 2^-20`.
- `H` = min-entropy per bit, declared or estimated for the source (≤ 1).

**Repetition Count Test (RCT):** detects stuck bits.

- Threshold: `C = 1 + ceil(-log2(α) / H)`.
- Example: with `H = 1`, `C = 41`; with `H = 0,9`, `C = 46` (α = 2^-40).
- Fails if any value repeats `C` or more times in a row.

**Adaptive Proportion Test (APT):** detects persistent bias.

- Window for binary data: `W = 1024`.
- Threshold: `C = 1 + CRITBINOM(W, 2^-H, 1 - α)`, computed with `scipy.stats.binom.ppf(1 - α, W, 2**-H)` + 1.
- For each window: takes the first bit and counts how many times it appears in the window; fails if the count ≥ `C`.

**Replay detection (complementary, not part of SP 800-90B):** stores the `batch_hash` of each batch and of 4096-bit blocks; fails if any repeats.

**Justification for the α values (measured, not assumed).** In a batch of 1.000.000 bits there are about 500 thousand sequences tested by the RCT. With `α = 2^-20` and `H = 1` (`C = 21`), the false-alarm rate per batch is close to 38% even for a fair source, which makes the gate unworkable. With `α = 2^-40` (`C = 41`), it is close to 5 × 10^-7 per batch, and the RCT still catches the 64-bit stuck run. In the APT, `α = 2^-20` gives about 8 × 10^-4 false-alarm rate per batch (976 windows) and catches a bias of p = 0,55. Both values fall within the 2^-40 to 2^-20 range of SP 800-90B. Values in `eal/config.py`.

**Batch limitation.** The APT only tests complete 1024-bit windows. In 1.000.000 bits, 576 bits are left out and are recorded in `discarded_bits`.

### 6.5 Min-entropy estimate (`eal/health/min_entropy.py`)

Uses the **minimum** of two estimators, to be conservative:

1. **Most Common Value (MCV), per bit** (SP 800-90B, section 6.3.1):
   - `p̂ = max_count / L`
   - `p_u = min(1, p̂ + 2,576 · sqrt(p̂ · (1 - p̂) / (L - 1)))`
   - `H_bit = -log2(p_u)`
2. **MCV on 8-bit symbols**, divided by 8. Captures correlation between neighboring bits that the per-bit estimator doesn't see.

`H_estimated = min(H_bit, H_byte / 8)`.

This is a simplified estimate. The project **makes no claim** of conformance with SP 800-90B. If there is time, compare with NIST's official entropy assessment tool (confirm availability on NIST's GitHub before using it).

**Use of min-entropy in the tests (Day 3 decision).**

- The RCT and APT tests use the source's **declared H**, not the estimated one. Using the estimated one loosens the limits precisely on the bad sources (measured: with the estimated H, the 64-bit stuck run passed the RCT).
- The **health test by estimated H** rejects the source if `H_estimated < 0,9`. The 0,9 threshold is a **project choice**, not a value derived from data: it separates the `os` source (0,954 to 0,963 across 25 batches of 1 million bits) from the measured faulty sources (`faulty_correlated` 0,752, `faulty_biased` 0,844, `faulty_stuck` 0,609). It was fixed before any real QPU data existed and will not be adjusted afterward to approve a source.
- The **extractor** uses `min(declared H, estimated H)`.
- The threshold rejects the real QPU if its bits have an estimated H below 0,9. This is the expected behavior (fail-closed), and the report must record the result, even if it is a rejection.

### 6.6 Statistical tests (`eal/health/stats_tests.py`)

From NIST SP 800-22, applied to batches of at least 1.000.000 bits when there is enough data:

| Test | What it detects | Approved if |
| --- | --- | --- |
| Frequency (monobit) | Excess of 0s or 1s | p-value ≥ 0,01 |
| Block frequency (M = 128) | Local bias | p-value ≥ 0,01 |
| Runs | Abnormal alternation | p-value ≥ 0,01 |

These tests **do not prove** randomness: a good pseudorandom generator passes all of them.

### 6.7 Batch report (`HealthReport`)

| Field | Description |
| --- | --- |
| `batch_id`, `source_id` | References |
| `rct_pass`, `rct_cutoff`, `rct_max_run` | RCT result |
| `apt_pass`, `apt_cutoff`, `apt_max_count` | APT result |
| `replay_pass` | No batch or block repetition |
| `h_bit`, `h_byte`, `h_estimated` | Min-entropy estimates |
| `stats` | p-values of the 3 tests |
| `approved` | `True` only if all tests passed |
| `reasons` | List of rejection reasons |

### 6.8 Toeplitz Extractor (`eal/extract/toeplitz.py`)

- Input per block: `n = 2048` raw bits.
- Block min-entropy: `k = n · H_estimated`.
- Extractor error: `ε = 2^-64`.
- Output per block (leftover hash lemma): `m = floor(k) - 2 · log2(1/ε) = floor(k) - 128`.
  - Example: `H = 0,9` → `k = 1843` → `m = 1715` bits.
- If `m ≤ 0`, the block is discarded.
- `m × n` Toeplitz matrix defined by a seed of `n + m - 1` bits **uniform and independent of the source**, drawn from the `os` source at the start of each run. The SHA3-256 of this seed goes into the receipt.
- Operation: `output = (T · x) mod 2`. With `n = 2048`, the matrix fits in memory (`scipy.linalg.toeplitz` + NumPy).
- Alternative for comparison (optional, first cut): conditioning with SHA3-512.

<!-- dia4-rendimento:start -->
### 6.8.1 Extractor yield (Day 4, step 3)

Generated by `scripts/gerar_secao_rendimento.py` from the files listed below, with the SHA3-256 checked against the meta. No number was typed by hand. Tables A, B, and C come from the loss model (`eal/extract/budget.py`) and hold for any H; table A is based on the readings from the comparison CSV, and D measures the estimator.

**Accounting.** Per block of n = 2048 bits, with k = floor(n·H) and margin 2·log2(1/ε) = 128: each input bit goes to the entropy deficit (n − n·H), rounding (n·H − k), the margin, the output m = k − margin, or the remainder (bits that don't complete a block). The sum is exactly the input. If m = 0, the whole batch is discarded for insufficient entropy.

**Data origin.**
- Extractor comparison: `data/results/dia4_extract_2026-10-30_120623.csv`, SHA3-256 `bb6fde627dcd1f38e2a802931396a074436d77d670191893fddb91ce005ca6b8`.
- Yield analysis: `data/results/dia4_yield_2026-10-30_131212.csv` (`4dddce9eb49d03d847e784e73329cc3181650af9aee409d7df3a86f198bc72d6`), `data/results/dia4_yield_curve_h_2026-10-30_131212.csv` (`038b0783c49c025b17547c53d2467af5290cc4fcb0e6d0ad08226d5c962af7a9`), `data/results/dia4_yield_curve_n_2026-10-30_131212.csv` (`e8e51d143247e5fe8c2c52058e9d2ba6b6cb2ef1ab5b3604188834aba90986ea`); measured at 2026-10-30T13:12:12.370978+00:00.
- Estimator × size: `data/results/dia4_estimator_2026-10-30_131219.csv` (`27ca56e46a0d61776899cf843c7aa9cdf5b849cec59970e4f3f22c099bc3ac87`), `data/results/dia4_estimator_summary_2026-10-30_131219.csv` (`bf2b01b7a6a15b2491a40d074f11acd30ccd96a41af553644e1315976d9b283b`); measured at 2026-10-30T13:12:19.117430+00:00; 50 readings from the `os` source.

**Table A: where each input bit went (readings from the comparison CSV, 1.000.000-bit batch).** The `qpu_sim_*` sources are simulated (classical generator) and do not represent real entropy.

| Source | Reading | H used | m | Output | Deficit | Rounding | Margin | Remainder |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `os` | 1 | 0,961 | 1840 | 89,79% | 3,89% | 0,01% | 6,25% | 0,06% |
| `os` | 2 | 0,961 | 1840 | 89,79% | 3,86% | 0,04% | 6,25% | 0,06% |
| `qpu_sim_ideal` | 1 | 0,958 | 1833 | 89,45% | 4,24% | 0,01% | 6,25% | 0,06% |
| `qpu_sim_ideal` | 2 | 0,957 | 1831 | 89,35% | 4,30% | 0,05% | 6,25% | 0,06% |
| `qpu_sim_noise` | 1 | 0,955 | 1828 | 89,21% | 4,45% | 0,04% | 6,25% | 0,06% |
| `qpu_sim_noise` | 2 | 0,953 | 1824 | 89,01% | 4,66% | 0,02% | 6,25% | 0,06% |

**Table B: yield per block as a function of H (n = 2048).** First H on the grid (step 0,001) with positive output: 0,063.

| H | k = floor(n·H) | m | m/n | Deficit/block | Rounding/block | Margin/block |
| --- | --- | --- | --- | --- | --- | --- |
| 0,500 | 1024 | 896 | 0,4375 | 1024,0 | 0,000 | 128 |
| 0,900 | 1843 | 1715 | 0,8374 | 204,8 | 0,200 | 128 |
| 0,954 | 1953 | 1825 | 0,8911 | 94,2 | 0,792 | 128 |
| 1,000 | 2048 | 1920 | 0,9375 | 0,0 | 0,000 | 128 |

**Table C: yield as a function of n, with H = 0,954 and a 1.000.000-bit batch** (H is assumed the same for every n; the CSV also brings H = 0,9 and 1,0).

| n | m | Blocks in 1M bits | m/n | Margin/block | log2(ε of the batch) |
| --- | --- | --- | --- | --- | --- |
| 512 | 360 | 1953 | 0,7031 | 25,00% | -53,07 |
| 1024 | 848 | 976 | 0,8281 | 12,50% | -54,07 |
| 2048 | 1825 | 488 | 0,8911 | 6,25% | -55,07 |
| 4096 | 3779 | 244 | 0,9226 | 3,13% | -56,07 |
| 8192 | 7687 | 122 | 0,9384 | 1,56% | -57,07 |

**Table D: estimated H of the `os` source as a function of batch size.** Measures the estimator, not the source. Batches smaller than 1.000.000 bits would not pass the gate (inconclusive statistics).

| Bits | Readings | Estimated H | sd | Min to max | H_bit | H_byte | Bit ref. (p̂=0,5) | Limited by (byte) | Passes H ≥ 0,9 | Average output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 65.536 | 10 | 0,8652 | 0,0102 | 0,8516 to 0,8835 | 0,9811 | 0,8652 | 0,9856 | 100% | 0% | 52.589 |
| 262.144 | 10 | 0,9249 | 0,0037 | 0,9193 to 0,9306 | 0,9905 | 0,9249 | 0,9928 | 100% | 100% | 225.997 |
| 1.000.000 | 10 | 0,9585 | 0,0027 | 0,9534 to 0,9617 | 0,9948 | 0,9585 | 0,9963 | 100% | 100% | 895.187 |
| 1.048.576 | 10 | 0,9586 | 0,0027 | 0,9520 to 0,9619 | 0,9950 | 0,9586 | 0,9964 | 100% | 100% | 939.366 |
| 4.194.304 | 10 | 0,9791 | 0,0016 | 0,9767 to 0,9815 | 0,9976 | 0,9791 | 0,9982 | 100% | 100% | 3.843.277 |

**Reading of the results** (sentences generated from the CSVs):
- The safety margin is fixed: 128 bits per 2048-bit block (6,25% of the input), whatever H is.
- Across the 6 readings of the comparison CSV, the H used ranged from 0,953 to 0,961 and the output ranged from 89,01% to 89,79% of the input.
- The average estimated H goes from 0,865 with 65.536 bits to 0,979 with 4.194.304 bits.
- The average grows with batch size across all measured sizes.
- The health test by H (threshold 0,9) rejected some or all readings with: 65.536 bits (0% of the readings passed).
- At every size, the byte branch limited H in 100% of the readings.
- With 4.194.304 bits, the analytical reference for the bit branch (p̂ = 0,5) is 0,9982 and the measured average H_bit is 0,9976; the estimated H (0,9791) falls below that because of the byte branch.
- The spread of H across the 6 readings of the comparison CSV (0,953 to 0,961, a difference of 0,0080) should be read against the spread between readings of `os` with 1.000.000 bits (0,0027, 10 readings). The spread is at most 4 standard deviations: with few readings per source, this comparison does not distinguish one source from another.

**Interpretation (not measured).** The estimator uses a 99% upper bound and, in the byte branch, the maximum over 256 symbol counts; by construction it comes out below 1 even for a uniform source. This measurement does not separate real entropy from the estimator's conservatism. Under premise P3, `os` has H close to 1, but that is a premise, not a result. The extractor's yield inherits this conservatism.
<!-- dia4-rendimento:end -->

### 6.9 Mixer (`eal/mix/mixer.py`)

**Policy (fail-closed):**

1. Only sources with `approved = True` enter.
2. In `keygen` mode, **at least 1 approved, non-simulated local source** is mandatory (in practice, `os`), whose extracted outputs add up to at least 512 bits (the seed size). Reason: the QPU provider knows the bits it generated.
3. Simulated sources only enter in `experiment` mode, never in `keygen`: in `keygen`, a simulated source in the list is a configuration error, even if rejected. In `experiment`, 1 approved local source (simulated or not) is enough, with the same 512-bit floor, and the seed comes out marked `usable_for_key = False`.
4. If the policy is not satisfied, **no seed is generated** and the error is recorded.

**Combination:**

```
seed = SHA3-512(
    "EAL-v1-mix" ||
    for each approved source, in alphabetical order of source_id:
        len(source_id) || source_id || len(output) || extracted_output
)
```

- Output: 64 bytes.
- Why hash and not XOR: in XOR, an adversarial source that sees the others can cancel out the entropy. Hash combination resists this better (tested in E4).

<!-- dia4-mixer:start -->
### 6.9.1 Mixer: what the code fixes (Day 4)

Text written from `eal/mix/mixer.py`; it supplements 6.9, which didn't say how to encode the sizes.

**Modes.** `keygen`: a simulated source in the list is an error (even if rejected); requires at least 1 local, non-simulated, approved source, and the local part must add up to 512 extracted bits; the seed comes out with `usable_for_key = True`. `experiment`: accepts simulated sources; requires at least 1 approved local source (simulated or not) with the same 512-bit floor; the seed always comes out with `usable_for_key = False`.

**Encoding.** `SHA3-512( MIX_DOMAIN || for each included source, in Unicode code-point order of source_id: len(id in UTF-8) [8 bytes, big-endian] || id || n_bits [8 bytes, big-endian] || packbits(output) )`. The counter is of BITS, not bytes: `packbits` pads the last byte with zeros, and without the counter `[1]` and `[1,0,0,0,0,0,0,0]` would give the same seed.

**Pairing.** `make_mix_input` ties the health report and the extraction to the batch bits via the `input_hash` (`hash_bits` of the batch bits), the `batch_id`, the `source_id`, and the size. Repeated `source_id`, `batch_id`, and `input_hash` across contributions are rejected.

**Flags.** `is_local` only counts if it is boolean true; `is_simulated`, only if it is boolean false; `approved`, only if it is boolean true (`bool` or `numpy.bool_`). Any other value counts as the worst case.

**Record.** A rejected source, or one with no output, is excluded and recorded with `source_id`, `batch_id`, and the reasons, in `source_id` order. `MixResult.to_dict()` brings the mode, `usable_for_key`, policy text, `seed_hash`, and, per included source, `source_id`, `batch_id`, `input_hash`, flags, and mixed bits; not a single seed byte.
<!-- dia4-mixer:end -->

### 6.10 Key derivation (`eal/pqc/keygen.py`)

Deterministic from the seed, with domain separation:

| Algorithm | Internal input (default) | Derivation |
| --- | --- | --- |
| ML-KEM-768 (FIPS 203) | `d` and `z`, 32 bytes each | `d‖z = SHAKE256("EAL-v1|ML-KEM-768|" ‖ seed, 64 bytes)` |
| ML-DSA-65 (FIPS 204) | `ξ`, 32 bytes | `ξ = SHAKE256("EAL-v1|ML-DSA-65|" ‖ seed, 32 bytes)` |
- Library used: `kyber-py` 1.2.0 and `dilithium-py` 1.5.1 (pure Python). Confirmed in Day 5, step 1: both expose `key_derive` from a seed, and the project does not use `keygen()`. Both `key_derive` functions reproduce the NIST ACVP keyGen test vectors (25 of 25 per algorithm); see `tests/data/kat/SOURCE.json`.
- Alternative: `liboqs-python` (harder to install on Windows).
- Mandatory test: encapsulate and decapsulate (ML-KEM), sign and verify (ML-DSA), and the same seed always producing the same keys.
- Derived private keys **are not written to disk**, except with the explicit `--export-demo` option, for demonstration only. The option does not yet exist in the CLI (step 4); it is left for the Day 9 demo.

### 6.11 Receipt (`eal/receipt/`)

**Issuer key:** a separate ML-DSA-65 key pair, generated once from the `os` source. The private key lives in `keys/issuer_ml_dsa_65.sk` (in `.gitignore`); the public key in `keys/issuer_ml_dsa_65.pk`.

**Receipt example** (illustrative and abbreviated: "…" marks what was omitted; the exact shape of the body comes from `build_receipt_body` and is validated by `validate_body`). A simulated source never appears in a receipt, not even as excluded: `validate_body` rejects it.

```json
{
  "eal_version": "0.1.0",
  "receipt_id": "uuid5 of the seed_hash, canonical, lowercase",
  "created_at": "2026-10-28T14:03:12+00:00",
  "mode": "keygen",
  "prev_receipt_hash": "sha3-256 of the previous receipt (with signature), or 64 zeros on the first one",
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
      "health": {"…": "HealthReport.to_dict() (section 6.7)"},
      "extraction": {"seed_hash": "sha3-256 of this source's Toeplitz seed", "…": "ExtractionResult.to_dict()"}
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
      "reasons": ["reason for rejection"],
      "health": {"…": "…"},
      "extraction": null
    }
  ],
  "extractor": {"type": "toeplitz", "n": 2048, "epsilon_log2": -64},
  "mixer": {"…": "MixResult.to_dict(): mode, usable_for_key, policy, seed_hash, included and excluded sources; not a single seed byte"},
  "seed_hash": "sha3-256 of the seed",
  "keys": {"ml_kem_768_pk_hash": "…", "ml_dsa_65_pk_hash": "…"},
  "limitations": ["prototype", "no_sp800_90b_claim", "no_quantum_origin_claim", "chsh_is_sanity_check_only", "pqc_pure_python_not_constant_time", "issuer_key_unencrypted_on_disk"],
  "signature": {"alg": "ML-DSA-65", "issuer_pk_hash": "…", "value": "base64…"}
}
```

**Rules:**

1. The receipt contains **only hashes**, never the seed or private keys.
2. The signature covers the canonical JSON of all fields except `signature` (sorted keys, no spaces, UTF-8).
3. `prev_receipt_hash` chains the receipts (hash of the COMPLETE previous receipt, including the signature); the log lives in `data/receipts/chain.jsonl` and is described right below.
4. Verification (`eal verify`): recomputes the canonical JSON, checks the signature with the issuer's public key, and checks the chaining.
5. Batch params (G6, Day 6): only the keys from the closed list in `eal/config.py` enter the `batch_params` block of each source; token, seed, and other fields are left out. A `qpu_ibm` source with a batch requires `job_id` (otherwise the receipt is rejected). Receipts prior to G6 don't have the block and remain valid.

**Receipt builder (Day 5, step 2B, `eal/receipt/builder.py`).** Assembles the receipt body from the `PipelineResult`, the `DerivedKeys`, and the `Source` objects. Each source carries `source_type`, `source_version`, `status`, `batch_id`, `batch_hash` (the batch's `input_hash`), flags, `approved`, reasons, the `HealthReport`, and the extraction metadata, including the `seed_hash` of that source's Toeplitz seed. The top-level `extractor` block carries only type, `n`, and `epsilon_log2`. The `receipt_id` is the UUID5 of the `seed_hash`. The keys are re-derived from the seed and checked. Sources that failed enter with `approved: false` and the reason, without the exception message.

**Issuer key.** `xi = SHAKE256("EAL-v1|issuer|ML-DSA-65|" ‖ seed, 32 bytes)`, from a `keygen` run validated by the mixer.

**Chained log (Day 5, step 3, `eal/receipt/chain.py`).** API: `append_receipt(receipt, issuer_pk, directory) -> Path`, `verify_chain(directory, issuer_pk, *, expected_head=None) -> ChainResult(ok, reasons, length, head)`, `chain_head(directory, issuer_pk)`, and `ChainError`. The log's name is `RECEIPT_CHAIN_NAME = "chain.jsonl"` in `eal/config.py`.

*Format.* `<folder>/chain.jsonl` has one line per receipt; each line is the canonical JSON of the full receipt followed by `\n`, written in binary mode (no `\r\n`, which matters on Windows with `core.autocrlf`). Each receipt also goes to `<folder>/<receipt_id>.json`, with the same bytes as the line, so `eal verify` can take a single file. The log is the official record; the individual file is a copy checked against it.

*Writing.* `append_receipt` refuses with `ChainError`, writing nothing, if: the issuer's public key is invalid; the existing chain is invalid (fail-closed: a corrupted log also refuses new writes); the receipt is invalid; `prev_receipt_hash` is not the head of the chain (`GENESIS_PREV_HASH` with an empty log); the `receipt_id` is not the `uuid5` of the `seed_hash`; the `receipt_id` is already in the log; or `<receipt_id>.json` already exists. The folder is only created after the receipt passes every check. The order is: first the line (`ab` mode, `flush`, and `fsync`), then `<receipt_id>.json` (`xb` mode, which never overwrites, with `fsync`). If the second write fails, the line stays in the log, `append_receipt` raises `ChainError`, and `verify_chain` flags "missing individual file" (the line wins over the file).

*Verification.* `verify_chain` does not raise an exception because of file content. It checks, per line: empty line; invalid JSON (including a repeated key, NaN, a value that is not an object, and invalid UTF-8); canonical form; `verify_receipt` with the SAME issuer public key for the whole chain (one key per chain); unique `receipt_id` equal to the `uuid5` of the `seed_hash`; and the link (`prev_receipt_hash` equal to the hash of the previous line). It then checks the individual file for each line (missing or different), `.json` files with no line in the log, a last line without `\n`, and, if `expected_head` is given, the head of the chain. After an unreadable line, the link of the following line is not verifiable and does not generate an extra flag. Other files in the folder (like `.gitkeep`) are ignored. The messages carry only line numbers and counts, never the receipt's content.

*Tests.* `tests/test_receipt_chain.py` (79 tests, in a temporary folder), `tests/test_receipt_chain_pipeline.py` (4 tests, with two real pipeline runs and a deterministic test source), and `scripts/mutacoes_chain.py` (55 manual mutations of `chain.py`, 55 killed). This shows that the tests catch these errors, not that the module is correct.

### 6.12 Command line (`eal/cli.py`)

Usage: `py -3.12 -m eal <comando>`. There is no `eal` executable (the project has no `pyproject.toml`). It is a research prototype; the help generated by `argparse` has parts in English.

| Command | Does | State |
| --- | --- | --- |
| `init-issuer [--bits N] [--keys-dir D] [--logs-dir D]` | A `keygen` run using only the `os` source; derives the issuer's ML-DSA-65 pair (`issuer_seed_from_mix`) and writes `keys/issuer_ml_dsa_65.sk` and `.pk`. Refuses if either one already exists | Step 4 |
| `run [--sources os] [--bits N] [--keys-dir D] [--receipts-dir D] [--public-keys-dir D] [--logs-dir D]` | `keygen` pipeline with the `os` source, derived ML-KEM-768 and ML-DSA-65 keys, and a signed receipt written to the chained log | Step 4 |
| `verify <arquivo> [--keys-dir D] [--chain-dir D] [--sem-cadeia] [--expected-head HASH]` | Verifies the receipt, the chain, and the receipt's position in it | Step 4 |
| `collect-ibm --qubits 156 --shots 4096 --budget-seconds 30` | Planned command; it does not exist under this name in `python -m eal`. Collection on the real QPU is done by a separate entry point, `scripts/coletar_ibm.py` (logic in `eal/ibm_cli.py`), with the commands `status`, `calibrar`, `enviar`, and `recuperar`, under the budget guard | Exists as `scripts/coletar_ibm.py` (Day 6) |
| `health data/raw/<arquivo>.npy` | Runs only the health tests on a file | Does not exist as a command (the health tests run inside `run` and in the analysis scripts) |
| `experiment e2` | Runs an experiment | Does not exist as a command; the experiments are scripts: `scripts/e2_ataques.py`, `scripts/e3_vazao_custo.py`, `scripts/e4_mistura.py`, and `scripts/e5_chsh.py` (Day 7) |

**Exit codes.** 0: ok. 1: expected failure (fail-closed, refusal, rejected receipt or chain) or unexpected error, which is caught and shows only the exception's class name. 2: usage error (invalid option or command).

**`init-issuer`.** The issuer's pair comes from its own `keygen` run, never from the seed of the user's keys. Without a seed (fail-closed), nothing is created.

**`run`.** The order is: (1) loads the issuer key (without it: "rode `init-issuer`"); (2) checks the existing chain, and a corrupted log refuses BEFORE the pipeline; (3) runs the `keygen` pipeline a single time (without a seed: fail-closed, no automatic retry; `os` can be rejected by chance, as the Day 4 gate shows, and running again is a legitimate choice); (4) derives the keys, builds and signs the receipt, and writes it to the log; (5) writes ONLY the derived public keys to `data/public_keys/<receipt_id>/` (`ml_kem_768.ek.hex` and `ml_dsa_65.pk.hex`, in hex with a trailing `\n`, binary mode, without overwriting). If step 5 fails, the receipt is already in the log, and the message says so (exit code 1). The output brings `receipt_id`, the receipt's path, the seed hash, the public-key hashes, each source's status, and the `chain head`; keeping it outside the log allows using `--expected-head` later. `--sources` only accepts `os`: a simulated or faulty source is a usage error (T13), and `run` does not take the IBM source (IBM collection is done separately, by `scripts/coletar_ibm.py`).

**`verify`.** Checks, in this order: the issuer's public key (`--keys-dir`); the file; the receipt's format and signature; and, unless `--sem-cadeia` is given, the chain in the file's folder (or `--chain-dir`), with `--expected-head` if given. The receipt must be in the log, which is checked by canonical content, not by the file name. Without `chain.jsonl` in the folder, the error tells you to use `--chain-dir` or `--sem-cadeia`. With `--sem-cadeia` the output brings "AVISO: cadeia não conferida". On success it prints "recibo válido: <id>", "cadeia: posição X de N", and, with `--expected-head`, "cabeça conferida".

**Default folders** (relative to the current directory, each with its own option): `keys/`, `data/receipts/`, `data/public_keys/`, and `data/logs/`.

**Failure log (T14).** `init-issuer` and `run` append a JSON line to `data/logs/eal_runs.jsonl` on every failure, with `ts`, `command`, `stage` (`issuer_key`, `chain`, `pipeline`, `public_keys`, or `unexpected`), `ok: false`, `reason`, and `pipeline` (`PipelineResult.to_dict()` or `null`). `verify` does not write to the log.

**What the output never carries.** The seed, private keys (derived or the issuer's), and exception text — only the class name. There are tests for this (T10).

**Tests.** `tests/test_cli.py` (63 tests, in temporary folders; the test sources enter through an internal parameter of `main`, never through a CLI option; an automatic barrier keeps the tests from writing to the real `data/logs`) and `scripts/mutacoes_chain_cli.py` (58 manual mutations, 58 killed). This shows that the tests catch these errors, not that the CLI is correct.

### 6.13 Dashboard (`dashboard/app.py`)

A single Streamlit page: sources and status, health per batch, min-entropy per source, bias per qubit, latest receipt (with a verify button), and experiment charts. Run with `py -3.12 -m streamlit run dashboard/app.py`.

<!-- dia4-pipeline:start -->
### 6.14 Pipeline (`eal/pipeline.py`, Day 4)

`run_pipeline(sources, seed_source, mode, n_bits, h_declared, detector, health_fn)` returns a `PipelineResult`. `health_fn` and `detector` are optional: without them, the pipeline imports `build_health_report` and `ReplayDetector` (the policy tests inject fake versions).

**Flow per source.** (1) reads a batch; (2) runs the health test, with the same replay detector for every source; (3) if approved, extracts with Toeplitz using a seed from a SEPARATE reading of `seed_source` (a fresh reading per approved source); if rejected, creates an empty extraction linked to the batch by the hash, without spending a seed; (4) assembles the `MixInput`. At the end it calls `mix`.

**Principle.** A source's failure never brings down the pipeline; only the mixer's policy brings down the seed. Without a satisfied policy, `mix = None`, the reason goes in `error`, and no seed is generated (fail-closed).

**States of each source** (`SourceOutcome.status`):

| State | Meaning |
| --- | --- |
| `mixed` | entered the mix |
| `excluded` | rejected or with no output; recorded with the reason |
| `not_mixed` | approved, but the policy failed and no seed came out |
| `read_failed` | the read raised an exception |
| `health_failed` | the health test raised an exception |
| `extraction_failed` | extraction seed unavailable or rejected, or estimated H missing |

**Rules.** Only `Exception` is caught (`KeyboardInterrupt` passes through). The message of a source or test exception is not recorded, only the class name, because it may contain provider data; the only message that is recorded is the extractor's own `ValueError`. `to_dict()` carries no seed bit or byte. The replay detector holds for one run; to detect replay across consecutive runs, the caller passes the same `detector`.
<!-- dia4-pipeline:end -->

---

## 7. Folder structure

```
EntropyAssuranceLayer/
├── PROJECT.md
├── THREAT_MODEL.md
├── README.md
├── requirements.txt
├── .env                    # IBM token (never in Git)
├── .gitignore
├── eal/
│   ├── __init__.py
│   ├── __main__.py         # allows "py -3.12 -m eal"
│   ├── cli.py
│   ├── config.py           # constants: α, W, n, ε, budget
│   ├── storage.py          # writing and reading batches in data/raw/
│   ├── pipeline.py         # sources -> health -> extraction -> mixer -> seed (Day 4)
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
│   ├── raw/                # raw bits (.npy) + metadata (.json)
│   ├── results/            # experiment CSVs
│   ├── receipts/           # real receipts (chain.jsonl + <id>.json), outside Git
│   ├── public_keys/        # derived public keys, one folder per receipt, outside Git
│   └── logs/               # qpu_usage.csv and eal_runs.jsonl (CLI failures), outside Git
├── keys/                   # issuer key (.sk and .pk outside Git)
├── scripts/                # document and analysis generation (gerar_docs_dia4.py, resilience_dia4.py, plot_bias.py, …)
└── scratch/                # loose test scripts: teste_qiskit.py, teste_ibm.py
```

**`.gitignore` (current file content):**

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

## 8. Environment

### 8.1 Situation confirmed on Day 1

- System: Windows 11, PowerShell.
- Project Python: **3.12.10**, installed by the Python Install Manager, always invoked with **`py -3.12`**.
- Python 3.15.2 also exists as the machine's default. **Never** use `python` or `py` without `-3.12`.
- **No virtual environment:** creating the `.venv` failed with `WinError 2` (cause not resolved). The libraries are installed directly in Python 3.12.
- VS Code: selected interpreter = Python 3.12.10.

### 8.2 Installed and confirmed versions

| Package | Version |
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
pandas==3.1.1
streamlit==1.66.1

```

Installation: `py -3.12 -m pip install -r requirements.txt`. Whenever you install something new, pin the version here.

---

## 9. IBM QPU and budget

### 9.1 Account

- Plan: Open Plan (free).
- Channel: `ibm_quantum_platform`.
- Instance: `open-instance` (pass it explicitly to avoid the warning).
- Token: in `.env`, variable `IBM_QUANTUM_TOKEN`.
- Limit: about 10 minutes of execution per rolling 28-day window; only chip time counts, not the queue. Paid plan: US$ 96 per minute. **Check the balance on the IBM dashboard before every collection.**

### 9.2 First job (Day 1)

| Field | Value |
| --- | --- |
| Backend | ibm_kingston |
| Circuit | 1 qubit, Hadamard + measurement |
| Shots | 128 |
| Job ID | dbgiga4dgr2s73crj1h0 |
| Result | `{'0': 31, '1': 97}` |

**First finding:** 97 of 128 is about 76% "1". For a fair coin, that is about 5,8 standard deviations from 64, so it's not chance: there is real bias on this physical qubit, likely a readout error. That is exactly what E1 will measure at scale.

### 9.3 Planned budget

| Use | Day | Minutes |
| --- | --- | --- |
| Access test (done) | 1 | 0,2 |
| Calibration of real per-job consumption | 6 | 0,5 |
| Collection 1 (main) | 6 | 3,0 |
| Collection 2 (another time of day) | 6 | 2,0 |
| Collection 3 (drift between days) | 7 | 1,5 |
| CHSH on hardware | 7 | 0,5 |
| Reserve | — | 2,3 |

### 9.4 Rules

1. Never debug on the real QPU. Everything runs first on the simulator and on a fake backend.
2. Every submission goes through `qpu_ibm.py`, which has a **hard limit**: it refuses the job if the day's accumulated consumption would exceed the budget.
3. Each job is recorded in `data/logs/qpu_usage.csv`: date, backend, qubits, shots, job_id, QPU time (usage field reported by the Runtime; confirm the name in the documentation), output file.
4. Raw QPU data is saved **before** any processing.
5. `SamplerV2` has been marked deprecated since qiskit-ibm-runtime 0.50. Decision: keep it in the prototype while it works, isolated in `qpu_ibm.py`, so it can be swapped for the new `Sampler` in a single file.
6. Each shot of N qubits generates N bits. With 156 qubits and 4.096 shots: about 639 thousand bits per job. Also keep the **qubit → bit position map**, to analyze bias per qubit.

---

## 10. Experiments

| # | Question | Method | Metrics | Output |
| --- | --- | --- | --- | --- |
| E1 | How good is the QPU as a source? | `qpu_sim` with noise vs. real QPU vs. `os`, across 3 sessions | Bias per qubit, correlation between neighbors, `h_estimated`, drift between sessions | `data/results/e1_*.csv` |
| E2 | Does the system detect bad sources? | 5 faulty sources × intensities × batch sizes, hundreds of batches | Detection rate, false positives (on `os`) | `data/results/e2_*.csv` |
| E3 | How much does it cost, and what's the throughput? | Bits per job and per second of QPU | QPU bits/s, cost per megabit at US$ 96/min | `data/results/e3_*.csv` |
| E4 | Does the mix hold up? | Failure or bias of one source; adversarial source that sees the others; XOR vs. hash | Approved output per scenario | `data/results/e4_*.csv` |
| E5 | Does CHSH help? | S on the noiseless simulator, with noise, on the real QPU, and classical generator | S (classical limit 2; quantum maximum 2√2 ≈ 2,83) | `data/results/e5_*.csv` |

**CHSH angles:** Alice measures at 0 and π/2; Bob at π/4 and −π/4. `S = E(a0,b0) + E(a0,b1) + E(a1,b0) − E(a1,b1)`.

**Hypotheses** (to be measured, not proven):

- E1: small but measurable bias on the real QPU; `h_estimated` below 1.
- E2: bias, stuck runs, and replay detected; a disguised classical generator **passes** (a fundamental limitation of testing the output).
- E3: much more expensive than the `os` source.
- E4: with 1 good, independent source, good output; XOR fragile against an adversarial source.
- E5: noiseless simulator ≈ 2,83; real QPU between 2 and 2,83; classical ≤ 2. This serves only as a sanity check.

---

## 11. Data conventions

- **Raw bits:** `numpy.packbits` in `.npy`, with a sibling `.json` metadata file (the `RawBatch` fields except `bits`).
- **Names:** `AAAA-MM-DD_<source_id>_<sessao>_<n>.npy`, for example `2026-11-02_ibm_kingston_s1_003.npy`.
- **Results:** CSV with a header, one line per batch or scenario.
- **Reproducibility:** simulated and faulty sources use a fixed seed recorded in the CSV. The `os` source and the real QPU are, by nature, not reproducible; that's why the raw data is kept.
- **Every number in the report comes from a file in `data/results/` generated by a script.** Nothing typed by hand.

---

## 12. Code rules

1. Python 3.12, always run with `py -3.12`.
2. Code and names in English; comments and messages may be in Portuguese.
3. Types on parameters and returns; a short docstring on every public function.
4. Short functions (target: up to 50 lines); no global state; constants in `eal/config.py`.
5. Randomness **only** through the sources. The Python `random` module is forbidden outside `faulty.py`.
6. Every module comes with `pytest` tests. Nothing is done without a green test.
7. Tests with **known answers** at the critical points: RCT/APT thresholds, the MCV estimator, the extractor (dimensions and linearity), key derivation (same seed, same keys), receipt signature.
8. One module per task; commit at every green step.
9. No `print` of a seed, private key, or token, not even in debug mode.

---

## 13. Security rules

1. The IBM token only in `.env`; `.env` in `.gitignore`. If the token appears in chat, a screenshot, or a public file, generate a new one on IBM.
2. The issuer's private key only in `keys/*.sk`, in `.gitignore`.
3. The seed and derived keys live only in memory; the receipt carries only hashes.
4. The QPU is never the sole source of a seed used as a key.
5. Simulated sources never enter `keygen` mode.
6. Honest language in every result (see section 9 of `THREAT_MODEL.md`).
7. Real receipts, derived public keys, the issuer's `.pk`, and the logs stay outside Git. Only the Day 9 demo publishes a demonstration chain, in its own folder.

---

## 14. How to work with the AI

**Roles:** the AI writes; I decide, run, read the output, and commit.

**Cycle per task:**

1. Ask for a plan before code (up to 5 lines, affected files, how to test).
2. Code together with tests, one module at a time.
3. Run `py -3.12 -m pytest`; only move on once it's green.
4. Error: paste the whole message and ask for a diagnosis before the fix.
5. Ask for a summary in Portuguese of what changed and what might be wrong.
6. Commit.

**At the critical points** (health tests, min-entropy, extractor, key derivation, CHSH): ask the AI to cite the specification and section, and do an adversarial review at the end of the module.

**Opening each session:**

```
Read PROJECT.md and THREAT_MODEL.md. Today is Day N. Task: <task>.
Don't write code yet. Propose the plan in up to 5 lines, the files you'll create or change, and how we'll test it.
Remember: Windows, PowerShell, always "py -3.12", no virtual environment.
```

---

## 15. Definition of done

A task is done when:

1. The code runs with `py -3.12`.
2. The tests pass (`py -3.12 -m pytest`).
3. No secret appears in output, log, or versioned file.
4. What was measured is saved in `data/`.
5. There is a commit with a descriptive message.
6. New limitations have been noted in section 17.

---

## 16. Plan for the 9 days (summary)

| Day | Focus | Gate |
| --- | --- | --- |
| 1 | Foundation: environment, IBM account, brief, threat model, structure | `pytest` green, 1-qubit job ran, brief ready |
| 2 | Bit sources and simulator with noise | 5 sources each generate 1 million bits in under 5 min, and the bias chart exists |
| 3 | Health tests and min-entropy | Rejects biased, stuck, and replay; approves `os` |
| 4 | Extractor, mixer, seed | Complete pipeline on the simulator, through to the seed |
| 5 | PQC keys and receipt | One command generates keys and a receipt; another verifies |
| 6 | Collection on the real QPU | 2 to 3 million real bits saved, if the budget allows |
| 7 | Experiments E1 to E5 | Table with the 5 results |
| 8 | Dashboard and report | Dashboard opens with real data; complete report |
| 9 | Delivery: one-pager, demo, README, roadmap | Someone else runs everything using only the README |

**Order of cuts, if running late:** FastAPI → chained log → SHA3 alternative → collection 3 and CHSH on hardware → dashboard becomes a static report.

**Never cut:** sources, health tests, mixer, PQC keys, receipt, and real QPU data.

---

<!-- dia3-gate:start -->
### 16.1 Day 3 gate result

Official gate: `dia3_health_2026-10-30_112209.csv`, commit `ac7637b`, created at `2026-10-30T11:22:09.143096Z`, SHA3-256 `3b322c4d73d2da52bd4c8ae317f4ca363aea2d7aa5bad20e4893ad0bcd0867af`. Result: **APPROVED**. The meta marks git_dirty=true because of untracked files; the tracked code is the one from the indicated commit.

Earlier rounds, not to be cited as the result: `dia3_health_2026-10-29_200210` (broken controls, commit 11c6d4c), `dia3_health_2026-10-29_200513` and `dia3_health_2026-10-30_112016` (prior to the fixes in commit ac7637b).

| Source | Readings | Approved | Rejected | Error or pending |
|---|---|---|---|---|
| `os` | 2 | 2 | 0 | 0 |
| `qpu_sim [ideal (control)]` | 2 | 2 | 0 | 0 |
| `qpu_sim [noise, FakeKingston (control)]` | 2 | 1 | 1 | 0 |
| `faulty_biased` | 2 | 0 | 2 | 0 |
| `faulty_correlated` | 2 | 0 | 2 | 0 |
| `faulty_prng` | 2 | 2 | 0 | 0 |
| `faulty_replay` | 3 | 1 | 2 | 0 |
| `faulty_stuck` | 2 | 0 | 2 | 0 |
| `ibm_<backend> [real QPU]` | 0 | 0 | 0 | 1 |

Controls (their verdict does not enter the gate, which only requires that they ran):
- qpu_sim [ideal (control)], reading 1: approved; monobit p = 0.7840846216576349; reasons: sem motivos
- qpu_sim [ideal (control)], reading 2: approved; monobit p = 0.7565609563559614; reasons: sem motivos
- qpu_sim [noise, FakeKingston (control)], reading 1: approved; monobit p = 0.056650205654175154; reasons: sem motivos
- qpu_sim [noise, FakeKingston (control)], reading 2: rejected; monobit p = 0.00044474799901887707; reasons: monobit: p = 0.000445 (< 0.01)

Gate rules:
- [ok] os approved: all readings approved
- [ok] faulty_biased rejected: all rejected, with APT and the H threshold failing
- [ok] faulty_stuck rejected: all rejected, with RCT failing
- [ok] faulty_correlated rejected: all rejected, with the H threshold failing
- [ok] faulty_replay caught by replay: 1st reading approved; subsequent ones rejected by replay (only by replay if they have N bits)
- [ok] faulty_prng passes (limitation T4): all approved: output tests do not detect a classical generator

**Day 3 decision (A):** the approval criterion remains that of section 6.6 (monobit, block, and runs with p ≥ 0,01 on batches of 1 million bits). This rule was not adjusted after seeing real QPU data. Expected consequence: a QPU with bias on the order of the simulated noise (about 0,15 percentage point, predicted by the chip's calibration) may be rejected on some readings. E1 should report the fraction of approved readings, not just each one's verdict.

Limitations of this measurement:
- The noisy control is simulated. Its rejection is a finding about the FakeKingston calibration, not about a real QPU.
- `faulty_prng` is reproducible only as the instance's sequential stream: the metadata records the seed, not the stream's offset.
- `qpu_sim` records the base seed in the metadata; the effective seed of each run is the base plus the run counter.
- With 1 million bits, the monobit test detects deviations on the order of 0,1 percentage point. Bias smaller than that does not show up in the gate.
<!-- dia3-gate:end -->

<!-- dia4-gate:start -->
### 16.2 Day 4 gate result (pipeline resilience)

Measured at 2026-10-30T13:52:03.537145+00:00 (commit `d98e8bb`). Table: `data/results/dia4_resilience_2026-10-30_135203.csv`, SHA3-256 `e8b23bb9f44ab1995063420eb7cf6b57dfa8499a6e74b1f7ec8e70ea4c0c5dc6`. CSV versioned at `2996df2`. Parameters: 5 repetitions per scenario, 1.000.000-bit batches, `FakeKingston` noise backend; 60 runs. Generated by `scripts/gerar_docs_dia4.py`; the summary, the gate, and the false-alarm count were recomputed from the CSV.

**Gate rules.**
- No run with VIOLATION in any scenario.
- In the BASE scenario, in every run where `os` is approved: a 64-byte seed is generated and `usable_for_key = False` (`experiment` mode), and at least one such run exists.

**Gate result: MET.**

**Verdicts per scenario.** `DETECTION_MISS` is a faulty source that passed the tests (an E2 measurement, not a pipeline failure); `UNEXPECTED`, a source that should have entered and didn't; `VIOLATION`, policy or isolation broken.

| Scenario | Mode | Runs | ok | ok_experiment_only | ok_fail_closed | DETECTION_MISS | UNEXPECTED | VIOLATION |
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

**Runs outside the expected** (everything that is not `ok`, except the expected fail-closed cases from the C5 scenarios):

| Scenario | Rep. | States | Verdict | Recorded reason |
| --- | --- | --- | --- | --- |
| `BASE` | 2 | `os:excluded;qpu_sim:mixed` | ok_experiment_only | os: reprovada pelo teste de saúde: block: p = 0.00924 (< 0.01) / sem saída de extração (lote curto ou entropia... |
| `C2_biased_correlated` | 2 | `os:excluded;faulty_biased:excluded;faulty_correlated:excluded` | ok_fail_closed | os: runs: p = 0.00129 (< 0.01) ; faulty_biased: APT: 20 de 976 janelas no limite 589 ou acima (máximo 611) / m... |
| `K1_keygen_standin` | 2 | `os:mixed;ibm_standin:excluded` | UNEXPECTED: não entrou na mistura: ibm_standin | ibm_standin: reprovada pelo teste de saúde: block: p = 0.00881 (< 0.01) / sem saída de extração (lote curto ou... |

**Reading of the results** (sentences generated from the CSV):
- `os` did not enter the mix in 2 of 45 runs outside the scenarios where it fails on purpose (rejection by the health tests or a read failure). Reference from section 16.1: about 3% per batch. This count does not include rejections of the remote stand-in (see the "Runs outside the expected" table).
- In 19 runs with faulty or unavailable sources and `os` approved (`C1_stuck`, `C2_biased_correlated`, `C3_replay/second`, `C4_remote_down`), no faulty source entered the mix.
- `faulty_prng` entered the mix in 5 of 5 runs with `os` approved (C6): output tests do not distinguish a good classical generator (limitation T4).
- In `keygen`, with `os` out (failed read or tampered batch) and the remote source up, the seed was generated in 0 of 10 runs (expected: 0; G2).
- K1: usable seed in 5 of 5 runs; 1 with UNEXPECTED (see the "Runs outside the expected" table). In that run, the recorded reason is rejection by the health test with p < 0,01 (criterion from section 6.6). Since the stand-in uses `os` bits (premise P3), the result is compatible with the false alarm that this threshold produces by chance (about 1% per test on a good source), not with a pipeline defect.
- C5c: in `experiment`, with `os` out, `qpu_sim` alone generated a seed marked unusable in 5 of 5 runs.
- Runs with VIOLATION (policy or pipeline isolation broken): 0.

**What this gate does not show.** The "remote" source of the `keygen` scenarios is a stand-in (`os` bits labeled as a non-simulated remote source), not the IBM QPU. The gate checks policy, isolation, and fail-closed behavior; it does not measure the seed's statistical quality (the SHA3-512 of garbage also looks uniform) nor the detection rate of faulty sources, with 5 repetitions per scenario (that is E2). The CSV stores only the seed's SHA3-256; no seed or bit is recorded.
<!-- dia4-gate:end -->

<!-- dia5-gate:start -->
### 16.3 Day 5 manual gate (real run on the author's machine)

Generated by `scripts/registrar_gate_dia5.py` from `data/results/dia5_gate_manual_2026-10-31.json` (SHA3-256 `00a967715daef34d650310018f47e386f0a3b55632e2c8b08a9c8dec1924ec15`). No number was typed by hand. Before writing, the script checked each receipt, head, and public key against the log and the files in `data/receipts/`, and confirmed in Git that the keys and the log stay outside version control. The JSON came from the `gate_manual_dia5_resultado` block of the handoff (SHA3-256 `906ee784e14b24812c3db84f62d1eb5afd7add1d5644307033645fdbe11f7c2d`).

**Origin.** 2026-10-31, the user's machine, real `os` source, `py -3.12 -m eal` commands.

**Runs.**

| Attempt | Code | receipt_id | seed_hash | ML-KEM-768 (pk_hash) | ML-DSA-65 (pk_hash) | Sources | Head after the run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 20388d1d-5896-5efe-9e16-67c964db7f60 | 4d42873eb3a99f077fc16a4c09f01d8a175f66482a119b2f500c1eabb477a6e8 | b82cf0c2d6f57a71139f5032cda011060ef1a0adf5281eee3fae0d17838c7bd9 | 2a473104b7b98a5d8daa8f58b1a1e96bfef146cb6091aa958d04e22e159db808 | os=mixed | 9f3cf4dcf3d3e6acb4bb53aad3391a6611269d9cdce1af096a3f425377f27001 |
| 2 | 0 | 8efb7176-2edd-5b97-bb5f-4e11709b5d92 | b0e5106433359e629777d198829c1396f40c123f5c70864c79732f9488911aed | 983cf9ed4a2649236396d38265ba3abfdea7d2b2d63cf0ba4303a3f108e4a509 | 22229e42df74a7242bea251aa1a1fc5ab72e103e64017752e1b02434ddeda587 | os=mixed | ae6b331a3db5d81b43a1ebbbe8c2661b21ac8d4761fb8938a6e089b691d1687a |

**Issuer key.** code 0; pk_hash 729e5cfbd664fafc6b444050f6cae2863b7a6fdf4bf20e2369b5e52dd14d57d0; .sk and .pk ignored by Git (.gitignore:6 keys/*.sk and :14 keys/*.pk).

**Checks.**

- verify of the last receipt + --expected-head (position 2 of 2, head checked): code 0
- verify of the second-to-last receipt (position 1 of 2): code 0
- verify of an identical copy with another name and --chain-dir: code 0
- verify of a TAMPERED copy ('mode':'keygen' -> 'keygex', copy in %TEMP%): code 1, 'recibo reprovado'
- verify with wrong head ('a'*64): code 1, 'cadeia reprovada'

**Other checks on the gate date.** Public keys with 2369 and 3905 bytes (2 x size + 1, no \r). git status shows nothing from keys/ or data/. No failure recorded. Only two runs: do not generalize (e.g., do not claim a fail-closed rate).

**What this gate shows and what it doesn't.**

- 2 run(s) with the `os` source. This is one day's data, not a rate: with it you cannot estimate the frequency of chance failures.
- The source is `os`, whose unpredictability is a premise (P3). The IBM QPU did not enter this run, and the CLI does not yet have QPU collection.
- The gate checks the flow, the chain, and the keys on disk. It does not measure the seed's statistical quality nor the detection rate of faulty sources (that is E2).
<!-- dia5-gate:end -->

<!-- dia5-nota:start -->
**Note about the Day 5 gate.** The gate fulfills the flow below. It is not a single command that does everything:

- `py -3.12 -m eal init-issuer` creates the receipt issuer's key. It must exist before the first `run`.
- `py -3.12 -m eal run` derives the ML-KEM-768 and ML-DSA-65 keys from the seed and writes the ML-DSA-65-signed receipt to the chained log. It does not create the issuer key.
- `py -3.12 -m eal verify <recibo>` checks the signature, the format, and the receipt's position in the chain.

The derived private keys stay only in memory (AT2 of THREAT_MODEL). The `--export-demo` exception is not part of this gate.
<!-- dia5-nota:end -->

<!-- dia5-revisao:start -->
### 16.4 Day 5 adversarial review

Done by reading the code, in parts, from the file the collector generates (`revisao_parteN_*.txt`), with the commit read and the SHA-256 of each file. What was confirmed by execution is stated in each finding; the rest is reading, and does not prove the absence of defects.

**Part 1 (31/10/2026), commit `90d15b8`.** `eal/cli.py` (SHA-256 `0ADAC6167E0A570F56BA1D0C4A220AFB6F2A96F1BEBFFD9F564FBC076040DFA5`); `eal/receipt/chain.py` (SHA-256 `779BE0DA09A47EAC1F39AF65A7F9C89977FE67669D7FA7409DDBC1132D2685FE`); `eal/receipt/verify.py` (SHA-256 `371DD71FFA5B99078EB044008AFE7AB0D997FF070763D3D9C0956DAF5F598733`).

**Part 2 (31/10/2026), commit `20e7055`.** `eal/pqc/keygen.py` (SHA-256 `005C589DF037D54ACE97863BCA3B4CE5EAFE5723896D2BCE31A82B50AD6B4F81`); `eal/receipt/builder.py` (SHA-256 `313F49039BD338A7C0635FE3FF3C274945982CC8367FB04B16F0C9A47A31E7EA`); `eal/receipt/sign.py` (SHA-256 `496646F61566563C5F1DE6F3F715B6ACCF035D3E658E55C6CA111D71D923A3FB`); `eal/receipt/schema.py` (SHA-256 `731FCC7D8B52F54C8B603E51D21FFB722990B4C05939B1BA44B724AA9AE87AC3`).

**Part 3 (31/10/2026), commit `20e7055`.** `eal/mix/mixer.py` (SHA-256 `4B0D47C93C2F41152BCE47C834E01F085D7635214DA98CA7AE7B293A1B929807`); `eal/pipeline.py` (SHA-256 `5B6D4DFD862D81B390ACA90A41521ABC82057C7465D23A260A8F230628296A80`); `eal/config.py` (SHA-256 `98DB40E62374FB4A6458C730CCFDC97C4D453B2353C57DE98C9082D06093BD74`); `eal/health/report.py` (SHA-256 `FCAD8168F5AF5C34443C4CE4475EF44D31AAA53651DC5210BC69A1BDE12F8095`); `eal/extract/toeplitz.py` (SHA-256 `6930DFACEE5F36C3395CF849E6A22EA6044F4E0CC48B4C9E8B2F85AFA317D9AC`); `eal/extract/budget.py` (SHA-256 `AB3EE27C0E810A593381985BB344B70ED10F4B95BCAE445B5ADDF62F28FD4765`); `eal/extract/blocks.py` (SHA-256 `CF19EF4E795026914019626FC414AE75E0FCBCB3F0CD96170676E54AD04C64FA`); `eal/extract/sha3.py` (SHA-256 `1DD58535A853B1E2816E097F2E088D9186DADF83AD4F963611FD7125DEF416EC`).

| ID | Severity | Where | Finding | Decision |
| --- | --- | --- | --- | --- |
| F1 | Low | `cli.py`, `verify` | `--sem-cadeia` with `--expected-head` silently ignored the head; only the chain-not-checked warning appeared. Confirmed by execution. | Fixed: together, the two options are now a usage error (exit code 2), before reading the file. Tests in `tests/test_cli_revisao_parte1.py`. |
| F2 | Low (availability) | `chain.py`, `append_receipt` | A log line with no individual file leaves the chain invalid, and `run` refuses before the pipeline. Confirmed by execution, on a copy. | Already documented (section 17, step 3). The limitation gained a manual repair procedure. |
| F3 | Low | `chain.py` | No lock against two simultaneous writes: the chain is flagged as broken and stops; it does not accept the wrong receipt. | Already documented; no change. |
| F4 | Low (latent) | `cli.py`, `run` | `--sources` was validated and never read. | Fixed: the list that validates the argument is the same one that creates the sources (`_SOURCE_FACTORIES`). Tests in the same file as F1. |
| F5 | Informative | `verify.py`, `verify_receipt_text` | The "invalid JSON" reason includes the JSON parser's error text. | Accepted without change: the text carries only the position and fixed messages, never the receipt's content, and it helps diagnose. |
| F6 | Informative | `cli.py` and `chain.py` | `run` verifies the whole chain twice (one ML-DSA verification per line). | To be measured as the chain grows. The first pass is what avoids spending entropy on a bad log. |
| F7 | Low (availability) | `sign.py`, `cli.py` | The `.pk` is written before the `.sk`; if the second one fails, `init-issuer` refuses ("already exists") and `run` says to run `init-issuer`: a dead end. Confirmed by execution in `sign.py`; the effect on the CLI is from reading the code. | Fixed: `init-issuer` and `run` detect the incomplete pair and say which file is missing and what to do. |
| F8 | Low (message) | `schema.py`, `chain.py`, `cli.py` | `--expected-head` in uppercase (as `Get-FileHash` prints it) was rejected as a different head. Confirmed by execution. | Fixed: the argument is normalized to lowercase with no spaces; the comparison stays exact. |
| F9 | Low (hardening) | `schema.py`, `report.py`, `builder.py` | The validator doesn't look inside `mixer`, `sources[i]`, etc., and `HealthReport.to_dict()` uses `asdict`: a new field would go into the signed receipt without an alarm. Today none of these objects carries secret material. Confirmed by execution: acceptance of the extra field; the rest is reading. | Fixed in the builder: a closed list of fields in the nested objects, rejection of long hexadecimal text and of a long bit list, and tests that lock down the 35 fields of `HealthReport`. Verification did not change: old receipts remain valid. |
| F10 | Informative | `pipeline.py` | The `except ValueError` recorded the text of any `ValueError` from the `try`, including the one from reading the seed. | Fixed: reading the seed has its own `try`, and only the extractor's message (fixed text and sizes) is recorded. |
| F11 | Low (latent) | `toeplitz.py` | The seed check used truthiness: `is_simulated=None`, `''`, or `0`, and `is_local='não'` passed. Confirmed by execution. | Fixed: strict boolean, as in the mixer and the receipt builder. |
| F12 | Medium for Day 6, low today | `pipeline.py`, `report.py` | The replay detector is created on every `eal run`: replay across runs is not detected. Already in section 17; THREAT_MODEL (T3) said "low for exact replay". | Resolved on Day 6 (steps 1 and 2, commits e25e8dd and e4b9f1d): the history is saved in `data/logs/replay_history.json` and loaded before any source read; T3 and N14 updated in THREAT_MODEL v1.3. |

**Resolved without code change:** `save_issuer_key` writes in exclusive mode; the four seed domain prefixes (`EAL-v1|ML-KEM-768|`, `EAL-v1|ML-DSA-65|`, `EAL-v1|issuer|ML-DSA-65|`, and `EAL-v1-mix`) are distinct and none is a prefix of another (verified by execution); `PipelineResult.to_dict()` and `MixResult.to_dict()` are fixed field lists; a `--bits` below 1.000.000 does not approve the source, because the statistical test stays inconclusive (reading).

**F12 resolved on Day 6** (steps 1 and 2, commits e25e8dd and e4b9f1d): the replay detector's history is saved between runs and loaded before any source read; the write happens before any receipt. A read or write failure refuses the run (fail-closed). Limitations in section 17.
**G6 (Day 6, resolved):** batch params in the receipt. Step 1 (`df231d7`): `SourceOutcome` carries the params, outside `to_dict()`. Step 2 (`e0b4dd4`): closed list in `config.py`, `batch_params` block in the builder and the schema, `job_id` mandatory for `qpu_ibm`. Verification: suite with 1623 passed and 1 skipped; real chain valid (position 2 of 2, head checked); old receipts without the block remain valid.

<!-- dia5-revisao:end -->

## 17. Known limitations

1. Research prototype; do not use to protect real data.
2. Simplified min-entropy estimate; no claim of conformance with SP 800-90B.
3. Pure-Python PQC libraries: not constant-time, not audited.
4. The QPU provider knows the bits it generated.
5. CHSH on a cloud QPU is not a loophole-free Bell test.
6. The simulator is a classical generator.
7. Environment without `.venv` (unresolved issue on Windows).
8. The QPU budget limits the size of the real samples.
9. The simulator treats the qubits as independent (each one is simulated separately): it doesn't reproduce correlation between neighbors (crosstalk) that a real chip may have.
10. The `qpu_sim` noise comes from a fixed `FakeKingston` calibration (15/04/2026), which may not reflect today's chip; the comparison with the real chip is E1.
11. The Aer `NoiseModel.from_backend` builds the readout error symmetrically, which erases a qubit's bias in a 50/50 way; the project rebuilds the error asymmetrically from the calibration (`eal/sources/noise.py`).

---

### Day 3 limitations

- Health and statistical tests do not detect a good-quality classical generator (T4). The defense is structural (mandatory local source in the mix).
- Replay detects identical 4096-bit blocks. It does not detect transformed replay (one bit changed per block), replay shifted off multiples of 4096 bits, or replay smaller than a block, unless the whole batch is identical.
- The replay detector's state exists only in memory, during one run. Replay across runs is not detected.
- The health test by estimated H uses a 0,9 threshold, which is a project choice, not a value derived from data.
- The APT and the statistical tests only test complete windows and blocks; trailing bits are discarded and recorded in `notes`.
- A batch smaller than 1.000.000 bits: the statistical tests are inconclusive, and the batch is not approved.

### Day 4 limitations (step 1: extractor)

- The Toeplitz ε = 2^-64 holds per block. Over a batch, the bound is n_blocks · ε (≈ 2^-55 for 488 blocks) and only holds if each block has the estimated min-entropy conditioned on the previous blocks; correlation between blocks breaks this premise.
- The Toeplitz guarantee (leftover hash lemma) depends on premise P4: a seed uniform and independent of the source. The code rejects a simulated, non-local, or batch-identical seed, but does not prove statistical independence.
- The SHA3 extractor has only a heuristic guarantee (random oracle model); it serves for comparison, not for the pipeline.
- Good statistics at the extractor's output prove nothing: the SHA3 of stuck bits also looks uniform. The extractor is sized by the H measured at the input.
- The output p-values in the comparison CSV are diagnostic, not approval (output < 1M bits).

### Day 5 limitations (step 1: PQC derivation)

- The official vectors (NIST ACVP) cover the libraries' `key_derive`, not EAL's derivation (SHAKE256 with a domain prefix over the seed), which has no official vector and is checked against `hashlib` in the test.
- The vectors are the ML-KEM-768 and ML-DSA-65 subset of the ACVP-Server master branch, downloaded on 30/10/2026; each file's commit was checked by the SHA3-256 of the original content: ML-KEM-768 `15c0f3deeefbfa8cb6cd32a99e1ca3b738c66bf0`, ML-DSA-65 `2972def23bf9f3680c2c531561ed9bdd0f1086ad` (see `tests/data/kat/SOURCE.json`).
- The vectors cover key generation. Encapsulation, decapsulation, signing, and verification are tested by round-trip and tampering, without official vectors.
- The secrecy test looks for secret spans defined by the FIPS 203/204 format. The start of the ML-DSA private key (`ρ`) is public, so the test looks for `K`; if a future library version changes the format, the `test_sk_do_ml_dsa_comeca_com_rho_publico` test will warn.
- Pure-Python libraries: not constant-time and not audited (T15, N5). The seed stays in `bytes`, which Python does not erase from memory (P1).
- Mutations: 14 manual mutations of the derivation, the mix policy, and secrecy were all detected (`scripts/mutacoes_pqc.py`); this shows that the tests catch these errors, not that the module is correct.


<!-- dia4-limitacoes:start -->
### Day 4 limitations (step 3: extractor yield)

- The loss model is accounting, not measurement: it says what the extractor does with the H it receives, not whether that H is correct (T8).
- The curve as a function of n assumes the same H for every n; the batch's ε (n_blocks · ε) holds under the premise of independence between blocks.
- The estimated H of `os` comes out below 1 by construction of the estimator, and the health test by H (threshold 0,9) rejects small batches even from a source that premise P3 considers good; see table D for the affected sizes.
- Table D has 10 readings per size: the spread between readings is reported, but there is no confidence interval.
- The `os` source is not reproducible and the bits from this measurement were not kept; only estimates and batch hashes.
- With few readings per source, differences in H between `os`, ideal `qpu_sim`, and noisy `qpu_sim` are not conclusive; the comparison between sources is E1's job.
<!-- dia4-limitacoes:end -->

<!-- dia4-limitacoes-pipeline:start -->
### Day 4 limitations (steps 2 and 4: mixer, pipeline, and resilience)

- A `MixInput` assembled by hand, without `make_mix_input`, can declare a fake `input_hash`: the pairing only holds for whoever uses the normal entry point.
- The seed stays in `bytes`, which Python cannot erase from memory; this is acceptable in the prototype and covered by premise P1 (sound host).
- The 512-bit floor counts extracted bits, not proven entropy; it holds under the same premises as the extractor (P4 and independence between blocks).
- In `experiment`, the mixer does not require a non-simulated local source (see 6.9); the seed comes out unusable for a key, but a run without `os` still generates a seed.
- The pipeline's policy tests use fake health functions; the behavior with the real statistical tests only shows up when the resilience script runs.
- The remote source in the `keygen` scenarios is a stand-in (`os` bits with a remote label), not the QPU: the gate says nothing about the real QPU nor about the provider's independence (N7).
- Scenario C5b tampers with the `os` batch using a run of zeros, which only exercises the RCT; it doesn't cover bias or correlation in `os`.
- The test with an adaptive source shows that SHA3-512 resists canceling out `os`'s entropy (canceling it would require collisions), but it does not protect someone who sees `os`'s output (G3 only holds for someone who doesn't know it), and an adaptive source can "grind" candidates, at a cost of 2^k to fix k bits of the seed.
- Few repetitions per scenario: the counts in 16.2 do not estimate rates (neither the `os` false-alarm rate nor the detection rate); that is E2's job.
<!-- dia4-limitacoes-pipeline:end -->

### Day 5 limitations (step 2: receipt)

- The batch `params` (e.g., IBM's `job_id`) did not reach the receipt. Resolved on Day 6 (G6): see the "Day 6 limitations (G6)" section below.
- The receipt is verifiable by this Python code; the canonical JSON with floating-point numbers has not been tested against a verifier in another language.
- The integration test uses a deterministic source (SHAKE256) in place of `os`, so it doesn't fail by chance; it is not an entropy source and only exists in the tests.
- The issuer key depends only on the `os` source (P3) and sits on disk unencrypted (N11).

### Day 6 limitations (G6: batch params)

- Receipts prior to G6 don't have the `batch_params` block; verification accepts the absence, so they remain valid, but they don't prove the `job_id` of any collection.
- The key names (`backend`, `job_id`, `shots`, `qubits`) and the formats (text up to 64 characters, integers from 1 to 10⁹) are this prototype's assumptions. This note dates from before the Day 6 adapter (`eal/sources/qpu_ibm.py`) existed: the real names and formats of `job_id` and the qubit count need to be checked against the qiskit-ibm-runtime documentation before collection. If the provider uses another format, the receipt is rejected (fail-closed).
- The `job_id` is stored in the clear in the receipt. It is not a secret, but it reveals that the job existed on the account.
- The receipt proves the params that the code handed to the builder, not that the IBM API returned those values.

### Day 6 limitations (F12: replay history)

- The history starts at the first `eal run` after commit `e4b9f1d`. Batches from earlier runs are not in it, so replay of an old batch is not detected.
- `state_hash` detects accidental corruption, not tampering: someone with disk access can redo the file, and deleting it resets the protection without an alarm. The chain head noted outside the repository does not cover this file.
- There is no lock against two simultaneous `eal run` processes (like F3): the last write wins.
- The file grows with the batches; above 64 MiB `run` refuses, until someone archives it by hand.
- Transformed replay and replay shifted off multiples of 4096 bits remain undetected (see the Day 3 limitations).

### Day 5 limitations (step 3: chained log)

- There is no lock against two simultaneous writes: two processes can read the same head and write two receipts with the same `prev_receipt_hash`. `verify_chain` flags this afterward, but the write is not prevented. The prototype's scope is a single user (THREAT_MODEL, section 1).
- Deleting the LAST receipt (or truncating the end of the log) leaves a valid chain. Only the head kept outside the log (`expected_head`) exposes it, and the prototype doesn't yet store that head anywhere.
- Whoever has the issuer's private key and disk access can redo the entire chain with valid signatures (N11, a residue of T9).
- One issuer key per chain, no rotation: changing the key means starting another chain.
- Writing to the two files is not atomic. If the process crashes between the line and the `<receipt_id>.json`, the log ends up with a line and no file, and starts refusing new writes (fail-closed) until a manual intervention; there is no repair command. The repair is to recreate `<receipt_id>.json` with the same bytes as the log line followed by `\n`, written in binary mode (an editor could swap `\n` for `\r\n`), and check it with `eal verify`. If the crash leaves an incomplete line at the end of the log, the repair is different (remove that line) and has not been tested. See finding F2 in section 16.4.
- `fsync` asks the operating system to write to disk; behavior during a power loss has not been tested.
- `created_at` is supplied by whoever issues the receipt and is not checked (nor is the order between receipts).
- The chain's integration test uses the same deterministic test source from step 2 in place of `os`; it is not an entropy source.
- Mutations: 55 manual mutations of `chain.py` were all detected (`scripts/mutacoes_chain.py`); this shows that the tests catch these errors, not that the module is correct.

### Day 5 limitations (step 4: command line)

- `run` only accepts the `os` source. IBM collection (Day 6) is done outside `run`, by `scripts/coletar_ibm.py`, so the CLI does not mix `os` with another source.
- With only `os`, an occasional fail-closed is possible (the block test already rejected `os` in one of the Day 4 gate's scenarios). The command does not retry on its own; running it again is the user's decision.
- The `chain head` is printed by `run`, but the prototype doesn't store it anywhere: `--expected-head` only serves whoever wrote it down. Without that, deleting the last receipt remains undetectable (step 3's limitation).
- Real receipts, derived public keys, the issuer's `.pk`, and the logs stay outside Git. Losing `data/receipts/` erases the evidence, and there is no backup. The Day 9 demonstration chain will go in its own folder, with a copy of the issuer's `.pk`.
- The issuer's `.sk` sits in hex, unencrypted, in `keys/` (N11). `init-issuer` does not overwrite; there is no key rotation or recovery.
- The `--export-demo` mentioned in 6.10 does not exist: no derived private key goes to disk.
- `run` writes the derived public keys, but no command later checks them against the receipt's hashes.
- The failure log has no rotation or tamper protection, and the `reason` field may contain the user's folder paths.
- The default folders are relative to the current directory: running from another folder creates `keys/` and `data/` there.
- Two simultaneous `run` processes remain without a lock (inherited from step 3).
- Characters the console can't write turn into `?` (the Windows console uses ibm850), and parts of `argparse`'s help stay in English.
- The CLI tests use the deterministic source (SHAKE256) in place of `os`, with the real pipeline. The CLI with the real `os` only runs in the manual gate.
- Mutations: 58 manual mutations of `cli.py` were all detected (`scripts/mutacoes_chain_cli.py`); this shows that the tests catch these errors, not that the CLI is correct. One of them, "doesn't create the keys folder", was equivalent, because `save_issuer_key` already creates the folder; it's covered by a test that pins down the command's `mkdir`.

## 18. Glossary

| Term | Meaning |
| --- | --- |
| Entropy | A measure of unpredictability |
| Min-entropy | Worst-case entropy: how good the most likely guess is; the measure used in cryptography |
| Bias | Deviation from 50/50 between 0 and 1 |
| Extractor | A function that turns imperfect bits into fewer, nearly uniform bits |
| Seed | A 64-byte value that feeds key derivation |
| Fail-closed | When in doubt, the system generates nothing |
| QPU | Quantum processor |
| Shot | One run of the circuit; generates 1 bit per measured qubit |
| Backend | The machine (real or simulated) that runs the circuit |
| KEM | Key encapsulation mechanism (ML-KEM) |
| CHSH | A Bell test with two qubits; measures correlations that no local classical model can exceed 2 on |
| Receipt | A signed record of how a seed and its keys were produced |
| RCT / APT | SP 800-90B continuous health tests |

---

## 19. References

- NIST FIPS 203 (ML-KEM): https://csrc.nist.gov/pubs/fips/203/final
- NIST FIPS 204 (ML-DSA): https://csrc.nist.gov/pubs/fips/204/final
- NIST SP 800-90B (entropy sources): https://csrc.nist.gov/pubs/sp/800/90/b/final
- NIST SP 800-22 Rev. 1a (statistical tests): https://csrc.nist.gov/pubs/sp/800/22/r1/upd1/final
- IBM Quantum Platform, plans: https://quantum.cloud.ibm.com/docs/guides/plans-overview
- IBM Quantum, pricing: https://www.ibm.com/quantum/pricing
- Quantinuum Quantum Origin: https://docs.quantinuum.com/origin/user_guides/introduction/how-quantum-origin-works.html
- NCSC, quantum security technologies: https://www.ncsc.gov.uk/paper/quantum-security-technologies

Confirm the links and the API versions before relying on them; plans, prices, and APIs change.


## 20. Day 6: calibration on the real QPU and pending items (record)
Calibration job: dbji1pgnceqs73ak2c8g, backend ibm_kingston, 156 qubits, 1000 shots, 20 s reserve, SamplerV2 (qiskit 2.6.1, qiskit-ibm-runtime 0.51.0).
State: DONE. Billed usage: 2 s of QPU (usage() and qpu_charge_time_seconds). Created at 08:22 (São Paulo time) and already completed by the 11:26 inspection.
Conversion validated with a real result: BitArray with 156 bits and 1000 shots; the adapter's conversion matches to_bool_array(order='little'). 156000 uint8 bits. Overall fraction of 1: 0,4971.
Columns furthest from 0,5 (position, physical qubit, fraction of 1): 121, 0,3450; 46, 0,4080; 112, 0,5740. A single job's sample: not a conclusion about bias.
Calibration: properties() at the start of the run has the date 2026-11-01 11:09:06 (-03:00); the snapshot recorded at submission has 07:36:54 (-03:00). The date changed, but the readout error of the 156 qubits did not (maximum difference 0,00000). It's not yet known which property changed.
Confirmed on ibm_kingston: 156 operational qubits; max_shots 100000; default_rep_delay 0,00025 s; readout error (31/10/2026) minimum 0,00134, median 0,00989, maximum 0,49451.
Budget window: 28 rolling days (usage_period from 03/10 to 31/10 in the 31/10 probe). Open Plan limit: 600 s.
Dry-run unavailable for ibm_kingston on the Open Plan (QiskitBackendNotFoundError: no mock_ backend). The real cost can only be measured with a real job. Failure message fixed in commit ab11bc5.
SamplerV2 deprecated since qiskit-ibm-runtime 0.50.0 (DeprecationWarning, removal no sooner than 3 months after release). Version pinned at 0.51.0; the switch to executor_sampler comes after collection 1.
Single-point estimate (upper bound, not measured): 2 million bits fit in a job of about 12.821 shots with a reserve of ~41 s; 3 million in about 19.231 shots with a reserve of ~60 s. A second calibration job will confirm or overturn this.
Pending items before collection 1: (1) retrieve the calibration job, which closes the accounting in the log; (2) a second calibration job; (3) record the frozen collection-1 plan here before the first submission; (4) P1: copy data/logs/replay_history.json after the first real `eal run`; (5) the Day 6 gate (2 to 3 million real bits saved), not yet evaluated.
New limitation (section 17): the adapter first reads usage from metrics()['usage']['quantum_seconds'], a key IBM did not return for this job; IBM exposes qpu_charge_time_seconds. The read fell back to usage(), which returned the same value. Fix before collection 1.
New limitations (section 17), not yet listed: a crash window between checking the batch and writing it (the batch ends up consumed and unrecorded); Toeplitz seed readings don't go through the replay detector (premise P3); the 64 MiB limit on the replay history.

<!-- coleta1-plano:start -->
### Frozen plan for collection 1 (Day 6, recorded before the first submission)

Recorded on 01/11/2026 against commit dca8fb6. No parameter below changes after the first submission of collection 1 (this frozen plan is itself the rule; PROJECT.md has no separate section for it, and section 6.5 only fixes the H threshold of 0,9).

- **Backend:** ibm_kingston.
- **Qubits:** all 156 operational ones, with no exclusion. The decision was made when QPU output from the calibration jobs already existed; excluding any qubit now would mean choosing while looking at the data.
- **Circuit:** Hadamard on every qubit and measurement (`hadamard_all_measure`), SamplerV2, the backend's default `rep_delay` (0,00025 s).
- **Session:** `coleta1`.
- **Jobs:** 2, sent one at a time. The second is only sent after the first has been retrieved and inspected.
- **Shots per job:** 9.616, giving 1.500.096 bits per job and 3.000.192 total.
- **Reserve per job:** 20 s.
- **Cost basis:** two calibration jobs (1.000 shots: 2 s; 4.000 shots: 3 s). The model is 1,667 s fixed + 0,333 ms per shot, with a central estimate of 4,9 s per job. IBM charges in whole seconds; with ±0,5 s at each point, the worst case is about 7,2 s per job.
- **Stopping criteria:** the collection ends when both jobs are saved. It stops earlier if any of these happen:
  - budget refusal;
  - a job with a status other than DONE;
  - a conversion failure, or batch params other than OK in `inspecionar`;
  - a duplicate-batch warning;
  - the first job using more than 15 s (3 times the central estimate, a sign that the cost model is wrong).

  On stopping: document it and do not resend without a new decision recorded here.
- **What is not a stopping criterion:** the bits' statistics (bias, estimated H). Rejection at the 0,9 threshold is a valid result.
- **Calibration bits:** those from the `cal` session (`cal_001` and `cal_002`, 780.000 bits) do not count toward the gate.
- **Day 6 gate:** 3.000.192 real bits saved in `data/raw`, in session `coleta1`.
<!-- coleta1-plano:end -->

<!-- dia6-gate:start -->
### Day 6 gate result (collection 1)

Generated by `scripts/atualizar_docs_gate6.py` from `data/results/dia6_coleta1_inventario.csv` (SHA-256 `9f01c43147013f6da2de009f010899bfd46d775ac8dac2b908f9b010746d5b81`), which comes out of `scripts/inventario_coleta1.py`. The numbers below come from that file.

- **Result:** MET. 3.000.192 real QPU bits saved in `data/raw`, session `coleta1`; the frozen plan's target was 3.000.192.
- **Batches:** 2, backend ibm_kingston, 156 qubits.
  - `2026-11-01_ibm_kingston_coleta1_001.json`: job `dbjlg80nceqs73ak89g0`, 9.616 shots, 1.500.096 bits, usage 5 s, SHA-256 of the `.npy` `0b8d5b04482331f1eb7b8a356963fde7155126a033d0f66daf2e0d68a3652412`.
  - `2026-11-01_ibm_kingston_coleta1_002.json`: job `dbjlkahffo6c73b9t1u0`, 9.616 shots, 1.500.096 bits, usage 5 s, SHA-256 of the `.npy` `c8a9ca348727ecda02f79b67b052cc3b1f3517d31ec88646cc269e0780054cc9`.
- **QPU usage for collection 1:** 10 s total.
- **Stopping criteria:** none triggered; status DONE, conversion and batch params OK, and no duplicate warning, checked with `inspecionar_job_ibm.py` on each job.
- **Copy of the raw data:** `C:\projeto\ancoras\coleta1_2026-11-01`, with SHA-256 checked file by file. `data/raw` is not versioned.
- **Left for later:** reorganize sections 6.12, 9.3, 9.4, and 17 (R11), change the Status field (R12), and analyze the data in E1.
<!-- dia6-gate:end -->

<!-- dia6-e1parcial:start -->
### Partial E1 (Day 6): real QPU, simulator, and the os source; cal jobs

Generated by `scripts/atualizar_docs_e1parcial.py`. Every number below comes from the CSVs in `data/results` (SHA-256 with line endings normalized to LF):

- `dia6_qpu_vs_sim_lotes.csv`: `5023a1a6df5473f2be955d66681d732127f6d29714424d0060b9b13cefbb6e14`
- `dia6_qpu_vs_sim_resumo.csv`: `dd6f7375d0947e8cd0030eddf9552330468964dcbee860d51a1a47e4790ef7ba`
- `dia6_qpu_excesso_leitura.csv`: `d3fe3fad35fa33c3fd50d5b861903dc9a56cb70c16cfbb7bf789b41c1f4f40a6`
- `dia6_qpu_vs_sim_por_qubit.csv`: `9af7321c7c7e5423a1e6337de05f29455f6c2a529962f5220f2177951df05895`
- `dia6_deriva_dia_lotes.csv`: `3078d678a7beb06409d8a804de88e3327ddf7b65276f146283d588ebe0bcdcf2`
- `dia6_deriva_dia_conjunto_fixo.csv`: `543627875f9bfa2c64d0c642ab338b6e9375e25e391b26d008836f439ad63e9e`
- `dia6_deriva_dia_estabilidade.csv`: `0051ad524090bf8a20563f2bce7118aabb03feb58693869d10a38f12de9638e2`

Input: 2 batches per source, of 1500096 bits each, from session `coleta1`. The simulator is `qpu_sim` with FakeKingston noise; the `os` source has the same format.

#### Health tests per batch

Estimated H threshold: 0,90 (section 6.5, fixed before the real data and not adjusted).

| Source | Batch | Approved | RCT, APT and replay | Estimated H | H >= threshold | p monobit | p blocks | p runs | Extracted bits | Yield |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qpu_real (ibm_kingston) | 1 | no | ok | 0,9623 | yes | 2,91e-18 | 0,359 | 0 | 0 | 0,000 |
| qpu_real (ibm_kingston) | 2 | no | ok | 0,9555 | yes | 6,62e-07 | 0,839 | 0 | 0 | 0,000 |
| simulador (qpu_sim) | 1 | no | ok | 0,9592 | yes | 6,78e-17 | 0,699 | 0 | 0 | 0,000 |
| simulador (qpu_sim) | 2 | no | ok | 0,9618 | yes | 7,29e-20 | 0,715 | 0 | 0 | 0,000 |
| os (os) | 1 | yes | ok | 0,9695 | yes | 4,76e-01 | 0,742 | 9,37e-01 | 1359324 | 0,906 |
| os (os) | 2 | yes | ok | 0,9665 | yes | 8,23e-02 | 0,029 | 7,40e-01 | 1354932 | 0,903 |

- qpu_real batch 1 rejected: monobit: p = 2.91e-18 (< 0.01); runs: p = 0 (< 0.01) (frequency pre-test failed; p = 0 (SP 800-22 2.3.4))
- qpu_real batch 2 rejected: monobit: p = 6.62e-07 (< 0.01); runs: p = 0 (< 0.01) (frequency pre-test failed; p = 0 (SP 800-22 2.3.4))
- simulador batch 1 rejected: monobit: p = 6.78e-17 (< 0.01); runs: p = 0 (< 0.01) (frequency pre-test failed; p = 0 (SP 800-22 2.3.4))
- simulador batch 2 rejected: monobit: p = 7.29e-20 (< 0.01); runs: p = 0 (< 0.01) (frequency pre-test failed; p = 0 (SP 800-22 2.3.4))

The `p = 0` of the runs test, when it appears, comes from the frequency pre-test that failed (SP 800-22, 2.3.4); it is not independent evidence from the monobit.

#### Bias, correlation, and stability between the two collection-1 batches

156 qubits, 9616 shots per batch. In each two-value cell: batch 1 / batch 2. The z of p1 is relative to 0,5.

| Source | Fraction of 1 | \|z\| max of p1 | Qubits with \|z\| > 3 | Correlation with the neighbor, \|z\| > 3 | Correlation with the next shot, \|z\| > 3 | Std. dev. of zdiff | \|zdiff\| > 3 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qpu_real | 0,4964 / 0,4980 | 33,1 / 36,1 | 28 / 27 | 3 / 2 | 1 / 0 | 1,14 | 3 |
| simulador | 0,5034 / 0,5037 | 96,1 / 96,3 | 26 / 26 | 0 / 0 | 0 / 0 | 1,00 | 0 |
| os | 0,5003 / 0,5007 | 2,9 / 3,5 | 0 / 1 | 0 / 0 | 0 / 0 | 1,04 | 0 |

zdiff compares each qubit's p1 between batches 1 and 2; with no drift and no structure, the expected standard deviation is close to 1. The `simulador` and `os` sources serve as controls.

#### Real QPU: deviation from 0,5 beyond the snapshot's readout error

- Batch 1: 5 of 156 qubits above the limit (positions: 14, 21, 105, 138, 144).
- Batch 2: 7 of 156 qubits above the limit (positions: 14, 21, 87, 106, 135, 138, 142).
- Above the limit in both batches: 14, 21, 138.
- Expected by chance, with no bias beyond the readout error: about 0,42 per batch.

The limit is 3 standard errors of p1 (0,5 / sqrt of the shot count), and the excess is \|p1 - 0,5\| minus the readout error of the snapshot recorded at submission.

#### Correlation with the neighboring position

- qpu_real batch 1: pairs above the Bonferroni limit (|z| > 3,60, 155 pairs): 112-113 (z = -6,65).
- qpu_real batch 2: pairs above the Bonferroni limit (|z| > 3,60, 155 pairs): 112-113 (z = -5,59).
- simulador batch 1: pairs above the Bonferroni limit (|z| > 3,60, 155 pairs): none.
- simulador batch 2: pairs above the Bonferroni limit (|z| > 3,60, 155 pairs): none.
- os batch 1: pairs above the Bonferroni limit (|z| > 3,60, 155 pairs): none.
- os batch 2: pairs above the Bonferroni limit (|z| > 3,60, 155 pairs): none.
- Real QPU, above the limit in both batches: 112-113.

z = r times the square root of the shot count (approximation). "Neighbor" is physical index position i + 1, not necessarily a coupled pair on the chip.

#### Largest snapshot readout error

Position 146: readout error 0,4912 (batch 1: p1 = 0,5057, z = 1,12; batch 2: p1 = 0,4926, z = -1,45). With a readout error close to 0,5, the output tends not to depend on the prepared state and may look unbiased. This is an inference from the recorded snapshot, not a measurement from this collection, and it shows that an output test does not certify the origin (E2's hypothesis).

#### Cal jobs against collection 1 (persistence within the day)

| Batch | criado_em (UTC) | Calibration at submission | Shots | Fraction of 1 | Check |
| --- | --- | --- | --- | --- | --- |
| cal_001 | 2026-11-01T14:30:25Z | 2026-11-01 07:36:54-03:00 | 1000 | 0,4971 | batch_hash |
| cal_002 | 2026-11-01T15:09:16Z | 2026-11-01 11:57:51-03:00 | 4000 | 0,4973 | batch_hash |
| coleta1_001 | 2026-11-01T15:24:23Z | 2026-11-01 11:57:51-03:00 | 9616 | 0,4964 | inventario+batch_hash |
| coleta1_002 | 2026-11-01T15:28:12Z | 2026-11-01 11:57:51-03:00 | 9616 | 0,4980 | inventario+batch_hash |

Intervals by the `criado_em` field, which is the moment the batch was saved, not the moment of execution on the QPU: cal_001 → cal_002: 39 min; cal_002 → coleta1_001: 15 min; cal_001 → coleta1_001: 54 min.

| Item | Group | Batch | Estimate | z | Expected z | Testable | Replicates | Compatible magnitude |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pair 112-113 | par_replicado_coleta1 | cal_001 | -0,0223 | -0,70 | 1,97 | no | — | — |
| pair 112-113 | par_replicado_coleta1 | cal_002 | -0,0473 | -2,99 | 3,95 | yes | yes | yes |
| pair 130-131 | par_replicado_coleta1 | cal_001 | -0,0712 | -2,25 | 1,07 | no | — | — |
| pair 130-131 | par_replicado_coleta1 | cal_002 | -0,0286 | -1,81 | 2,14 | no | — | — |
| qubit 121 | controle_leitura | cal_001 | 0,3450 | -9,80 | 11,17 | yes | yes | yes |
| qubit 121 | controle_leitura | cal_002 | 0,3232 | -22,36 | 22,34 | yes | yes | yes |
| qubit 131 | controle_leitura | cal_001 | 0,5540 | 3,42 | 9,03 | yes | yes | no |
| qubit 131 | controle_leitura | cal_002 | 0,6475 | 18,66 | 18,07 | yes | yes | yes |
| qubit 138 | vies_alem_da_leitura | cal_001 | 0,4940 | -0,38 | 8,78 | yes | no | no |
| qubit 138 | vies_alem_da_leitura | cal_002 | 0,3887 | -14,07 | 17,55 | yes | yes | no |
| qubit 14 | vies_alem_da_leitura | cal_001 | 0,5070 | 0,44 | 9,29 | yes | no | no |
| qubit 14 | vies_alem_da_leitura | cal_002 | 0,4035 | -12,21 | 18,59 | yes | yes | no |
| qubit 21 | vies_alem_da_leitura | cal_001 | 0,5070 | 0,44 | 1,47 | no | — | — |
| qubit 21 | vies_alem_da_leitura | cal_002 | 0,5220 | 2,78 | 2,95 | yes | yes | yes |

- qubit 14: replicates in cal_002; does not replicate in cal_001; not testable in either batch.
- qubit 21: replicates in cal_002; does not replicate in either batch; not testable in cal_001.
- qubit 138: replicates in cal_002; does not replicate in cal_001; not testable in either batch.
- qubit 121: replicates in cal_001, cal_002; does not replicate in either batch; not testable in either batch.
- qubit 131: replicates in cal_001, cal_002; does not replicate in either batch; not testable in either batch.
- pair 112-113: replicates in cal_002; does not replicate in either batch; not testable in cal_001.
- pair 130-131: replicates in neither batch; does not replicate in either batch; not testable in cal_001, cal_002.

Stability of the qubits' p1 between batch pairs (zdiff, with different shot counts):

| Batch pair | Mean zdiff | Std. dev. of zdiff | \|zdiff\| > 3 | \|zdiff\| max |
| --- | --- | --- | --- | --- |
| cal_001 x cal_002 | -0,01 | 1,45 | 6 | 6,05 |
| cal_001 x coleta1_001 | +0,05 | 1,62 | 5 | 10,33 |
| cal_001 x coleta1_002 | -0,05 | 1,57 | 6 | 8,90 |
| cal_002 x coleta1_001 | +0,10 | 1,26 | 2 | 6,76 |
| cal_002 x coleta1_002 | -0,07 | 1,13 | 2 | 4,37 |
| coleta1_001 x coleta1_002 | -0,21 | 1,14 | 3 | 4,36 |

#### Limits of this analysis

- One session, on a single day, on a single backend. The full E1 calls for sessions at other times and on other days (section 9.3); nothing here measures drift between days.
- The fixed set and the criteria (testable, replicates, compatible magnitude) are hardcoded in `scripts/analisar_cal.py` and were fixed before reading the cal batches, based only on collection 1. One of the fixed set's positions (112, from pair 112-113) had already appeared among the columns furthest from 0,5 of `cal_001` in the section 20 record; the pair's correlation had not been seen.
- The cal batches are not in the inventory: their integrity is only the `batch_hash`. Collection 1 is also checked by the inventory's SHA-256.
- The recorded readout-error snapshot and calibration date are those of submission, not of execution (R8). The four batches share the same readout-error snapshot.
- `criado_em` is the moment the batch was saved; QPU execution times are not in the data and do not enter the conclusions.
- The simulator uses FakeKingston's frozen calibration, not the collection day's; it serves as a qualitative reference. The estimated-H threshold and the health-test thresholds were not changed.
- More than one test per qubit: the cited qubits and pairs come from scans of 156 and 155 items; only what repeats across independent batches or passes the indicated Bonferroni limit carries weight.
- This is a record of measurements. The cause of the bias (readout, gate, relaxation, calibration, or crosstalk) was not determined.

<!-- dia6-e1parcial:end -->

<!-- dia6-estado:start -->
### State at the end of Day 6, step 5 (record)

Generated by `scripts/atualizar_estado_dia6.py` from git, the CSVs in `data/results`, and `eal/config.py`. This document's Status field was not changed (R12 depends on R11).

- Branch `master`; HEAD at the time of the record (before the record's own commit): `700cddd`; clean tree.
- Last complete suite run, reported at the time of the record: 2500 passed, 1 skipped (`py -3.12 -m pytest -q`).
- Collection 1: 2 jobs, 3000192 bits, 10 s of QPU (per the inventory).
- Budget (`eal/config.py`): 600 s per 28-day window; 24 h ceiling 330 s; maximum reserve per job 60 s; margin 30 s. The current balance is not in this record: check before any submission.

#### Commits since `23d328a`

| Commit | Title |
| --- | --- |
| `182c5a8` | Day 6 step 0: account and IBM backend reconnaissance script (read-only) |
| `2c911e8` | Day 6 step 0b: supplementary probe (budget window, max_shots, readout error per qubit, SamplerV2 warning) |
| `aa8f385` | Day 6 step 1, part 1: QPU budget guard and usage log (qpu_budget), 107 tests, 34 mutations |
| `542fcbf` | Day 6 step 1, part 2: BitArray-to-bits conversion and IBM batch params (ibm_bits), 82 tests, 33 mutations |
| `203a73f` | Day 6 step 1, part 3a: QPU policy and IBM access constants in config.py (all-or-nothing script), 39 tests |
| `b6bd0cd` | Day 6 step 1, part 3b: IBM adapter (submission with a hard limit, retrieval, manifest), 102 tests, 42 mutations; mutation scripts without stale bytecode |
| `f0e38a6` | Day 6 step 1, part 4a: QPU cost model and collection planning (qpu_calibration), 110 tests, 31 mutations |
| `655bf84` | Day 6 step 1, part 4b: IBM collection entry point (status, calibrate, submit with confirmation, retrieve) and calibration constants, 102 tests, 40 mutations |
| `8e6ba62` | Day 6 P2: closes out the G6 mutations (batch params in the receipt): 20 gap tests, mutation script with automatic discovery, 19 mutations killed |
| `ab11bc5` | Day 6: dry-run message with no mock backend (nothing was spent), read-only inspection of an IBM job (queue, estimate, calibration drift), 53 tests, mutations 46 and 28 |
| `2ce238c` | Day 6: record of the calibration on the real QPU and pending items in PROJECT.md and THREAT_MODEL.md (block appended at the end, without editing sections), 19 tests |
| `dca8fb6` | R2: usage read first from qpu_charge_time_seconds (IBM's real format), then usage() and quantum_seconds; 122 tests, 49 mutations; T11 checked at 2ce238c and in staging |
| `80837a0` | R4: frozen collection-1 plan in PROJECT.md before the first submission (2 jobs x 9616 shots, 20 s reserve, 156 qubits, session coleta1), 18 tests |
| `deac699` | R6: Day 6 gate met (3.000.192 real bits, session coleta1, 2 jobs, 10 s of QPU); inventory in data/results and record in PROJECT.md, 48 tests |
| `c1d8210` | Day 6 step 4: pipeline on collection 1's real data vs. simulator and os (script, 16 tests, 2 CSVs); QPU rejected on monobit, estimated H 0,956-0,962; 2422 tests |
| `863fb14` | Day 6 step 4b: collection-1 summary (frac1, correlations, zdiff) and excess over the readout error; script, 15 tests, 2 CSVs; 2437 tests |
| `a3bfb8c` | Day 6 step 5: partial E1 recorded in PROJECT.md (generated from the CSVs); cal jobs vs. collection 1 per qubit with a pre-registered fixed set; bias at 14 and 138 present in cal_002 and absent in cal_001; intervals between batches corrected (15 to 54 min, by criado_em); 2 scripts, 40 tests, 4 CSVs |
| `e0f7225` | Day 6: analisar_cal.py docstring fixed (the interval between batches comes from criado_em) |
| `700cddd` | Day 6: state script (block in PROJECT.md and JSON for the next chat) and 23 tests |

#### Results from this stage (SHA-256 with line endings normalized to LF)

| File | SHA-256 |
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

The analysis is in the `dia6-e1parcial` block, right above.

#### What remains

| Id | Pending item | When |
| --- | --- | --- |
| T11 | secrets check (T11) over all the commits in the list above; the user has not yet confirmed its output for the commits made in this phase | before any new commit |
| COLETA2 | collection 2 at another time of day, to measure drift (section 9.3): frozen plan in PROJECT.md before the first submission; only the user submits, with an explicit command and YES | next step |
| DEP_SESSAO | inventario_coleta1.py, analisar_coleta1.py, and analisar_cal.py hardcode the coleta1 session (and the coleta1_ prefix); parameterize the session before analyzing collection 2 (changes code: needs a plan and approval) | before analyzing collection 2 |
| R8 | record the execution's calibration snapshot in each batch; without it, drift by time and by calibration cannot be separated (the section 20 record says cal_001 ran under a calibration different from the date recorded in the batch) | before collection 2 |
| CRITERIO_REPLICA | the 'replicates' criterion (same sign and \|z\| > 2) is weak: where the magnitude is incompatible, report 'direction reproduced, not the magnitude' | when writing the report |
| R11 | reorganize sections 6.12, 9.3, 9.4, and 17 of PROJECT.md with the content of the blocks appended at the end (dia6-e1parcial and dia6-estado included) | before changing the Status |
| R12 | PROJECT.md's Status field still says Day 5 of 9; update after R11 | after R11 (historical entry from Day 6; the Status field now says Day 9 of 9) |
| BACKUP_RESULTADOS | copy data/results to C:\projeto\ancoras (the raw data already has a copy in coleta1_2026-11-01) | low |
| COLETA3 | collection 3 (drift between days), section 9.3: user decision; comes before collection 2 in section 16's cutting order | decide before Day 7 |
| R7 | copy data\logs\replay_history.json to C:\projeto\ancoras after the first real eal run | after the first real eal run |
| R9 | swap SamplerV2 for executor_sampler.Sampler before any package update | low, version pinned |
| R10 | cleanup: the status text 'available for a job' ignores the 60 s limit; RuntimeJobNotFound shows up as an unexpected error; log entry for a refused dry-run | low |
| T_TEMPO | test_noisy_million_bits_fast depends on the machine's speed; record as a limitation in section 17 | together with R11 |

#### Next step

Collection 2 session at another time of day, to measure drift (section 9.3). First the frozen plan in this document, without sending anything; only the user submits.

<!-- dia6-estado:end -->

<!-- coleta2-plano:start -->
### Frozen plan for collection 2 (Day 6, recorded before the first submission)

Recorded on 01/11/2026 against commit e82e081. No parameter below changes after the first submission of collection 2 (this frozen plan is itself the rule; PROJECT.md has no separate section for it, and section 6.5 only fixes the H threshold of 0,9).

- **Objective:** measure drift within the same day (section 9.3), comparing with collection 1.
- **Backend, qubits, circuit, and `rep_delay`:** same as collection 1 (ibm_kingston; the 156 operational ones, no exclusion; `hadamard_all_measure` with SamplerV2; 0,00025 s).
- **Session:** `coleta2`.
- **Jobs:** 2, sent one at a time. The second is only sent after the first has been retrieved and inspected.
- **Shots per job:** 9.616, giving 1.500.096 bits per job and 3.000.192 total.
- **Reserve per job:** 20 s.
- **Time:** the first submission does not happen before 17:00 (-03:00) on 01/11/2026, about 5 h after collection 1.
- **Cost:** collection 1 used 5 s per job. Balance before submission: 583 s.
- **Calibration:** each batch records the submission snapshot (`calibration_date`, `readout_error_by_position`) and, per R8 (commit e82e081), the execution one (`calibration_date_run`, `readout_error_run_by_position`).
- **Stopping criteria and what is not a stopping criterion:** same as collection 1, including stopping if the first job uses more than 15 s. On stopping: document it and do not resend without a new decision recorded here.
- **Analysis criteria, fixed before seeing the data:**
  - health and estimated H per batch, through the same pipeline as collection 1, with a 0,9 threshold;
  - fixed set: bias beyond the readout at qubits 14, 21, and 138; controls 121 and 131; pairs 112-113 and 130-131. No item enters or leaves after seeing collection 2;
  - replication against collection 1: same sign and |z| > 2. Where the direction reproduces and the magnitude doesn't (`magnitude_compativel`), the result is "direction reproduced, not the magnitude";
  - each comparison records whether the execution's calibration is the same as collection 1's or not.
- **Analysis:** only after the session is parameterized in the analysis scripts (DEP_SESSAO).
<!-- coleta2-plano:end -->

<!-- dia6-coleta2:start -->
### Collection 2 and same-day drift (Day 6, record generated from the CSVs)

Generated by `scripts/registrar_deriva_coleta2.py` from the CSVs listed at the end of this block. No number was typed by hand. The criteria are those of the frozen collection-2 plan, recorded before the first submission.

**Collection 2 batches (inventory):** 2 batches, 3.000.192 bits, 10 s of QPU.

| File | Job | Bits | Usage (s) |
|---|---|---|---|
| 2026-11-01_ibm_kingston_coleta2_001.json | dbjq01pffo6c73ba4lo0 | 1.500.096 | 5 |
| 2026-11-01_ibm_kingston_coleta2_002.json | dbjq4ehkdqps73912u30 | 1.500.096 | 5 |

**Health per batch (same pipeline as collection 1, 0,9 threshold):**

| Source | Batch | Approved | Estimated H | Extracted bits |
|---|---|---|---|---|
| qpu_real | 1 | no | 0,959769 | 0 |
| qpu_real | 2 | no | 0,955301 | 0 |
| simulador | 1 | no | 0,959153 | 0 |
| simulador | 2 | no | 0,961837 | 0 |
| os | 1 | yes | 0,966476 | 1.354.932 |
| os | 2 | yes | 0,966476 | 1.354.932 |

**Calibration and fraction of 1 per batch:**

| Batch | Session | Calibration in effect | Readout snapshot | Same as collection 1 | Fraction of 1 |
|---|---|---|---|---|---|
| coleta1_001 | coleta1 | 2026-11-01 11:57:51-03:00 | submission | yes | 0,4964 |
| coleta1_002 | coleta1 | 2026-11-01 11:57:51-03:00 | submission | yes | 0,4980 |
| coleta2_001 | coleta2 | 2026-11-01 16:56:51-03:00 | execution | no | 0,5025 |
| coleta2_002 | coleta2 | 2026-11-01 16:56:51-03:00 | execution | no | 0,5011 |

**Fixed set, collection 2 against collection 1:**

| Item | Group | Batch | Estimate | z | Expected z | Result |
|---|---|---|---|---|---|---|
| qubit 14 | vies_alem_da_leitura | coleta2_001 | 0,5017 | 0,33 | 28,82 | does not replicate |
| qubit 14 | vies_alem_da_leitura | coleta2_002 | 0,4997 | -0,06 | 28,82 | does not replicate |
| qubit 21 | vies_alem_da_leitura | coleta2_001 | 0,5232 | 4,55 | 4,57 | replicates |
| qubit 21 | vies_alem_da_leitura | coleta2_002 | 0,5236 | 4,63 | 4,57 | replicates |
| qubit 138 | vies_alem_da_leitura | coleta2_001 | 0,4875 | -2,45 | 27,22 | direction reproduced, not the magnitude |
| qubit 138 | vies_alem_da_leitura | coleta2_002 | 0,4844 | -3,06 | 27,22 | direction reproduced, not the magnitude |
| qubit 121 | controle_leitura | coleta2_001 | 0,3514 | -29,15 | 34,63 | direction reproduced, not the magnitude |
| qubit 121 | controle_leitura | coleta2_002 | 0,3481 | -29,80 | 34,63 | direction reproduced, not the magnitude |
| qubit 131 | controle_leitura | coleta2_001 | 0,6856 | 36,41 | 28,01 | direction reproduced, not the magnitude |
| qubit 131 | controle_leitura | coleta2_002 | 0,6736 | 34,04 | 28,01 | direction reproduced, not the magnitude |
| pair 112-113 | par_replicado_coleta1 | coleta2_001 | -0,0726 | -7,12 | 6,12 | replicates |
| pair 112-113 | par_replicado_coleta1 | coleta2_002 | -0,0742 | -7,28 | 6,12 | replicates |
| pair 130-131 | par_replicado_coleta1 | coleta2_001 | -0,0528 | -5,18 | 3,32 | replicates |
| pair 130-131 | par_replicado_coleta1 | coleta2_002 | -0,0396 | -3,88 | 3,32 | replicates |

Count: direction reproduced, not the magnitude: 6; does not replicate: 2; replicates: 6.

**Stability between batch pairs (qubits' zdiff):**

| Batch A | Batch B | Mean | Std. dev. | Qubits above 3 |
|---|---|---|---|---|
| coleta1_001 | coleta1_002 | -0,212 | 1,145 | 3 |
| coleta1_001 | coleta2_001 | -0,845 | 3,274 | 12 |
| coleta1_001 | coleta2_002 | -0,649 | 3,377 | 9 |
| coleta1_002 | coleta2_001 | -0,633 | 3,111 | 10 |
| coleta1_002 | coleta2_002 | -0,437 | 3,313 | 11 |
| coleta2_001 | coleta2_002 | 0,196 | 1,133 | 2 |

**Limits:**

- Collection 2 ran under a different calibration (2026-11-01 16:56:51-03:00) than collection 1 (2026-11-01 11:57:51-03:00). The difference between the collections mixes the elapsed time with the calibration change, and this data doesn't separate the two.
- The replication criterion (same sign and |z| > 2) is weak; that's why the magnitude is reported separately.
- This is a record of measurements. The cause of any difference (readout, gate, relaxation, calibration, or other) is not asserted here.

**CSVs (SHA-256 of the bytes on disk):**

- `dia6_coleta2_inventario.csv`: `d2d1fc799f0f1360e910c21cd9899ab188cb673d8fb76702e78291a015be1901`
- `dia6_coleta2_qpu_vs_sim_lotes.csv`: `0a30e43ae33ad62b8cbef7cea034beb3c0199c95beebab3ba3a23c7e36930edf`
- `dia6_deriva_coleta2_conjunto_fixo.csv`: `6f823feef65d7b593a99f4e723f5a0150e88beaedbb93bd4475b0f09c74a4032`
- `dia6_deriva_coleta2_estabilidade.csv`: `efdba5aedc83b95ba23a88135415facadd3a2f5697fb5537b62270d813fc5b99`
- `dia6_deriva_coleta2_lotes.csv`: `24d3ba1bd8b02b6d1b775baee773260e7f6bfc06589c7fdd01af0cf78ffb628b`
<!-- dia6-coleta2:end -->

<!-- dia7-e2:start -->
### E2, attacks: detection rate and false positives (Day 7, record generated from the CSVs)

Generated by `scripts/registrar_e2.py` from `e2_lotes.csv` and `e2_resumo.csv`. No number was typed by hand. The sentences in the reading section are only recorded if each one is confirmed by the CSVs; the script refuses if any fails.

**Protocol (pre-registered):** run against commit `f5b35166ff9550357d0dc30cc14c4ed7fd975130`, checked in the `commit` column of the 7.900 lines. 36 cells, batches of 1.000.000 and 4.000.000 bits. Each batch uses a fresh source instance, its own recorded seed, and a new replay detector; for replay, the two readings of each pair come from the same instance. Detection is a batch with `approved` false; for replay only the 2nd reading counts, and the 1st enters as the reference. A false positive is a rejected `os` batch. 95% Clopper-Pearson CI.

**Results per cell** (RCT, APT, Replay, H, and Stat. count the batches where the respective test failed; a batch can fail more than one):

| Group | Source | Value | Bits | Rejected | Batches | Rate | 95% CI | RCT | APT | Replay | H | Stat. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| detection | faulty_biased | 0,501 | 1.000.000 | 60 | 200 | 0,3000 | 0,2374 to 0,3686 | 0 | 0 | 0 | 0 | 60 |
| detection | faulty_biased | 0,502 | 1.000.000 | 185 | 200 | 0,9250 | 0,8793 to 0,9574 | 0 | 0 | 0 | 0 | 185 |
| detection | faulty_biased | 0,505 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 0 | 1 | 0 | 0 | 200 |
| detection | faulty_biased | 0,51 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 0 | 2 | 0 | 0 | 200 |
| detection | faulty_biased | 0,55 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 0 | 200 | 0 | 200 | 200 |
| detection | faulty_correlated | 0,501 | 1.000.000 | 64 | 200 | 0,3200 | 0,2560 to 0,3895 | 0 | 1 | 0 | 0 | 63 |
| detection | faulty_correlated | 0,502 | 1.000.000 | 184 | 200 | 0,9200 | 0,8733 to 0,9536 | 0 | 0 | 0 | 0 | 184 |
| detection | faulty_correlated | 0,505 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 0 | 1 | 0 | 0 | 200 |
| detection | faulty_correlated | 0,51 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 0 | 1 | 0 | 0 | 200 |
| detection | faulty_correlated | 0,6 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 0 | 10 | 0 | 200 | 200 |
| detection | faulty_stuck | 8 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 0 | 0 | 0 | 0 | 200 |
| detection | faulty_stuck | 16 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 0 | 2 | 0 | 200 | 200 |
| detection | faulty_stuck | 24 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 13 | 5 | 0 | 200 | 200 |
| detection | faulty_stuck | 32 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 200 | 9 | 0 | 200 | 200 |
| detection | faulty_stuck | 64 | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 200 | 126 | 0 | 200 | 200 |
| detection | faulty_prng | - | 1.000.000 | 6 | 200 | 0,0300 | 0,0111 to 0,0642 | 0 | 0 | 0 | 0 | 6 |
| reference (1st reading) | faulty_replay | - | 1.000.000 | 4 | 200 | 0,0200 | 0,0055 to 0,0504 | 0 | 0 | 0 | 0 | 4 |
| detection (2nd reading) | faulty_replay | - | 1.000.000 | 200 | 200 | 1,0000 | 0,9817 to 1,0000 | 0 | 0 | 200 | 0 | 4 |
| false positive | os | - | 1.000.000 | 52 | 2.000 | 0,0260 | 0,0195 to 0,0340 | 0 | 0 | 0 | 0 | 52 |
| detection | faulty_biased | 0,501 | 4.000.000 | 95 | 100 | 0,9500 | 0,8872 to 0,9836 | 0 | 0 | 0 | 0 | 95 |
| detection | faulty_biased | 0,502 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 1 | 0 | 0 | 100 |
| detection | faulty_biased | 0,505 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 0 | 0 | 0 | 100 |
| detection | faulty_biased | 0,51 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 0 | 0 | 0 | 100 |
| detection | faulty_biased | 0,55 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 100 | 0 | 100 | 100 |
| detection | faulty_correlated | 0,501 | 4.000.000 | 89 | 100 | 0,8900 | 0,8117 to 0,9438 | 0 | 2 | 0 | 0 | 89 |
| detection | faulty_correlated | 0,502 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 0 | 0 | 0 | 100 |
| detection | faulty_correlated | 0,505 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 0 | 0 | 0 | 100 |
| detection | faulty_correlated | 0,51 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 1 | 0 | 0 | 100 |
| detection | faulty_correlated | 0,6 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 19 | 0 | 100 | 100 |
| detection | faulty_stuck | 8 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 0 | 0 | 0 | 100 |
| detection | faulty_stuck | 16 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 3 | 0 | 100 | 100 |
| detection | faulty_stuck | 24 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 24 | 2 | 0 | 100 | 100 |
| detection | faulty_stuck | 32 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 100 | 14 | 0 | 100 | 100 |
| detection | faulty_stuck | 64 | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 100 | 96 | 0 | 100 | 100 |
| detection | faulty_prng | - | 4.000.000 | 4 | 100 | 0,0400 | 0,0110 to 0,0993 | 0 | 0 | 0 | 0 | 4 |
| reference (1st reading) | faulty_replay | - | 4.000.000 | 0 | 100 | 0,0000 | 0,0000 to 0,0362 | 0 | 0 | 0 | 0 | 0 |
| detection (2nd reading) | faulty_replay | - | 4.000.000 | 100 | 100 | 1,0000 | 0,9638 to 1,0000 | 0 | 0 | 100 | 0 | 0 |
| false positive | os | - | 4.000.000 | 18 | 500 | 0,0360 | 0,0215 to 0,0563 | 0 | 1 | 0 | 0 | 17 |

**`os` false positive, by test that rejected the batch:**

| Bits | `os` batches | Rejected | monobit | block | runs | APT |
|---|---|---|---|---|---|---|
| 1.000.000 | 2.000 | 52 | 13 | 18 | 21 | 0 |
| 4.000.000 | 500 | 18 | 6 | 6 | 5 | 1 |

Reference (accounting, not a measurement): 3 independent statistical tests with a minimum p of 0,01 would reject 0,0297 of a perfect source's batches.

**Reading (each sentence was checked against the CSVs before being recorded):**

- Bias and correlation (`faulty_biased`, `faulty_correlated`) with an intensity equal to or greater than 0,505 on 1.000.000-bit batches, or 0,502 on 4.000.000-bit batches, were rejected on every batch.
- At the weaker values on the grid (0,501 at both sizes and 0,502 at 1.000.000 bits), detection is partial: some batches pass.
- The RCT did not reject any bias or correlation batch.
- Stuck bits (`faulty_stuck`): every batch was rejected at every length on the grid, including the smallest (8). The lower detection bound for stuck bits was not found.
- At the smallest stuck-run length (8), the RCT and the min-entropy test rejected no batch, and the statistical tests rejected all of them.
- The RCT does not reject stuck runs of 8 and 16 bits, rejects only some batches at 24 bits, and rejects every batch at 32 and 64 bits.
- The min-entropy test only rejected batches with a bias of 0,55, a correlation of 0,6, or a stuck run of 16 bits or more; it rejected no batch in the other cells, including `os`, `faulty_prng`, and `faulty_replay`.
- The replay test rejected every 2nd reading of `faulty_replay` and no batch in any other cell (no false replay alarm).
- On the `os` source, the RCT and the min-entropy test rejected no batch.
- The 95% CIs of `os`'s false positive at both sizes overlap; this data doesn't distinguish the two sizes.
- `faulty_prng`'s rejection rate is indistinguishable from `os`'s: the 95% CIs overlap at both sizes. The output test does not separate a PRNG from a good source (limitation T4 of the threat model).

**Caveats:**

- The faulty sources are simulated (`eal.sources.faulty`, generated by numpy). The rates hold for these defect models, not for real attacks. E2 did not use the QPU.
- The rates for the weak intensities include the background noise of the false positive, which is on the order of `os`'s; nothing was subtracted.
- The statistical tests only reach a conclusion above a minimum batch size (`STATS_MIN_BITS`). E2 measured only batches above that minimum and did not measure smaller batches.
- By construction, the statistical tests reject a fraction of perfect sources tied to the minimum p (reference above). Changing that threshold would also change the sensitivity at weak intensities; this can only be assessed in a new, pre-registered experiment, and was not done here.
- `os` batches have no seed and are not reproducible. The faulty sources' batches are reproducible via the seed recorded in `e2_lotes.csv`. The raw bits were not kept.
- The grid, the sizes, and the repetitions were fixed at the commit indicated above, before the run. The increase in repetitions (10-fold) was decided after measuring the time and before seeing any rate.

**CSVs (SHA-256 of the bytes on disk):**

- `e2_lotes.csv`: `f6d7cc87d3fa3fde9b7691307daa4a299628784fabd65ec4fc961510c94ad90a`
- `e2_resumo.csv`: `2fd202e9b3cc0dccf1dd52a6212de0f6296fb6d3e067ddff68a92e1a0de62a0c`
<!-- dia7-e2:end -->

<!-- coleta3-plano:start -->
### Frozen plan for collection 3 (Day 7, recorded before the first submission)

Recorded on 02/11/2026 against commit 01666ec. No parameter below changes after the first submission of collection 3 (this frozen plan is itself the rule; PROJECT.md has no separate section for it, and section 6.5 only fixes the H threshold of 0,9).

- **Objective:** measure drift between days (section 9.3).
- **Backend, qubits, circuit, and `rep_delay`:** same as collections 1 and 2 (ibm_kingston; the 156 operational ones, no exclusion; `hadamard_all_measure` with SamplerV2; 0,00025 s).
- **Session:** `coleta3`.
- **Jobs:** 2, sent one at a time. The second is only sent after the first has been retrieved and inspected.
- **Shots per job:** 9.616, giving 1.500.096 bits per job and 3.000.192 total.
- **Reserve per job:** 20 s.
- **Time:** the first submission happens between 17:00 and 20:00 (-03:00) on 02/11/2026: the day after collections 1 and 2, in the same time window as collection 2. If the first submission doesn't happen in this window, this plan is void and gets redone.
- **Cost:** collections 1 and 2 used 5 s per job. Balance after collection 2: 573 s; the balance is checked again with `coletar_ibm.py status` before the first submission.
- **Calibration:** each batch records the submission snapshot (`calibration_date`, `readout_error_by_position`) and the execution one (`calibration_date_run`, `readout_error_run_by_position`, R8).
- **Stopping criteria and what is not a stopping criterion:** same as collections 1 and 2, including stopping if the first job uses more than 15 s. On stopping: document it and do not resend without a new decision recorded here.
- **Analysis criteria, fixed before seeing the data:**
  - health and estimated H per batch, through the same pipeline as collections 1 and 2, with a 0,9 threshold;
  - fixed set: bias beyond the readout at qubits 14, 21, and 138; controls 121 and 131; pairs 112-113 and 130-131. No item enters or leaves after seeing collection 3;
  - main analysis: against collection 1, with `analisar_deriva.py --sessao coleta3`. Replication: same sign and |z| > 2; where the direction reproduces and the magnitude doesn't (`magnitude_compativel`), the result is "direction reproduced, not the magnitude". This comparison mixes the day with the time of day (collection 1 near midday, collection 3 after 17:00), and the record says so;
  - secondary analysis, optional: against collection 2 (same time window, the following day), with the same fixed set and the same replication rule, only if `analisar_deriva.py` gains a reference parameter, with tests. If it isn't done, the record says it wasn't done;
  - each comparison records whether the execution's calibration is the same as the reference's or not.
- **Analysis:** with the commands that already accept `--sessao` (inventory, health, summary, and drift).
<!-- coleta3-plano:end -->

<!-- dia7-coleta3:start -->
### Collection 3 and drift between days (Day 7, record generated from the CSVs)

Generated by `scripts/registrar_deriva_coleta3.py` from the CSVs listed at the end of this block. No number was typed by hand. The criteria are those of the frozen collection-3 plan (`coleta3-plano` block), recorded before the first submission. Main analysis: against collection 1.

**Collection 3 batches (inventory):** 2 batches, 3.000.192 bits, 10 s of QPU.

| File | Job | Bits | Usage (s) |
|---|---|---|---|
| 2026-11-02_ibm_kingston_coleta3_001.json | dbkf24d6p51s73cmg7ng | 1.500.096 | 5 |
| 2026-11-02_ibm_kingston_coleta3_002.json | dbkf4f1ffo6c73bbc8m0 | 1.500.096 | 5 |

**Health per batch (same pipeline as collections 1 and 2, 0,9 threshold):**

| Source | Batch | Approved | Estimated H | Extracted bits |
|---|---|---|---|---|
| qpu_real | 1 | no | 0,960593 | 0 |
| qpu_real | 2 | no | 0,955904 | 0 |
| simulador | 1 | no | 0,959153 | 0 |
| simulador | 2 | no | 0,961837 | 0 |
| os | 1 | yes | 0,962463 | 1.349.076 |
| os | 2 | yes | 0,968625 | 1.357.860 |

**Calibration and fraction of 1 per batch:**

| Batch | Session | Calibration at submission | Calibration in effect | Readout snapshot | Same as collection 1 | Fraction of 1 |
|---|---|---|---|---|---|---|
| coleta1_001 | coleta1 | 2026-11-01 11:57:51-03:00 | 2026-11-01 11:57:51-03:00 | submission | yes | 0,4964 |
| coleta1_002 | coleta1 | 2026-11-01 11:57:51-03:00 | 2026-11-01 11:57:51-03:00 | submission | yes | 0,4980 |
| coleta3_001 | coleta3 | 2026-11-02 16:36:41-03:00 | 2026-11-02 17:14:09-03:00 | execution | no | 0,5028 |
| coleta3_002 | coleta3 | 2026-11-02 17:14:09-03:00 | 2026-11-02 17:14:09-03:00 | execution | no | 0,5048 |

**Fixed set, collection 3 against collection 1:**

| Item | Group | Batch | Estimate | z | Expected z | Result |
|---|---|---|---|---|---|---|
| qubit 14 | vies_alem_da_leitura | coleta3_001 | 0,4882 | -2,30 | 28,82 | direction reproduced, not the magnitude |
| qubit 14 | vies_alem_da_leitura | coleta3_002 | 0,5006 | 0,12 | 28,82 | does not replicate |
| qubit 21 | vies_alem_da_leitura | coleta3_001 | 0,5147 | 2,88 | 4,57 | replicates |
| qubit 21 | vies_alem_da_leitura | coleta3_002 | 0,5275 | 5,38 | 4,57 | replicates |
| qubit 138 | vies_alem_da_leitura | coleta3_001 | 0,5101 | 1,98 | 27,22 | does not replicate |
| qubit 138 | vies_alem_da_leitura | coleta3_002 | 0,4992 | -0,16 | 27,22 | does not replicate |
| qubit 121 | controle_leitura | coleta3_001 | 0,4418 | -11,42 | 34,63 | direction reproduced, not the magnitude |
| qubit 121 | controle_leitura | coleta3_002 | 0,4457 | -10,65 | 34,63 | direction reproduced, not the magnitude |
| qubit 131 | controle_leitura | coleta3_001 | 0,6621 | 31,80 | 28,01 | direction reproduced, not the magnitude |
| qubit 131 | controle_leitura | coleta3_002 | 0,6581 | 31,00 | 28,01 | replicates |
| pair 112-113 | par_replicado_coleta1 | coleta3_001 | -0,0666 | -6,53 | 6,12 | replicates |
| pair 112-113 | par_replicado_coleta1 | coleta3_002 | -0,0628 | -6,16 | 6,12 | replicates |
| pair 130-131 | par_replicado_coleta1 | coleta3_001 | -0,0399 | -3,91 | 3,32 | replicates |
| pair 130-131 | par_replicado_coleta1 | coleta3_002 | -0,0288 | -2,82 | 3,32 | replicates |

Count: direction reproduced, not the magnitude: 4; does not replicate: 3; replicates: 7.

**Stability between batch pairs (qubits' zdiff):**

| Batch A | Batch B | Mean | Std. dev. | Qubits above 3 |
|---|---|---|---|---|
| coleta1_001 | coleta1_002 | -0,212 | 1,145 | 3 |
| coleta1_001 | coleta3_001 | -0,882 | 3,063 | 12 |
| coleta1_001 | coleta3_002 | -1,171 | 3,067 | 14 |
| coleta1_002 | coleta3_001 | -0,670 | 2,965 | 11 |
| coleta1_002 | coleta3_002 | -0,959 | 2,983 | 11 |
| coleta3_001 | coleta3_002 | -0,288 | 1,089 | 1 |

Standard deviation of zdiff between batches of the same session: 1,089 to 1,145. Between batches of different sessions: 2,965 to 3,067.

**Limits:**

- Collection 3 ran under a different calibration (2026-11-02 17:14:09-03:00) than collection 1 (2026-11-01 11:57:51-03:00), on a different day and at a different time of day (frozen plan). The difference between the collections mixes the day, the time of day, and the calibration change, and this data doesn't separate the three.
- In batch coleta3_001, the calibration in effect at execution (2026-11-02 17:14:09-03:00) differs from the one at submission (2026-11-02 16:36:41-03:00); the analysis uses the execution snapshot (R8).
- The secondary analysis called for in the plan (against collection 2, same time window on a different day) was not done in this record.
- The replication criterion (same sign and |z| > 2) is weak; that's why the magnitude is reported separately.
- This is a record of measurements. The cause of any difference (readout, gate, relaxation, calibration, or other) is not asserted here.

**CSVs (SHA-256 of the bytes on disk):**

- `dia6_coleta3_inventario.csv`: `9de74bbe035c5d10ddfba06ed88ae42448ae108eaebf71b799012a21480d0ba2`
- `dia6_coleta3_qpu_vs_sim_lotes.csv`: `f7e6619f21370f48273dafeb96efa6206471dbf8f4037bb81723f7058a29c13f`
- `dia6_deriva_coleta3_conjunto_fixo.csv`: `aa5c3fbc07a5720c2922993134f52e7661575fdbab9429ecff2fcb5d88c12887`
- `dia6_deriva_coleta3_estabilidade.csv`: `1c8009100de560e6c6a4e98c14e93459263294690cb3687d6a4670e0914518a8`
- `dia6_deriva_coleta3_lotes.csv`: `ba97a9f9c21ac3736bff511e2d0d14bdac519408ce47419a0b2b98e3d056385a`
<!-- dia7-coleta3:end -->

<!-- dia7-e4:start -->
### E4, mix resilience: XOR against the mixer's hash (Day 7, record generated from the CSVs)

Generated by `scripts/registrar_e4.py` from `e4_sequencias.csv` and `e4_resumo.csv`. No number was typed by hand. The sentences in the reading section are only recorded if each one is confirmed by the CSVs; the script refuses if any fails.

**Protocol (pre-registered):** run against commit `ed4ae200d4d3047b442e9120f1437707298fab48`, checked in the `commit` column of the 1.440 lines; 18 cells; 2.000 512-bit seeds per sequence. Two sources per seed: the honest one (`os`, local) and the second one (`qpu_remota`, remote), which changes per scenario; both enter declared as approved. `hash` is the real `mix` in `keygen` mode; `xor` is a comparator from the script (XOR of the first 512 bits of each source). The hash and the XOR of the same scenario and repetition use the same inputs. Approved: the pipeline's 3 statistical tests pass on the concatenated seeds. 95% Clopper-Pearson CI.

**Results per cell:**

| Scenario | Combiner | k | Expected | Complete sequences | Approved | Rate | 95% CI | Refused | Fraction on target | Distinct seeds | Max \|z\| | Positions \|z\| > 5 | Adversary failures |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_boa | hash | - | segura | 100 of 100 | 97 | 0,9700 | 0,9148 to 0,9938 | 0 | - | 2000 | 4,0696 | 0 | - |
| base_boa | xor | - | segura | 100 of 100 | 94 | 0,9400 | 0,8740 to 0,9777 | 0 | - | 2000 | 4,2485 | 0 | - |
| enviesada | hash | - | segura | 100 of 100 | 97 | 0,9700 | 0,9148 to 0,9938 | 0 | - | 2000 | 4,0249 | 0 | - |
| enviesada | xor | - | segura | 100 of 100 | 98 | 0,9800 | 0,9296 to 0,9976 | 0 | - | 2000 | 4,0249 | 0 | - |
| travada | hash | - | segura | 100 of 100 | 99 | 0,9900 | 0,9455 to 0,9997 | 0 | - | 2000 | 4,4721 | 0 | - |
| travada | xor | - | segura | 100 of 100 | 98 | 0,9800 | 0,9296 to 0,9976 | 0 | - | 2000 | 4,1591 | 0 | - |
| constante | hash | - | segura | 100 of 100 | 98 | 0,9800 | 0,9296 to 0,9976 | 0 | - | 2000 | 4,5616 | 0 | - |
| constante | xor | - | segura | 100 of 100 | 95 | 0,9500 | 0,8872 to 0,9836 | 0 | - | 2000 | 4,2933 | 0 | - |
| copia | hash | - | sem_semente | 0 of 100 | 0 | - | - | 200.000 | - | 0 | - | - | - |
| copia | xor | - | insegura | 100 of 100 | 0 | 0,0000 | 0,0000 to 0,0362 | 0 | - | 1 | 44,7214 | 512 | - |
| adv_alvo | hash | - | segura | 100 of 100 | 97 | 0,9700 | 0,9148 to 0,9938 | 0 | 0,0000 | 2000 | 4,0249 | 0 | - |
| adv_alvo | xor | - | insegura | 100 of 100 | 97 | 0,9700 | 0,9148 to 0,9938 | 0 | 1,0000 | 2000 | 4,3380 | 0 | - |
| sem_fonte_boa | hash | - | insegura | 100 of 100 | 0 | 0,0000 | 0,0000 to 0,0362 | 0 | - | 1 | 44,7214 | 512 | - |
| sem_fonte_boa | xor | - | insegura | 100 of 100 | 0 | 0,0000 | 0,0000 to 0,0362 | 0 | - | 1 | 44,7214 | 512 | - |
| adv_forca | hash | 1 | k_bits | 10 of 10 | 8 | 0,8000 | 0,4439 to 0,9748 | 0 | 1,0000 | 2000 | 44,7214 | 1 | 0 |
| adv_forca | hash | 4 | k_bits | 10 of 10 | 0 | 0,0000 | 0,0000 to 0,3085 | 0 | 1,0000 | 2000 | 44,7214 | 4 | 0 |
| adv_forca | hash | 8 | k_bits | 10 of 10 | 0 | 0,0000 | 0,0000 to 0,3085 | 0 | 1,0000 | 2000 | 44,7214 | 8 | 0 |
| adv_forca | hash | 12 | k_bits | 10 of 10 | 0 | 0,0000 | 0,0000 to 0,3085 | 0 | 1,0000 | 2000 | 44,7214 | 12 | 0 |

**Reading (each sentence was checked against the CSVs before being recorded):**

- With one good, independent source (`base_boa`, `enviesada`, `travada`, `constante`), both combiners produced seeds that were all distinct, no bit position with |z| > 5, and an approval rate whose 95% CI overlaps that of `base_boa` for the same combiner.
- An exact copy of the honest source: the real `mix` refused every seed (repeated `input_hash`, fail-closed); XOR produced a single seed, repeated throughout the sequence.
- An adversarial source that sees the honest one (`adv_alvo`): with XOR, every seed was the one chosen by the adversary (fraction on target 1), and the approval rate's 95% CI overlaps `base_boa`'s, meaning the statistical tests don't see the control. With hash, no seed matched the target and the seeds were all distinct.
- With no good source (both constant), both combiners repeated a single seed throughout each sequence.
- An adversary testing candidates against the hash (`adv_forca`, k = 1, 4, 8, 12): at every k, every seed had its first k bits at zero, exactly k bit positions with |z| > 5, seeds all distinct, and no failures within the attempt limit. Each chosen seed was checked against the real `mix` during the run (the script would refuse if any diverged).
- On the concatenated seeds, the statistical tests rejected only part of the sequences with k = 1 and all of them with k = 4, 8, 12.
- In the `copia/xor`, `sem_fonte_boa/hash`, `sem_fonte_boa/xor` cells, every sequence is identical (same p-values, same max |z|, and the same distinct seeds): the repetitions are not independent observations, and the 95% CI of the approval rate does not apply to them. No cell with a good source is on this list.

**Caveats:**

- The model is the worst case. In the pipeline, no source receives another's output; the source that sees the honest one is hypothetical (for example, a remote provider that had access to `os`'s output).
- All sources enter declared as approved: E4 isolates the combination and does not re-assess health, which is measured in E2.
- Approval is measured over thousands of concatenated seeds. The pipeline generates one seed per run, and in an isolated seed you don't see repetition or forced bits. The adversary's control over XOR doesn't show up in the tests even with the seeds concatenated.
- XOR exists only in the E4 script, as a comparator; `eal` uses only the hash.
- Forcing k bits costs about 2^k hash evaluations per seed, and with more computation k grows. What the hash limits is control to those k bits out of the seed's 512; with XOR, the adversary's control is total and free.
- The execution time varied a lot relative to the previous measurement, especially at the largest k. This doesn't affect the results, which are deterministic by each sequence's seed.

**CSVs (SHA-256 of the bytes on disk):**

- `e4_sequencias.csv`: `65321cf68ecf1cfebae4f28228ae37be7ba5f1a6484f8b2af0d0ef92f4500779`
- `e4_resumo.csv`: `aae9bf5c306c5be64dab60c13108804aae4754af55e6cbb600d0434281b4da5a`
<!-- dia7-e4:end -->

<!-- dia7-e3:start -->
### E3, throughput and cost per megabit (Day 7, record generated from the CSVs)

Generated by `scripts/registrar_e3.py` from `e3_qpu.csv`, `e3_local.csv`, and `e3_resumo.csv`. No number was typed by hand. The structural sentences are only recorded if confirmed by the CSVs; the verdict, the ratio at the extremes, and the time groups are computed from the CSVs.

**Protocol (pre-registered):** no job was submitted; the 8 jobs already run on the Open Plan were used (usage log, raw JSONs, and health CSVs, cross-checked). Theoretical cost: API QPU seconds times the price per minute (pay-as-you-go US$ 96/min, flex US$ 72/min, premium US$ 48/min); source https://www.ibm.com/quantum/pricing, consulted on 2026-11-03. 1 Mbit = 1.000.000 bits. Local benchmark: the real `run_pipeline` with `os`, batches of 1.500.096 bits, 1 discarded warm-up run, and 20 measurements, against commit `af1f1c4ab8d2687f57b70291cabd33e551da6a0f`. Criterion: a ratio of at least 10.

**QPU jobs:**

| Session | Job | Shots | Bits | Seconds of QPU | Bits/s | Theoretical cost (US$) | US$/Mbit | Health | Usable bits | Hypothetical usable bits |
|---|---|---|---|---|---|---|---|---|---|---|
| cal | dbji1pgnceqs73ak2c8g | 1.000 | 156.000 | 2,0 | 78000,0000 | 3,2000 | 20,5128 | - | - | - |
| cal | dbjlaghkdqps7390qbq0 | 4.000 | 624.000 | 3,0 | 208000,0000 | 4,8000 | 7,6923 | - | - | - |
| coleta1 | dbjlg80nceqs73ak89g0 | 9.616 | 1.500.096 | 5,0 | 300019,2000 | 8,0000 | 5,3330 | rejected | 0 | 1.348.344 |
| coleta1 | dbjlkahffo6c73b9t1u0 | 9.616 | 1.500.096 | 5,0 | 300019,2000 | 8,0000 | 5,3330 | rejected | 0 | 1.338.096 |
| coleta2 | dbjq01pffo6c73ba4lo0 | 9.616 | 1.500.096 | 5,0 | 300019,2000 | 8,0000 | 5,3330 | rejected | 0 | 1.344.684 |
| coleta2 | dbjq4ehkdqps73912u30 | 9.616 | 1.500.096 | 5,0 | 300019,2000 | 8,0000 | 5,3330 | rejected | 0 | 1.338.096 |
| coleta3 | dbkf24d6p51s73cmg7ng | 9.616 | 1.500.096 | 5,0 | 300019,2000 | 8,0000 | 5,3330 | rejected | 0 | 1.346.148 |
| coleta3 | dbkf4f1ffo6c73bbc8m0 | 9.616 | 1.500.096 | 5,0 | 300019,2000 | 8,0000 | 5,3330 | rejected | 0 | 1.338.828 |

**Summary (`e3_resumo.csv`):**

| Metric | Value | Unit |
|---|---|---|
| `preco_fonte` | https://www.ibm.com/quantum/pricing | url |
| `preco_data_consulta` | 2026-11-03 | date |
| `qpu_jobs` | 8 | jobs |
| `qpu_segundos` | 35,0 | s |
| `qpu_bits_brutos` | 9.780.576 | bits |
| `qpu_custo_pay_as_you_go` | 56,00 | USD |
| `qpu_custo_flex` | 42,00 | USD |
| `qpu_custo_premium` | 28,00 | USD |
| `coleta_jobs` | 6 | jobs |
| `coleta_segundos` | 30,0 | s |
| `coleta_bits_brutos` | 9.000.576 | bits |
| `coleta_bits_por_s` | 300019,2000 | bits/s |
| `coleta_s_por_mbit_bruto` | 3,3331 | s/Mbit |
| `coleta_custo_por_mbit_bruto_pay_as_you_go` | 5,3330 | USD/Mbit |
| `coleta_custo_por_mbit_bruto_flex` | 3,9997 | USD/Mbit |
| `coleta_custo_por_mbit_bruto_premium` | 2,6665 | USD/Mbit |
| `ajuste_fixo_s` | 1,6296 | s/job |
| `ajuste_por_shot_s` | 0,00035031 | s/shot |
| `ajuste_custo_marginal_por_mbit_pay_as_you_go` | 3,5930 | USD/Mbit |
| `coleta_lotes_aprovados` | 0 | batches |
| `coleta_bits_uteis` | 0 | bits |
| `coleta_custo_por_mbit_util_pay_as_you_go` | undefined | USD/Mbit |
| `coleta_bits_uteis_hipoteticos` | 8.054.196 | bits |
| `coleta_custo_por_mbit_util_hipotetico_pay_as_you_go` | 5,9596 | USD/Mbit |
| `local_execucoes` | 20 | runs |
| `local_t_mediana_s` | 0,324724 | s |
| `local_t_min_s` | 0,074158 | s |
| `local_t_max_s` | 0,384965 | s |
| `local_s_por_mbit_bruto` | 0,216468 | s/Mbit |
| `local_bits_por_s` | 4619610,2222 | bits/s |
| `local_bits_extraidos_mediana` | 1.354.932 | bits |
| `razao_s_por_mbit_qpu_sobre_os` | 15,40 | times |
| `criterio_limiar` | 10 | times |
| `criterio_muito_mais_caro` | True | boolean |

**Local times per run, in order (s):** 0,082213; 0,074158; 0,074319; 0,095391; 0,106602; 0,079099; 0,283410; 0,332715; 0,325059; 0,312211; 0,317399; 0,325880; 0,324388; 0,359362; 0,340648; 0,336673; 0,353267; 0,333450; 0,384965; 0,328416.

**Reading:**

- Pre-registered criterion (the ratio between QPU seconds per raw megabit and `os`'s CPU seconds per raw megabit, by the local median, equal to or greater than 10): ratio 15,40; the "much more expensive than `os`" hypothesis confirmed under this definition.
- The ratio at the extremes of the local times: 67,4236 with the fastest run and 12,9882 with the slowest, at or above the threshold on the slowest run.
- The local times form two non-overlapping groups, in execution order: runs 0 to 5 (6 runs, from 0,074158 to 0,106602 s) and 6 to 19 (14 runs, from 0,283410 to 0,384965 s); the smallest time in the second group is 2,6586 times the largest in the first. The pre-registered median falls in the slow group. Ratio with the fast group's median: 61,9917; with the slow group's: 15,1256. The cause of the difference was not investigated.
- None of the collection jobs had a batch approved by health: usable bits = 0, and the cost per usable megabit is undefined. There is no observed cost per usable megabit; only the cost per raw megabit.
- The seconds-per-shot fit gives a positive fixed cost per job and a marginal cost per megabit lower than the average cost per megabit of the collection jobs: bigger jobs come out cheaper per bit.
- If the batches had been approved, the hypothetical cost per usable megabit would be higher than the cost per raw megabit, because the extractor only makes use of part of the bits.

**Caveats:**

- The cost is theoretical. The Open Plan charges nothing; the paid plan's price was read on IBM's page on the consultation date recorded above and may change. No job was submitted for E3: it uses only the 8 jobs already run.
- The QPU seconds come from the API as whole values (2,0; 3,0; 5,0), and there are only 3 job sizes; the fixed- and marginal-cost fit is coarse and its uncertainty was not quantified.
- QPU time is billed execution time; local time is the wall-clock time of `os`'s whole pipeline (read, health, extraction, and mix). These are different resources and were not priced in the same currency: `os`'s dollar cost was not priced (CPU and energy are left out). QPU bits would still go through the same local processing.
- There is no measurement of queue latency or QPU wall-clock time: the log records the retrieval time, not the job's finish time.
- All jobs used a `rep_delay` of 0,00025 s. IBM's documentation records a temporary increase of the default to 4 ms; it was not checked whether this affects jobs that set the value, and the cost holds for the configuration used.
- The IBM dashboard's RUs were not used; the conversion between RUs and seconds remains pending (IBM_RU).
- The local benchmark is from a single machine and the speed fluctuated (see the per-run times); the criterion was assessed by the median, as pre-registered.
- The hypothetical usable bits use the project's extractor with each batch's estimated H. These batches were rejected by health, so they are not usable bits.

**CSVs (SHA-256 of the bytes on disk):**

- `e3_qpu.csv`: `7cb9aa0f916600cfebf8d1d5ed1be7e0c7e2a18ceefee3ce62b029663aca85da`
- `e3_local.csv`: `4861db25ed42880723ad9cf5d567d7dc88fd2db0b9fea1e70bdc859bcbb6b3b9`
- `e3_resumo.csv`: `8b3a0ef0abffa11b1d28c629cdb515d7976b859c594966c1b7c023088471ba8f`
<!-- dia7-e3:end -->

<!-- dia7-e5a:start -->
### E5 (step A), CHSH test without QPU (Day 7, record generated from the CSVs)

Generated by `scripts/registrar_e5.py` from `e5_rodadas.csv` and `e5_resumo.csv`. No number was typed by hand. The structural sentences are only recorded if confirmed by the CSVs; the per-configuration criteria and the noise effect are computed from the CSVs.

**Protocol (pre-registered):** run against commit `a467431cc9c8af0cec1414d41a083358e850bd70`, checked in the `commit` column of the 401 lines. Bell state Φ⁺ (H and CX) with an Ry(−θ) rotation before measurement on each side; Alice measures at 0 and π/2, Bob at π/4 and −π/4; E = P(same) − P(different); S = E(a0,b0) + E(a0,b1) + E(a1,b0) − E(a1,b1). 4000 shots per setting (16000 per S estimate) and 100 repetitions per sampled configuration, each with its own recorded seed. No QPU calls. Criteria margin: 3 standard errors of the repetitions' mean.

**Results per configuration:**

| Configuration | Expected | Repetitions | Mean S | Std. dev. | Mean std. error | Min S | Max S | Fraction S > 2 | Margin | Criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| `ideal_exato` | S = 2*sqrt(2) (exact) | 1 | 2,828427 | 0,000000 | 0,000000 | 2,828427 | 2,828427 | 1,0000 | 0,000000 | met |
| `ideal_amostrado` | compatible with 2*sqrt(2) | 100 | 2,828795 | 0,024325 | 0,022354 | 2,770000 | 2,884500 | 1,0000 | 0,007297 | met |
| `ruido_fake_kingston` | between 2 and 2*sqrt(2) (assistant's hypothesis) | 100 | 2,759055 | 0,024498 | 0,022892 | 2,700000 | 2,821000 | 1,0000 | 0,007349 | met |
| `classico_aleatorio` | S <= 2 | 100 | -0,000685 | 0,030991 | 0,031619 | -0,077500 | 0,093000 | 0,0000 | 0,009297 | met |
| `classico_otimo` | S <= 2 | 100 | 2,000000 | 0,000000 | 0,000000 | 2,000000 | 2,000000 | 0,0000 | 0,000000 | met |

**Physical pair for the simulated noise:** qubits 147-148 of `FakeKingston`; CZ error 0,0024336098672234907; mean readout error 0,005859375 and 0,002197265625; calibration 2026-04-15T09:15:15+02:00.

**Reading:**

- Pre-registered criteria met for: `ideal_exato`, `ideal_amostrado`, `ruido_fake_kingston`, `classico_aleatorio`, `classico_otimo`. No configuration failed to meet the criterion.
- Effect of the simulated noise: the mean S went from 2,828795 (sampled ideal) to 2,759055 (`ruido_fake_kingston`), a drop of 0,069740, 20,200762 standard errors of the difference between the means.
- Independent classical outputs: mean S -0,000685; compatible with 0 within the margin of 0,009297. The classical limit is 2 and the quantum maximum is 2√2.
- The circuit's exact S (state probabilities, no sampling) is 2√2, with a tolerance of 1e-12.
- The noise was simulated on a single physical pair, with the same CZ and readout errors, the same calibration date, and one two-qubit gate per circuit across all repetitions.
- The deterministic classical strategy gave S = 2 and a standard error of 0 in every repetition: the repetitions are identical by construction.
- The computed mean standard error matches the theoretical one within 5%: √(2/N) = 0,022361 for the Bell state and √(4/N) = 0,031623 for independent outputs, with N = 4000 shots per setting.
- The standard deviation of S across repetitions falls between 0,75 and 1,25 times the computed standard error in the three sampled configurations (with 100 repetitions, the sample standard deviation has a relative error of about 7%).

**Caveats:**

- The simulator is a classical generator (limitation 6): the S of 2√2 comes from computing the Bell state's probabilities, not from a quantum experiment.
- CHSH on a cloud QPU is not a loophole-free Bell test (limitation 5): the measurement settings are chosen by the experimenter and the two qubits sit on the same chip, with no separation. This is only a sanity check of the code and the analysis.
- The noise is the `FakeKingston` model (eal.sources.noise, asymmetric readout) with the calibration recorded on the simulated backend, on the date recorded above; it doesn't include crosstalk. A real QPU on another date may give a different S.
- The qubit pair came from the pre-registered rule (smallest sum of the CZ error and the mean readout error), and was not chosen by S.
- The two classical generators are references by construction: the deterministic strategy reaches the classical limit of 2, and the independent outputs give S near 0. They are not measurements of any device.
- The hypothesis that the real QPU falls between 2 and 2√2 was not tested: this is step A, without the QPU.
- The range 2 < S < 2√2 for the noisy simulator is the assistant's hypothesis; PROJECT.md only fixes that range for the real QPU.
- The run's timing varied relative to the previous measurement (see T_TEMPO); this doesn't affect the results, which are deterministic by each repetition's seed.

**CSVs (SHA-256 of the bytes on disk):**

- `e5_rodadas.csv`: `d782bf7dacff9197338e4641c94b201b829e497d40b2420cefb070b062507574`
- `e5_resumo.csv`: `4080372e87285858226bde56757f031de2d79afce0260d129fbde70825eaff2f`
<!-- dia7-e5a:end -->

<!-- dia7-consolidado:start -->
### Consolidated E1 to E5 for the dashboard (Day 7, record generated from the CSVs)

Generated by `scripts/registrar_consolidado.py` from `consolidado_gate.csv` and `consolidado_e1_e5.csv`, which `scripts/consolidar_dia7.py` assembled from the results CSVs in the run against commit `a00df75b11b5a25e2a9a4db288ea3f2a4f11326e` (`commit` column of the gate's 5 lines). No number was typed by hand. The record checks that both CSVs are the exact derivation of the source files, with each source's SHA-256; the sentences about drift, CHSH, usable cost, and the dashboard files are only recorded if confirmed by the CSVs.

**Day 7 gate (table with the 5 experiments):** E1 (partial), E2 (complete), E3 (complete), E4 (complete), E5 (partial); 2.091 lines in long format (experiment, key, metric, value, unit, state, source file, and source SHA-256).

| Experiment | State | Metrics | Source files | Caveat |
|---|---|---|---|---|
| E1 | partial | 1.201 | 12 | drift between days measured only against collection 1; collection 3 against collection 2 not done |
| E2 | complete | 532 | 1 | - |
| E3 | complete | 34 | 1 | theoretical cost, no spend (Open Plan) |
| E4 | complete | 274 | 1 | - |
| E5 | partial | 50 | 1 | step A only, without QPU; CHSH on the real QPU not done |

In the tables below, `-` marks an empty cell in the source CSV; the metrics backing the Reading sentences are mandatory, and if they are missing, the record is refused.

**E1, real QPU against simulator and `os` (3 collections) and drift:**

| Collection | Source | Batch | Approved | Estimated H | Pipeline | Extracted bits |
|---|---|---|---|---|---|---|
| 1 | qpu_real | 1 | no | 0,9623 | excluded | 0 |
| 1 | qpu_real | 2 | no | 0,9555 | excluded | 0 |
| 1 | simulador | 1 | no | 0,9592 | excluded | 0 |
| 1 | simulador | 2 | no | 0,9618 | excluded | 0 |
| 1 | os | 1 | yes | 0,9695 | mixed | 1.359.324 |
| 1 | os | 2 | yes | 0,9665 | mixed | 1.354.932 |
| 2 | qpu_real | 1 | no | 0,9598 | excluded | 0 |
| 2 | qpu_real | 2 | no | 0,9553 | excluded | 0 |
| 2 | simulador | 1 | no | 0,9592 | excluded | 0 |
| 2 | simulador | 2 | no | 0,9618 | excluded | 0 |
| 2 | os | 1 | yes | 0,9665 | mixed | 1.354.932 |
| 2 | os | 2 | yes | 0,9665 | mixed | 1.354.932 |
| 3 | qpu_real | 1 | no | 0,9606 | excluded | 0 |
| 3 | qpu_real | 2 | no | 0,9559 | excluded | 0 |
| 3 | simulador | 1 | no | 0,9592 | excluded | 0 |
| 3 | simulador | 2 | no | 0,9618 | excluded | 0 |
| 3 | os | 1 | yes | 0,9625 | mixed | 1.349.076 |
| 3 | os | 2 | yes | 0,9686 | mixed | 1.357.860 |

| Collection | Source | Fraction of 1 (batch 1) | Fraction of 1 (batch 2) | SD of zdiff | Qubits with |z| > 3 | |z| max |
|---|---|---|---|---|---|---|
| 1 | qpu_real | 0,4964 | 0,4980 | 1,145 | 3 | 4,36 |
| 1 | simulador | 0,5034 | 0,5037 | 0,999 | 0 | 2,77 |
| 1 | os | 0,5003 | 0,5007 | 1,036 | 0 | 2,64 |
| 2 | qpu_real | 0,5025 | 0,5011 | 1,133 | 2 | 7,36 |
| 2 | simulador | 0,5034 | 0,5037 | 0,999 | 0 | 2,77 |
| 2 | os | 0,5005 | 0,4999 | 0,997 | 0 | 2,91 |
| 3 | qpu_real | 0,5028 | 0,5048 | 1,089 | 1 | 3,20 |
| 3 | simulador | 0,5034 | 0,5037 | 0,999 | 0 | 2,77 |
| 3 | os | 0,5005 | 0,4998 | 0,973 | 0 | 2,78 |

| Comparison | Batch A | Batch B | Mean zdiff | SD of zdiff | Qubits with |z| > 3 | |z| max |
|---|---|---|---|---|---|---|
| mesmo_dia | cal_001 | cal_002 | -0,011 | 1,447 | 6 | 6,05 |
| mesmo_dia | cal_001 | coleta1_001 | 0,046 | 1,615 | 5 | 10,33 |
| mesmo_dia | cal_001 | coleta1_002 | -0,048 | 1,567 | 6 | 8,90 |
| mesmo_dia | cal_002 | coleta1_001 | 0,097 | 1,264 | 2 | 6,76 |
| mesmo_dia | cal_002 | coleta1_002 | -0,066 | 1,129 | 2 | 4,37 |
| mesmo_dia | coleta1_001 | coleta1_002 | -0,212 | 1,145 | 3 | 4,36 |
| coleta2_vs_coleta1 | coleta1_001 | coleta1_002 | -0,212 | 1,145 | 3 | 4,36 |
| coleta2_vs_coleta1 | coleta1_001 | coleta2_001 | -0,845 | 3,274 | 12 | 22,60 |
| coleta2_vs_coleta1 | coleta1_001 | coleta2_002 | -0,649 | 3,377 | 9 | 25,89 |
| coleta2_vs_coleta1 | coleta1_002 | coleta2_001 | -0,633 | 3,111 | 10 | 23,80 |
| coleta2_vs_coleta1 | coleta1_002 | coleta2_002 | -0,437 | 3,313 | 11 | 27,09 |
| coleta2_vs_coleta1 | coleta2_001 | coleta2_002 | 0,196 | 1,133 | 2 | 7,36 |
| coleta3_vs_coleta1 | coleta1_001 | coleta1_002 | -0,212 | 1,145 | 3 | 4,36 |
| coleta3_vs_coleta1 | coleta1_001 | coleta3_001 | -0,882 | 3,063 | 12 | 21,91 |
| coleta3_vs_coleta1 | coleta1_001 | coleta3_002 | -1,171 | 3,067 | 14 | 22,21 |
| coleta3_vs_coleta1 | coleta1_002 | coleta3_001 | -0,670 | 2,965 | 11 | 19,73 |
| coleta3_vs_coleta1 | coleta1_002 | coleta3_002 | -0,959 | 2,983 | 11 | 19,17 |
| coleta3_vs_coleta1 | coleta3_001 | coleta3_002 | -0,288 | 1,089 | 1 | 3,20 |

**E2, attacks (detection and false positive):**

| Source | Parameter | Type | Bits | Reading | Batches | Rejected | Rate |
|---|---|---|---|---|---|---|---|
| faulty_biased | p=0.501 | deteccao | 1.000.000 | 1 | 200 | 60 | 0,3000 |
| faulty_biased | p=0.502 | deteccao | 1.000.000 | 1 | 200 | 185 | 0,9250 |
| faulty_biased | p=0.505 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_biased | p=0.51 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_biased | p=0.55 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_correlated | rho=0.501 | deteccao | 1.000.000 | 1 | 200 | 64 | 0,3200 |
| faulty_correlated | rho=0.502 | deteccao | 1.000.000 | 1 | 200 | 184 | 0,9200 |
| faulty_correlated | rho=0.505 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_correlated | rho=0.51 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_correlated | rho=0.6 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_stuck | run_length=8 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_stuck | run_length=16 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_stuck | run_length=24 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_stuck | run_length=32 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_stuck | run_length=64 | deteccao | 1.000.000 | 1 | 200 | 200 | 1,0000 |
| faulty_prng | - | deteccao | 1.000.000 | 1 | 200 | 6 | 0,0300 |
| faulty_replay | - | referencia | 1.000.000 | 1 | 200 | 4 | 0,0200 |
| faulty_replay | - | deteccao | 1.000.000 | 2 | 200 | 200 | 1,0000 |
| os | - | falso_positivo | 1.000.000 | 1 | 2000 | 52 | 0,0260 |
| faulty_biased | p=0.501 | deteccao | 4.000.000 | 1 | 100 | 95 | 0,9500 |
| faulty_biased | p=0.502 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_biased | p=0.505 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_biased | p=0.51 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_biased | p=0.55 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_correlated | rho=0.501 | deteccao | 4.000.000 | 1 | 100 | 89 | 0,8900 |
| faulty_correlated | rho=0.502 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_correlated | rho=0.505 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_correlated | rho=0.51 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_correlated | rho=0.6 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_stuck | run_length=8 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_stuck | run_length=16 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_stuck | run_length=24 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_stuck | run_length=32 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_stuck | run_length=64 | deteccao | 4.000.000 | 1 | 100 | 100 | 1,0000 |
| faulty_prng | - | deteccao | 4.000.000 | 1 | 100 | 4 | 0,0400 |
| faulty_replay | - | referencia | 4.000.000 | 1 | 100 | 0 | 0,0000 |
| faulty_replay | - | deteccao | 4.000.000 | 2 | 100 | 100 | 1,0000 |
| os | - | falso_positivo | 4.000.000 | 1 | 500 | 18 | 0,0360 |

**E3, throughput and cost (theoretical cost):**

| Metric | Value | Unit |
|---|---|---|
| qpu_jobs | 8 | jobs |
| qpu_segundos | 35,0 | s |
| qpu_bits_brutos | 9.780.576 | bits |
| coleta_bits_por_s | 300.019,2000 | bits/s |
| coleta_custo_por_mbit_bruto_pay_as_you_go | 5,3330 | USD/Mbit |
| coleta_lotes_aprovados | 0 | batches |
| coleta_bits_uteis | 0 | bits |
| coleta_custo_por_mbit_util_pay_as_you_go | undefined | USD/Mbit |
| local_bits_por_s | 4.619.610,2222 | bits/s |
| razao_s_por_mbit_qpu_sobre_os | 15,40 | times |
| criterio_limiar | 10 | times |
| criterio_muito_mais_caro | yes | boolean |

**E4, mix resilience:**

| Scenario | Combiner | k | Expected | Sequences | Complete | Approved | Approval rate | Target fraction |
|---|---|---|---|---|---|---|---|---|
| base_boa | hash | - | segura | 100 | 100 | 97 | 0,9700 | - |
| base_boa | xor | - | segura | 100 | 100 | 94 | 0,9400 | - |
| enviesada | hash | - | segura | 100 | 100 | 97 | 0,9700 | - |
| enviesada | xor | - | segura | 100 | 100 | 98 | 0,9800 | - |
| travada | hash | - | segura | 100 | 100 | 99 | 0,9900 | - |
| travada | xor | - | segura | 100 | 100 | 98 | 0,9800 | - |
| constante | hash | - | segura | 100 | 100 | 98 | 0,9800 | - |
| constante | xor | - | segura | 100 | 100 | 95 | 0,9500 | - |
| copia | hash | - | sem_semente | 100 | 0 | 0 | - | - |
| copia | xor | - | insegura | 100 | 100 | 0 | 0,0000 | - |
| adv_alvo | hash | - | segura | 100 | 100 | 97 | 0,9700 | 0,0000 |
| adv_alvo | xor | - | insegura | 100 | 100 | 97 | 0,9700 | 1,0000 |
| sem_fonte_boa | hash | - | insegura | 100 | 100 | 0 | 0,0000 | - |
| sem_fonte_boa | xor | - | insegura | 100 | 100 | 0 | 0,0000 | - |
| adv_forca | hash | 1 | k_bits | 10 | 10 | 8 | 0,8000 | 1,0000 |
| adv_forca | hash | 4 | k_bits | 10 | 10 | 0 | 0,0000 | 1,0000 |
| adv_forca | hash | 8 | k_bits | 10 | 10 | 0 | 0,0000 | 1,0000 |
| adv_forca | hash | 12 | k_bits | 10 | 10 | 0 | 0,0000 | 1,0000 |

**E5, CHSH step A (without QPU):**

| Configuration | Expected | Repetitions | Mean S | SD of S | Criterion |
|---|---|---|---|---|---|
| ideal_exato | S = 2*sqrt(2) (exact) | 1 | 2,828427 | 0,000000 | yes |
| ideal_amostrado | compatible with 2*sqrt(2) | 100 | 2,828795 | 0,024325 | yes |
| ruido_fake_kingston | between 2 and 2*sqrt(2) (assistant's hypothesis) | 100 | 2,759055 | 0,024498 | yes |
| classico_aleatorio | S <= 2 | 100 | -0,000685 | 0,030991 | yes |
| classico_otimo | S <= 2 | 100 | 2,000000 | 0,000000 | yes |

**Reading (counts computed from the CSVs):**

- Batches approved by the health tests (the 3 collections combined): `qpu_real` 0 of 6; `simulador` 0 of 6; `os` 6 of 6.
- False positive on the `os` source: 52 of 2000 batches at 1.000.000 bits (0,0260); 18 of 500 batches at 4.000.000 bits (0,0360).
- The real QPU's cost per usable Mbit is undefined: 0 batches approved in the collection.
- Pre-registered criterion met in 5 of 5 configurations.

**Caveats (drift, CHSH, usable cost, and dashboard files checked against the CSVs before recording; "no spend" and T_TEMPO come from a decision and a limitation already recorded, not from the CSVs):**

- E1: drift between days was measured only against collection 1; collection 3 against collection 2 was not done (every comparison between different sessions involves a collection-1 batch, and none compares collection 2 with collection 3).
- E5: only step A, with the 5 configurations without the real QPU; CHSH on the real QPU was not done, and the hypothesis that the real QPU falls between 2 and 2√2 was not tested.
- E3: theoretical cost on the Open Plan, no spend; the measured times depend on the machine's speed (T_TEMPO).
- The consolidated record does not carry bias per qubit or the readout excess; the dashboard reads the `dia6_*_por_qubit.csv` and `dia6_*_excesso_leitura.csv` files from the 3 collections directly (the 6 files exist in `data/results`).

**Origins (SHA-256 of the bytes on disk, as recorded in the consolidated file):**

- `dia6_qpu_vs_sim_resumo.csv`: `dd6f7375d0947e8cd0030eddf9552330468964dcbee860d51a1a47e4790ef7ba`
- `dia6_coleta2_qpu_vs_sim_resumo.csv`: `d0af195608cac1e2fbb274110b3a5e2e05cb487d6f7c0f4793586f56c2b1abf7`
- `dia6_coleta3_qpu_vs_sim_resumo.csv`: `76ac3049a647f478beee1c0ab8b11bbf7ae0be570990978bf76367601b4f978a`
- `dia6_qpu_vs_sim_lotes.csv`: `5023a1a6df5473f2be955d66681d732127f6d29714424d0060b9b13cefbb6e14`
- `dia6_coleta2_qpu_vs_sim_lotes.csv`: `0a30e43ae33ad62b8cbef7cea034beb3c0199c95beebab3ba3a23c7e36930edf`
- `dia6_coleta3_qpu_vs_sim_lotes.csv`: `f7e6619f21370f48273dafeb96efa6206471dbf8f4037bb81723f7058a29c13f`
- `dia6_deriva_dia_estabilidade.csv`: `0051ad524090bf8a20563f2bce7118aabb03feb58693869d10a38f12de9638e2`
- `dia6_deriva_coleta2_estabilidade.csv`: `efdba5aedc83b95ba23a88135415facadd3a2f5697fb5537b62270d813fc5b99`
- `dia6_deriva_coleta3_estabilidade.csv`: `1c8009100de560e6c6a4e98c14e93459263294690cb3687d6a4670e0914518a8`
- `dia6_deriva_dia_conjunto_fixo.csv`: `543627875f9bfa2c64d0c642ab338b6e9375e25e391b26d008836f439ad63e9e`
- `dia6_deriva_coleta2_conjunto_fixo.csv`: `6f823feef65d7b593a99f4e723f5a0150e88beaedbb93bd4475b0f09c74a4032`
- `dia6_deriva_coleta3_conjunto_fixo.csv`: `aa5c3fbc07a5720c2922993134f52e7661575fdbab9429ecff2fcb5d88c12887`
- `e2_resumo.csv`: `2fd202e9b3cc0dccf1dd52a6212de0f6296fb6d3e067ddff68a92e1a0de62a0c`
- `e3_resumo.csv`: `8b3a0ef0abffa11b1d28c629cdb515d7976b859c594966c1b7c023088471ba8f`
- `e4_resumo.csv`: `aae9bf5c306c5be64dab60c13108804aae4754af55e6cbb600d0434281b4da5a`
- `e5_resumo.csv`: `4080372e87285858226bde56757f031de2d79afce0260d129fbde70825eaff2f`

**CSVs generated (SHA-256 of the bytes on disk):**

- `consolidado_e1_e5.csv`: `8c143a3e9ca7d232ec3eeb5b719fd2b17969c77dc5697dcad67a600c9d4d889e`
- `consolidado_gate.csv`: `dd3940b3b9793c11b5f14bc58dd7102ccd9331cedd385157e8a5925effe0a0d6`
<!-- dia7-consolidado:end -->

---

## 21. Day 8 and Day 9: dashboard, report, and delivery (record)

**Dashboard (`dashboard/`).** `data.py` (loading and validation, without Streamlit, tested) and `app.py` (one page: sources, health per batch, min-entropy, bias per qubit with drift, latest receipt with a verify button, E1 to E5). It reads only `data/results` and the receipts. On a clean clone there is no real chain, and it uses `demo/`, warning on screen. `streamlit==1.66.1` and `pandas==3.1.1` pinned. Dashboard gate: the server comes up (HTTP 200), the app runs without an exception on real data (tested with `AppTest`), and receipt verification passes on the real chain and rejects a tampered copy.

**Report (`relatorio/RELATORIO.md`, 7 figures).** Generated by `scripts/gerar_relatorio.py` from the CSVs; the uncertainty ranges come from `scripts/incerteza_dia8.py` (`data/results/dia8_incerteza.csv`). The generator refuses to write a sentence if the CSVs no longer support it. All 5 experiments are in the report.

**Critical review (two passes).** One against the uncertainty ranges, and another from an independent reviewer, who received the report and the CSVs without the first pass's list. Fixed in the report and the dashboard:

- E3: the QPU/os ratio is one of **time**, and the threshold of 10 falls within the range (the marginal cost alone is 10,37 and the mean on the slowest local machine is 12,99, both above 10; only the marginal cost together with the slowest local machine falls below 10, at 8,75); the uncertainty of the marginal fit was not measured.
- Simulator: only 2 distinct batches (fixed seed) appear across the 3 collections; the count became 0 of 2.
- The QPU's rejection is by monobit; runs rejects on a pre-requisite; min-entropy and block frequency approve. "No batch passed" describes the batch size and the chosen gate, not the QPU's quality.
- Estimated H: the absolute value is the estimator's (`os` also comes out below 1); the exact 6-against-6 p is only a hint (batches not independent).
- Drift: collections 1 and 2 are from the same day, so the comparison is "between collections" and not "between days"; the zdiff's SD already exceeds 1 within the same day; the bootstrap CIs are descriptive; the concentration in a few qubits is conjecture.
- E4: no evidence of a difference in approval between hash and XOR (n = 100 per arm); "no seed on target" for hash holds by construction; the hash does not protect against someone testing candidates (k bits with 2^k attempts).
- E5: a check of the code, not evidence about the QPU or about randomness.
- Language: "approved" means the absence of a visible defect in the output; the signature guarantees integrity and order; the extraction guarantee depends on the H estimate and on the independence of the bits.

**Delivery (Day 9).** `README.md`, `docs/ONE_PAGER.md`, `docs/ROADMAP.md`, and `demo/` (3 chained receipts made by the CLI with an issuer key belonging only to the demo; only the public key was published; `demo/**/*.sk` is in `.gitignore`). Secrets sweep before delivery: no `.env`, private key, or token in versioned files or in the Git history.

**Declared pending items.** FastAPI (optional) was not done. The 3-to-5-minute recorded demo depends on the author. The one-pager's market and competitor data come from section 3 of this brief and were not revalidated. The license is resolved: MIT (`LICENSE`, Copyright 2026 Bruno Pascual, cited in `README.md`). E1 remains partial (collection 3 against collection 2) and E5, only at step A.
