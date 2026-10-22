# ORNEUR pre-training engineering baseline

Date of inspection: 22 October 2026 (Asia/Calcutta). This file records what was in the repository when this branch started. It does not accept any requirement.

## Inspected commits

| Ref | SHA | What it is |
|---|---|---|
| `origin/main` | `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` | Merge of PR #51, 15 October 2026, 17:03 Asia/Calcutta. 0 commits ahead of this branch's merge-base. |
| `origin/claude/genesis-audit077-p0-remediation-2026-10-21` | `97582a94efcb93dda6c4e8a8c89e457f446a5af2` | GENESIS remediation HEAD. 74 commits ahead of main. Audited code baseline cited by the programme is `55eb4fea5c5c4820db6b15e1a2aac5885bddce78`; later commits on this branch are CI and documentation. |
| This branch base | `97582a94efcb93dda6c4e8a8c89e457f446a5af2` | Work is stacked on the remediation HEAD so it can exercise `orca/genesis` without copying it. It is not a claim that the remediation branch is merged. |

`python3 scripts/acceptance/validate_register_graph.py --check` on this base printed:

```
pretraining=95 numerator=0 application=3 execution=2 post=1
```

Zero of 95 pre-training requirements are accepted. `scripts/cursor/pretraining_preflight.py` prints the same line and does not write the ledger.

## Workstream ownership

Cursor, on this branch: data admission, keyed derived-cache mode, training-math checks, tokenizer robustness, synthetic eval integrity, model-family records, a fail-closed external-anchor adapter, synthetic agent orchestration, fault injection, scenario labels, and this evidence.

Claude, not modified here: B01–B16 frontend, C02 mission execution (open draft PR #78's sibling PR #79, `claude/c02-mission-execution-backend-2026-10-22`), and the GENESIS checkpoint confinement work already on the base branch.

## Reusable components already on the base

Status below is from reading the base, not from formal acceptance.

| Area | Status | Evidence |
|---|---|---|
| Decoder-only GENESIS transformer, loss, AdamW, cosine schedule, grad clip | VERIFIED IMPLEMENTED on the base branch | `orca/genesis/model/transformer.py`, `orca/genesis/training/primitives.py`, `orca/genesis/training/learning_step.py` |
| Resumable checkpoint, dataset identity, config fingerprint, local anti-rollback ledger | VERIFIED IMPLEMENTED on the base branch | `orca/genesis/training/resumable_checkpoint.py` and its tests |
| Streaming corpus pipeline, manifests, contamination screen | VERIFIED IMPLEMENTED on the base branch | `orca/genesis/data/pipeline.py`, `manifest.py`, `contamination.py` |
| Block-store cache with unkeyed truncated SHA-256 | VERIFIED IMPLEMENTED, residual documented in the module | `orca/genesis/data/loader.py` |
| Tokenizer framework (SentencePiece, NFC, byte fallback) | VERIFIED IMPLEMENTED | `orca/genesis/tokenizer/framework.py` |
| Worker process, peer credentials, fail-closed uid drop | VERIFIED IMPLEMENTED on the base branch. Same-uid is explicitly not a privilege boundary. | `orca/genesis/training/isolated_worker.py` |
| Private eval V2 custody | BLOCKED BY AUTHORIZATION | Existing phase-21 records. This branch does not create a secret corpus. |
| Training authorization | BLOCKED BY AUTHORIZATION | Register numerator stays 0. |
| Hardware, external anchor, founder signatures | BLOCKED BY EXTERNAL RESOURCES or founder action | Not created here. |

## Defects this branch closes

1. `stream_records` opened text as strict UTF-8, so an invalid byte raised `UnicodeDecodeError` instead of a counted rejection.
2. A symlink input was followed.
3. Derived block-store integrity was unkeyed. A caller who can rewrite the store and the manifest together was outside the stated check. Keyed mode now fails closed when the caller supplies a 32-byte key.
4. `TrainingState.restore` loaded optimizer state without rejecting a non-finite moment or a shape mismatch.
5. Finite-difference, reference AdamW, accumulation-under-stated-assumptions, repeated interruption, and token-position checks were not in the suite.
6. GENESIS / NOVUS / AETERNUM had no single registry that refuses TRAINED / AVAILABLE / FRONTIER_QUALIFIED.

## Security-sensitive files left unchanged

`orca/genesis/training/checkpoint_integrity.py`, `orca/genesis/training/isolated_worker.py`, `orca/genesis/training/resumable_checkpoint.py`, `orca/genesis/training/learning_governance.py`, `orca/genesis/governance/authorization.py`, `docs/orneur/acceptance/**`, and authorization JSON. No signature was written.

## Integration dependency

This branch does not apply on `main` by itself. `orca/genesis` exists only on the unmerged GENESIS line. The pull request base is `claude/genesis-audit077-p0-remediation-2026-10-21`.
