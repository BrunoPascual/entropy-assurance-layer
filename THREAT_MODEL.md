# Entropy Assurance Layer (EAL) — Threat model

- **Document version:** 1.3
- **Date:** 27/10/2026 (v1.0); revised on 31/10/2026 (v1.1, v1.2 and v1.3)
- **Author:** Bruno Pascual
- **Sibling document:** `PROJECT.md`

> This document states **who can attack**, **what EAL guarantees** and, with the same weight, **what it does not guarantee**.
> Every claim in the results, the dashboard, the report and the one-pager must fit within the guarantees in section 6.

---

## 1. Scope

The model covers the EAL prototype running on the author's machine (Windows 11, Python 3.12), using:

- the operating system's local source (`os`);
- the QPU simulator (`qpu_sim`, Qiskit Aer);
- IBM's real QPU via the cloud (`ibm_<backend>`, Open Plan);
- the simulated faulty sources (`faulty_*`), used only in tests and experiments.

The model **does not** cover use in production, multiple users, public servers, or embedded devices.

---

## 2. Assets

| ID | Asset | Why it matters | Where it lives |
| --- | --- | --- | --- |
| AT1 | 64-byte seed | Whoever knows it reconstructs all derived keys | In memory only |
| AT2 | Derived private keys (ML-KEM-768, ML-DSA-65) | Decrypt or sign on behalf of the owner | In memory only (except `--export-demo`) |
| AT3 | Receipt issuer's private key | Allows forging receipts | `keys/*.sk`, outside Git |
| AT4 | Receipt integrity | This is the product's audit evidence. The chain head is printed by `run`, but the prototype does not store it anywhere | `data/receipts/` (receipts and `chain.jsonl`); `data/logs/eal_runs.jsonl` records CLI failures and carries no seed or private keys |
| AT5 | Integrity of raw data and results | Experiments depend on them | `data/raw/`, `data/results/` |
| AT6 | IBM token | Consumes the budget and accesses the account | `.env`, outside Git |
| AT7 | QPU budget | Scarce resource (about 10 min per 28 days) | IBM account |

---

## 3. Trust boundaries

```
┌───────────────────────── Local machine (trusted) ─────────────────────────┐
│  os source  →  tests  →  extractor  →  mixer  →  keys  →  receipt         │
│                  ▲                                                        │
│                  │ bits from the QPU (untrusted data)                     │
└──────────────────┼────────────────────────────────────────────────────────┘
                  │  TLS (qiskit-ibm-runtime SDK)
┌──────────────────┴────────── IBM cloud (untrusted for secrecy) ───────────┐
│  job queue  →  QPU (ibm_kingston etc.)  →  results                        │
└───────────────────────────────────────────────────────────────────────────┘

Third-party libraries (qiskit, numpy, scipy, pure-Python PQC): trusted, not audited.
```

**Central rule:** everything that comes from the cloud is treated as **untrusted data**. The QPU bits go through the same tests as any source and are **never** the sole origin of a seed.

---

## 4. Adversaries

| ID | Adversary | Capability | Goal | In scope? |
| --- | --- | --- | --- | --- |
| ADV1 | Faulty source (no malicious intent) | Bias, stuck bits, correlation, drift from noise or calibration | — (accidental failure) | **Yes** |
| ADV2 | Curious cloud provider | Sees all the bits the QPU generated | Learn the seed | **Yes** |
| ADV3 | Malicious provider or intermediary | Returns chosen bits: a classical generator in disguise, replay, fabricated bits | Make the seed predictable | **Partial** |
| ADV4 | Network observer | Reads or alters traffic | Read or swap QPU bits | **Yes**, mitigated by the SDK's TLS |
| ADV5 | Receipt forger | Edits or creates receipts | Forge audit evidence | **Yes** |
| ADV6 | Adaptive adversarial source | Controls one source and sees the outputs of the others | Cancel the entropy in the mix | **Yes** (E4) |
| ADV7 | Attacker with host access | Malware, administrator, memory reading | Steal seed, keys, token | **No** |
| ADV8 | Supply chain | Malicious or compromised pip package | Anything | **No** (minimal mitigation: pinned versions) |
| ADV9 | Future quantum computer | Shor's algorithm | Break RSA and ECC | **Yes**, for keys and receipt signature (hence PQC) |
| ADV10 | Misuse by the author | Treating the simulator as real entropy, overstating results | — (human error) | **Yes** |

---

## 5. Threats and mitigations

| ID | Threat | Adversary | Mitigation | How it is tested | Residual risk |
| --- | --- | --- | --- | --- | --- |
| T1 | Bias or correlation in the source | ADV1 | APT, MCV estimator per bit and per byte, extractor sized by the estimated entropy | E1, E2, unit tests | Low for gross bias; medium for subtle correlations |
| T2 | Stuck bits | ADV1 | RCT | E2, tests with a known sequence | Low |
| T3 | Batch or block replay | ADV3 | Hash of each batch and of 4096-bit blocks; the history is kept in `data/logs/replay_history.json` and loaded before any source read, so it rejects repetition within one run and across runs (F12, Day 6) | E2; F12 tests | Low for exact replay; **deleting or swapping the history file resets the protection with no alarm**; high for transformed replay; replay shifted outside a 4096-bit block is not detected |
| T4 | Classical generator disguised as a QPU | ADV3 | Not detectable by output tests. Structural mitigation: a local source is mandatory in the mix; CHSH as a sanity check (done only in simulation, with no QPU run, so it says nothing about the real QPU) | E2, E5 | **High**, declared as a limitation |
| T5 | Provider knows the bits | ADV2 | Policy: ≥ 1 approved, non-simulated local source in every seed | Policy test in the mixer | Low, if the host is intact |
| T6 | Adaptive source cancels the mix | ADV6 | Combination via SHA3-512 with domain separation (not XOR) | E4 | Low, under assumption P2 |
| T7 | Source drift over time | ADV1 | Continuous tests on every batch; comparison across sessions | E1 | Medium |
| T8 | Overestimating entropy | ADV1, ADV10 | At least two estimators; 128-bit margin in the extractor; never claim SP 800-90B compliance | Review, optional comparison with the NIST tool | Medium |
| T9 | Receipt altered, forged, or removed from the end of the chain | ADV5 | ML-DSA-65 signature over canonical JSON; hash chain; `eal verify`; for removal from the end, the chain head is kept outside the log and passed via `--expected-head` (the prototype does not yet store it) | Tampering tests; 31/10/2026 demo, steps 8 and 9 | Low for alteration, if the issuer's key is protected; **high for removal of the last receipts without a head stored outside the log** |
| T10 | Leakage of the seed or keys | ADV10 | In memory only; receipt with hashes only; `print` forbidden; test that scans outputs for secrets | Automated test | Low (high if ADV7) |
| T11 | Leakage of the IBM token | ADV10 | `.env` in `.gitignore`; never paste into chat; rotate if exposed | Check before every commit | Low |
| T12 | QPU budget overrun | ADV10 | Hard limit in `qpu_ibm.py`; per-job usage log | Limit test with simulated values | Low |
| T13 | Simulator used as real entropy | ADV10 | `is_simulated` flag; policy excludes simulated sources in `keygen` mode | Policy test | Low |
| T14 | Failure of all sources | ADV1 | Fail-closed: no seed, no keys, error logged | Policy test | None (the system just stops) |
| T15 | Bugs or side channels in the PQC libraries | ADV8 | Declared as prototype use; round-trip tests; pinned versions | Unit tests | **High** outside the prototype |
| T16 | IBM unavailability or long queue | — | Pipeline works with local sources alone; experiments can use already-collected data | Run without network | Low for the pipeline; medium for the experiments |

---

## 6. What EAL guarantees

Each guarantee holds **only** under the assumptions in section 8.

| ID | Guarantee | Condition |
| --- | --- | --- |
| G1 | Gross source failures (stuck bits, bias persisting above the threshold, batch repetition) are detected per batch, with a false-alarm rate of `α = 2^-40` per sample in the RCT and `α = 2^-20` per window in the APT (about 5 × 10^-7 and 8 × 10^-4 per batch of 1 million bits), by the test's design | Declared entropy `H` correct for the source |
| G2 | **Fail-closed:** without at least one approved, non-simulated local source, no seed and no key are generated | Mixer policy unchanged |
| G3 | **Conditional on P1 to P3** (not an unconditional guarantee): if the host is intact, the combined sources are independent and SHA3-512 behaves as an ideal function, and `os` is cryptographically strong, then the seed should be unpredictable to anyone who does not know the approved local source's output, **including the QPU provider**. If any of the three fails, nothing is guaranteed | P1, P2, P3 |
| G4 | Every receipt is signed with ML-DSA-65 and chained to the previous one; alteration of a receipt or of the middle of the chain is detected by `eal verify`. Removal of the last receipts is only detected if the verifier holds the chain head stored outside the log (`--expected-head`); without it, a chain missing its end still verifies as valid (see N13) | Issuer key not compromised; for removal from the end, head stored outside the log |
| G5 | Receipts contain no secrets, only hashes | Code matches `PROJECT.md` |
| G6 | Every seed has recorded provenance: sources, versions, job IDs, test results, estimates, and extractor parameters | — |
| G7 | QPU consumption never exceeds the configured budget | Every submission goes through `qpu_ibm.py` |
| G8 | Receipt signatures and derived keys use standardized post-quantum algorithms (FIPS 203 and 204) | Correct libraries |

---

## 7. What EAL does not guarantee

| ID | Does not guarantee | Why |
| --- | --- | --- |
| N1 | That the bits have **quantum origin** | On a cloud QPU you do not control the device; the CHSH in this scenario is not a loophole-free Bell test |
| N2 | Detecting a well-made pseudorandom generator or an adversarial source that passes the tests | Output tests do not distinguish a good classical generator from a genuine source |
| N3 | Compliance with NIST SP 800-90B, FIPS 140-3, or any certification | Simplified estimators and no formal validation |
| N4 | Protection against a compromised host | Malware or an administrator reads memory, keys, and token |
| N5 | PQC implementations safe for production | Pure Python: not constant-time, not audited |
| N6 | Protection of classical cryptography (RSA, ECC) against Shor | EAL improves key quality; it does not replace migrating to PQC |
| N7 | That IBM does not see the QPU bits | It generates and transmits the results |
| N8 | That entropy estimates are exact | They are statistical estimates with a confidence interval, not proofs |
| N9 | Availability | Depends on the queue, IBM maintenance, and budget |
| N10 | That the simulator is a source of entropy | Aer uses a classical pseudorandom generator |
| N11 | Protection of the issuer key on disk | Local file, no HSM, no encryption |
| N12 | Resistance to physical or side-channel attacks | Outside the prototype's scope |
| N13 | Detecting removal of the last receipts of the chain without a head stored outside the log | A log missing its end is still a valid chain; the prototype prints the head on `run` but does not store it |
| N14 | Detecting batch replay between `eal run` executions when the history file is deleted, swapped, or rebuilt | The history (`data/logs/replay_history.json`, F12) is a local file: anyone with disk access can delete or rebuild it, and the `state_hash` detects only accidental corruption; there is no lock for concurrent runs; deleting it resets the protection with no alarm |

---

## 8. Assumptions

| ID | Assumption |
| --- | --- |
| P1 | The local host is intact during execution (no malware, no third-party access) |
| P2 | The combined sources are independent of each other, and SHA3-512 behaves as an ideal random function for the mix |
| P3 | Windows's `os` source (`os.urandom` / `secrets`) provides cryptographically strong randomness |
| P4 | The Toeplitz extractor's seed is uniform and independent of the extracted source (drawn from the `os` source) |
| P5 | The TLS used by the IBM SDK protects the integrity of results in transit |
| P6 | The libraries (qiskit, numpy, scipy, PQC) do what they document at the versions pinned in `requirements.txt` |
| P7 | The entropy `H` used in the test thresholds is a conservative estimate for each source |

If an assumption falls, the guarantees that depend on it fall with it, and this must be stated in the report.

---

## 9. How to communicate results

**Can say:**

- "measured", "estimated", "observed", "detected in X% of the simulated cases";
- "the real QPU showed bias of X on qubit Y in this session";
- "sanity check" (for CHSH);
- "research prototype".

**Cannot say:**

- "certified", "proven", "validated by NIST", "SP 800-90B compliant";
- "guaranteed quantum randomness", "unbreakable", "100% secure";
- "production-ready";
- "protects against quantum computers" without explaining that this holds for the PQC keys, not for the entropy source.

**Every relevant limitation appears:** in the report, in the README, in the one-pager, and in the `limitations` field of each receipt.

---

## 10. Main residual risks

1. **T4 (disguised generator):** this is the product's fundamental limit. The defense is structural (mandatory local source), not statistical. It is also E2's most important finding.
2. **T15 (PQC libraries):** acceptable in the prototype; blocks any real use.
3. **T8 (overestimated entropy):** mitigated by margins, but only a formal assessment would resolve it.
4. **ADV7 (compromised host):** out of scope; in production this would require an HSM, enclave, or dedicated chip.

---

## 11. When to revise this document

- When adding a new source (another provider, a local QRNG chip).
- When changing the mixer policy or the extractor.
- When swapping the PQC library.
- If an experiment contradicts a hypothesis or a guarantee.
- Before any use outside the prototype.

<!-- revisao-v11:start -->
## 12. Revision history

### v1.1 (31/10/2026)

**Reason.** An experiment contradicted a guarantee (section 11, fourth item). In the 31/10/2026 end-to-end demo (`scripts/demo_dia5.py`, steps 8 and 9), a log with the last receipt deleted still verified as valid under `eal verify`, and only the chain head noted beforehand (`--expected-head`) rejected it. This contradicts v1.0's wording of G4 ("any alteration is detected").

**What changed.** G4 rewritten; T9 given a separate residual risk; N13 created; AT4 updated; version and date in the header.

**What did not change.** Adversaries, assumptions, G1 through G3, G5 through G8, and the other non-guarantees. No Day 5 result contradicted them. The CLI and chain code had not yet gone through Day 5 closing's adversarial review, and this revision of the model does not cover it.
<!-- revisao-v11:end -->

<!-- revisao-v12:start -->
### v1.2 (31/10/2026)

**Reason.** The adversarial code review (parts 2 and 3) showed that the replay detector keeps its history only in memory and starts empty on every `eal run` (already recorded in PROJECT.md, section 17, Day 3 limitations). v1.1's T3 said "low for exact replay," which only holds within a single run.

**What changed.** T3 given separate mitigation and residual risk; N14 created; version and date in the header.

**What did not change.** Adversaries, assumptions, and the other guarantees and non-guarantees. Persistence of the detector's history was not implemented: it is a pending item before the IBM source (Day 6).
<!-- revisao-v12:end -->
<!-- revisao-v13:start -->
### v1.3 (31/10/2026)

**Reason.** F12 from the Day 5 adversarial review: the replay detector started empty on every `eal run`, so an old batch returned on a later run went unnoticed. It was a pending item before the IBM source (Day 6).

**What changed.** T3: the history is now kept in `data/logs/replay_history.json` and loaded before any source read; the write happens before any receipt; a read or write failure rejects the run (fail-closed). N14 rewritten: the non-guarantee is now the file being deleted, swapped, or rebuilt, and the residual risk is stated separately. Version and date in the header.

**What did not change.** Adversaries, assumptions, and the other guarantees and non-guarantees. Transformed replay and shifted replay remain outside the detector's reach. Batches from runs prior to commit `e4b9f1d` are not in the history.
<!-- revisao-v13:end -->

## Day 6 annex: execution observations (does not change the document version)
Observed: IBM's calibration changed between a job's submission and its execution (07:36 to 11:09), with no change in the measured readout error. The risk of drift between submission and execution is still not fully covered: the snapshot recorded at submission may not represent the execution. Current mitigation: the inspector compares the two. Planned, not implemented, mitigation: also record the execution snapshot in the batch.
Observed: dry-run unavailable on the Open Plan for ibm_kingston. Does not affect budget guarding, which does not depend on dry-run; only the prior server-side validation is lost.
Observed: IBM returns usage in both `qpu_charge_time_seconds` and in `usage()`; the code reads the other key first. No security effect today (the values match), but it is a contract flaw to fix.
Confirmed: the dry-run failure message no longer says 'uncertain result' (commit ab11bc5); the real-submission text was kept.
