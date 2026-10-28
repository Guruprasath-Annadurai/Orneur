# Backend ↔ Frontend Contract — FOUNDATION LANDMARK-01

Canonical contract for Claude’s browser-facing LANDMARK-01 integration.  
**Backend tip:** see `FOUNDATION_01_TIP_SHA.txt` / PR #132 HEAD.  
**Cursor does not redesign `conversation.html` or Claude’s frontend branch.** Frontend changes required by this contract are Claude’s.

## Claude — copyable handoff (required FE changes)

1. **Before generation:** `fetch`/`XHR` to `POST /api/stream`. If `status` is not 200 **or** `Content-Type` is not `text/event-stream`, parse **JSON body** as an admission error (`auth_required` 401, `model_access_denied` 402, `content_refused` 400, `not_found` 404, `quota_exceeded` 429). Do **not** attach an EventSource/SSE parser.
2. **After admission:** parse SSE events (`session` → `generation` → `model` → `stream` → `chunk*` → `done`).
3. **Persistence:** delivered `chunk` text ≠ SQLite commit. On `done`, if `user_message_id` is null/missing, treat history as unconfirmed; always reload `GET /api/session/{session_id}/messages` for SoT.
4. Use server `session_id`, `generation_id`, `message_id`, `user_message_id`, and `model_identity` — never invent client-side authority for ownership or model entitlement.
5. Edits: `POST /api/session/{session_id}/messages/{message_id}/edits` then refresh context from messages API.
6. Logout: `POST /api/auth/logout` (or logout-all); clear bearer; subsequent calls with old token must surface 401.
7. Temporary chat: create via temporary session API; on close/expiry do not expect transcript resurrection.
8. Retries: prefer `Idempotency-Key` / consumed `request_id` replay rules; do not double-submit blindly after uncertain network.

## Authentication

| Item | Contract |
|---|---|
| Header | `Authorization: Bearer <session JWT>` or `Authorization: Bearer athr_<api_key>` |
| Missing credential | Route-dependent: product chat/stream currently allow anonymous local nano; private history/export require auth (`auth_required` / 401) |
| Invalid / expired / revoked / wrong-type token | **401** — never downgraded to anonymous |
| Password-reset / email-verify / 2FA-pending tokens | 401 — not session credentials |
| Logout | `POST /api/auth/logout` revokes current `jti` |
| Logout-all | `POST /api/auth/logout-all` invalidates all sessions via `tokens_valid_after` |

Sensitive errors must not reveal whether a session id exists for another user (prefer 404).

## Session creation & ownership

- Client may omit `session_id` (server allocates) or send an existing id.
- First authenticated writer claims ownership (`claim_session`).
- Cross-user access to transcript / edit / export / memory → refuse (404/403). Zero model dispatch.

## Chat (non-stream)

`POST /api/chat`

```json
{ "message": "...", "session_id": "...", "model_variant": "nano" }
```

Success (shape — fields may grow; required for Claude):

```json
{
  "response": "<DLP-safe text>",
  "session_id": "...",
  "model_identity": { },
  "request_id": "<quota reservation id when authenticated>"
}
```

Failures (HTTP JSON, not SSE): `quota_exceeded` (429), `model_access_denied` (402), `content_refused` (400), `not_found` (404, ownership), `auth_required` (401), `request_abstained`.

Optional: `Idempotency-Key` header (signed-in). Same key + payload → replay without second dispatch (`Idempotent-Replay: true`).

## Streaming SSE

`POST /api/stream`

### Pre-stream admission refusals (HTTP JSON — no SSE body)

When admission fails **before** generation starts, the response is ordinary JSON with the correct HTTP status (not `text/event-stream` 200):

| Code | Status |
|---|---|
| `model_access_denied` | 402 |
| `quota_exceeded` | 429 |
| `content_refused` | 400 |
| `not_found` (foreign/unowned session) | 404 |
| `auth_required` | 401 |

Claude **must** inspect HTTP status and `Content-Type` before parsing SSE. Zero model dispatch on these refusals.

### Successful stream (`text/event-stream`)

Typical event order:

1. `{"type":"session","session_id":"..."}`
2. `{"type":"generation","generation_id":"...","session_id":"..."}`
3. `{"type":"model","identity":{...}}`
4. `{"type":"stream","delivery":"upstream"|"replayed","cancellable":true|false}`
5. zero or more `{"type":"chunk","text":"..."}` (already DLP-redacted)
6. `{"type":"done", ... "message_id":"...","user_message_id":"...", "model_identity":{...}}`

Rules:

- `delivery: "replayed"` means one complete payload, **not** token streaming.
- Secrets are redacted **before** browser delivery.
- Client disconnect cancels upstream when `cancellable: true`.
- Delivered chunks are not a persistence guarantee; reload transcript after `done` for SoT.

## Inference API

`POST /api/inference/complete` and `/api/inference/stream` require authentication (`get_current_user`). Same admission controls (quota reservation, ownership, DLP, SQLite fencing commit).

## Editing

`POST /api/session/{session_id}/messages/{message_id}/edits`

```json
{ "content": "new text" }
```

- Owner only.
- Creates a new message version; subsequent model context uses active version and drops invalidated tail after the edit point.
- Idempotency key supported when provided by client headers (see route).
- After edit, reload messages API before next generation.

## Transcript retrieval

`GET /api/session/{session_id}/messages?limit=&offset=`

- Auth required; ownership enforced.
- Source of truth: SQLite turns (+ version overlay). Not uncommitted JSONL.

## Quota errors

```json
{ "error": { "code": "quota_exceeded", "message": "...", "used": 50, "limit": 50 } }
```

On stream, quota may also arrive as HTTP JSON **429** before SSE starts. Concurrent admits at the limit: only the permitted count succeed. Consumed `request_id` replay returns stored response without redispatch when fingerprint matches.

## Model identity

- Server-assigned `model_identity` is authoritative (includes resolved provider/backend facts the server chooses to expose).
- Client `model_variant` is a request hint, not an entitlement proof.
- GENESIS / NOVUS / AETERNUM are native programmes — not Ollama aliases. Unauthorized native identities must be refused.
- Ollama tags with colons (e.g. `llama3.2:1b`) are preserved via colon-safe deployment ids.

## Temporary chat

- `POST /api/sessions/temporary` → activate TTL-bound private session.
- Close / expiry deletes transcript content; tombstones may remain without private text.
- Late workers must not re-publish closed temporary content (`_stream_may_publish` / finish gates).

## Cancellation

- Stream: client disconnect or generation cancel flag.
- Quota: release reservation if generation fails before consume; consumed reservations are not refunded.

## Persistence confirmation

- Durable truth is SQLite `commit_turn` success (fencing epoch + fence token).
- Redis `persist_to_redis` is advisory cache only — never sole commit authority.
- JSONL / episodic files are derived; do not treat them as SoT.
- `/api/chat` returns model text after a best-effort `_persist_turn`; it does **not** emit a `saved: true` claim. On commit failure the HTTP body still carries delivered text — reload `GET /api/session/{id}/messages` for authoritative history.
- `/api/stream` `done` always carries the generation `message_id`. `user_message_id` is present only when SQLite commit succeeded; `null`/`omitted` means commit did not confirm — reload messages API.
- Delivered SSE chunks ≠ confirmed persistence.

## Retry semantics

- Same `request_id` + fingerprint after consume → replay, no second provider call.
- Same Idempotency-Key + payload → cached HTTP response.
- Uncertain commit: reload transcript; do not assume JSONL order.

## Concurrent requests

- Same session: turn lease / SQLite authority serializes commits.
- Same user, different sessions: parallel admits subject to global daily quota.
- Cross-user: isolation mandatory.
