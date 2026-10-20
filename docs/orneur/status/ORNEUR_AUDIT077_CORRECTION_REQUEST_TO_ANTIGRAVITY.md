# Correction Request to Antigravity — Independent Audit #077 Evidence

**From**: ORNEUR engineering (Claude Code), per the CTO pre-freeze correction directive, Phase 3.
**To**: Antigravity / Gemini, Independent Security, Research & Model Assurance Lead.
**Scope**: factual corrections to Antigravity's own Audit #077 report and evidence file (`docs/orneur/audits/ORNEUR_GENESIS_INDEPENDENT_AUDIT077_REPORT.md`, `tests/test_audit077_master_requalification.py`, branch `antigravity/genesis-audit077-master-requalification`, PR #77), audited at documentation HEAD `70747d15d1bb39b9f83d82804690d827c5a50f81` / engineering HEAD `d4228713dd37711e008ca2675062ca562d7645ca`.

**This document does not rewrite, edit, or override any independent audit finding.** Every item below is a factual, reproducible observation, quoting Antigravity's own report and test file directly, offered for Antigravity's own review and correction. Antigravity remains the party who corrects its own evidence.

---

## 1. The validated-path versus used-path mismatch was never exercised

**Audit #077's own Domain B test** (`test_audit077_domain_b_checkpoint_path_confinement_adversarial`) calls `_enforce_checkpoint_path_confinement()` **directly, in isolation**, for all five of its sub-cases — including sub-case 5, the "legitimate relative path" case:
```python
# 5. Legitimate relative path inside workspace succeeds
_enforce_checkpoint_path_confinement(cfg, "legit_subdir/ckpt.pt")
_enforce_checkpoint_path_confinement(cfg, "ckpt.pt")
```
This test never calls `save_checkpoint`/`restore_checkpoint` (the actual IPC handlers) at all, and never inspects where a file ends up on disk. At the audited commit (`d4228713...`), `_enforce_checkpoint_path_confinement()` computed a correctly-confined, resolved path but **never returned it** — every call site then passed the caller's **original, unresolved** path string to the real `save_resumable_checkpoint()`/`restore_resumable_checkpoint()` calls instead. For a relative path like `"ckpt.pt"`, these are two different filesystem targets: validation checked `(workspace / "ckpt.pt").resolve()`, but the actual write landed wherever `Path("ckpt.pt")` resolves relative to the **worker process's own current working directory** — not the configured workspace. Because the audit's own test calls the validation helper only, and never performs the real save/restore, it could not have observed this divergence, by construction.

**Independently reproduced, before fixing**, via a minimal repro script: a relative path passed the (then-unreturning) validation function while the actual checkpoint file was written outside the configured workspace entirely. **Fixed**: `_enforce_checkpoint_path_confinement()` now returns the resolved, validated path, and both `save_checkpoint`/`restore_checkpoint` handlers use exactly that return value — never the caller's original string — for the real filesystem operation. New regression tests (`tests/test_genesis_isolated_worker.py::test_audit077_relative_checkpoint_path_is_actually_written_inside_the_workspace`, `test_audit077_relative_checkpoint_path_round_trips_by_the_same_relative_name`) exercise the **actual IPC handlers**, not the helper alone, and would have caught this before it reached production use.

**Requested**: Domain B's test should be extended (or a companion test added) to call `save_checkpoint`/`restore_checkpoint` through a live `IsolatedTrainingWorker` and verify the file's actual on-disk location, not only the validation helper's return behavior.

---

## 2. No dynamic symlink-swap/race qualification was attempted

Antigravity's own report, Domain 2, item 5, states: *"Residual TOCTOU Boundary: POSIX filesystems without `openat` and `O_NOFOLLOW` possess an inherent race condition if an external unconfined process swaps or renames parent directories between path validation and atomic replacement."* This is an accurate, honest acknowledgment — but no test in `tests/test_audit077_master_requalification.py` attempts to exercise it. Domain B's symlink test (`test_audit077_domain_b_checkpoint_path_confinement_adversarial`, sub-case 3) only tests a **pre-planted, static** symlink present before validation begins — never a symlink substituted dynamically, timed to land between validation and use.

This phase added `tests/test_genesis_isolated_worker.py::test_audit077_destination_substitution_after_validation_is_incidentally_defeated_by_atomic_rename`, which injects exactly such a substitution via monkeypatching the validation call site. The result, verified directly rather than assumed: this specific substitution shape (swapping the final target NAME) does **not** succeed, because `save_resumable_checkpoint()`'s pre-existing atomic-write discipline (`tempfile.mkstemp()` + `os.replace()`) incidentally defeats it — POSIX `rename()` replaces whatever sits at the destination name rather than following it. This is a genuine, verified finding, but it covers only one substitution shape; a parent-directory-component swap, or a substitution landing during the temp file's own write, remain untested and are not claimed closed by this phase either.

**Requested**: Antigravity's own future requalification should include a dynamic-race test (not only a static pre-planted symlink) to independently confirm or refute this phase's own finding about the atomic-rename's incidental protection.

---

## 3. "Bit-exact" is used to describe a tolerance-based comparison

**Antigravity's own report, Domain 5 / Table row 10** states: *"Model parameter tensors: Every named parameter matched with max|p_a - p_b| < 10^-7 (bit-exact on CPU)."* The test itself (`test_audit077_domain_e_exact_restart_equivalence_on_synthetic_stream`) asserts `max_diff < 1e-6` — a **tolerance-based** floating-point comparison, not bit-exact equality. "Bit-exact" means byte-for-byte identical IEEE-754 bit patterns (zero difference); `max_diff < 1e-6` is a real, legitimate, and strong equivalence claim, but it is a different, weaker claim than "bit-exact," and conflating the two overstates what was actually verified. This codebase's own established convention (used consistently throughout this phase's own reports) is to state the exact comparison method and its explicit tolerance, and never describe a tolerance-based result as bit-identical.

**Requested**: replace "bit-exact on CPU" with language stating the actual comparison performed (`torch.allclose`-equivalent, `atol`/tolerance explicitly named) in the report's Domain 5 section and the Table-10 verdict cell.

---

## 4. The restart-equivalence test is in-process, not isolated-worker-based

`test_audit077_domain_e_exact_restart_equivalence_on_synthetic_stream` constructs `GenesisTransformer`/`TrainingStepEngine` **directly in the test process** and calls `engine.step(..., capability=ExecutionCapability.for_unchecked_synthetic_test())` — it never constructs or touches an `IsolatedTrainingWorker` at all. This is a legitimate, valid test of `TrainingStepEngine`'s own resumption mechanics, but it is a different, narrower claim than a genuine cross-process worker restart (two **separately spawned OS processes**, communicating only over the real IPC protocol, with the model/optimizer never directly accessible to the test process). Table row 10's "QUALIFIED" verdict for "Determinism & Restart Equivalence" does not distinguish between the two.

This phase's own `tests/test_genesis_end_to_end_synthetic_integration.py::test_restart_equivalence_against_uninterrupted_training` performs the genuinely cross-process version — two independently-spawned `IsolatedTrainingWorker` processes, real IPC `save_checkpoint`/`restore_checkpoint` commands, with every comparison (parameters, optimizer state, step/scheduler progression, sampler position, probe loss, held-out accuracy) stated with its own explicit, non-bit-exact tolerance.

**Requested**: Domain 5 / Table row 10 should note which claim (in-process engine resumption vs. genuine cross-process worker restart) each piece of evidence supports, rather than treating them as equivalent.

---

## 5. Cross-run checkpoint migration was found but not qualified as requiring authorization

**Antigravity's own report, Domain 3, finding 2**, states: *"`run_id` is NOT part of the checkpoint HMAC tag... When `run_B` is launched with identical model/dataset configs and the same integrity key, it can restore `run_A`'s checkpoint, initializing `run_B`'s ledger at step 10. This is structurally legitimate for checkpoint migration between runs, provided caller authorization and key custody are maintained."* "Boundary 3" in the same report recommends an "explicit migration authorization receipt signed by founder authority... in Phase 2" as a **future** enhancement, not a required fix at the time of that audit.

At the audited commit, no such authorization gate existed at all — a checkpoint saved under one `run_id` could be restored under any other `run_id` with no separate authorization step, as long as `config_fingerprint`/`dataset_identity`/`integrity_key` happened to match. Describing this as "structurally legitimate... provided caller authorization... [is] maintained" assumes a caller-side discipline the code itself did not enforce.

**Fixed, this phase**: the resumable-checkpoint manifest now carries an HMAC-bound `owning_run_id`; `restore_resumable_checkpoint()` requires `manifest.owning_run_id == run_id` by default, raising `CrossRunCheckpointAccessError` otherwise, with a new, explicitly-named `allow_cross_run_migration: bool = False` parameter for a deliberate, operator-driven migration (never exposed over the untrusted worker IPC surface). Reproducing Audit #077's own Domain C test (`tests/test_audit077_master_requalification.py`, imported verbatim into this repo for provenance) against the now-fixed code: `test_audit077_domain_c_checkpoint_ledger_monotonicity_and_cross_run_boundary` now **fails** at the point it demonstrates `run_B` successfully restoring `run_A`'s checkpoint — the intended, documented flip confirming the gap it found is now closed by default.

**Requested**: Domain 3 / Boundary 3 should be updated to reflect that cross-run restoration is now rejected by default (not "structurally legitimate" without qualification), with migration available only via the new, explicit, non-IPC-exposed parameter.

---

## 6. The report's own "Unresolved Architectural Boundaries" list omits two previously-established limitations

Antigravity's Audit #077 report lists exactly three unresolved boundaries (local filesystem ledger replay; tokenizer internal memory; cross-run migration authority). It does **not** restate two limitations Audits #075/#076 already established and that remain genuinely unresolved:
- **Same-UID worker security**: a same-uid co-resident process can still `ptrace`/read `/proc/<pid>/mem` of the worker absent a genuine `drop_to_uid` (which requires root and was never exercised end-to-end).
- **Unkeyed block-store cache integrity**: the derived block-store's per-block digest is plain SHA-256, not an HMAC, so a coordinated rewrite of store+digests+manifest together remains undetected.

Neither is independently remediated by this phase's own work, and the CTO's own directive requires both to "remain explicitly documented unless independently remediated." Their absence from Audit #077's own boundary list is a factual gap in that report's completeness, not a claim that either is newly resolved.

**Requested**: add these two items back to the "Unresolved Architectural Boundaries" section (as Boundary 4 and 5, or merged into the existing numbering), explicitly, so a reader of Audit #077 alone does not conclude they were resolved somewhere between Audit #076 and #077.

---

## 7. No observed exact-head CI execution of the new Audit #077 test suite itself

Antigravity's report's Section 1 cites 9 passing GitHub Actions CI jobs on commit `70747d15d1bb39b9f83d82804690d827c5a50f81` (run `39155014743`). That commit is PR #73's own history **before** `tests/test_audit077_master_requalification.py` existed anywhere in it — the file lives only on Antigravity's own audit branch (`antigravity/genesis-audit077-master-requalification`), which was never merged into, or run through CI as part of, PR #73. The report's own "Local Test Suite Qualification" section is explicit that the 9 new Audit #077 tests were run **locally** ("Antigravity constructed a new adversarial test suite... All 9 tests passed"), not via an observed CI execution of that file. The cited CI run's "all 9 jobs green" is a true, but separate, fact about an earlier commit's own (already-existing) test files — it does not constitute CI evidence for the NEW Audit #077 suite specifically.

This phase imported `tests/test_audit077_master_requalification.py` verbatim into this repo for provenance, and (consistent with this project's own established practice) will push it alongside this phase's own corrective commits so that a genuine, observed, exact-head CI run against it can be reported honestly in this phase's own final engineering report — not assumed from the earlier, unrelated CI run Audit #077's report cites.

**Requested**: Section 1 should distinguish "CI passed on an earlier commit that predates the new test file" from "the new test file itself was observed to pass in a real CI job," which it was not, at the time of that report.
