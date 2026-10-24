# Incident INC-DOC-DELETE-001

Recovery result: `PATCH DEVELOPED AND TESTED`.

Authorization decision: `DENIED`. This is not `PRODUCTION FIXED` and it is not `RECOVERY VERIFIED`.

The patch was written with the local editor after a failing pytest. No enrolled model backend generated it. The incident engine refuses a caller-supplied exit code; it does not contain this repair and it cannot approve its author.

## Identity

| Field | Value |
|---|---|
| Incident id | `INC-DOC-DELETE-001` |
| Known-bad revision | `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` |
| Isolated fix | `cursor/doc-delete-consistency-a8b0` at `9e66770b172395b5f48b120d3dfdfb9878ea47c9` |
| Observed | 24 October 2026, 16:19 IST |
| Zone | Asia/Kolkata |

PR #106 (`4f82a6ee`) is not an ancestor of this branch. PR #105 is, through PR #107 and the integrity commit `2009ccbd84edd61282e7bf55011419eb25851b5a`.

## Observed failure

`DocStore.delete_doc` returned immediately after a successful collection delete and left the keyword fallback file in place. `retrieve` then served `secret attachment body` when the collection query raised. A collection delete that raised fell through, removed the fallback, and still returned true.

Command, before the edit, with `PYTHONPATH` pointed at a worktree of `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`:

`python3 -m pytest -q tests/test_doc_delete_consistency.py --tb=short`

Result: 2 failed. The first failure was `assert store.retrieve("secret") == []` while the returned chunk text was `secret attachment body`. The second failure was `assert store.delete_doc("d1") is False` while the method returned `True`.

## Root cause

`orca/docs/store.py` treated a collection delete as the whole deletion. The fallback JSONL is a second store. The HTTP handler then called `unregister_doc` even when `delete_doc` returned false, so the registry could drop a document the stores still held.

## Patch

Changed files: `orca/docs/store.py`, `orca/serve/api.py`, `tests/test_doc_delete_consistency.py`.

The collection delete now has to succeed before the fallback is rewritten. If the collection raises, the fallback stays and the method returns false. The route returns 409 `delete_incomplete` and does not unregister the document unless deletion returned true.

## Tests after the patch

Same command in the worktree at `9e66770b172395b5f48b120d3dfdfb9878ea47c9`: `tests/test_doc_delete_consistency.py`, `tests/test_b2_conversation_documents.py`, and `tests/test_doc_session_no_model_runtime.py` — 19 passed.

`tests/test_g006_tenant_isolation.py` and `tests/test_session_ownership_isolation.py` — 42 passed, 2 xfailed. Those xfail marks were already on that tree.

## Independent verification and authorization

The author of the patch is this engineering session. That session cannot enroll itself as a reviewer. `reviewer_enrolled` stays false. `authorization_decision` stays `DENIED`. No merge, deployment, training, or spending was performed.

The incident engine can record a second actor id checking an observation digest. That check is not an enrolled identity and cannot set production authorization. Forged digests, a missing observation, contradictory patch texts, and a caller boolean `recovered: true` are refused.

## Execution

The fix was applied only in the isolated worktree and on branch `cursor/doc-delete-consistency-a8b0`. Execution status: `simulated-isolated` for that worktree's pytest. No production process loaded the patch.

## Resource consumption

Local pytest only. The deletion tests finished in about 18 seconds and the isolation tests in about 12 seconds on this machine. No GPU, no model inference, no spend.

## Notification

No external notifier is enrolled. Delivery state for this incident: `NOT_ATTEMPTED`. A failed sender in the engine leaves the incident state unchanged and records `FAILED`. A crash after a notification has started and before it finishes refuses a second send.

## Remaining risk

Production authorization is DENIED. No reviewer is enrolled. The acceptance ledger is unchanged (`[]\n`, sha256 `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`). Native GENESIS, NOVUS, and AETERNUM models were not loaded; their probes are `NOT_OBSERVED`. The journal hash chain is not a signature. A process that can rewrite the whole file and recompute the chain is outside this control. In-flight handler bodies are still not preempted. Class K, R65, G1, trust enrollment, corpus custody, foundation selection, private evaluation, rights clearance, and qualified compute are unchanged.

## Counts, kept separate

| Item | Value |
|---|---|
| Declared role contracts | 100 |
| Implemented synthetic handlers | 12 |
| Independently qualified agents | 0 |
| Production-authorized actions | 0 |
| `IMPLEMENTED_SYNTHETIC` capabilities | 17 |
| Accepted pretraining requirements | 0 / 95 |

The incident engine is not a new qualified capability and it is not one of the 12 handlers.

## What Antigravity should challenge

1. Check out `9e66770b172395b5f48b120d3dfdfb9878ea47c9` and re-run the pytest commands above. Refuse the report if the secret text is still retrieved after delete.
2. On the parent `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`, the same new test fails. That failure is the defect, not a fixture flag.
3. On this branch, `python3 -m pytest -q tests/test_incident_engine.py tests/test_orchestration_integrity.py`. Confirm a caller `exit_code: 0` cannot enter `TESTED`, the author cannot verify, contradictory patches block verification, a torn or edited journal fails closed, and `build_report` never returns `PRODUCTION FIXED` or `RECOVERY VERIFIED`.
4. Confirm `monitoring_contracts()` reports `model_loaded: false` for GENESIS, NOVUS, and AETERNUM.
5. Recompute the ledger hash. Confirm PR #106 is still not contained in this branch.
