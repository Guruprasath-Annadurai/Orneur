# PR #85 integration plan

Reviewed Claude PR #85 at the requested commit `950909e7533c9d26aa62b689e64f8badbfebf0f8` and the current PR head `92b6f155b49e` (one later B16 attachment-identity correction). No frontend file was edited. No protected branch was merged. This is a contract and test plan, not an integration candidate and not acceptance.

PR #90 remains the audit target at `476ee36137aae1600048187d9a46d4a35816b00d`. An integration branch is not opened until Antigravity requalifies that head and the revocation-freshness follow-up.

## What the backend already does

| Area | Backend today | Claude UI at PR #85 |
|---|---|---|
| No `Authorization` header | Guest where the route allows it | Guest shell |
| Valid bearer | Authenticated user | Signed-in shell |
| Expired, revoked, forged, reset, 2FA-pending, or malformed `Authorization` | HTTP 401 `Invalid or expired token` | `_handleSessionExpired()` on status 401. 403 `retrieval_unauthorized` is not session expiry |
| Other user's session | HTTP 404 | Must not show the other account's transcript |
| `POST /api/stream` disconnect | `request.is_disconnected()` cancels upstream generation on the kernel-direct and agent paths. Replayed Truth Fabric / frontier answers are `cancellable: false` | Stop aborts the browser fetch and says the server stop is not confirmed |
| History, search, rename, export, delete | Present for the owner | Wired |
| Upload, list, delete, authorized retrieval | Signed-in passages come from the conversation's authorized index. Citations carry `doc_id` and `content_sha256` when authorized | B16 wires the existing upload pipeline. PR head `92b6f15` corrects attachment identity |
| Account switch | Ownership is per user id. A second account's token must 404 on the first account's session | UI drops the previous view on identity change |

## Tests an integration candidate must run

Do not treat a green isolated PR as proof of the combination.

1. Signup, login, `GET /api/auth/me`, then the same calls with an expired bearer. Expect 401, not an empty session list.
2. `POST /api/stream` with FakeOllama or the kernel-direct double. Expect `delivery=upstream`, `cancellable=true`, and a closed client to stop further chunks.
3. A Truth Fabric or frontier replay stays `delivery=replayed`, `cancellable=false`.
4. `GET /api/sessions/search` returns only the caller's conversations. A second account searching the same string does not see them.
5. Upload, list, chat, and delete for one signed-in conversation. The model request contains the uploaded text. After delete or revoke it does not. A legacy-only poison string never appears.
6. Source cards keep `doc_id` and `content_sha256` for authorized passages. `tool_grant` and `production_neural` are false.
7. Sign in as A, load A's session as B. Expect 404. Switch the token back to A and the session still loads.
8. Expired token on upload, session load, and stream. Expect 401 and no write.
9. Two conversations of one user do not share passages, including after a second process revokes only one of them.

## Not available yet

These are named gaps. The UI must keep its disabled or honest-limitation states until the backend below exists. None of them is claimed complete.

- **B10 / B12.** The cancellable `/api/stream` path now returns a `generation` event and `done.generation_id`. `GET /api/generations/{id}` reports the stored state: `running`, `completed`, `cancelled`, or `failed`. A stored `running` record with a heartbeat older than 30 seconds is reported as `interrupted_unknown`; that is not written back and is not `cancelled`. The open request refreshes the heartbeat every 5 seconds, including across a chunk longer than 30 seconds. `POST /api/generations/{id}/cancel` only sets `cancel_requested` and returns `state: "running"` with `cancel_accepted: true`. The worker stores `cancelled` when it actually stops. `done` is emitted only after `finish` stored `completed`. `retry_eligible` is true only for `cancelled`, `failed`, and observed `interrupted_unknown`, and it means the client may send a new request. It does not regenerate. The same `Idempotency-Key` and the same body on the same session do not open a second stream. A different body for that key is HTTP 422 `idempotency_mismatch`. A crash after the key file and before the record republishes the reserved id. Replayed frontier responses still have no generation id. The UI Stop control is still a browser abort until it calls the cancel route and reads `GET` after the worker stops. Do not treat the cancel response itself as `cancelled`.
- **B11.** `POST /api/session/{id}/messages/{message_id}/edits` appends an immutable version and moves the active pointer. `POST .../regenerate` asks the model for a new assistant version, bound to a generation id, and commits it only after the completion returns text. A model failure leaves the previous version active and stores the generation as `failed`. The same idempotency key and body do not create a second version or a second model call. A different edit body for that key is HTTP 422. `GET .../versions` lists every committed version, including the original. Transcript, search, and export show the active text. The JSONL line is not rewritten. Long-term vector memory is not rewritten. The Save control in the UI stays disabled until it calls these routes. Regenerate does not re-run authorized document retrieval, and it is not cancelled by the generation cancel route.
- **B13.** `POST /api/sessions/temporary` stores an active temporary chat after a policy check. TTL is 60 seconds to 24 hours. List, search, export, long-term memory, continuum ingest, Redis history, and knowledge-graph extraction do not keep it. Close and expiry delete the transcript, versions, and generation records before the response says `closed` or `expired`. The UI control stays disabled until it calls these routes.
- **B14.** `POST /api/runs` creates a correlation id for the signed-in account. `POST /api/stream` with `X-Run-Id` attaches that stream's generation to the run when the caller owns both the run and the conversation. `GET /api/runs/{id}` lists those generation and session ids. Another account receives HTTP 404 and cannot attach. A stream without the header has `run_id: null`. The run does not grant conversation access. Workspace tabs are not implemented.
- **B06 / B09.** `POST /api/session/{id}/pin` and `DELETE` are owner metadata. The session list includes `pinned`. Folders are `POST /api/folders` and `POST /api/folders/{id}/sessions`. A share is `POST /api/session/{id}/shares` with a grantee id and a TTL from 60 seconds to 30 days. The grantee reads `GET /api/shares/{id}/messages`. That body and the grant JSON omit the session id. `GET /api/session/{id}/messages` stays HTTP 404 for that grantee. Revoke, expiry, conversation deletion, and account deletion stop the grant. An active temporary chat cannot be shared. The UI pin and share controls stay disabled until they call these routes.

## C-series

Claude's matrix, reconfirmed against the later design archives, marks C01–C11 blocked on missing authentic design source and C12–C14 blocked on backend or authority. The contract for what a backend can promise without those approvals is `docs/orneur/cursor/ORNEUR_C_SERIES_API_CONTRACTS.md`. Library, connectors, schedules, and notifications are proposed shapes there and are not mounted. `GET` and `POST` on those paths return HTTP 404. No enterprise, billing extension, or third-party connector is invented. Designer Chat visual specifications are still required before those screens are built.

## When qualification permits

The integration candidate should merge, without rewriting history:

- `cursor/p0-security-correction-a8b0` at `476ee36`, plus the revocation-freshness descendant once requalified
- `claude/b04-b09-implementation-2026-10-23` at `92b6f15` or a later requalified frontend head

Reconcile `orca/serve/api.py` by behavior, not by picking one side. Do not merge into a protected branch from this plan.
