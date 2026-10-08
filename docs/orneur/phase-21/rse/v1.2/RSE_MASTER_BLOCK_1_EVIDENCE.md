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

IMP-4 (`orca/rse/imp4/ocr1.py`) is OCR1 v2 framing over pyhpke 0.6.5 (RFC 9180 Base: DHKEM X25519 HKDF-SHA256, HKDF-SHA256, ChaCha20-Poly1305) plus Ed25519 over `OCR1v2-SIG || 0x00 || header || ciphertext`, verified before `create_recipient_context`. cryptography supplies X25519, HKDF, ChaCha20-Poly1305, and Ed25519. This module does not reimplement those primitives. Ephemeral IKM is `HKDF-SHA256(salt=SHA256(Ed25519(OCR1v2-EPH || 0x00 || sender || environment)), info=grant || sequence || counter).derive(os.urandom(32))` then pyhpke `derive_key_pair`. That is the public API, so residual R-RNG1 (caller-supplied IKM unavailable) is not used. The all-zero X25519 shared secret is rejected before open. A low-order `enc` that cryptography rejects with `ValueError` is mapped to `ZERO_SHARED_SECRET` (N12) without changing the X25519 implementation. The keyless checker is a Python subprocess. Its label is `SYNTHETIC_NOT_A_SANDBOX`: a resource limit is not an isolation boundary. If `setrlimit` fails, the child exits and the parent fails closed. Its `STRUCTURAL_OK` line has `ZERO_ACCEPTANCE_AUTHORITY`.

## N-1

Presenting a stale grant records that grant id as dead and refuses it. It does not void a different outstanding challenge and it does not set a blanket void flag. The outstanding challenge is voided when `RoleFreshness.authenticate` accepts a successor registry. That is the availability cost of exact snapshot binding: a real registry update burns the current challenge, and a corrected grant needs a new OCH1. A stale presentation cannot be used against the new registry. This is stricter on availability than a reading of ACR-12 that would void the outstanding challenge on any mismatched presentation, including one that names a different challenge. The security property is the one Clarification 1 requires: a stale grant never becomes usable.

## N-2

`Session.confirm` and `Session.accept_ack` reject unexpected keyword arguments, including `challenge_ledger` and `highest_authenticated_version`. Assigning `session.freshness` fails closed. The session builds the IMP-1 `ChallengeLedger` it passes to `consumer_verify` from its own journal after `RoleFreshness.evaluate`. A caller-supplied ledger is not consulted. IMP-1 `consumer_verify` itself is unchanged and still fails closed when those arguments are omitted.

That in-process check was the whole of N-2 on the first candidate. It did not stop a caller from booting a pre-activation journal, and it did not stop a caller from passing a fresh recipient journal into OCR1. Those two gaps are the remediation below. N-2 is not a claim that a synthetic fence is TPM NV.

## Architecture-change requests (not applied)

These are recommendations. Manifest V3 and the normative documents were not edited.

1. OEL1 is 102 bytes. The freeze names the fields and does not number every width. The implemented layout is magic, version, kind, index, payload digest, grant id, epoch, registry version, previous record digest.
2. OCI1 is 2102 bytes (64 proof slots). OCA1 is 217 bytes. OCH1 is 181 bytes. Widths are inferred from the named fields and from the OCK1 width the freeze does state (181).
3. OCK1 and OCH1 signatures use `"<magic>-SIG" || 0x00 || body`, the domain pattern the freeze states for OCA1.
4. N-1 above, if an independent reviewer reads ACR-12 as requiring void-on-presentation rather than void-on-authenticated-successor.
5. OMJ1, the monitor journal. RSE12_02 defines OCP1 and the packet rules (strictly increasing `packet_seq` per source and witness, idempotent replay, no log rollback). It does not define a monitor journal. The software writes a bounded OMJ1 (version 1; generation `u64`; epoch floor; witness id; registry version taken from the signed checkpoint; previous checkpoint digest; evidence-log root; at most 64 log rows; at most 256 packet rows). This note does not make OMJ1 normative. In-memory `Monitor` fields are not durable evidence.
6. OFJ1 version 2 stores forfeited sequences as merged inclusive intervals, with a shared cap of 8192 set members. The freeze does not number this journal. A mutation that would exceed the cap fails closed and does not emit a journal the parser would reject.
7. OBS1 version 2 carries a `u64` generation. `SyntheticFence` rejects a generation below its floor, and the same generation with a different digest. The label is `SYNTHETIC_NOT_REAL_HARDWARE_PROOF`. A virgin fence has not authenticated a journal. This is not TPM NV enforcement, and it does not retire the hardware residual.
8. OCJ1 is the hedge-counter journal inside OBS1. RFC 8937 needs a counter that is not reused for the same grant and sequence. `Session.seal_frames` commits that counter before it returns. An unbound `Sender()` still keeps a process-local counter; that object is not the restart boundary. No new signature domain is implied. OCR1 header width stays 210. The OCK1/OCH1 domain in item 3 remains an open recommendation.

## Residuals

- R-N1. Tests enrol two monitors with distinct synthetic keys. They do not prove that two humans, two machines, or two environments exist. One operator can still hold both test keys.
- R-N2. Records appended after a checkpoint are visible to the consumer as a stale head when they are state-changing. A suppressed tail that is never revealed is an IMP-6 / witnessed-storage problem, not something this process journal can see.
- A synthetic fence is not a TPM. A process that boots with a newly constructed fence has no authenticated floor. Real NV enforcement remains deferred with IMP-6. A restored ACTIVE grant becomes INTERRUPTED and cannot rehearse.
- `Monitor` state that was never written to OMJ1 is not witness evidence. Docker is still not a witness.
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

## Remediation of candidate `465ae14880d841ca902457c0645511d30548067b`

The independent review verdict on that SHA was `RSE_MASTER_BLOCK_1_REMEDIATION_REQUIRED`. This section records the software changes. It does not accept them.

- F-1. `activate` calls `JournalSink.commit` on the OBS1 blob and advances `SyntheticFence` only after that call returns. A failed or partial commit raises `JOURNAL_COMMIT`, moves an in-memory ACTIVE grant to INTERRUPTED, and does not return ACTIVE. Boot rejects a journal generation below the fence floor. Tests cover commit failure, a short write, a write that raises after storing bytes, pre-activation rollback, restart, and a second `rehearse`.
- F-2. `ingest_phase2` takes no caller journal. The session `RecipientJournal` is inside OBS1. Admission is committed before success is returned. A substituted journal is `UNEXPECTED_ARGUMENT`. Restart loads the admitted sequence.
- F-3. `Monitor.export` / `Monitor.boot` use OMJ1 (ACR 5). A new `Monitor()` has no fork history. Restart tests cover a second genesis, packet replay, fork, rollback, and an older journal against the same fence.
- F-4. Forfeited sequences are one merged interval. A range of 5,000 and 4,100 voided challenges round-trip. Input past the shared cap fails closed at the mutation.
- F-5. `_reject_zero_shared` catches the library `ValueError` from a low-order public key and raises `ZERO_SHARED_SECRET`. N12 uses real X25519 keys. The all-zero mock remains a separate test and is not the proof.
- F-6. `ENC_DIVERGENCE` marks that grant id and `durable_commit` runs before the quarantine is reported. A later sequence of that grant fails closed after restart. Another grant id is not marked.
- F-7. `verify_grant_inclusion` requires the evidence-record epoch and registry version, and the checkpoint epoch and registry version, to match the grant.
- F-8. `Egress.note_witnessed` without the session admit token raises `RESULT_EGRESS`. `accept_result` checks inclusion `tree_size` against the checkpoint. An unwitnessed digest cannot be classified as a training input. Locks stay denied.
- F-9. Checker label `SYNTHETIC_NOT_A_SANDBOX`. The temporary directory is removed. `setrlimit` failure exits the child.
- F-10. Journal sections are checked before recovery. A missing grant id is `GRANT_ABSENT`. Malformed blobs are `JOURNAL` or `FRESHNESS`, not `KeyError`.
- F-11. See the governance section. The N-2 row in the traceability matrix no longer says the first in-process check closed disk rollback or recipient-journal substitution.

`Session.seal_frames` persists the hedge counter in the same commit that returns the frames. A restart that presents the committed journal cannot take that grant and sequence again.

## Workflow trigger and dependency governance

`.github/workflows/test.yml` push branches include `cursor/**`. That filter is what makes a push of this branch run the six jobs on the commit SHA. A pull_request run checks out a merge ref, which is not the candidate. The change does not add workflow permissions. It is disclosed here for owner review; it is not an authority change.

pyhpke is declared in the `dev` extra and in the `rse` extra. It is not a base dependency. `uv pip install -e .` cannot import OCR1. `uv.lock` does not contain pyhpke. CI installs with `uv pip install -e ".[extras]"`, not `uv sync`, so the lockfile is not what the jobs resolve. The dependency-scan job installs the base package only, so that job does not scan pyhpke. A successful import is not an audit of pyhpke. cryptography stays on `>=49,<51`. No normative file was edited to add the dependency.

## Checks

Local `tests/rse` (IMP-1 invariants plus IMP-2/3/4, the remediation campaign, and the cross-IMP rehearsal) is the software regression for this block. Exact-SHA CI is recorded on the candidate commit after the six push jobs finish. A green pull-request merge ref is not a substitute for that push SHA. The run id is recorded on the pull request for the SHA that was tested, so this file does not move that SHA.
