# ORNEUR — C02 Mission Execution Backend: Phase A/B Engineering Report

**Directive**: CTO Master Engineering Continuation Directive (GENESIS Foundation Preservation + B01–B16 Frontend + C02 Mission Execution), Phases A and B.
**Branch**: `claude/c02-mission-execution-backend-2026-10-22`, based on `origin/main` (NOT the security remediation branch — branch discipline preserved per the directive's explicit instruction).
**Security baseline preserved**: no file under `orca/genesis/`, `orca/config.py`'s checkpoint-confinement helpers, or any file touched by PR #78 was modified. The proposed synthetic foundation freeze (`55eb4fe`) is unaffected — this branch does not build on top of it.

---

## Phase A — Repository inspection baseline

Classification uses exactly the six labels the directive specifies: IMPLEMENTED & TESTED, IMPLEMENTED BUT UNTESTED, PARTIALLY IMPLEMENTED, MOCKED, NOT IMPLEMENTED, UNKNOWN.

| Component | Status | Evidence |
|---|---|---|
| App shell / frontend framework | **NOT IMPLEMENTED** | No `package.json`, no frontend directory exists anywhere in this repository. B01–B16 is greenfield frontend work. |
| Existing B01–B16 implementation | **NOT IMPLEMENTED** | Confirmed by the same search above; no screen-specific frontend code exists. |
| Mission domain models | **IMPLEMENTED & TESTED** | `orca/mission/` — 43 files, ~2300+ lines across state machine, mission store, operation store, authority bridge, relay store, court/verification gates. 285 pre-existing tests, all independently re-run and passing (281 immediately, 4 required installing `psycopg` locally — an environment gap, not a defect). This is materially more mature than the directive's own framing assumed. |
| Mission state machine | **IMPLEMENTED & TESTED** | `orca/mission/state_machine.py` — 15 canonical states (`DRAFT` … `CANCELLED`), structurally enforced invariants (`COMPLETED_VERIFIED` requires passing through verification AND a non-empty evidence ref — "no fake completion" is enforced in code, not just documented). |
| Operation store (permission/approval lifecycle) | **IMPLEMENTED & TESTED** | `orca/mission/operation_store.py` — `REQUESTED → AUTHORIZED → STARTED → SUCCEEDED/FAILED`, atomic idempotency-key deduplication (`INSERT … ON CONFLICT DO NOTHING RETURNING *`), and a structural self-authorization guard (`approved_by == requested_by` is rejected before any call into the authority engine). |
| Authority/approval engine | **IMPLEMENTED & TESTED** | `orca/mission/authority_bridge.py` delegates to the existing, already-battle-tested `orca.godmode.resolution.resolve_and_consume_lease()` (Phases 9–14B) — this is not reimplemented, by design. |
| Persistent storage | **IMPLEMENTED & TESTED** | Real Neon Postgres (`orca/mission/db.py`), pooled vs. direct/unpooled connections correctly separated for application traffic vs. schema migrations. `tests/test_*_live_neon.py` suites exist for live-DB verification (skipped locally/in this report without live credentials, exactly as this repo's own test suite already designs for). **Already satisfies** the directive's "do not rely on a process-local dictionary" requirement — this was true before this phase's own work began. |
| Authenticated API routes for missions | **NOT IMPLEMENTED (until this phase)** | `orca/serve/api.py` had zero mission-related routes before this branch — confirmed by grep across the entire serving layer. This was the single largest gap, and this phase's own work (below) addresses a first, scoped slice of it. |
| SSE / event transport for mission execution | **NOT IMPLEMENTED** | `orca/serve/streaming.py` exists but is unrelated to missions (it's the chat-completion admission/backpressure layer). No mission-specific event transport exists. |
| Worker execution processes for missions | **PARTIALLY IMPLEMENTED** | `orca/mission/executor.py`, `container_executor.py`, `sandbox_executor.py` exist but were not exercised or modified in this phase — not independently re-verified here, status inherited as "existing, not re-audited this phase." |
| Evidence interfaces | **PARTIALLY IMPLEMENTED** | `orca/mission/production_proof.py`, `production_proof_store.py`, `supply_chain_evidence.py`, `traceability.py` exist; not exercised by this phase's new API routes. |
| Cancellation-requested vs. cancelled distinction | **NOT IMPLEMENTED** | The existing `MissionState` enum has no `CANCELLATION_REQUESTED` state — `CANCELLED` is reached directly from `RUNNING`/`WAITING_*`/`PAUSED_*`/`BLOCKED` with no intermediate "requested, not yet confirmed" state. This is a genuine, confirmed gap against the directive's explicit "Cancellation truth" requirement — not addressed in this increment (see Known Gaps below). |

**A CSS mockup does not qualify as backend integration; a route declaration does not prove a working user journey** — per the directive's own standard, the table above reflects what is actually wired and tested, not what exists as adjacent, unconnected logic.

---

## Phase B — C02 backend: this increment's actual scope

**New files**: `orca/serve/mission_api.py` (REST router), `tests/test_mission_api.py` (12 integration tests).
**Modified files**: `orca/serve/api.py` (+6 lines: router import and mount, no other change).

### What is implemented and tested in this increment

A first, scoped vertical slice of the C02 mission lifecycle, built entirely on the **existing, already-tested** `orca.mission` domain layer — no mission domain logic was reimplemented:

- `POST /v1/missions` — authenticated mission creation. `owner_user_id` is always the server-verified caller (`orca.auth.get_current_user`), never taken from the request body.
- `GET /v1/missions` — minimal mission history (C02-12), owner-filtered **in the SQL query itself**, not post-filtered in Python.
- `GET /v1/missions/{id}` — fetch, 404 (never 403) for a mission that exists but belongs to someone else, so a caller cannot distinguish "not yours" from "does not exist" and enumerate other tenants' mission IDs.
- `POST /v1/missions/{id}/plan` — transitions `DRAFT → PLANNING → READY` via the existing state machine (this increment does NOT generate a real plan; it performs only the legal state transition a real planning step would perform on success — no plan content is fabricated or claimed).
- `POST /v1/missions/{id}/cancel` — direct transition to `CANCELLED` (see Known Gaps: this does NOT yet distinguish a cancellation *request* from a confirmed, worker-terminated cancellation).
- `POST /v1/missions/{id}/operations` — permission request (C02-01). Idempotent: the same `idempotency_key` with the same parameters returns the existing operation; the same key with *different* parameters is rejected with 409, never silently accepted.
- `GET /v1/missions/{id}/operations/{op_id}` — fetch, ownership-scoped through the parent mission.
- `POST /v1/missions/{id}/operations/{op_id}/approve` — approval decision (C02-02), delegating entirely to `orca.mission.operation_store.authorize_operation()` (which itself delegates the actual ALLOW/DENY decision to `orca.godmode`).
- `POST /v1/missions/{id}/operations/{op_id}/deny` — fast-reject path (cancels a `REQUESTED` operation directly, without consulting the authority engine at all).

### Security properties verified by this increment's own tests (12 tests, all passing)

Directly matching the directive's "essential integration tests" list:
- **Unauthorized creation**: rejected (401) with no auth override installed.
- **Cross-user / cross-tenant access**: a mission belonging to another user returns 404 (identical body to a genuinely nonexistent mission), for `GET`, `plan`, and `cancel`. Mission listing is owner-filtered.
- **Self-approval rejection**: the requester attempting to also approve their own operation is rejected with 403, via the *existing* `SelfAuthorizationError` guard in `operation_store.py` — not reimplemented or bypassed by this HTTP layer.
- **Approval denial**: the fast-reject `/deny` path correctly marks the operation `CANCELLED`.
- **Duplicate side-effect prevention (idempotency)**: a retried operation request with the same idempotency key and same parameters returns the *existing* operation, not a new one; the same key with different parameters is rejected (409).
- **Terminal-state guard**: attempting to deny an already-denied (`CANCELLED`) operation is rejected (409) by the existing operation state machine.

Test methodology: `fastapi.testclient.TestClient` against the real, unmodified `orca.serve.api.app`, with only the mission-DB connection dependency faked (a lightweight in-memory stand-in implementing just enough of the psycopg cursor/connection protocol for the real, unmodified `mission_store`/`operation_store` code to run against) — this tests this phase's own authorization/ownership/wiring logic for real, without requiring a live Neon connection (which remains covered separately by this repo's own pre-existing `test_*_live_neon.py` suites).

### Regression check

Full existing `tests/test_mission_*.py`, `tests/test_relay_*.py`, `tests/test_court_mission_gate.py` suites (301 tests) plus the new `tests/test_mission_api.py` (12 tests): **all pass, zero regressions**. A broader sweep of `tests/test_api_*.py` (39 files) surfaced exactly one pre-existing failure (`test_api_production_cutover.py::test_rag_forces_deferral_to_existing_stack_when_docs_are_loaded`) — independently confirmed, via `git stash`, to fail **identically on unmodified `origin/main`**, i.e. unrelated to this phase's changes.

---

## Known gaps in this increment — not hidden

This is a **first, scoped slice**, not the full C02-01…C02-12 surface. Explicitly NOT implemented:

1. **SSE / live event transport.** No mission execution events stream to a client at all yet. The directive's detailed requirements (reconnection, ordered sequence IDs, replay horizon, resynchronization, backpressure, auth-header limitations of native `EventSource`) are real, substantial work not attempted in this increment.
2. **Cancellation truth** (`CANCELLATION_REQUESTED` vs. confirmed `CANCELLED`). The current `/cancel` endpoint performs a direct, immediate state transition with no verification that any running worker process has actually stopped. This is the single most significant known gap against the directive's own explicit requirement and should be the next priority.
3. **C02-03 through C02-11 execution-time screens** (Mission Running, Tool Action Details, Evidence and Outputs, Waiting for User Input, Failed/Interrupted, Resume Review, Mission Completed) have no dedicated endpoints yet — `GET /v1/missions/{id}` and `GET /v1/missions/{id}/operations/{op_id}` expose the underlying state, but there is no execution trigger, no tool-action detail view, and no evidence/output reference endpoint.
4. **Resume** (`resume_mission()` already exists in `mission_store.py` and is tested there) is not yet exposed over HTTP.
5. **Reconnect/retry integration tests** from the directive's list are not covered (no streaming exists yet to reconnect to).
6. **Tenant/workspace model**: `User` has no workspace/tenant field beyond `id` in this codebase today; this increment's authorization boundary is per-owner-user, not per-workspace. If ORNEUR's actual multi-user mission-sharing model requires workspace-level sharing (not just single-owner), that is a separate, larger design question outside this increment's scope.
7. **Frontend (B01–B16, C02 Variant A/B + 12 states)**: not started in this increment. The approved B01–B16 design archive (`ORNEUR_UIUX_FINAL_CTO_REVIEW_HANDOFF(2).zip`) was received, extracted into an isolated directory, and its SHA-256 manifest verified (274/274 files match) — but no frontend code has been written yet. The C02 design archive (`ORNEUR_C02_FINAL_FOUNDER_APPROVED_DESIGN_LOCK.zip`) was not supplied; per the directive's own instruction, this is explicitly deferred rather than fabricated.

---

## Deliverables (directive section 13)

1. **Exact baseline SHA**: `55eb4fea5c5c4820db6b15e1a2aac5885bddce78` (PR #78, security baseline), independently audited.
2. **Development branch**: `claude/c02-mission-execution-backend-2026-10-22`, based on `origin/main`, not the security branch.
3. **Draft PR URL**: [#79](https://github.com/Guruprasath-Annadurai/Orneur/pull/79).
4. **Changed production files**: `orca/serve/api.py` (+6 lines, router mount only), `orca/serve/mission_api.py` (new).
5. **Changed test files**: `tests/test_mission_api.py` (new, 12 tests).
6. **Approved design assets actually inspected**: B01–B16 handoff archive (`ORNEUR_UIUX_FINAL_CTO_REVIEW_HANDOFF(2).zip`), extracted into an isolated directory, SHA-256 manifest verified (274/274 files match). README, design system, and the B02 implementation handoff were read in full to confirm the archive is genuine, detailed implementation material (not just screenshots).
7. **Missing design dependencies**: C02 design archive (`ORNEUR_C02_FINAL_FOUNDER_APPROVED_DESIGN_LOCK.zip`) not supplied.
8. **B01–B16 implementation matrix**: not started this increment (see Phase A table — frontend row is NOT IMPLEMENTED).
9. **C02 implementation matrix**: see Phase B section above (lifecycle slice done; execution/streaming/cancellation-truth open).
10. **Auth/API integration evidence**: 12 passing integration tests against the real FastAPI app (`tests/test_mission_api.py`).
11. **Database persistence evidence**: real Neon Postgres, pre-existing (`orca/mission/db.py`), not newly built this phase; this phase's API layer uses it through the existing, unmodified store functions.
12. **Browser screenshots**: none — no frontend work in this increment.
13. **Visual comparison reports**: none — no frontend work in this increment.
14. **Responsive and accessibility results**: none — no frontend work in this increment.
15. **Exact test counts**: 301 existing mission/relay tests passing (zero regressions) + 12 new tests passing = 313. One pre-existing, unrelated `test_api_*.py` failure confirmed present on unmodified `main`.
16. **CI checks with immutable commit SHA**: GitHub Actions run [`39768749559`](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39768749559), `headSha` confirmed equal to `ddbb5e1e56b766def4efeee3c04ee2483f43166c`, conclusion `success`.
17. **Remaining bugs and unresolved security boundaries**: see "Known gaps" above; the Genesis-side residual boundaries (same-UID isolation, unkeyed cache integrity, local-only rollback ledger) are unrelated to this branch and remain tracked against PR #78.
18. **Genuine operational features**: mission create/list/get/plan/cancel; operation request/get/approve/deny — all backed by real, tested persistence and authorization logic.
19. **Disabled or unavailable features**: live execution, streaming, tool-action details, evidence/output references, resume-over-HTTP, the full C02 state surface, and all frontend screens.
20. **Engineering verdict**: **PARTIAL** (see below).

## CTO review corrections (PR #79, commit `cabd376`)

The CTO's review of the actual code in PR #79 found six real, confirmed defects. Each was independently reproduced before fixing, consistent with this project's established discipline.

**P0-01 — Operation idempotency isolation, confirmed and fixed.** `operations.idempotency_key` is a GLOBALLY unique column (pre-existing schema, unchanged) — `request_operation()`'s own conflict check compares fingerprints, not mission identity. Reproduced directly: the same key, reused under a different mission with matching kind/target/parameters, returned the OTHER mission's operation as if it were a successful retry. Fixed at the API layer (not the shared domain function, preserving existing behavior other callers may depend on): `request_operation` in `mission_api.py` now verifies the returned operation's `mission_id` matches the URL's mission before treating it as a legitimate retry; a cross-mission collision is now a 409. New regression test: `test_idempotency_key_collision_across_missions_is_rejected_not_silently_returned`.

**P0-02 — Approval resource binding, confirmed and fixed.** `approve_operation` checked only that the caller owned the URL's `mission_id` — it never verified the `operation_id` path parameter actually belonged to that mission before calling `authorize_operation()`. Reproduced directly: operation A (mission A) was authorizable through mission B's URL. Fixed: `approve_operation` now performs the same operation-belongs-to-this-mission check `get_operation`/`deny_operation` already had, before calling into the authority engine. New regression test: `test_cannot_approve_operation_belonging_to_a_different_mission`. The existing self-authorization guard (`SelfAuthorizationError`) is untouched.

**P0-03 — Cancellation truth, confirmed and fixed.** `/cancel` previously transitioned straight to `CANCELLED` even from `RUNNING`, with no verification any worker had stopped. Fixed with a real domain-level change (not a cosmetic API wrapper): `orca.mission.state_machine.MissionState` gains a 16th state, `CANCELLATION_REQUESTED` (schema CHECK constraint widened via a new idempotent migration, `CANCELLATION_REQUESTED_MIGRATION_SQL`). Every state that might have a live worker (`RUNNING`, all `WAITING_*`, all `PAUSED_*`, `BLOCKED`) can no longer transition directly to `CANCELLED` — only to `CANCELLATION_REQUESTED`, which itself resolves only to `CANCELLED` (confirmed) or `FAILED` (fail-closed, termination could not be confirmed). `DRAFT`/`PLANNING`/`READY` still cancel directly (nothing is running). New `POST /v1/missions/{id}/confirm-cancelled` endpoint performs the confirmation step — honestly scoped: it does not itself verify worker termination (no reconciliation loop exists in this codebase yet), it only makes "requested" and "confirmed" genuinely distinct, persisted states, refusing to invent the confirmation itself. One existing test (`test_paused_states_can_be_cancelled`) asserted the old, now-incorrect direct-cancel behavior and was rewritten (`test_paused_states_can_request_cancellation_then_confirm`) along with 4 new `TestCancellationRequested` tests in `tests/test_mission_state_machine.py`, plus 5 new tests in `tests/test_mission_api.py`. **A bug was caught by this increment's own tests during this fix**: the first implementation used "not a live-worker state" as the direct-cancel condition, which let a second `/cancel` call on an already-`CANCELLATION_REQUESTED` mission self-confirm straight to `CANCELLED`, bypassing `/confirm-cancelled` entirely — corrected to an explicit allowlist of only the genuinely pre-run states.

**P1-01 — Planning truth, confirmed and fixed.** `/plan` reached `READY` with zero persisted plan content. This codebase has no automatic plan-generation capability (no LLM-driven planner is wired up anywhere), so "real planning integration" in this increment means persisting and validating a genuine, non-empty, caller-supplied plan — not fabricating one. `PlanMissionRequest.steps` now requires a non-empty list (Pydantic `min_length=1`, rejected with 422 before the handler runs if empty); `mission_store.create_mission_steps()` (new) persists each as a real `mission_steps` row, and only then does the mission advance to `READY`. New `GET /v1/missions/{id}/steps` endpoint exposes the persisted plan. New tests: `test_plan_transitions_draft_to_ready_and_persists_real_steps`, `test_plan_with_no_steps_is_rejected_and_mission_stays_in_draft`.

**P1-02 — Real approval path, demonstrated, with an honest scope limitation documented rather than worked around.** Directly verified (`test_distinct_principal_approval_journey_reaches_a_real_allow_decision`) that `orca.mission.operation_store.authorize_operation()`'s underlying mechanism — including the real `orca.godmode` authority engine, not a mock — genuinely supports two distinct principals (one requests, a different one approves) and reaches a real `ALLOW` decision, while self-authorization remains independently, structurally rejected by the same code path. **Honest limitation surfaced, not hidden**: this phase's HTTP API gates both operation requests and approvals on mission ownership, and `orca.auth.store.User` has no workspace/role concept beyond a bare `id` — so, as built today, the only HTTP caller who can reach `/approve` for a given mission is that mission's own owner. A genuinely distinct HTTP-level requester/approver pair is not yet expressible without a real multi-principal authorization model, which is a separate, future piece of work (e.g. a workspace/role system, or an "approver" permission distinct from ownership) — not invented or faked here.

**P1-03 — Database qualification, addressed via a new live-Neon test file, matching this repo's own established pattern.** New `tests/test_mission_api_live_neon.py` (5 tests), skipped unless `ORNEUR_MISSION_DATABASE_URL`(`_DIRECT`) point at a real, disposable Neon branch — exactly the same skip discipline every other `_live_neon.py` file in this repo already uses, so no infrastructure was provisioned to write or commit this file. Covers, against a REAL database (not the fake in-memory connection the rest of `test_mission_api.py` uses): durable persistence across a fresh connection, real CHECK-constraint rejection of an illegal raw state write (transaction rollback), ownership enforcement against the real row, the real `idempotency_key` UNIQUE constraint as a backstop beneath the application-level dedup logic, and concurrent `/cancel` calls on the same mission correctly serialized by the existing `SELECT ... FOR UPDATE` row lock (exactly one of five concurrent calls succeeds). **Not run in this session** — no Neon credentials were available or provisioned; this is explicitly noted rather than claimed verified.

All fixes independently regression-tested: `tests/test_mission_api.py` grew from 12 to 21 tests (all passing); `tests/test_mission_state_machine.py` grew from 54 to 57 tests (all passing, including the one rewritten test); the full existing mission/relay suite (301 tests) plus all new/changed tests: 312 passed, 5 skipped (the new live-Neon file), zero regressions.

---

## Verdict

**PARTIAL.** A real, tested, authenticated API surface now exists for mission creation, validated planning, permission requests, and approval/denial decisions, with the six CTO-identified P0/P1 defects independently reproduced and fixed — built entirely on the pre-existing, mature `orca.mission` domain layer (plus one additive, backward-compatible schema migration for cancellation truth), with no reimplementation of its already-correct authorization/idempotency logic. Live execution streaming, the full C02/B01–B16 frontend, and the live-Neon test file's actual execution (no credentials available) remain open and explicitly enumerated — not claimed done here.

No merge, no tag, no training, no GPU/paid infrastructure provisioning, no founder-approved-design modification occurred in this phase.
