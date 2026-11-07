# Roadmap after the 9 days

Starting state: a research prototype in Python, with `os`, simulator, and IBM QPU sources; health tests; a Toeplitz extractor; a fail-closed SHA3-512 mixer; ML-KEM-768 and ML-DSA-65 derivation; a signed, chained receipt; a dashboard and a report. **None of the below is done.** The order reflects what reduces the most risk per effort, and the duration estimates are guesses to be revised.

## 1. Closing what was left partial (weeks)

- **E1:** compare collection 3 against collection 2 and investigate the drift (few qubits? a calibration change?). More collections on another backend and on other days; with 3 collections over 2 days there is no way to talk about "QPUs" in general.
- **E5:** CHSH on the real QPU (stage B), with the qubit pair chosen by a rule fixed before the collection. This remains a sanity check, not a certification.
- **Estimators:** implement the full SP 800-90B set (today there are only the two "most common value" estimators) and handle non-independent bits. The current estimator assumes independence, and the receipts' extraction guarantee depends on it.
- **Experiment power:** E4 with more sequences per cell (the `adv_forca` cells have 10) and E3 with more job sizes to fit the marginal cost.

## 2. Local QRNG chip (a few months)

- An adapter for a real QRNG chip or module (for example, over USB or SPI) implementing the contract in `eal/sources/base.py`; the continuous health tests (RCT and APT) run over the chip's stream.
- Choose the chip after reading the vendor's certification documentation, not before. Measure bias, correlation, and drift by temperature and by chip batch, as was done with the QPU.
- Mixing policy: the local hardware source becomes first-class; the cloud QPU stays as an additional source, never the only one.

## 3. Porting to C or Rust (a few months)

- Core (health tests, extractor, mixer, derivation) in C or Rust, with **audited, constant-time PQC libraries** in place of `kyber-py` and `dilithium-py`.
- Keep Python as the analysis layer. Reuse the 3,200 tests and the known-answer test vectors (KAT) as the port's conformance suite.
- Manage the issuer's key outside the disk in plain text (today it sits unencrypted in `keys/`).

## 4. Certification (one to two years, depends on partners)

- Decide on the target: SP 800-90B (entropy source) and FIPS 140-3 (cryptographic module). This requires an accredited lab, a module with a defined boundary, and formal documentation; none of that exists today.
- Before spending on this, validate with potential customers whether the per-key receipt is what they ask for, or whether they want only the testing layer.
- While there is no certification, keep the language of `THREAT_MODEL.md`: no claim of conformance and no claim of quantum origin.

## 5. Product, if the problem is confirmed

- API (FastAPI) to request a seed and a receipt, and public receipt verification. Cut from the 9-day schedule.
- A chain-verification service and periodic publication of the chain's head outside the log (verification already accepts an expected head).
- Integration with key managers and with HSMs.

## Risks the roadmap needs to watch

- The QPU provider knows the bits it generated; that is why the QPU is never the only source of a seed.
- Testing the output does not detect a disguised pseudorandom generator: trust in the source also has to come from the physical design and the supply chain.
- Competitors with formal validation already exist; the EAL's space is the neutral layer of evidence, not the source.
