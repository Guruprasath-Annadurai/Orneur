# ORNEUR C02 LIVE MISSION EXECUTION — BACKEND CAPABILITY MATRIX
## Founder-Approved UI State Mapping & Domain Capability Evaluation

**Document ID:** ORNEUR-C02-MATRIX-002 (Corrected)  
**Status:** QUALIFIED FOR TARGETED ENGINEERING REPAIR  
**Classification:** P0 Architecture & Transport Alignment  
**Author:** Antigravity / Gemini Engineering & Independent Audit Agent  
**Review Standard:** Strict Evidence-Driven Qualification (No Overstated Claims)  

---

## 1. Executive Summary & Architecture Boundary Separation

This document establishes the corrected capability matrix for the **Founder-Approved C02 Live Mission Execution Specification**.

### Crucial Architectural Separation:
- **UI State Identifiers (C02-01 through C02-12 and Variants A/B):** Authoritative visual and user-interaction interfaces approved by the founder. These must never be renamed, replaced, or merged into backend enum names.
- **Backend Domain States (`orca.mission.state_machine.MissionState` & `operations.status`):** The underlying finite-state machine governing invariants, data storage, and process transitions.
- **Qualification Posture:** The domain logic in `orca/mission/` provides robust unit-level rules and transition invariants. However, because `orca/serve/api.py` exposes zero `/api/missions` routes, and persistence currently relies on in-memory/ephemeral stores rather than active PostgreSQL migrations, **C02 execution is NOT yet production-grade end-to-end**.

---

## 2. Founder-Approved Visual Presentation Variants

> [!IMPORTANT]
> **Preserve Founder-Approved Variant Roles Exactly:**
> - **Variant A (Quiet Mission Brief):** Focused **Mission creation** interface.
> - **Variant B (Contextual Mission Review):** Dedicated **Pre-execution plan, scope and permission review** interface.
> - **Live Telemetry Separation:** Live operational execution telemetry (streaming logs, tool parameters, step progress) belongs strictly to running and tool-detail states (**C02-03: Mission Running** and **C02-04: Tool Action Details**), NOT as a replacement for Variant B.

| Variant ID | Variant Name | Primary Role & Interface Purpose | Backend Mapping & Data Dependencies |
|---|---|---|---|
| **Variant A** | **Quiet Mission Brief** | **Mission creation.** Clean, distraction-free modal/card capturing user intent, target systems, objectives, and initial constraints prior to plan generation. | Backed by `MissionCreate` / `ExecutionPlan` intent schemas. Feeds `POST /api/missions` draft initialization. |
| **Variant B** | **Contextual Mission Review** | **Pre-execution plan, scope and permission review.** Comprehensive pre-flight review displaying proposed execution DAG, requested tool permissions, blast-radius boundaries, and required supervisor sign-offs before launching execution. | Projected from proposed `ExecutionPlan`, `CapabilityAction` lists, and `OperationStore` permission manifests prior to transition into `READY` / `RUNNING`. |

---

## 3. 12-State Canonical Capability Matrix (9 Dimensions)

| UI State ID & Name | (1) Domain Object | (2) API / Event Contract | (3) Auth / Permission Model | (4) Storage & Persistence | (5) Transition Rules | (6) Current Repo Status | (7) Automated Tests | (8) Concrete Gaps | (9) Recommended Next Steps |
|---|---|---|---|---|---|---|---|---|---|
| **C02-01: Permission Request** | `CapabilityAction`, `PermissionRequest` in `code_mode.py` | SSE event `permission_requested` with required scope payload | Tool-scoped; evaluates `requires_authority()` and mode allowance | Ephemeral in-memory queue | Triggered when subagent requests privileged tool during `RUNNING` | Domain model implemented in `code_mode.py` | `test_proposed_mission_cannot_execute_without_required_permissions` (Unit) | Missing REST payload to transport request to frontend | Expose permission request frame in SSE stream |
| **C02-02: Approval Pending** | `ApprovalTicket`, `operations.status='REQUESTED'` | SSE `approval_pending` + `POST /api/missions/{id}/permissions/{req_id}/decision` | Strict non-self-approval (`approved_by != requested_by`) | `operations` row in `operation_store.py` | `RUNNING` -> `WAITING_APPROVAL`; blocks step execution | `authorize_operation` checks self-approval | `test_permission_self_authorization_strictly_prevented` (Real domain check) | Missing HTTP route to receive supervisor approval | Mount approval route in `orca/serve/api.py` |
| **C02-03: Mission Running** | `MissionState.RUNNING`, `ExecutionPlan` | SSE event `state_changed(RUNNING)` + continuous telemetry | Actor bearer token; session currency verified | In-memory `MissionStore`; lacks Neon migration | Legal from `READY`, `WAITING_*`, `PAUSED_*`; illegal from `DRAFT` | Implemented in `state_machine.py` | `test_running_status_requires_real_execution_transition` (Unit) | No child process lifecycle manager attached to state | Bind async worker execution loop to `RUNNING` |
| **C02-04: Tool Action Details** | `StepExecution`, `ToolCall` in `executor.py` | SSE event `step_progress` with tool arguments and timing | Worker execution lease; credential boundary checks | `operation_store.py` hash-chained ledger | Internal step transitions within `RUNNING` | Implemented in `executor.py` | `test_tool_results_preserve_actor_and_tenant_boundaries_and_redact_secrets` | SSE transport bridge not wired to FastAPI | Stream stdout/stderr frames over `/events` |
| **C02-05: Evidence and Outputs** | `VerificationRecord`, `MissionArtifact` in `verification.py` | SSE event `evidence_produced` with artifact hashes | System verifier role; tamper-evident digest | Hash-chained records in ledger | Emitted during or after step execution | Implemented in `verification.py` | `test_completed_status_requires_authoritative_terminal_result` (Unit) | Artifact download endpoints not mounted | Expose signed artifact download routes |
| **C02-06: Waiting for User Input** | `MissionState.WAITING_EXTERNAL_EVENT` / `WAITING_TOOL` | SSE `waiting_user_input` + `POST /api/missions/{id}/input` | Authenticated actor session | Ephemeral pause point | `RUNNING` -> `WAITING_EXTERNAL_EVENT` -> `RUNNING` | Supported in `state_machine.py` | `test_running_status_requires_real_execution_transition` (Unit) | No interactive prompt input API route | Implement `POST /api/missions/{id}/input` |
| **C02-07: Failed / Interrupted** | `MissionState.FAILED`, `FailureReport` | SSE event `mission_failed` with diagnostic trace | Actor session; redacted error messages | `operations.status='FAILED'` | `RUNNING` / `VERIFYING` -> `FAILED` (Terminal) | Implemented in `state_machine.py` | `test_network_disconnection_cannot_silently_become_successful_completion` | Raw exception sanitization for public web | Sanitize tracebacks via DLP filter |
| **C02-08: Cancellation Requested** | Missing intermediate wind-down marker | `POST /api/missions/{id}/cancel` -> SSE `cancellation_requested` | Actor session or supervisor role | In-flight cancellation token | `RUNNING` -> `CANCELLATION_REQUESTED` -> `CANCELLED` | **GAP:** `MissionState` enum lacks `CANCELLATION_REQUESTED` | `test_cancellation_requested_cannot_be_mistaken_for_cancellation_completed` | Enum jumps directly to `CANCELLED` | Add `CANCELLATION_REQUESTED` to `MissionState` |
| **C02-09: Mission Cancelled** | `MissionState.CANCELLED` (Terminal) | SSE event `mission_cancelled` | Actor session or supervisor role | Terminal record in store | `CANCELLATION_REQUESTED` -> `CANCELLED` | Implemented in `state_machine.py` | `test_cancellation_requested_cannot_be_mistaken_for_cancellation_completed` | Process termination SIGTERM handler | Attach worker process cleanup hook |
| **C02-10: Resume Review** | `RevisionCurrency`, `RelayMutationPrecondition` | `GET /api/missions/{id}/diff` + `POST .../resume` | Authenticated session with matching user/tenant | Verified state revision check | `PAUSED_*` -> `READY` / `RUNNING` | Revision check implemented in `relay_reconnect.py` | `test_resume_requires_verified_state_and_rejects_stale_revision` (Unit) | Frontend diff view not exposed | Implement revision diff inspection endpoint |
| **C02-11: Mission Completed** | `MissionState.COMPLETED_VERIFIED` | SSE event `mission_completed` with evidence proof | Requires non-empty evidence and passed verification | Sealed terminal record in ledger | `VERIFYING` -> `COMPLETED_VERIFIED` (Strict) | Enforced in `state_machine.py` | `test_completed_status_requires_authoritative_terminal_result` (Unit) | Final telemetry summary card contract | Expose completion summary payload |
| **C02-12: Mission History** | `list_operations_for_mission()` | `GET /api/missions/{id}/history` | Strict tenant and user boundary check | Chronological `operations` rows | Read-only audit log query | Access control in `reconcile_operation` | `test_mission_history_cannot_leak_across_users_or_tenants` (Real boundary) | Missing paginated history endpoint in `api.py` | Add `GET /api/missions/{id}/history` |

---

## 4. Architectural Gaps & Implementation Roadmap

1. **Domain vs UI Separation:** The UI identifiers (`C02-01` through `C02-12`) are now mapped to backend states without altering the visual design contract.
2. **Missing Intermediate Enum:** Add `CANCELLATION_REQUESTED` to `orca/mission/state_machine.py` to allow graceful subprocess wind-down.
3. **Transport Layer:** Wire FastAPI router in `orca/serve/api.py` to handle REST and SSE streaming according to the corrected contract.
