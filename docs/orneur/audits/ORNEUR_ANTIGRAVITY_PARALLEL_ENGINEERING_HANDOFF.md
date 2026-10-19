# ORNEUR ANTIGRAVITY PARALLEL ENGINEERING HANDOFF
## Mission Backend Qualification + GENESIS Adversarial Security Tests

**Document ID:** ORNEUR-HANDOFF-AGY-SPRINT-003 (Final Test-Handoff Correction)  
**Status:** `READY FOR TARGETED CLAUDE REPAIR`  
**Date:** 19 October 2026  
**From:** Antigravity / Gemini Engineering & Independent Audit Agent  
**To:** GPT-6 (ORNEUR CTO) & Claude Code Engineering Agent  
**Operational Window:** Ready for Claude execution upon credit reset (20 October 2026 at 5:30 PM IST)  
**Branch:** `antigravity/sprint-c02-mission-and-genesis-security`  
**Test Suite Status:** LOCAL ONLY — **19 Passed, 2 Xfailed, 0 Failed, 0 Skipped in 15.41s**  
**Training Authorization:** NO-GO  
**GPU Expenditure:** ₹0  

---

## 1. Executive Summary & Corrected Qualification Posture

In response to CTO corrective instructions, Antigravity has revised all test suites, matrix mappings, and transport contracts to eliminate overstated claims:

- **C02 Security Status:** Domain business logic, state transitions, secret redaction, and access control checks in `operation_store.py` and `relay_reconnect.py` are locally verified with real domain boundaries (self-authorization rejection, tenant isolation). However, because `orca/serve/api.py` exposes zero `/api/missions` routes, and database persistence is not yet active, **C02 live execution is NOT yet production-grade end-to-end**.
- **Founder-Approved C02 State Mapping Restored:** UI states strictly preserve canonical founder designs:
  - **Variant A (Quiet Mission Brief):** Focused **Mission creation** interface.
  - **Variant B (Contextual Mission Review):** Dedicated **Pre-execution plan, scope and permission review** interface.
  - **Live Telemetry Separation:** Telemetry belongs strictly to running and tool-detail states (**C02-03** and **C02-04**), NOT as a replacement for Variant B.
  - Canonical identifiers **C02-01 through C02-12** remain unchanged.
- **Authenticated SSE Contract:** Defines a primary fetch-based streaming client (`fetch()` with `ReadableStream` / `fetchEventSource`) alongside a cookie-authenticated native fallback, enforcing server-derived tenant identity.
- **GENESIS Fix-Acceptance Test Gates:**
  - **G01:** Spawns live `IsolatedTrainingWorker` over UNIX socket IPC, proving relative paths escape to `os.getcwd()` (`test_g01_worker_ipc_vulnerability_demonstration_relative_path_escapes_to_cwd`). Desired behavior gated under strict XFAIL (`test_g01_fix_acceptance_worker_confinement_desired_behavior`).
  - **G02:** Proves cross-run restore accepted on current code without migration grant (`test_g02_vulnerability_demonstration_cross_run_restore_accepted_without_migration`). Desired rejection gated with direct `pytest.raises((ResumableManifestTamperedError, PermissionError))` under strict XFAIL (`test_g02_fix_acceptance_cross_run_restore_without_migration_denied`), with zero artificial test exceptions.
  - **G03:** Verifies key-custody and documents local monotonic ledger residual threat boundary.
- **Strict Expected-Failure Lifecycle:** Explicitly details how Claude should update/retire vulnerability demonstrations and when to remove `@pytest.mark.xfail(strict=True)` so repaired code passes CI.

---

## 2. Exact Git Lineage & Safe Integration Instructions

### 2.1 Branch Ancestry & Commit Provenance
- **Sprint Branch:** `origin/antigravity/sprint-c02-mission-and-genesis-security`
- **Immediate Branch Point:** `2d2ba74331b3aa6d868cc1bb73f269f9c62d55e0` (`antigravity/genesis-audit077-master-requalification`)
- **Upstream PR #73 Anchor:** Commit `70747d15d1bb39b9f83d82804690d827c5a50f81` on `origin/claude/genesis-native-learning-engine-phase1-2026-10-17`

### 2.2 Ordered Sprint Commit Sequence
Do NOT use `..HEAD` (which could pull unwanted upstream history). Apply only these three discrete, verified sprint commits in exact chronological order:

1. `7e54414a564191abcbf6592cd2cb4f714c9912ff` — *feat(audit-sprint): C02 mission backend qualification and GENESIS checkpoint security regressions*
2. `b0d48086ca7818c5f9c33c56b34b7a78ef1d5ede` — *fix(audit-corrective): restore founder-approved C02 mapping, invoke real security boundaries, and add fix-acceptance tests*
3. `origin/antigravity/sprint-c02-mission-and-genesis-security` (Head of audit branch) — *docs(audit-handoff): finalize C02 variant roles, live worker IPC evidence, and expected-failure lifecycle*

### 2.3 Safe Integration Command for Claude
Target development branch: `origin/claude/genesis-native-learning-engine-phase1-2026-10-17` (Draft PR #73).
```bash
# 1. Fetch the latest Antigravity sprint branch:
git fetch origin antigravity/sprint-c02-mission-and-genesis-security

# 2. Checkout or stay on Claude's PR #73 branch:
git checkout claude/genesis-native-learning-engine-phase1-2026-10-17

# 3. Cherry-pick the three discrete sprint commits in exact order:
git cherry-pick 7e54414a564191abcbf6592cd2cb4f714c9912ff
git cherry-pick b0d48086ca7818c5f9c33c56b34b7a78ef1d5ede
git cherry-pick origin/antigravity/sprint-c02-mission-and-genesis-security
```

### 2.4 Merge Conflict Risk & Isolation Analysis
- **Conflict Risk: ZERO.**
- Antigravity created **new, isolated test files** (`tests/test_c02_mission_lifecycle_security.py` and `tests/test_genesis_checkpoint_adversarial_regression.py`) and **new documentation files** in `docs/orneur/mission/` and `docs/orneur/audits/`.
- Zero lines of existing production code in `orca/` were modified in this sprint branch. Cherry-picking will cleanly apply without collisions on Claude's working tree.

---

## 3. Priority 1: C02 Live Mission Execution Qualification

### 3.1 Canonical Founder-Approved State Mapping
Documented in [`ORNEUR_C02_BACKEND_CAPABILITY_MATRIX.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/mission/ORNEUR_C02_BACKEND_CAPABILITY_MATRIX.md):
- **Variant A — Quiet Mission Brief:** Focused **Mission creation** interface. Clean, distraction-free modal/card capturing user intent, targets, objectives, and initial constraints before plan generation.
- **Variant B — Contextual Mission Review:** Dedicated **Pre-execution plan, scope and permission review** interface. Comprehensive pre-flight review displaying proposed execution DAG, requested tool permissions, blast-radius boundaries, and required supervisor sign-offs before launching execution.
- **C02-01 — Permission Request:** Subagent requests privileged tool execution.
- **C02-02 — Approval Pending:** Escalation awaiting supervisor or human authorization (strict anti-self-approval).
- **C02-03 — Mission Running:** Active execution of DAG plan steps (home of live execution telemetry).
- **C02-04 — Tool Action Details:** In-depth tool execution telemetry, parameters, duration, and output chunks.
- **C02-05 — Evidence and Outputs:** Verified intermediate outputs and guardrail evaluation receipts.
- **C02-06 — Waiting for User Input:** Paused awaiting interactive user clarification or data.
- **C02-07 — Failed / Interrupted:** Error or interruption occurred; diagnostic trace sanitized.
- **C02-08 — Cancellation Requested:** Graceful wind-down in flight; awaiting subagent halt.
- **C02-09 — Mission Cancelled:** Terminal cancelled state.
- **C02-10 — Resume Review:** Revision conflict comparison prior to resuming paused/failed mission.
- **C02-11 — Mission Completed:** Terminal success verified with non-empty evidence proof.
- **C02-12 — Mission History:** Chronological audit log of operations and decisions.

### 3.2 Corrected Security Test Evidence (`tests/test_c02_mission_lifecycle_security.py`)
Documented in [`ORNEUR_C02_MISSION_SECURITY_TEST_REPORT.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/mission/ORNEUR_C02_MISSION_SECURITY_TEST_REPORT.md):
- `test_permission_self_authorization_strictly_prevented`: Directly invokes `authorize_operation()` from `orca.mission.operation_store`, verifying that `approved_by == requested_by` raises `SelfAuthorizationError` and rolls back before reaching godmode. Third-party approval succeeds.
- `test_mission_history_cannot_leak_across_users_or_tenants`: Directly invokes `reconcile_operation()` from `orca.mission.relay_reconnect`, verifying cross-mission and cross-user lookups raise `RelayReconnectAccessDeniedError`.
- **Test Output:** `12 passed in 0.93s` (**LOCAL ONLY**).

### 3.3 Corrected Transport Contract
Documented in [`ORNEUR_C02_FRONTEND_INTEGRATION_CONTRACT.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/mission/ORNEUR_C02_FRONTEND_INTEGRATION_CONTRACT.md):
- Unified route: `GET /api/missions/{mission_id}/events`
- Unified plan decision: `POST /api/missions/{mission_id}/plan/decision`
- Primary Transport: Fetch-based streaming client (`fetch()` + `ReadableStream` / `fetchEventSource`) with `Authorization: Bearer <token>`.
- Fallback Transport: `EventSource` with `HttpOnly`, `SameSite=Strict`, `__Host-` session cookie.
- Server-Derived Tenancy: `tenant_id` is extracted strictly server-side from validated session/JWT claims; client `X-Tenant-ID` is rejected as an authorization claim.
- Reconnection & Replay: `Last-Event-ID` replayed from a 1,000-event ring buffer; expired history returns HTTP 410 Gone with `REPLAY_HORIZON_EXCEEDED`, prompting full resync.
- DLP Redaction: All text streamed over SSE passes through `orca.serve.dlp` / `redact_secrets()`.

---

## 4. Priority 2: GENESIS Checkpoint Hardening (G01, G02, G03)

Documented in [`ORNEUR_GENESIS_CHECKPOINT_ADVERSARIAL_REPORT.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/audits/ORNEUR_GENESIS_CHECKPOINT_ADVERSARIAL_REPORT.md), [`ORNEUR_GENESIS_CROSS_RUN_AUTHORITY_REPORT.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/audits/ORNEUR_GENESIS_CROSS_RUN_AUTHORITY_REPORT.md), and [`ORNEUR_GENESIS_SECURITY_REGRESSION_HANDOFF.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/audits/ORNEUR_GENESIS_SECURITY_REGRESSION_HANDOFF.md):

| Finding | Defect Summary | Vulnerability Reproduction | Fix-Acceptance Test Gate | Acceptance Criteria for Claude |
|---|---|---|---|---|
| **G01** | Relative path writes to `os.getcwd()` instead of workspace; dynamic symlink TOCTOU window. | `test_g01_worker_ipc_vulnerability_demonstration_relative_path_escapes_to_cwd` (Live worker process over UNIX IPC: PASSED), `test_g01_dynamic_symlink_substitution_toctou` (PASSED) | `test_g01_fix_acceptance_worker_confinement_desired_behavior` (XFAIL) | Return resolved path from `_enforce_checkpoint_path_confinement` and pass it to save/restore. Checkpoint must land in workspace and not CWD. |
| **G02** | `ResumableManifest` HMAC tag omits `run_id`, allowing Run B to restore Run A's state without migration grant. | `test_g02_vulnerability_demonstration_cross_run_restore_accepted_without_migration` (PASSED) | `test_g02_fix_acceptance_cross_run_restore_without_migration_denied` (XFAIL) | Add `origin_run_id` to manifest and HMAC tag payload. Must raise `PermissionError` or `ResumableManifestTamperedError` on cross-run restore without migration grant. |
| **G03** | Local anti-rollback ledger can be rolled back in lockstep if an attacker has full filesystem write access. | `test_g03_integrity_key_custody_and_local_ledger_replay_limitation` (PASSED) | Documented residual boundary under local threat model. | Trusted controller holds key; worker checks entropy; monotonic ledger protects against accidental rollback. |

---

## 5. Local Test Execution Ledger

```
tests/test_c02_mission_lifecycle_security.py ............                [ 57%]
tests/test_genesis_checkpoint_adversarial_regression.py ....x..x.        [100%]
======================== 19 passed, 2 xfailed in 15.41s ========================
```
*Note: All results are LOCAL ONLY. Remote GitHub CI has not been triggered for this branch.*

---

## 6. Prioritized Correction Checklist for Claude (20 Oct 5:30 PM IST)

When Claude Code credits reset, follow this targeted repair sequence:

- [ ] **1. Review Sprint Handoff:**
  Inspect [`docs/orneur/audits/ORNEUR_ANTIGRAVITY_PARALLEL_ENGINEERING_HANDOFF.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/audits/ORNEUR_ANTIGRAVITY_PARALLEL_ENGINEERING_HANDOFF.md).
- [ ] **2. Cherry-Pick the Discrete Sprint Commits in Exact Order:**
  ```bash
  git fetch origin antigravity/sprint-c02-mission-and-genesis-security
  git checkout claude/genesis-native-learning-engine-phase1-2026-10-17
  git cherry-pick 7e54414a564191abcbf6592cd2cb4f714c9912ff
  git cherry-pick b0d48086ca7818c5f9c33c56b34b7a78ef1d5ede
  git cherry-pick origin/antigravity/sprint-c02-mission-and-genesis-security
  ```
- [ ] **3. Run Baseline Test Suite:**
  ```bash
  uv run --no-sync --frozen --with torch --with numpy --with sentencepiece --with cryptography pytest tests/test_c02_mission_lifecycle_security.py tests/test_genesis_checkpoint_adversarial_regression.py -v
  ```
  Expected baseline: `19 passed, 2 xfailed`.
- [ ] **4. Fix G01 Workspace Confinement (`isolated_worker.py`):**
  Update `_enforce_checkpoint_path_confinement` to return the resolved path anchored to `cfg.checkpoint_workspace_dir`, and pass `path=safe_path` in `_handle_save_checkpoint` and `_handle_restore_checkpoint`.
  Remove `@pytest.mark.xfail(strict=True)` from `test_g01_fix_acceptance_worker_confinement_desired_behavior`.
  Retire or update `test_g01_worker_ipc_vulnerability_demonstration_relative_path_escapes_to_cwd`.
- [ ] **5. Fix G02 Checkpoint Run Binding (`resumable_checkpoint.py`):**
  Bump schema to `genesis-resumable-checkpoint-v2`.
  Add `origin_run_id: str` to `ResumableManifest` and include it in `_compute_manifest_hmac`.
  Update `restore_resumable_checkpoint` to enforce `manifest.origin_run_id == run_id` (raising `PermissionError` without migration grant).
  Remove `@pytest.mark.xfail(strict=True)` from `test_g02_fix_acceptance_cross_run_restore_without_migration_denied`.
  Retire or invert `test_g02_vulnerability_demonstration_cross_run_restore_accepted_without_migration`.
- [ ] **6. Add `CANCELLATION_REQUESTED` to `MissionState` (`state_machine.py`):**
  Support graceful wind-down from `RUNNING` to `CANCELLATION_REQUESTED` to `CANCELLED`.
- [ ] **7. Mount `/api/missions` Router in `orca/serve/api.py`:**
  Implement the contract specified in [`ORNEUR_C02_FRONTEND_INTEGRATION_CONTRACT.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/mission/ORNEUR_C02_FRONTEND_INTEGRATION_CONTRACT.md).
- [ ] **8. Wire Sub-Agent Pods in `index.html`:**
  Replace static `sendStarter()` prompt injection with live mission creation and SSE event streaming.
- [ ] **9. Run Full Regression Verification:**
  All 21 tests must report clean **`21 passed`** (0 failed, 0 xfailed, 0 xpassed).

