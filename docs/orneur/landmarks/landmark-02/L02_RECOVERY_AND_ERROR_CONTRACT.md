# L02-03 — Network recovery, outcome truth and error contract

Evidence state: **VERIFIED_ENGINEERING** (engineering-owned tests; not independently qualified).
Code: `orca/serve/turn_requests.py`, `orca/serve/conversations.py` (`turn_requests` table, `commit_turn(request_key=…)`), `orca/serve/api.py` (`/api/turns/*`, idempotency helpers), `orca/serve/errors.py`, `orca/serve/web/conversation.html` (reconcile / Stop handlers).

## 1. Outcome states (what the server will say about a request)

Every streamed turn that carries an `Idempotency-Key` has one durable `turn_requests` row **in the same SQLite database, written in the same transaction as `commit_turn`**, so "committed" and "recorded as committed" cannot diverge.

| State | Meaning | Source of truth |
|---|---|---|
| `rejected` | refused before admission (auth, rate, quota, plan, moderation) – nothing ran | refusal response |
| `admitted` / `running` | accepted; a live worker holds turn authority | `turn_requests` + authority lease |
| `cancellation_requested` | `POST /api/turns/{key}/cancel` recorded | `turn_requests` |
| `cancelled` (confirmed) | the worker observed the cancel and stopped before commit | `turn_requests` |
| `committed` | the answer is in the transcript | transcript row carries the key |
| `not_committed` + reason | terminal, nothing stored (`worker_lost`, `server_shutdown`, `superseded`, `provider_failed`, `cancelled`…) | authority-derived |
| `superseded` | another turn took authority first (`turn_superseded`) | fencing epoch |
| `outcome_unknown` (HTTP 503) | the store itself could not be read; the server will not guess | read failure |

`outcome_unknown` is returned **only** when the store is unreadable; it is never inferred from a missing row.

## 2. Mechanisms

* **Idempotency first, then outcome.** Same key + same request hash → replay of the recorded result; same key + different body → `422`; stale in-progress row left by a killed worker is released (`_idem_resolve_stale`) so a retry runs instead of waiting forever (found by live R5).
* **Committed replay.** If the transcript already holds a turn with the key, the retry is answered from the transcript (no second model call, no second quota unit).
* **Authority-derived resolution.** A `running` row whose lease expired or whose epoch was superseded resolves to `not_committed`(`worker_lost`/`superseded`) on read; a clean shutdown records `server_shutdown`.
* **Stop.** The page sends a server cancel and then asks the server for the outcome; a lost race (commit won) is shown as saved, not as "stopped".
* **After a dropped connection** the page asks `/api/turns/{key}` instead of showing a conflict or "failed".

## 3. HTTP vs SSE refusal table (measured, additive to B-01 §6)

| Code | HTTP / channel | Meaning |
|---|---|---|
| `auth_required` | 401 JSON | invalid/expired/revoked credential – no model call |
| `rate_limited` | 429 JSON | per-IP limiter |
| `too_many_attempts` | 429 JSON | per-account login lockout (L02-04) |
| `email_verification_required` | 403 JSON | sign-in/session refused until the address is verified |
| `storage_quota_exceeded` | 413 JSON | document quota (L02-02) |
| `session_not_found`, `temporary_closed`/`temporary_expired` | 404 / 409 JSON | ownership / closed temporary chat |
| `server_draining` | 503 JSON or SSE | graceful shutdown: nothing started, nothing charged |
| `server_busy` | 503 JSON or SSE | stream admission cap reached (truthful capacity, was `backend_error`) |
| `request_timeout` | 504 / SSE | total stream deadline reached; nothing saved |
| `history_unavailable`, `session_busy`, `quota_exceeded`, `model_access_denied`, `content_refused`, `request_abstained`, `backend_error`, `turn_superseded` | SSE `error` | unchanged from B-01 |

Evidence: `tests/test_l02_turn_recovery.py` (21), `tests/test_l02_operational.py`, `tests/journey/test_l02_recovery_live.py` (R1–R8: cross-worker retry, drop-then-retry, cross-worker Stop, commit race, worker killed, restart, slow commit, Redis outage) → `evidence/l02_recovery_live_R*.json`; frontend `tests/frontend/test_l02_outcome_recovery.mjs`; browser journeys (`L02_CUSTOMER_JOURNEY_EVIDENCE.md`).

## 4. Limits
* A client that never reconnects never learns the outcome (the transcript is still correct on reload).
* `turn_requests` rows are retained 24 h (`RETENTION_S`); an older key is treated as unknown to the idempotency layer, not as committed.
* Temporary chats keep no `turn_requests` row after closure.
* The C11 Variant B recovery panel is not rendered in `/conversation`; recovery is shown by the existing status/notice surfaces (register item L02-B7).
