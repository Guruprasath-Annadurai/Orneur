# Lifecycle and provenance

Code: `orca/foundation_x/lifecycle.py`, function `assess_lifecycle`.

The checked links are dataset, transformation digest, tokenizer identity, config digest, authorization, run id, training-state digest, checkpoint digest, checkpoint-to-dataset digest, evaluation approval, model-family trained flag, and a witness when `witness_required` is set.

A missing link, a tokenizer mismatch, a synthetic authorization, a self-described founder grant that is still marked synthetic, an untrained `genesis`/`novus`/`aeternum` family, or a missing required witness returns `fail_closed`.

A chain that passes every link returns `chain_complete_training_not_authorized`. The function does not start training. The test `test_foundation_lifecycle_data_scaling_and_feedback` covers both decisions.

Answer provenance for retrieval is `AnswerEvidenceManifest` in `orca/rag_x/contracts.py`: schema `rag-x.1`, scope digest, config digest, evidence ids, and document versions. `test_temporal_version_and_replay_leave_history_unchanged` shows a stored answer string staying in place after the source version is revoked.
