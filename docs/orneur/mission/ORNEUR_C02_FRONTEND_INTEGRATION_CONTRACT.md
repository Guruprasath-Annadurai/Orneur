# ORNEUR C02 LIVE MISSION EXECUTION — FRONTEND INTEGRATION CONTRACT

**Document Version:** 1.0.0  
**Status:** SPECIFICATION COMPLETE / READY FOR ENGINEERING  
**Interface:** REST + Server-Sent Events (SSE)  
**Security Model:** Single Authority (Backend Authoritative; Frontend Pure Projection)  
**Author:** Antigravity / Gemini Engineering & Independent Audit Agent  

---

## 1. Architectural Principles & Authority Boundary

To preserve absolute security and auditability, the ORNEUR platform strictly prohibits **dual authority**:
1. **Single Source of Truth:** The backend state machine (`orca/mission/state_machine.py`) is the sole authority governing mission states, transitions, permissions, and terminal verdicts.
2. **Frontend as Pure Projection:** The frontend interface (C02 Live Mission Execution view) is strictly a reactive projection of the backend event stream. It must never compute state transitions, grant permissions locally, or synthesize completion statuses.
3. **Idempotency & Reconnection:** All mutations carry idempotency keys. All event streams support resumption via standard `Last-Event-ID` headers to prevent message loss during transient network disconnects.

---

## 2. REST Endpoints Specification

All endpoints are authenticated via `Authorization: Bearer <jwt_or_api_key>` and require `X-Tenant-ID` (or infer tenant from token claims).

### 2.1 Create Mission
- **Endpoint:** `POST /api/missions`
- **Request Body:**
  ```json
  {
    "title": "Quarterly Financial Analysis & SEC Filing Reconciliation",
    "goal": "Extract 10-K figures, reconcile balance sheet variances, and generate audit draft.",
    "pod_type": "ORNEUR_ANALYST",
    "parameters": {
      "ticker": "ORCA",
      "fiscal_year": 2026,
      "max_budget_usd": 50.0
    },
    "idempotency_key": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
  }
  ```
- **Response (201 Created):**
  ```json
  {
    "mission_id": "msn_01jd9a87f6e8b42c90e7f1",
    "state": "READY",
    "created_at": "2026-10-19T13:20:00.000Z",
    "revision": 1,
    "stream_url": "/api/missions/msn_01jd9a87f6e8b42c90e7f1/events"
  }
  ```

### 2.2 Get Mission State (Polling / Fallback)
- **Endpoint:** `GET /api/missions/{mission_id}`
- **Response (200 OK):**
  ```json
  {
    "mission_id": "msn_01jd9a87f6e8b42c90e7f1",
    "state": "RUNNING",
    "c02_state_id": "C02-04",
    "revision": 14,
    "current_step": {
      "step_id": "step_03",
      "title": "Executing SEC Edgar XBRL Fetch",
      "subagent": "EDGAR_EXTRACTOR",
      "status": "IN_PROGRESS",
      "started_at": "2026-10-19T13:21:05.120Z"
    },
    "stats": {
      "steps_completed": 2,
      "total_steps": 6,
      "tokens_consumed": 4120,
      "cost_usd": 0.0824
    }
  }
  ```

### 2.3 Approve / Reject Proposed Plan (C02-03)
- **Endpoint:** `POST /api/missions/{mission_id}/plan/decision`
- **Request Body:**
  ```json
  {
    "decision": "APPROVED", // or "REJECTED"
    "plan_revision": 1,
    "feedback": "Proceed with standard GAAP validation rules."
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "mission_id": "msn_01jd9a87f6e8b42c90e7f1",
    "state": "RUNNING",
    "revision": 2
  }
  ```

### 2.4 Human-in-the-Loop Permission Decision (C02-06)
- **Endpoint:** `POST /api/missions/{mission_id}/permissions/{request_id}/decision`
- **Request Body:**
  ```json
  {
    "decision": "GRANTED", // or "DENIED"
    "scope_limitations": {
      "max_spend_usd": 10.0,
      "read_only": false
    }
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "request_id": "req_esc_008",
    "status": "GRANTED",
    "mission_state": "RUNNING"
  }
  ```

### 2.5 Lifecycle Controls (Pause / Resume / Cancel)
- **Pause:** `POST /api/missions/{mission_id}/pause`
- **Resume:** `POST /api/missions/{mission_id}/resume` (requires `expected_revision`)
- **Cancel:** `POST /api/missions/{mission_id}/cancel` (requires `reason`)

---

## 3. Server-Sent Events (SSE) Stream Specification

- **Endpoint:** `GET /api/missions/{mission_id}/events`
- **Headers:**
  - `Accept: text/event-stream`
  - `Last-Event-ID: <last_received_seq_id>` (for automatic replay on reconnect)

### 3.1 Event Frame Envelope Format
Every event emitted by the stream conforms to standard SSE formatting:
```
id: 1042
event: mission_delta
data: {"mission_id":"msn_01jd9a87f6e8b42c90e7f1","c02_state":"C02-04","type":"STEP_PROGRESS","payload":{...},"timestamp":"2026-10-19T13:21:10.050Z"}
```

### 3.2 Canonical SSE Event Types

| Event Name | C02 State Mapping | Trigger / Meaning |
|---|---|---|
| `state_changed` | C02-01 to C02-14 | Global mission state transition (e.g. `READY` -> `RUNNING`). |
| `plan_proposed` | C02-03 | Planner has formulated steps; waiting for user review. |
| `step_progress` | C02-04 | Incremental execution telemetry, stdout/stderr chunk, subagent status. |
| `guardrail_evaluation` | C02-05 | Verification engine evaluated step output against security constraints. |
| `permission_requested`| C02-06 | Subagent requires elevated tool permission (HITL modal triggered). |
| `mission_paused` | C02-07 | Execution halted; safe point established. |
| `cancellation_requested`| C02-08 | User requested cancel; workers winding down active tools. |
| `mission_cancelled` | C02-09 | Terminal state; resources freed. |
| `mission_failed` | C02-10 | Fatal error encountered; diagnostic dump available. |
| `relay_heartbeat` | C02-11 | Connection keepalive ping (sent every 15s). |
| `operation_retry` | C02-12 | Transient error recovery; idempotent replay in-progress. |
| `mission_completed` | C02-13 | Terminal state; verification proof attached. |
| `artifacts_ready` | C02-14 | Post-mission deliverables ready for download/export. |

---

## 4. Reconnection & Durability Protocol (C02-11)

1. **Client Disconnection Detection:** The browser `EventSource` monitors heartbeats. If no message or heartbeat is received within 30 seconds, the frontend transitions the UI indicator to `C02-11: Transient Disconnection / Reconnecting`.
2. **Exponential Backoff Reconnect:** The client attempts reconnect at intervals: 1s, 2s, 4s, 8s (capped at 15s).
3. **Replay via `Last-Event-ID`:** On reconnect, the browser automatically sends `Last-Event-ID: <seq_id>`. The backend buffer (`orca/mission/relay_reconnect.py`) replays missed events in sequence from memory/ledger.
4. **Resync Fallback:** If `Last-Event-ID` has expired from the backend buffer (> 1000 events behind), the server emits HTTP 410 Gone with `resync_url: /api/missions/{id}` to trigger a full state snapshot fetch.

---

## 5. Security Guardrails for Frontend Implementation

1. **No Client-Side Invariant Checks as Authoritative:** The frontend must never assume an action is permitted. It renders UI affordances based on backend `allowed_actions: ["pause", "cancel", "approve"]` included in state envelopes.
2. **Strict Sanitization:** All logs and text streamed from tools must be rendered with HTML escaping (`esc()`) or as markdown via sanitized parsers to prevent DOM XSS.
3. **Dual-Key Escalation Signing:** In high-security enterprise tiers, human approvals can include a WebAuthn / Passkey signature passed in `approval_signature`.
