# RSE_ARCH_1_2_ARCHITECTURE_FREEZE

Immutable architecture-freeze record. It adds no design: it binds, classifies and locks what the independent audit accepted. A change to any governing file after this record requires a new RSE version, a new independent audit and a new freeze record; this file is never edited in place.

## 1. Binding

| Item | Value |
|---|---|
| Canonical RSE version | **RSE-ARCH-1.2** |
| Accepted architecture candidate | `1df94810bc35692b0ce8c969978920d4dea06d8e` (branch `session-update-2026-08-25`) |
| Exact-SHA CI of the candidate | run `37667679455` (`push`, head SHA exactly the candidate) — success on all six jobs: Deterministic Unit Tests; Genesis V2 Security; Genesis V2 Sandbox; Training Math (Torch); Production Container Build + Boot Smoke; Dependency Vulnerability Scan |
| Independent audit verdict | `RSE_ARCH_1_2_ACCEPTED_FOR_FREEZE` (as relayed by the owner; the audit report itself is not part of this repository) |
| Topology (Decision 9R) outcome | `DECISION_9R_P1_INDEPENDENT_WITNESS_CONFIRMED` |
| Canonical `main` at freeze creation | `0264242cb5ea544ca3eefc7c1ab4b4c7294f2de7` (not moved) |
| Manifest | `RSE_ARCH_1_2_FREEZE_MANIFEST.txt`, SHA-256 `4ce5f0afe4c68503070ca0b4919f5e063585b6ab7ef4ebcdf6348e2d38c0c008` |
| Manifest scope | bytes of each listed file **as committed at the candidate SHA**; the manifest and this record are not listed in themselves |

## 2. What "frozen" means

**RSE-ARCH-1.2 is frozen at DESIGN level.** It does **not** mean, and must not be cited as meaning: `IMPLEMENTED`, `PROVISIONED`, `TESTED ON REAL P1 HARDWARE`, `ACCEPTANCE_COMPLETE`, `CORPUS_AUTHORIZED`, `QUALIFICATION_AUTHORIZED`, or `TRAINING_AUTHORIZED`. Every acceptance row is `DESIGNED`; none is independently audited at maturity above design.

## 3. Bound architecture content (by reference; nothing restated or changed)

| Element | Governing text |
|---|---|
| H1 closure — owner-approved registry, Crown validation, display contract, bootstrap, Owner Floor Card | `v1.2/RSE12_01_REGISTRY_CROWN.md` |
| H2 closure — witness quorum (own checkpoint ∧ M1; irreversible ∧ M2 ∧ owner checkpoint), log-first sequence, offline transport, result egress, challenge freshness, crash and expiry semantics, role lifecycle | `v1.2/RSE12_02_WITNESS_LEDGER_FRESHNESS.md` |
| H3 closure — anti-rollback matrix, TPM NV fence, update transaction, replacement, no signed policies | `v1.2/RSE12_03_ROLLBACK_TPM.md` |
| H4 closure — OCR1 v2 profile: HPKE RFC 9180 Base (`DHKEM(X25519,HKDF-SHA256)`, `HKDF-SHA256`, `ChaCha20Poly1305`) plus Ed25519 sender signature; 210-byte header; derived lengths; frame rules; per-class grant layouts; enrolment | `v1.2/RSE12_04_OCR1_GRANTS_ENROLMENT.md` |
| Qualification, weight custody (nine stages), recovery, re-root, foundation provenance, supply chain, network verification | `v1.2/RSE12_05_CUSTODY_RECOVERY_SUPPLY_NETWORK.md` |
| P1 Witness requirements (25 rows), threat model, operator budget, **acceptance register C01–C50 (50 rows)**, residuals, roadmap, next action | `v1.2/RSE12_06_P1_ACCEPTANCE_OPERATIONS.md` |
| A–AI completion map and H1–H4 / B1–B12 design statuses | `v1.2/RSE12_00_INDEX_HISTORY_CLOSURE.md` |
| A–F, G, I, K, Q, R, U, Y, AA, AC–AE parts not amended by 1.2 | `v1.1/RSE11_01`…`RSE11_05`, normative **as amended by 1.2** |

Acceptance-register identity: the register is the C01–C50 table in `RSE12_06_P1_ACCEPTANCE_OPERATIONS.md` §4, bound by that file's SHA-256 in the manifest.

Profile boundaries: **P0** = `P0_SYNTHETIC_REHEARSAL_ONLY`; **P1** (Crown + Forge + independent physical Witness, with M1/M2 witnesses) is required before any real private corpus; **P2** (or an equivalent training-security architecture decided by the programme) is required before real training and remains research/design-only. No cloud provider, GPU, foundation model or spend is selected or authorized.

## 4. Normative versus non-normative

| Class | Files |
|---|---|
| **NORMATIVE** | `RSE12_00` … `RSE12_06` (1.2) |
| **NORMATIVE_AS_AMENDED_BY_1.2** | `RSE11_01` … `RSE11_05`: the parts the 1.2 index maps to A–AI items and does not override. Where a 1.1 statement conflicts with 1.2, **1.2 governs** |
| **NON-NORMATIVE** self-attack evidence | `RSE12_07_SELF_ATTACK.md` |
| **NON-NORMATIVE** historical | all of RSE-ARCH-1.0 (`RSE_00`…`RSE_04`), and `RSE11_00`, `RSE11_06` (carry `SUPERSEDED_BY_RSE_ARCH_1_2` pointers). Historical architecture remains recoverable in git history and in the tree; it never overrides 1.2 |
| **STRUCTURAL_CODEC_EVIDENCE_ONLY** | `v1.2/prototype/*` — a `PROTOTYPE_ONLY` framing decoder pair with 20,000 deterministic mutations (0 disagreements). It is **not** a normative implementation, has no cryptography, and must never be imported by production code |
| Research notes | quoted in `RSE11_01` §C and `RSE12_00`; informative only |

## 5. Frozen guardrails

**Cryptographic implementation guardrail.** No implementer may hand-roll HPKE, X25519 KEM internals, HKDF, ChaCha20-Poly1305, Ed25519, or any randomness-hedging modification. If a vetted implementation does not expose the safe API the architecture asks for (notably caller-supplied key-derivation input for the RFC 8937 wrapper), the implementer uses the standard supported construction and records the declared residual (R-RNG1) instead of modifying cryptographic internals or inventing a substitute.

**Result-egress guardrail.** Encrypted staged output that leaves Forge before its RESULT record is witnessed has **`ZERO_ACCEPTANCE_AUTHORITY`**. No downstream role may accept it, decrypt it for accepted processing, register it, use it for Qualification, use it for training, or treat it as valid output until the required witnessed RESULT evidence (RESULT leaf, inclusion proof, checkpoint carrying the required cosignatures) has been verified. Plaintext never leaves Forge or the Witness.

**Three-model family.** The controlled training programme covers `GENESIS`, `NOVUS` and `AETERNUM` **independently**. Each requires its own qualification evidence, training manifest, T authorization, compute/resource budget, checkpoint namespace, W authorization and D authorization. No family model inherits another's authority (registry entries hash the family; `RSE12_01` §2). This is architectural readiness only: **no model training is authorized**.

**Authority separation retained.** Training completion never implies W; W never implies D; Qualification produces evidence, never authorization.

## 6. Known residual risks (preserved; none is converted into a security property)

1. The same human operates M1, M2 and the owner offline checkpoint (R-N1).
2. Mac OS state rollback is `UNSOLVED`; Crown and Forge on Mac hardware cannot prevent it locally (R-W1).
3. P0 is synthetic rehearsal only.
4. Forge sees plaintext during the generation window (R-I1).
5. Backdoor or poisoning of a foundation model cannot be ruled out by inspection (R-F2).
6. Qualification counters need hardware/provider monotonic state; until P2 they are `UNPROVEN`, so Qualification stays unauthorized (R-Q).
7. Training-environment egress control is a future P2 requirement and blocks training authorization (R-EXF).
8. Operator and media-handling complexity: the operator budget is a target that drills must confirm; excess is treated as a security risk.
9. HPKE caller-IKM constraint: the RFC 8937 hedging needs a library interface that accepts caller-supplied input; otherwise the declared fallback and residual apply (R-RNG1).
10. Stale-challenge handling: a pre-issued challenge may sit a long time; only registry/epoch revocation and the one-outstanding rule bound it; incident handling voids challenges in maintenance (R-F1).

Also carried from `RSE12_06` §5, unchanged: consumer-side registry rollback detected only; routine-grant replay after an in-state rollback (bounded by ceilings); firmware persistence and non-removable radios on Mac hardware; time-shared minimum Crown before the dedicated device; verifier bug; shared upstream at genesis and in builds; owner error; disk plus recovery passphrase together; TPM bus, firmware-TPM and NV atomicity/endurance unverified; sandbox escape; research gaps. Novelty remains `INSUFFICIENT_RESEARCH`.

## 7. Authorization locks (unchanged)

`NO_PROVISIONING_AUTHORIZED`, `NO_HARDWARE_PURCHASE_AUTHORIZED`, `NO_SECRET_CREATION_AUTHORIZED`, `NO_CORPUS_GENERATION_AUTHORIZED`, `NO_QUALIFICATION_AUTHORIZED`, `NO_MODEL_SELECTION_AUTHORIZED`, `NO_GPU_AUTHORIZED`, `NO_TRAINING_AUTHORIZED`. The corpus-generation and model-evaluation authorization records remain `NOT_AUTHORIZED`; the Qualification registry remains `REGISTERED_NOT_AUTHORIZED`. Freezing authorizes nothing.

## 8. Implementation gate rule

`ARCHITECTURE_IMPLEMENTATION_GATE = CLOSED` at the time of this record. It becomes `OPEN` **only after all** of: (1) the dedicated freeze commit exists; (2) exact-SHA CI of that commit succeeds; (3) the freeze content has been reviewed; (4) the owner/ChatGPT explicitly authorizes canonical integration; (5) the freeze commit has become canonical on `main`. Until then the gate is closed and no implementation, provisioning or purchase may start. Opening the gate does not itself authorize any item in §7; each of those needs its own explicit authorization.

## 9. Next step

Explicit owner/ChatGPT decision on canonical integration of the freeze commit. Nothing proceeds before that.
