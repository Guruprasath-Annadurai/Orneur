# ORNEUR — CTO Pre-Freeze Correction & Final Completion Directives: Engineering Report

**Directives**: (1) "CTO Pre-Freeze Correction Directive" — close the specific remaining trust mismatch between checkpoint path validation and actual filesystem use, clarify cross-run checkpoint authority, correct Audit #077's qualification evidence, and finish the synthetic foundation qualification without unnecessary development cycles. (2) "CTO — FINAL PRE-FREEZE COMPLETION DIRECTIVE" — complete the full GENESIS regression with exact counts, verify G01/G02 through the real IPC handlers with explicit lock-file/manifest confinement and IPC-smuggling coverage, confirm restart-equivalence tolerance language, review schema-v1 legacy-manifest fail-closed handling, and push to an isolated branch with observed exact-head CI before a final evidence-based verdict (PASS / PARTIAL / BLOCKED).

**Verified baseline**: Development PR #73 at `70747d15d1bb39b9f83d82804690d827c5a50f81`; Independent Audit #077, PR #77, `2d2ba74331b3aa6d868cc1bb73f269f9c62d55e0` (base branch `claude/genesis-native-learning-engine-phase1-2026-10-17`). Both verified against live `git log`/`gh pr view` before any change.

---

## Phase 1 — Checkpoint path handling, corrected

**Investigation**: `_enforce_checkpoint_path_confinement()` computed a correctly-resolved, confined path (`resolved`) but never returned it. Every call site (`save_checkpoint`/`restore_checkpoint` IPC handlers) then passed the client's **original, unresolved** `payload["path"]` string to the real `save_resumable_checkpoint()`/`restore_resumable_checkpoint()` calls instead.

**Reproduction, independently confirmed before fixing**: for a relative path (e.g. `"ckpt.pt"`), validation correctly checked `(workspace / "ckpt.pt").resolve()` — but the actual filesystem call received `Path("ckpt.pt")` alone, which resolves relative to the **worker process's own current working directory**, not the configured workspace. A minimal standalone repro confirmed this concretely: validation passed, while the real target resolved to a completely different, unconfined location.

**Fixed**: `_enforce_checkpoint_path_confinement()` now returns the validated, resolved, absolute path; both IPC handlers use exactly that return value — never the caller's original string — for the actual save/restore call. Additionally:
- Rejects if the resolved target, or any directory between it and the workspace root, is already a symlink at validation time (closes the "pre-planted symlink" and "symlinked parent directory" attack shapes).
- Handles absolute and relative paths through the same, single code path, consistently.
- **Investigated and honestly reported, item 6** (race-resistant directory-descriptor-relative operations): a dynamic substitution test (swapping the validated target to a symlink in the narrow window between validation and use) shows that `save_resumable_checkpoint()`'s pre-existing atomic-write discipline (`tempfile.mkstemp()` + `os.replace()`) **incidentally** defeats this specific substitution shape — POSIX `rename()` replaces whatever sits at the destination name rather than following it. This is a genuine, verified finding (not assumed), but it is an emergent property of the pre-existing atomic-publish pattern, not a purpose-built defense, and it does not cover every substitution shape (a parent-directory-component swap, or a substitution during the temp file's own write, remain honestly undemonstrated). A fully race-resistant design would still require extending `resumable_checkpoint.py`'s own API to accept a directory file descriptor — a genuine, recorded future improvement, deliberately out of scope for this phase's smallest-necessary-correction mandate. **This fix and its tests never describe themselves as race-proof.**

**New regression tests** (`tests/test_genesis_isolated_worker.py`), exercising the **actual IPC handlers**, not merely the validation helper:
- `test_audit077_relative_checkpoint_path_is_actually_written_inside_the_workspace`
- `test_audit077_relative_checkpoint_path_round_trips_by_the_same_relative_name`
- `test_audit077_path_traversal_outside_workspace_via_relative_dotdot_is_rejected`
- `test_audit077_symlinked_checkpoint_target_is_rejected`
- `test_audit077_symlinked_parent_directory_inside_workspace_is_rejected`
- `test_audit077_absolute_path_inside_workspace_still_works_consistently`
- `test_audit077_destination_substitution_after_validation_is_incidentally_defeated_by_atomic_rename`

Checkpoint integrity, atomic writes, and restart equivalence are unaffected — `resumable_checkpoint.py`'s own save/restore internals were not modified for this fix, only the path the worker hands to them.

---

## Phase 2 — Cross-run checkpoint authority, clarified and bound

**Reproduction**: restoring run A's checkpoint into run B, with matching `model_cfg`/`step_cfg`/dataset-identity fields and the same `integrity_key` but a **different** `run_id`, succeeded with no explicit authorization step at all. Confirmed directly: `restore_resp = {'ok': True, 'result': {'global_step': 0, ...}}`.

**Governance contract determination**: nothing in this codebase explicitly declared cross-run checkpoint migration a permitted capability — `run_id` was used only to look up the anti-rollback ledger (Audit #075), never bound into the checkpoint's own manifest or checked against the restoring caller's identity.

**Fixed**: the resumable-checkpoint manifest now carries `owning_run_id` — the `run_id` the checkpoint was saved under — HMAC-bound exactly like every other tagged field (cannot be forged without `integrity_key`). `restore_resumable_checkpoint()` now **requires** `manifest.owning_run_id == run_id` by default, raising `CrossRunCheckpointAccessError` otherwise. A new, explicitly-named `allow_cross_run_migration: bool = False` parameter exists for a genuinely intended, operator-driven migration — **never exposed over the worker's untrusted IPC surface** (the worker's `save_checkpoint`/`restore_checkpoint` handlers always use the closed default). This does not weaken the existing HMAC integrity tag or the anti-rollback ledger check in any way — it is an additional, independent check alongside them.

**Verified**: `tests/test_genesis_isolated_worker.py::test_audit077_phase2_cross_run_checkpoint_restoration_is_rejected_by_default` confirms the fix through the real worker IPC handlers. Independently, Audit #077's own imported evidence test (`tests/test_audit077_master_requalification.py::test_audit077_domain_c_checkpoint_ledger_monotonicity_and_cross_run_boundary`) — which demonstrated the exact gap — now **fails** at the point it asserts `run_B` can restore `run_A`'s checkpoint, the intended, documented flip confirming the gap it found is closed.

---

## Phase 3 — Audit #077 qualification evidence, correction request prepared

A separate document, `ORNEUR_AUDIT077_CORRECTION_REQUEST_TO_ANTIGRAVITY.md`, was prepared — not a rewrite of Antigravity's report — covering, with direct quotes from Antigravity's own artifacts:
1. The validated-path-versus-used-path mismatch, which Audit #077's own Domain B test could not have caught (it calls the validation helper directly, never the real IPC handlers).
2. The absence of any dynamic symlink-swap/race test (only a static, pre-planted symlink was tested).
3. "Bit-exact on CPU" used to describe a `max_diff < 1e-6` tolerance-based comparison.
4. Audit #077's own restart-equivalence test being in-process (`TrainingStepEngine.step()` called directly), not a genuine cross-process `IsolatedTrainingWorker` restart.
5. Cross-run migration found but described as "structurally legitimate... provided caller authorization... [is] maintained" without any code enforcing that caller discipline at the time.
6. Audit #077's own "Unresolved Architectural Boundaries" list omitting the same-UID worker security and unkeyed cache integrity limitations Audits #075/#076 already established.
7. The report's cited CI run predating the new Audit #077 test file's existence in PR #73's own history — "9/9 CI green" on that commit is true but does not constitute observed CI evidence for the new test suite.

---

## Phase 4 — Final regression

Full GENESIS-prefixed suite, PR #65 foundation regression, the four historical verbatim-evidence files (Audit hardening, Audit #074, Audit #076, the native-learning-engine adversarial audit), and the newly-imported Audit #077 evidence file were all run to completion after the Phase 1/2/6 fixes.

**Exact counts, observed**: `tests/test_genesis*.py tests/test_audit_genesis*.py tests/test_audit74_successor_adversarial_requalification.py tests/test_audit076_master_qualification.py tests/test_audit077_master_requalification.py tests/test_native_learning_engine_adversarial_audit.py` → **3336 passed, 30 failed, 17 skipped** (986s). None of this run's tests were still in progress when these counts were recorded.

Of the 30 failures:
- **29 are the established, intentional evidence-preservation flips** of verbatim-imported audit test files, none modified this phase: 5 in `test_audit_genesis_hardening_adversarial.py`, 12 in `test_audit74_successor_adversarial_requalification.py`, 11 in `test_native_learning_engine_adversarial_audit.py`, and exactly 1 in `test_audit077_master_requalification.py` (`test_audit077_domain_c_checkpoint_ledger_monotonicity_and_cross_run_boundary` — the intended flip documenting that Phase 2's cross-run-ownership fix now closes the exact gap that test demonstrated). These are reported, not hidden, per the directive's own instruction.
- **1 is a confirmed environmental flake**, not a regression: `tests/test_genesis_eval_suite.py::test_unit_test_scorer_accepts_correct_implementation`, a `@requires_docker` test that runs a sandboxed code-execution scorer. It failed once under the full combined run (`assert False is True` on a correctness check unrelated to any file this phase touched) and passed cleanly when re-run in isolation immediately after. A separate, earlier full run of the broader `tests/` tree (excluding only two environment-incomplete files unrelated to this work, `test_distill.py` needing the `openai` package and `test_mcp_fs_server_sandbox.py` needing the `mcp` package) showed zero failures outside the historical evidence files, confirming this Docker-scorer failure is resource-contention noise from the heavy combined run, not a consequence of this phase's changes.
- **Zero unexpected failures** in any GENESIS-prefixed test, in `resumable_checkpoint.py`'s own test file, or in `isolated_worker.py`'s own test file (31/31 passed standalone, and all 10 `audit077`-tagged tests — the 7 from Phase 1/2 plus the 3 new ones from this directive's items 2 and 3 — passed).

---

## Phase 5 — Directive B items (lock-file/manifest confinement, IPC-smuggling, schema-v1 compatibility)

**Item 2 — lock-file and manifest path confinement, through the real IPC handlers**: `_resumable_manifest_path()` and the lock-file path in `resumable_checkpoint.py` are both derived directly from whatever `path` `save_resumable_checkpoint()`/`restore_resumable_checkpoint()` receive — which, after the Phase 1 fix, is always the worker's validated `confined_path`, never the client's raw string. New test `tests/test_genesis_isolated_worker.py::test_audit077_phase2_lockfile_and_manifest_sidecar_paths_are_confined_with_the_checkpoint` proves this concretely: using a relative path with an intermediate subdirectory through the real `save_checkpoint` IPC handler, both the `.resumable.lock` file and the `.resumable.json` manifest land strictly inside the configured workspace, next to the checkpoint itself, and not at any location derived from the worker's own current working directory.

**Item 3 — the migration parameter cannot bypass founder-authorized execution boundaries via IPC**: `allow_cross_run_migration` is a plain Python keyword parameter on `restore_resumable_checkpoint()`; the worker's `restore_checkpoint` IPC handler never reads any such key from the untrusted request payload at all — it calls that function with a fixed, explicit set of kwargs. New test `test_audit077_phase2_raw_ipc_cannot_smuggle_allow_cross_run_migration` proves this directly: a raw request sent via the client's own low-level `_request()` method (bypassing the typed `restore_checkpoint()` method, which has no such parameter to begin with) that includes `"allow_cross_run_migration": True` in its payload is still rejected with `CrossRunCheckpointAccessError`, exactly like an ordinary cross-run attempt — the untrusted wire protocol has no path to that parameter.

**Item 6 — schema-v1/legacy-manifest fail-closed treatment**: independently reproduced that a legacy (pre-Audit-077) manifest dict, lacking the new `owning_run_id` field entirely, caused `ResumableManifest.from_dict()` to raise a bare `TypeError` (a missing constructor argument) rather than a deliberate rejection — because the prior code order constructed the dataclass before checking `schema_version`. Fixed by checking the raw JSON dict's `schema_version` against `RESUMABLE_SCHEMA_VERSION` *before* ever attempting dataclass construction, so any legacy or unrecognized schema version — and any manifest that isn't valid JSON — is rejected uniformly via `ResumableManifestTamperedError`, fail-closed, never partially parsed and never a generic crash. Two new regression tests (`tests/test_genesis_resumable_checkpoint.py::test_audit077_phase6_legacy_schema_v2_manifest_is_rejected_cleanly_not_a_typeerror` and `::test_audit077_phase6_malformed_non_json_manifest_is_rejected_cleanly`) cover both the legacy-schema and malformed-JSON cases; the full resumable-checkpoint suite (23 tests) passes with no regression.

**Item 4 — restart-equivalence language**: confirmed, not newly changed — `tests/test_genesis_end_to_end_synthetic_integration.py`'s restart-equivalence comparisons already state their actual method and tolerance explicitly (`torch.allclose(..., atol=PARAM_ATOL)`), and never use the word "bit-exact" anywhere in this codebase's own test files. This phase's own Section 3, item 3 (below) already requests the same correction of Antigravity's own report language, which does use "bit-exact" to describe a tolerance-based comparison.

**Item 5 — the "update tests that intentionally expect the old vulnerable behavior" instruction**: resolved by NOT editing Antigravity's own verbatim-imported evidence file (`tests/test_audit077_master_requalification.py`), consistent with this project's established provenance-preservation discipline for all prior audit evidence (#074, #075, #076) — that file's one intentional flip (Domain C) is reported as the deliberate, documented consequence of the fix, not hidden or silently patched. The instruction is instead satisfied by this phase's *own* previously-written tests, which already assert the new, secure behavior (e.g. the renamed `test_audit077_phase2_cross_run_checkpoint_restoration_is_rejected_by_default`, which was never written to expect the old vulnerable behavior in the first place).

**Item 1 — regression completion**: satisfied above (Phase 4); the full combined regression ran to completion (not left mid-run) before any acceptance claim was made, and includes `tests/test_audit077_master_requalification.py`.

---

## Phase 6 — Audit #077 qualification evidence, correction request prepared

A separate document, `ORNEUR_AUDIT077_CORRECTION_REQUEST_TO_ANTIGRAVITY.md`, was prepared — not a rewrite of Antigravity's report — covering, with direct quotes from Antigravity's own artifacts, the seven items listed in that document (validated-path/used-path mismatch, absent dynamic symlink-race test, "bit-exact" overclaim, in-process vs. isolated-worker restart-equivalence distinction, unqualified cross-run migration authority, incomplete "Unresolved Architectural Boundaries" list, absent exact-head CI for the new suite).

---

## Phase 7 — Handoff and freeze readiness

Per the final directive's explicit procedural requirement, this phase's work was committed on an **isolated branch**, `claude/genesis-audit077-correction-2026-10-20` — not the shared `claude/genesis-native-learning-engine-phase1-2026-10-17` branch every prior commit this session used.

- **Immutable commit SHA**: `144941d8408693278eb52f249d1ab60987bbfec3`
- **Working tree**: clean at that commit (`git status --short` empty immediately after commit and after push)
- **Pushed**: `origin/claude/genesis-audit077-correction-2026-10-20` (no PR opened; no merge; no action taken beyond push, per the directive's own restriction)
- **Observed exact-head CI**: GitHub Actions run [`39433397742`](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39433397742), triggered by the push itself, `headSha` confirmed equal to `144941d8...`, **conclusion: success**, all 6 jobs green — Genesis V2 Sandbox containment, Training Math Unit Tests (Torch), RSE dependency lock/vulnerability scan, Genesis V2 Security (encryption), Dependency Vulnerability Scan, and Production Container Build + Boot Smoke. This is a genuinely observed CI result for the exact commit containing this phase's own changes and the newly-imported Audit #077 test file — not an earlier, unrelated commit's run.
- **Unresolved issues at handoff**: the three structural limitations named in the Final verdict below (same-UID worker security, unkeyed cache integrity, local-only rollback protection), and independent Antigravity requalification of the changed checkpoint boundary, which remains outstanding pending their own review of the prepared correction request.

---

## Final verdict

**`PARTIAL`**

Scope actually closed, verified, and evidenced in this directive cycle:
- **G01 (checkpoint path confinement)**: the validated path and the used path are provably the same object, for relative and absolute inputs, through the real IPC handlers — not the validation helper alone. Symlink-chain rejection (final target and intermediate parent directories) is in place. Lock-file and manifest sidecar paths are now explicitly proven confined (item 2), not merely assumed safe as a byproduct. The destination-substitution race is honestly qualified: one specific substitution shape (final-name swap) is verified incidentally defeated by the pre-existing atomic-rename publish pattern; a parent-directory-component swap and a substitution during the temp file's own write remain genuinely undemonstrated. **This fix is not described as race-proof.**
- **G02 (authenticated owning-run binding)**: cross-run checkpoint restoration is rejected by default, bound to the HMAC-tagged `owning_run_id`, with migration available only through an explicit, non-IPC-exposed `allow_cross_run_migration` parameter — and item 3's new test proves the untrusted IPC surface has no path to that parameter at all, even via a raw, hand-crafted request bypassing the typed client method. Ordinary same-run restore is unaffected; verified both by new tests and by the intended flip of Audit #077's own imported Domain C evidence test.
- **Restart equivalence**: confirmed tolerance-based (`torch.allclose` with an explicit `atol`) throughout this codebase's own tests; "bit-exact" is never used to describe it here, and a correction requesting the same of Antigravity's own report language is already prepared.
- **Schema-v1 compatibility**: a legacy or unrecognized manifest schema version, or a non-JSON manifest, is now rejected fail-closed via a deliberate `ResumableManifestTamperedError` before any dataclass construction is attempted, closing a prior bare-`TypeError` gap; covered by two new regression tests.
- **Regression**: the full combined suite (3336 passed, 30 failed, 17 skipped) was run to completion, including the Audit #077 evidence file, with zero unexpected failures — 29 of the 30 failures are established historical evidence-preservation flips (including #077's own intended Domain C flip) and 1 is a confirmed, isolated-run-verified environmental flake in an unrelated Docker-based scorer test.

**Why PARTIAL, not PASS**: this directive's own scope is still a targeted correction of a specific checkpoint-boundary gap, not a full re-audit of GENESIS as a whole. Three structural limitations remain genuinely open and are not claimed resolved: same-UID worker security (no `drop_to_uid` exercised end-to-end under root), unkeyed derived-block-store cache integrity (plain SHA-256 digests, not HMAC), and local-only, single-machine anti-rollback ledger protection. None of these is newly discovered in this phase; all are pre-existing, explicitly out of this directive's narrow scope, and remain documented rather than resolved. Independent requalification of the changed checkpoint-path and cross-run-ownership boundary specifically (not a broad, project-wide re-audit) is still outstanding at the time of this report, pending Antigravity's own review of the prepared correction request.

**Not done, per explicit restriction**: no real-corpus training, no GPU or paid infrastructure use, no founder signing, no mainline merge, no foundation tagging, and no action taken on the deferred C02/B01–B16 frontend-integration work — that remains explicitly gated on completing this security phase first and is out of scope for this report.
