# Entropy Assurance Layer: one-pager

*9-day research prototype (Bruno Pascual, November 2026). Not a product and not certified.*

## Problem

Every cryptographic key is born from random numbers. Historical randomness failures have come from **the source or the seeding**, not from the algorithm: the OpenSSL bug in Debian (2008), repeated RSA keys in network devices (2012), the Dual_EC_DRBG generator under suspicion of a backdoor. Security teams can rarely **show** where a key's randomness came from and that it was tested, and audits (FIPS 140-3, NIST SP 800-90B) ask for that evidence. The migration to post-quantum cryptography does not solve this: ML-KEM and ML-DSA also consume randomness.

## Solution

A software layer that is **neutral with respect to the source**:

1. accepts bits through an adapter; the sources actually tested here are the operating system (`os`), a QPU simulator (`qpu_sim`), a real IBM QPU (`ibm_*`), and simulated faulty sources (`faulty_*`); a chip is future work, and the scope is the one in [THREAT_MODEL.md](../THREAT_MODEL.md);
2. tests each batch (RCT and APT from SP 800-90B, a conservative min-entropy estimate, three tests from SP 800-22, a replay detector);
3. extracts (Toeplitz) and mixes (SHA3-512) only the sources with no visible defect, and **refuses to generate a seed** if there is not at least one approved local source;
4. derives ML-KEM-768 and ML-DSA-65 from the seed;
5. issues a **signed (ML-DSA-65), hash-chained receipt**, with only hashes, recording the sources, the tests, and each one's result.

Plus an **open, reproducible study** of how public QPUs behave as a bit source: versioned data and CSVs, with every number in the report traceable to a file.

## What the 9 days showed

- A real QPU (`ibm_kingston`, 3 collections, 6 batches of 1.5 million bits) **did not pass** the health gate: the bias is small (0.4964 to 0.5048 fraction of ones), but at this batch size it is measurable, and the sign changed between collections. This speaks to the batch size and the criterion, not proof of the QPU's poor quality.
- The system detects bias, correlation, stuck bits, and exact replay, within limits of statistical power: the smallest bias tested (p = 0,501) is detected in only about 30% of the 1-million-bit batches, and shifted or transformed replay is not detected (see T3 in [THREAT_MODEL.md](../THREAT_MODEL.md) and the report). A disguised pseudorandom generator **passes**, because the tests look only at the output. The false-positive rate on the `os` source is 2.6% to 3.6%.
- With XOR, an adversary who sees the other source chooses the final seed and the tests don't notice; with hash this doesn't happen, but an adversary who tests candidates forces k bits with 2^k attempts.
- In time, the QPU spends on the order of 10 times more seconds per megabit than the `os` source. It is not a ratio of money.
- The CHSH check was only done in simulation and **says nothing about the real QPU**.

## Market and competitors

**Not revalidated:** the market and competitor facts in this section (the SP 800-90B validation in April 2025, the IonQ control since May 2025, the Samsung Galaxy Quantum phones) come from section 3 of `PROJECT.md` (brief dated 27/10/2026) and were not rechecked against sources; treat them as unverified claims, not as established fact.

The market for quantum random number generation already exists and is built on hardware or a dedicated service: **Quantinuum Quantum Origin** (seed generated on a quantum computer, with local entropy refinement; validated against NIST SP 800-90B in April 2025), **ID Quantique** (QRNG chips and devices, controlled by IonQ since May 2025, present in Samsung Galaxy Quantum phones), Quside, QuintessenceLabs, Crypta Labs, KETS, Qrypt, and Quantum eMotion. The EAL **does not compete as a source of quantum bits**: a cloud QPU service, like the one tested here, proved slow, expensive in time, and dependent on trusting the provider.

**Where the EAL might have room (hypotheses to validate with customers, no market figures gathered):** teams that need **per-key evidence** of the origin and testing of randomness, that mix several sources (including from QRNG vendors) and want a verification layer independent of the provider, and those preparing for the post-quantum migration and for audits.

| Differentiator | Honest note |
|---|---|
| Neutral with respect to the source | Any QRNG can enter as a source; it does not replace the QRNG |
| Audit receipt per key | Integrity and ordering; it does **not** guarantee the entropy |
| Open data on public QPUs | One QPU, 3 collections: small, but reproducible |
| Integrated PQC derivation | Pure Python, not constant-time |

## Roadmap (summary)

A local QRNG chip as a first-class source; complete SP 800-90B estimators and health tests in a production line; porting the core to C or Rust with audited PQC libraries; certification only after settling on a path (SP 800-90B, FIPS 140-3); more QPUs and more collections. Details and order in [ROADMAP.md](ROADMAP.md).

Full report, with limitations and uncertainty ranges: [../relatorio/RELATORIO.md](../relatorio/RELATORIO.md).
