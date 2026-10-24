# Phase E — B14 Correlated Runs

Per the CTO's directive, using Cursor PR #96's real routes (`POST /api/runs`, `X-Run-Id` on `/api/stream`, `GET /api/runs/{run_id}`).

## Scope decision, stated honestly up front

**No UI trigger was built for creating or using a run.** This is a deliberate, disclosed scope boundary, not an oversight: no approved design exists for grouping conversations/generations in this product. The C-series contract itself confirms `/api/workspaces` doesn't exist, and `ORNEUR_B14_CORRELATED_RUNS_HANDOFF.md`'s own words are explicit — *"The run id is not a share and not a workspace tab."* Inventing a UI control to create/consume runs without an approved concept would be exactly what the directive forbids: *"Do not invent new workspace tabs, public resources or unsupported backend capabilities."*

## What was implemented instead: the real contract plumbing itself

- **`createRun()`**: calls the real `POST /api/runs`, handles 401 like every other authenticated call site, returns the real `run_id` or `null` on any failure. Not called by any UI path — exists so an approved future UI can use it without needing new wiring at this layer.
- **`sendMessage(runId)`**: now accepts an optional run id. When passed, the stream request includes a real `X-Run-Id` header; when omitted (every existing caller — the Send button, Retry), the header is absent, and the contract's own stated guarantee ("existing clients keep working") holds.
- **`_activeGenerationRunId`**: tracks the real `run_id` field now present on the `generation` SSE event, reset to `null` at the start of every attempt alongside the existing generation-id/cancellable state, defaulting to `null` when the stream wasn't attached to a run.

## Preserved, verified unchanged

- **Quick Switch**: live-verified against the current merged backend — opened the panel, confirmed real conversation rows rendered from `GET /api/sessions`.
- **Per-conversation drafts**: `test_b14_quick_switch_and_drafts.mjs` (9/9, unchanged) continues to pass untouched by this phase.

## Live verification, not just unit tests

Manually exercised the full plumbing end-to-end against the real merged backend (not a UI control — this capability has no UI trigger, by design, so verification called the real functions directly):
1. `createRun()` → a real `run_id` returned (confirmed via server log: `POST /api/runs HTTP/1.1 200 OK`).
2. `sendMessage(runId)` with that id → the real `generation` SSE event included the same `run_id`, correctly captured into `_activeGenerationRunId`.
3. **Independently confirmed via a fresh `GET /api/runs/{run_id}`** (not trusting the client's own tracked state): the run's real `members` array contained exactly one entry, with `generation_id` and `session_id` matching precisely what the client had tracked. This proves the full round-trip — creation, attachment, and independent read-back — all genuinely work.

## Tests

```
node --test tests/frontend/*.mjs   # 217/217 passing (was 211; +6 in a new test_b14_correlated_runs.mjs)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

New file `test_b14_correlated_runs.mjs`: structurally confirms `createRun()` is never called from any UI path (the explicit "no invented trigger" guard), confirms the `X-Run-Id` header is additive-only, confirms 401 handling, confirms the reset-per-attempt pattern, confirms Quick Switch/drafts are untouched, and behaviorally tests `createRun()`'s three outcomes (success, signed-out, server failure).

## Honest verdict

**IMPLEMENTED AND INTEGRATION-TESTED** (not independently qualified, not production authorized) — for the plumbing itself, which is real, live-verified end-to-end including independent server-side confirmation of run membership. **Not wired to any user-facing feature**, disclosed precisely as a scope decision driven by the explicit absence of an approved UI design, not a gap hidden from this report. The capability is ready the moment a design exists.
