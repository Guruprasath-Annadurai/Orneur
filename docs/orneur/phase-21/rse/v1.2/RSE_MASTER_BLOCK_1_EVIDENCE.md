# RSE master block 1 — implementation evidence

NON_NORMATIVE. This note is not part of Manifest V3 and does not amend RSE-ARCH-1.2 or Clarification 1. It records what the software on this branch does, which checks were run, and what remains unresolved.

Status target, only after the checks below are actually green on the candidate SHA:

- RSE_MASTER_BLOCK_1_READY_FOR_INDEPENDENT_SECURITY_REVIEW
- IMP_2_IMPLEMENTED_PENDING_INDEPENDENT_ACCEPTANCE
- IMP_3_IMPLEMENTED_PENDING_INDEPENDENT_ACCEPTANCE
- IMP_4_IMPLEMENTED_PENDING_INDEPENDENT_ACCEPTANCE
- IMP_5_NOT_AUTHORIZED

This branch does not merge. It does not claim production readiness, real-hardware independence, or secure-environment acceptance.

## Baseline

Implementation starts from canonical main `464b602f3f259b56f139c3304828baa660e6b860` (push CI `37821363822`, six jobs succeeded). Manifest V3 was re-checked at 32/32 and was not edited. IMP-1 modules under `orca/rse/imp1/` are unchanged. Authorization lock files and protected benchmark trees are unchanged.

## What was implemented

IMP-2 (`orca/rse/imp2/machine.py`) is the grant lifecycle table. A transition that is not listed fails closed. Classes K, Q, T, W, D, and R can be parsed and refused; they cannot advance toward ACTIVE. Reaching ACTIVE in a test is a lifecycle rehearsal. `rehearse` returns `NOT_AUTHORIZED` and does not flip corpus, qualification, or training locks.

IMP-3 (`orca/rse/imp3/`) is the role evidence log, Monitor-Lite acknowledgement, authoritative freshness journal, and result-egress gate. The registry Merkle tree in IMP-1 is a different profile (`RFC6962-SHA256-ENTRY-ID-LEAF`). The evidence tree is `RFC6962-SHA256-RECORD-LEAF` (RFC 6962 leaf/node domain separation, RFC 9162 inclusion and consistency). Docker containers are not witnesses. Only enrolled `ROLE_MONITOR_LITE` keys are. M1 and M2 must be distinct keys and distinct environment measurements. G and V quorum requires the configured M1 acknowledgement of the checkpoint that covers the grant. An acknowledgement of a later checkpoint does not satisfy an earlier one.

IMP-4 (`orca/rse/imp4/ocr1.py`) is OCR1 v2 framing over pyhpke 0.6.5 (RFC 9180 Base: DHKEM X25519 HKDF-SHA256, HKDF-SHA256, ChaCha20-Poly1305) plus Ed25519 over `OCR1v2-SIG || 0x00 || header || ciphertext`, verified before `create_recipient_context`. cryptography supplies X25519, HKDF, ChaCha20-Poly1305, and Ed25519. This module does not reimplement those primitives. Ephemeral IKM is `HKDF-SHA256(salt=SHA256(Ed25519(OCR1v2-EPH || 0x00 || sender || environment)), info=grant || sequence || counter).derive(os.urandom(32))` then pyhpke `derive_key_pair`. That is the public API, so residual R-RNG1 (caller-supplied IKM unavailable) is not used. The all-zero X25519 shared secret is rejected before open. The keyless checker is a stdlib subprocess with a restricted environment, CPU, address-space, and file-descriptor limits. Its `STRUCTURAL_OK` line has `ZERO_ACCEPTANCE_AUTHORITY`.

## N-1

Presenting a stale grant records that grant id as dead and refuses it. It does not void a different outstanding challenge and it does not set a blanket void flag. The outstanding challenge is voided when `RoleFreshness.authenticate` accepts a successor registry. That is the availability cost of exact snapshot binding: a real registry update burns the current challenge, and a corrected grant needs a new OCH1. A stale presentation cannot be used against the new registry. This is stricter on availability than a reading of ACR-12 that would void the outstanding challenge on any mismatched presentation, including one that names a different challenge. The security property is the one Clarification 1 requires: a stale grant never becomes usable.

## N-2

`Session.confirm` and `Session.accept_ack` reject unexpected keyword arguments, including `challenge_ledger` and `highest_authenticated_version`. Assigning `session.freshness` fails closed. The session builds the IMP-1 `ChallengeLedger` it passes to `consumer_verify` from its own journal after `RoleFreshness.evaluate`. A caller-supplied ledger is not consulted. IMP-1 `consumer_verify` itself is unchanged and still fails closed when those arguments are omitted. Disk rollback of an old journal is not solved here; that remains an IMP-6 / TPM residual.

## Architecture-change requests (not applied)

These are recommendations. Manifest V3 and the normative documents were not edited.

1. OEL1 is 102 bytes. The freeze names the fields and does not number every width. The implemented layout is magic, version, kind, index, payload digest, grant id, epoch, registry version, previous record digest.
2. OCI1 is 2102 bytes (64 proof slots). OCA1 is 217 bytes. OCH1 is 181 bytes. Widths are inferred from the named fields and from the OCK1 width the freeze does state (181).
3. OCK1 and OCH1 signatures use `"<magic>-SIG" || 0x00 || body`, the domain pattern the freeze states for OCA1.
4. N-1 above, if an independent reviewer reads ACR-12 as requiring void-on-presentation rather than void-on-authenticated-successor.

## Residuals

- R-N1. Tests enrol two monitors with distinct synthetic keys. They do not prove that two humans, two machines, or two environments exist. One operator can still hold both test keys.
- R-N2. Records appended after a checkpoint are visible to the consumer as a stale head when they are state-changing. A suppressed tail that is never revealed is an IMP-6 / witnessed-storage problem, not something this process journal can see.
- Journal rollback on disk is out of scope. The in-memory and parsed-journal API refuses caller-supplied replay state. A restored ACTIVE grant becomes INTERRUPTED and cannot rehearse.
- The Mac environment measurement in the architecture is `SELF_ATTESTED`. `signing_key_id` stays an opaque token id. An inspection digest is not a proof that a binary has no backdoor.
- pyhpke is the library named by RSE12_04. Its own review status is not an independent audit of this branch. The RFC 9180 A.2.1 base vector for sequences 0, 1, and 2 is admitted by `admit_rfc9180_base`. Sequences 4, 255, and 256 from the RFC are not checked.
- Forge still sees plaintext before it seals. The checker does not.
- Wall-clock expiry applies only before ACTIVE. After ACTIVE, a monotonic tick ceiling interrupts the grant. Neither clock is a hardware time root.
- No witness quorum can be downgraded by a parameter. Missing M1 fails closed. That can halt progress; it does not authorize the grant.

## Deferred hardware and later IMPs

IMP-5 is not authorized. Not started: real TPM, measured boot, LUKS, supply chain, real secrets, corpus generation, qualification, model selection, GPU, training, provisioning, or hardware purchase.

Permanent restrictions, still in force:

- NO_PROVISIONING_AUTHORIZED
- NO_HARDWARE_PURCHASE_AUTHORIZED
- NO_REAL_SECRET_CREATION
- NO_CORPUS_GENERATION_AUTHORIZED
- NO_QUALIFICATION_AUTHORIZED
- NO_MODEL_SELECTION_AUTHORIZED
- NO_GPU_AUTHORIZED
- NO_TRAINING_AUTHORIZED
- P0_SYNTHETIC_REHEARSAL_ONLY
- DECISION_9R_P1_INDEPENDENT_WITNESS_REQUIRED

Software tests and Docker are not a P1 witness and are not hardware proof. Label for anything in this block that resembles a P1 check: `SYNTHETIC_NOT_REAL_HARDWARE_PROOF`.

## Checks

Local `tests/rse` (IMP-1 invariants plus IMP-2/3/4 and the cross-IMP rehearsal) is the software regression for this block. Exact-SHA CI is recorded on the candidate commit after the six push jobs finish. A green pull-request merge ref is not a substitute for that push SHA.
