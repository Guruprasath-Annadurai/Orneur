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

- **B10 / B12.** The cancellable `/api/stream` path now returns a `generation` event and `done.generation_id`. `GET /api/generations/{id}` reports `running`, `completed`, `cancelled`, `failed`, or a stale `interrupted_unknown`. `POST /api/generations/{id}/cancel` asks a cancellable run to stop; the stream records `cancelled` before any further chunk. `retry_eligible` is true only for `cancelled`, `failed`, and `interrupted_unknown`, and it means the client may send a new request. It does not regenerate. A repeated `Idempotency-Key` on the same session does not open a second stream. Replayed frontier responses still have no generation id. The UI Stop control is still a browser abort until it calls the cancel route and reads the terminal state.
- **B11.** No message edit, immutable version, or idempotent regenerate route. `GET /api/session/{id}/messages` is read-only.
- **B13.** No temporary-chat mode, retention clock, or deletion sweep. A disabled control is the truthful UI.
- **B14.** One HTTP stream is owned by one session. There is no server run id correlating several live streams across conversations.
- **B06 / B09 organization.** List, search, rename, export, and delete exist. Pin, folder, and share-grant routes do not. A share must be an explicit grant with expiry and revocation, not a guessable session id.

## C-series

Claude's matrix, reconfirmed against the later design archives, marks C01–C11 blocked on missing authentic design source and C12–C14 blocked on backend or authority. Projects, onboarding completion, library, plugins, connectors, scheduled tasks, notifications, and skills are not implemented here. No enterprise, billing, or third-party connector is invented to fill that gap. Designer Chat visual specifications are still required before those screens are built.

## When qualification permits

The integration candidate should merge, without rewriting history:

- `cursor/p0-security-correction-a8b0` at `476ee36`, plus the revocation-freshness descendant once requalified
- `claude/b04-b09-implementation-2026-10-23` at `92b6f15` or a later requalified frontend head

Reconcile `orca/serve/api.py` by behavior, not by picking one side. Do not merge into a protected branch from this plan.
