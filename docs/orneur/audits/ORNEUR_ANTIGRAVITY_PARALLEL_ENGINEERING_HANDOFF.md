# ORNEUR ANTIGRAVITY PARALLEL ENGINEERING HANDOFF
## Mission Backend Qualification + GENESIS Adversarial Security Tests

**Document ID:** ORNEUR-HANDOFF-AGY-SPRINT-002 (Corrected)  
**Status:** `READY FOR TARGETED CLAUDE REPAIR`  
**Date:** 19 October 2026  
**From:** Antigravity / Gemini Engineering & Independent Audit Agent  
**To:** GPT-6 (ORNEUR CTO) & Claude Code Engineering Agent  
**Operational Window:** Ready for Claude execution upon credit reset (20 October 2026 at 5:30 PM IST)  
**Branch:** `antigravity/sprint-c02-mission-and-genesis-security`  
**Test Suite Status:** LOCAL ONLY (18 Passed, 2 Xfailed in 5.39s)  
**Training Authorization:** NO-GO  
**GPU Expenditure:** ₹0  

---

## 1. Executive Summary & Corrected Qualification Posture

In response to CTO corrective instructions, Antigravity has revised all test suites, matrix mappings, and transport contracts to eliminate overstated claims:

- **C02 Security Status:** Domain business logic, state transitions, secret redaction, and access control checks in `operation_store.py` and `relay_reconnect.py` are locally verified. However, because `orca/serve/api.py` exposes zero `/api/missions` routes, and database persistence is not yet active, **C02 live execution is NOT yet production-grade end-to-end**.
- **Founder-Approved C02 State Mapping Restored:** UI states strictly use the canonical identifiers: Variants A & B, and C02-01 through C02-12. Domain finite-state machine states (`MissionState` enum) are kept cleanly decoupled from UI identifiers.
- **Authenticated SSE Contract Corrected:** Solves browser `EventSource` header limitations by defining a primary fetch-based streaming client (`fetch()` with `ReadableStream` / `fetchEventSource`) alongside a cookie-authenticated native fallback. Enforces server-derived tenant identity (rejecting client `X-Tenant-ID` as an authorization claim) and formalizes replay/resync rules.
- **GENESIS Fix-Acceptance Test Gates:** Preserves confirmed findings G01, G02, G03. Distinguishes vulnerability demonstrations from fix-acceptance tests using `@pytest.mark.xfail(strict=True)` to establish unambiguous gates for Claude.
- **Git Ancestry & Isolation:** Records exact branch provenance and provides a cherry-pick command sequence so Claude does not inadvertently merge unrelated audit branches.

---

## 2. Exact Git Lineage & Safe Integration Instructions

### 2.1 Branch Ancestry
- **Active Sprint Branch:** `antigravity/sprint-c02-mission-and-genesis-security`
- **Immediate Parent:** `2d2ba74331b3aa6d868cc1bb73f269f9c62d55e0` (`antigravity/genesis-audit077-master-requalification`)
- **Upstream Anchor:** PR #73 documentation commit `70747d15d1bb39b9f83d82804690d827c5a50f81`
- **Note for Claude:** This branch stems from the Audit #77 line, NOT directly from `main`. Do not merge this branch directly into `main` without isolating the sprint commits.

### 2.2 Claude Cherry-Pick Integration Command
To apply these audit deliverables cleanly onto PR #73 or `main`:
```bash
# From PR #73 or target development branch:
git cherry-pick 7e54414a564191abcbf6592cd2cb4f714c9912ff..HEAD
# Or cherry-pick the specific sprint commit:
git cherry-pick <latest_sprint_commit>
```

---

## 3. Priority 1: C02 Live Mission Execution Qualification

### 3.1 Canonical Founder-Approved State Mapping
Documented in [`ORNEUR_C02_BACKEND_CAPABILITY_MATRIX.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/mission/ORNEUR_C02_BACKEND_CAPABILITY_MATRIX.md):
- **Variant A — Quiet Mission Brief:** Compact card view for passive monitoring.
- **Variant B — Contextual Mission Review:** Expanded operational console for telemetry and inspection.
- **C02-01 — Permission Request:** Subagent requests privileged tool execution.
- **C02-02 — Approval Pending:** Escalation awaiting supervisor or human authorization (strict anti-self-approval).
- **C02-03 — Mission Running:** Active execution of DAG plan steps.
- **C02-04 — Tool Action Details:** In-depth execution telemetry, parameters, duration, and output chunks.
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
- `test_permission_self_authorization_strictly_prevented`: Directly invokes `authorize_operation()` from `orca.mission.operation_store`, verifying that `approved_by == requested_by` raises `SelfAuthorizationError` and rolls back before reaching godmode.
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
| **G01** | Relative path writes to `os.getcwd()` instead of workspace; dynamic symlink TOCTOU window. | `test_g01_checkpoint_path_confinement_relative_path_discrepancy` (PASS), `test_g01_dynamic_symlink_substitution_toctou` (PASS) | `test_g01_fix_acceptance_worker_confinement_desired_behavior` (XFAIL) | Return resolved path from `_enforce_checkpoint_path_confinement` and pass it to save/restore. Checkpoint must land in workspace. |
| **G02** | `ResumableManifest` HMAC tag omits `run_id`, allowing Run B to restore Run A's state without migration grant. | `test_g02_vulnerability_demonstration_cross_run_restore_accepted_without_migration` (PASS) | `test_g02_fix_acceptance_cross_run_restore_without_migration_denied` (XFAIL) | Add `origin_run_id` to manifest and HMAC tag payload. Cross-run restore without migration grant must be rejected. |
| **G03** | Local anti-rollback ledger can be rolled back in lockstep if an attacker has full filesystem write access. | `test_g03_integrity_key_custody_and_local_ledger_replay_limitation` (PASS) | Documented residual boundary under local threat model. | Trusted controller holds key; worker checks entropy; monotonic ledger protects against accidental rollback. |

---

## 5. Local Test Execution Ledger

```
tests/test_c02_mission_lifecycle_security.py ............                [ 60%]
tests/test_genesis_checkpoint_adversarial_regression.py ........        [100%]
======================== 18 passed, 2 xfailed in 5.39s =========================
```
*Note: All results are LOCAL ONLY. Remote GitHub CI has not been triggered for this branch.*

---

## 6. Prioritized Correction Checklist for Claude (20 Oct 5:30 PM IST)

When Claude Code credits reset, follow this targeted repair sequence:

- [ ] **1. Review Sprint Handoff:**
  Inspect [`docs/orneur/audits/ORNEUR_ANTIGRAVITY_PARALLEL_ENGINEERING_HANDOFF.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/audits/ORNEUR_ANTIGRAVITY_PARALLEL_ENGINEERING_HANDOFF.md).
- [ ] **2. Run Baseline Test Suite:**
  ```bash
  uv run --no-sync --with torch --with numpy --with sentencepiece --with cryptography pytest tests/test_c02_mission_lifecycle_security.py tests/test_genesis_checkpoint_adversarial_regression.py -v
  ```
  Expected baseline: `18 passed, 2 xfailed`.
- [ ] **3. Fix G01 Workspace Confinement (`isolated_worker.py`):**
  Update `_enforce_checkpoint_path_confinement` to return the resolved path anchored to `cfg.checkpoint_workspace_dir`, and pass `path=safe_path` in `_handle_save_checkpoint` and `_handle_restore_checkpoint`.
  Verify `test_g01_fix_acceptance_worker_confinement_desired_behavior` flips from XFAIL to PASS.
- [ ] **4. Fix G02 Checkpoint Run Binding (`resumable_checkpoint.py`):**
  Add `origin_run_id: str` to `ResumableManifest` and include it in `_compute_manifest_hmac`. Update `restore_resumable_checkpoint` to enforce `manifest.origin_run_id == run_id`.
  Verify `test_g02_fix_acceptance_cross_run_restore_without_migration_denied` flips from XFAIL to PASS.
- [ ] **5. Add `CANCELLATION_REQUESTED` to `MissionState` (`state_machine.py`):**
  Support graceful wind-down from `RUNNING` to `CANCELLATION_REQUESTED` to `CANCELLED`.
- [ ] **6. Mount `/api/missions` Router in `orca/serve/api.py`:**
  Implement the contract specified in [`ORNEUR_C02_FRONTEND_INTEGRATION_CONTRACT.md`](file:///Users/ag/Downloads/Orneur/docs/orneur/mission/ORNEUR_C02_FRONTEND_INTEGRATION_CONTRACT.md).
- [ ] **7. Wire Sub-Agent Pods in `index.html`:**
  Replace static `sendStarter()` prompt injection with live mission creation and SSE event streaming.
