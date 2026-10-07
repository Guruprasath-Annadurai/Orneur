# ORNEUR / Genesis V2 — RSE-ARCH-1.2 (final architecture blocker remediation)

Package version **RSE-ARCH-1.2**, written 2026-10-07. Starting candidate `f188439eaf3e5962db95944abc7201ca4e9e4da2`; canonical `main` `0264242cb5ea544ca3eefc7c1ab4b4c7294f2de7`. Everything here is `DESIGNED`; nothing is provisioned, purchased, created or authorized. `DECISION_9R_P1_INDEPENDENT_WITNESS_CONFIRMED`; P0 is `P0_SYNTHETIC_REHEARSAL_ONLY`.

## History (nothing rewritten)

| Version | Candidate | Verdict | Note |
|---|---|---|---|
| 1.0 | `8fa4100d77636fc0e7382dbdcf748d9567b9396f` | rejected (`RSE_ARCHITECTURE_REMEDIATION_REQUIRED`) | `SUPERSEDED_BY_RSE_ARCH_1_2` |
| 1.1 | `f188439eaf3e5962db95944abc7201ca4e9e4da2` | remediation attempt; **rejected for freeze** (`RSE_ARCH_1_1_REMEDIATION_REQUIRED`) | `SUPERSEDED_BY_RSE_ARCH_1_2` |
| 1.2 | this commit | current candidate, **awaiting independent audit** | |

**Transparent correction.** RSE-ARCH-1.1 stated in `RSE11_06` that "unresolved HIGH blockers after this round: none" and graded B1–B12 RESOLVED. That statement is **withdrawn**: the re-audit found four unresolved HIGH gaps (H1 Crown digest provenance, H2 witness set and freshness, H3 anti-rollback classification, H4 OCR1 cryptographic completeness) and several MEDIUM defects. Old text stays in the repository unchanged except for a one-line supersession pointer at the top of the 1.0 and 1.1 index files. Where 1.2 and an earlier part differ, 1.2 governs; parts of 1.1 that 1.2 does not mention (for example A, B, C, D of `RSE11_01` and the 1.1 recovery table) remain in force as amended.

## Files

| File | Content |
|---|---|
| `RSE12_01_REGISTRY_CROWN.md` | H1: registries, Crown display contract, SAS and typed intent, bootstrap, Owner Floor Card |
| `RSE12_02_WITNESS_LEDGER_FRESHNESS.md` | H2: witness policy, log-first, offline transport, result egress, freshness, crash, mid-run expiry, role lifecycle |
| `RSE12_03_ROLLBACK_TPM.md` | H3: anti-rollback matrix, TPM NV fence, update transaction, replacement, signed-policy rollback |
| `RSE12_04_OCR1_GRANTS_ENROLMENT.md` | H4: HPKE decision and profile, OCR1 v2 layout, nonce/replay/frame rules, grant layouts, enrolment |
| `RSE12_05_CUSTODY_RECOVERY_SUPPLY_NETWORK.md` | Qualification, weight custody, recovery, re-root, foundation provenance, supply chain, network tests |
| `RSE12_06_P1_ACCEPTANCE_OPERATIONS.md` | P1 requirements, threat model, operator budget, 50-row acceptance register, roadmap, next action |
| `RSE12_07_SELF_ATTACK.md` | fresh hostile review; defects found and fixed |
| `prototype/` | `PROTOTYPE_ONLY` OCR1 v2 framing decoders (Python and JavaScript), mutation harness, command, expected output |

## H1–H4 closure (design level; independent audit still required)

| Blocker | Root-cause fix | Where | Residual | Status |
|---|---|---|---|---|
| H1 digest provenance | owner-approved signed registry for code, role images, foundations, tokenizers, models, corpora, enrolment, policy, destinations, holdouts; grants carry entry IDs only; Crown and consumer both validate; policy caps; 60-bit SAS with typed intent; genesis ceremony outside the registry; Owner Floor Card | `RSE12_01` | owner error; shared upstream at genesis | RESOLVED |
| H2 witness/freshness | exact required signatures per event (LH ∧ M1; irreversible ∧ M2 ∧ OC); independence rule; M1/M2 honestly classified REQUIRED_WITNESS; log-first sequence; OCP1/OCA1 offline transport; result gating with stated exceptions; challenge freshness; clock advisory | `RSE12_02` | one human runs M1/M2/OC | RESOLVED |
| H3 anti-rollback | authenticity separated from monotonic reference; per-object matrix with allowed classes only; one TPM NV fence with justified use; power-loss transaction; no signed policies | `RSE12_03` | Mac OS state UNSOLVED; NV atomicity unverified; routine-grant replay after in-state rollback bounded | RESOLVED |
| H4 OCR1 completeness | HPKE RFC 9180 Base (X25519/HKDF-SHA256/ChaCha20-Poly1305) plus Ed25519 signature; every field present or derived; ephemeral key via RFC 8937 wrapper; frame rules; grant layouts; enrolment | `RSE12_04` | library selection and test vectors; no cryptographic implementation evidence | RESOLVED |

**B1–B12 final design status (1.2):** B1 RESOLVED (A–AI map below); B2 RESOLVED (H1 + typed intent); B3 RESOLVED (H2); B4 RESOLVED (H3); B5 RESOLVED (`DUAL_TOKEN_OWNER_CONFIRMATION`; the unenforceable "time separation" wording removed from the state machine); B6 RESOLVED (H4); B7 RESOLVED (W/D separate, `RSE12_05` §2); B8 RESOLVED (Monitor-Lite reclassified REQUIRED_WITNESS honestly); B9 RESOLVED (rebuilt register); B10 RESOLVED (revised requirements); B11 RESOLVED (unchanged, accurate); B12 RESOLVED (correction above). All are design-level statuses.

## A–AI map

| Item | Where |
|---|---|
| A, B, C, D, E, F | `RSE11_01` as amended: E extended by the structured table in `RSE12_06` §2; B baseline additions: registry, Owner Floor Card, prototype = NOT_IMPLEMENTED or PROTOTYPE_ONLY |
| G, K | `RSE11_02` §G, §K |
| H Crown | `RSE12_01` |
| I Forge | `RSE11_02` §I |
| J Witness | `RSE12_06` §1 |
| L Qualification | `RSE12_05` §1 |
| M Transfer | `RSE12_04` (OCR1 v2) with `RSE11_03` §M two-phase text as amended |
| N Evidence Ledger | `RSE12_02` |
| O Monitor-Lite | `RSE12_02` §1 |
| P Reliquary/Recovery | `RSE12_05` §4 |
| Q Attestation | `RSE11_02` §Q + `RSE12_03` |
| R Keys | `RSE11_02` §R + `RSE12_04` §2 |
| S Grants | `RSE12_04` §8 |
| T Network | `RSE12_05` §7 |
| U Storage | `RSE11_03` §U |
| V Role lifecycle | `RSE12_02` §9 |
| W Anti-rollback | `RSE12_03` |
| X Supply chain | `RSE12_05` §6 |
| Y Corpus custody | `RSE11_04` §Y as amended by `RSE12_05` §3 |
| Z Weight custody | `RSE12_05` §2 |
| AA Compromise scenarios | `RSE11_04` §AA, `RSE12_06` §2, `RSE12_07` |
| AB Disaster recovery | `RSE12_05` §4 |
| AC–AE | `RSE12_06` §6 and `RSE11_05` |
| AF Implementation phases | `RSE12_06` §7 |
| AG Acceptance | `RSE12_06` §4 |
| AH Residuals | `RSE12_06` §5 |
| AI Next action | `RSE12_06` §8 |

## Research claims in this phase

Read this phase: RFC 9180 (HPKE: mode and suite IDs, sequence-number nonces, §9.7.1 message order, §9.7.3 replay, §9.7.5 bad ephemeral randomness, X25519 validation text), RFC 8937 (randomness wrapper), library existence checks (Go `crypto/hpke`, OpenSSL ≥ 3.2 HPKE API, Rust `hpke`, Python `pyhpke` 0.6.5, `cryptography` 50.0.2 — HPKE support in `cryptography` was **not** confirmed). Not reviewed: any library's audit status or API surface. Novelty: `INSUFFICIENT_RESEARCH`; no claim of world-first.

## Prototype evidence class

`STRUCTURAL_CODEC_EVIDENCE` only (`prototype/`; 20,000 deterministic mutations; Python and JavaScript decoders; 0 disagreements; identical verdict digest). There is **no** `CRYPTOGRAPHIC_IMPLEMENTATION_EVIDENCE`.
