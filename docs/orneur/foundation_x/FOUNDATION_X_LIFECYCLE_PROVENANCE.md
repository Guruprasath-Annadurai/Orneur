# Lifecycle and provenance

Code: `orca/foundation_x/lifecycle.py`, function `assess_lifecycle`.

The checked links are dataset, transformation digest, tokenizer identity, config digest, authorization, run id, training-state digest, checkpoint digest, checkpoint-to-dataset digest, evaluation approval, model-family trained flag, and a witness when `witness_required` is set.

A missing link, a tokenizer mismatch, an untrained `genesis`/`novus`/`aeternum` family, or a missing required witness returns `fail_closed`.

`authorization_kind="FOUNDER_GRANT"` is a caller claim. The test now expects `fail_closed` with `no NativePretrainingGrant was supplied` and `caller authorization claim ignored: FOUNDER_GRANT`. A duck-typed object with `verify_integrity` is rejected. Constructing `NativePretrainingGrant` without the gate seal raises `GRANT_NOT_ISSUED_BY_GATE`. Digest comparison is `_grant_binding_reasons`; it is not itself an authorization decision.

A chain can return `chain_complete_training_not_authorized` only after `verify_integrity()` and digest binding. That return does not start training. Tests do not reach it, because they cannot mint a grant.

Answer provenance for retrieval is `AnswerEvidenceManifest` in `orca/rag_x/contracts.py`: schema `rag-x.1`, scope digest, config digest, evidence ids, and document versions. `test_temporal_version_and_replay_leave_history_unchanged` shows a stored answer string staying in place after the source version is revoked.
