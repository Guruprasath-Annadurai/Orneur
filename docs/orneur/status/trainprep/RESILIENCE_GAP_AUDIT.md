# Train-prep resilience gap audit

Scope: synthetic-only, dry-run-only tooling (`orca/train/dryrun/`, `scripts/trainprep/`, `tests/test_trainprep_*.py`). Nothing here trains, authorizes, spends, uses a GPU, the network, a real key or a protected corpus. `TRAINING_AUTHORIZATION.json` stays `NOT_AUTHORIZED`; no frozen path is touched. Baseline before this change: 377 passed, 1 xfailed across the train-prep, genesis-not-trained and training-authorization-gate suites.

Legend: EXISTS = implemented and tested already (not re-implemented). GAP = missing; implemented additively in this change with a test that fails before it.

| # | Requirement | Already exists (file :: test) | Gap (added here) |
|---|---|---|---|
| 1 | Dependency lock verification | `lockcheck.py`, `requirements/train.txt` :: `test_trainprep_lock_env.py` (every line `==` pinned and hashed; URL/VCS/option/duplicate/no-hash refused; required `train` extra covered; env manifest carries lock sha) | GAP-1a duplicate hash inside one package and one hash shared by two packages were accepted; GAP-1b nothing refuses a run whose lock file no longer matches the lock sha bound in the env manifest (lock drift); GAP-1c a declared dependency that is unpinned/absent/version-mismatched in the lock was not checked per-spec (only names) |
| 2 | Run manifests deterministic, byte-stable, content-addressed | `ledger.py::build_run_manifest/seal_run_manifest` (O_EXCL, bound to ledger head) :: `test_trainprep_ledger.py` | GAP-2a no test/guarantee that two identical runs seal byte-identical manifests; GAP-2b manifests are named by run id, not by content; nothing detects a manifest renamed/edited relative to its address |
| 3 | Checkpoint verification | `ckpt.py` :: `test_trainprep_checkpoint.py` (bit flip, truncation, extra/deleted file, symlink, sidecar edit, ledger digest, wrong plan) | GAP-3a wrong run id was NOT checked: a byte-identical checkpoint transplanted from another run (same plan => same digest) verified; GAP-3b no checkpoint hash chain / ordering check across the whole set |
| 4 | Failure recovery | `Fault.raise_at/nan_at_step/crash_ckpt_at`, rollback of in-flight step :: `test_trainprep_budget.py`, `test_trainprep_checkpoint.py` | GAP-4a no sweep that kills the run at EVERY durable write (every ledger append, before and after) and proves recovery neither double-counts nor skips a step; the sweep exposed GAP-4b (a crash before the first checkpoint left a ledger that could neither resume nor restart) and GAP-4c (a crash between writing the sealed manifest and chaining its hash left an orphan file that blocked the next seal, and resuming a finished run raised instead of being a no-op) |
| 5 | Resume consistency | `test_trainprep_resume.py` (final state + final checkpoint bytes identical from any step k, two interruptions, negative controls) | GAP-5 "evidence" (effective timeline, checkpoint set, final state) is not compared byte-for-byte; no canonical final-evidence document exists |
| 6 | Cost ceilings | `budget.py` :: `test_trainprep_budget.py` (default 0 = nothing runs, cap exceeded refused, cumulative across resume), grant spend tests in `test_trainprep_authorization.py` | GAP-6a resume accepted a budget LARGER than the one bound in the chained `run_started` record (ceiling raise on resume); GAP-6b resuming with a zero budget re-entered the ledger (appended `run_finished`/`run_resumed`) instead of refusing everything; GAP-6c no test that editing the ledger-bound ceiling or the sealed manifest cannot move a ceiling |
| 7 | Grant enforcement | `harness.rehearse_with_grant` :: `test_trainprep_authorization.py` (expired at issue, revoked at issue, tampered/forged, wrong code tree/dataset/base model/config, replay, spend) | GAP-7a a grant revoked AFTER issuance but before use was honoured; GAP-7b no test for wrong subject (environment class) via the harness, nor for expiry between issue and use |
| 8 | Evidence integrity | `chainlog.py`, `auditlog.py`, `ledger.py` :: `test_trainprep_ledger.py`, `test_trainprep_auditlog.py` (edit, truncation, anchors, rotation, concurrency) | GAP-8 no single `verify_run_evidence` that cross-checks ledger + manifests + checkpoints + chain; no tests for record reorder / duplication / deletion at the run-evidence level or manifest swap |

## Implementation plan (additive)

* `orca/train/dryrun/lockverify.py` (new): GAP-1.
* `orca/train/dryrun/evidence.py` (new): GAP-2, GAP-3b, GAP-5, GAP-8.
* `ckpt.py`: optional `expected_run_id` keyword (default None keeps old behaviour): GAP-3a.
* `ledger.py`: read helpers plus `complete_pending_seal` (finish an interrupted seal only when the manifest is intact and binds the current head): GAP-4c.
* `harness.py`: resume-time checks only (run id on checkpoints, budget not above bound, zero budget refuses, grant revocation re-check): GAP-3a, 6a, 6b, 7a. No bypass parameter is added.
* Tests: `tests/test_trainprep_resilience_*.py`.

Design note: `max_steps` is intentionally not a bound ceiling on resume (it is the per-invocation pause control and the run is bounded by the hash-bound `Plan.total_steps`; the existing resume tests rely on raising it). Tokens, wall clock, spend and the simulated per-step cost (which may not be lowered) are bound by the chained `run_started` record. Checkpoints written at a stop point are operational and excluded from the plan-determined set compared by `final_evidence_bytes`.

Training-gate safety: the new tests assert no new function name or parameter can bypass the gate, that the committed authorization JSON is byte-identical, and that `authorize_training` still returns `NOT_AUTHORIZED` on the real repository.
