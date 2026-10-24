# B13 temporary chat handoff for the Claude frontend

No file under `orca/serve/web/` was edited. The "Start temporary chat" control stays disabled until it calls these routes. Do not treat a client-only flag as a temporary chat.

## Routes

Signed-in only. Another account receives HTTP 404.

| Call | Result |
|---|---|
| `POST /api/sessions/temporary` with `{"ttl_seconds": 3600}` | Creates a session and stores `state: "active"` only after the policy check. `ttl_seconds` must be from 60 to 86400. `created: true`. |
| Same call with that `session_id` while it is still active | `created: false` and the original `expires_at`. The TTL is not extended. |
| `ttl_seconds` outside that range | HTTP 400 `temporary_rejected`. No session is created. |
| An existing normal transcript | HTTP 409 `temporary_not_empty`. The transcript is kept. |
| `GET /api/session/{id}/temporary` | `active`, `closed`, `expired`, `failed`, or `inactive` for a normal owned session. |
| `POST /api/session/{id}/temporary/close` | Deletes the transcript, message versions, generation records, and the usual session cascade, then stores `closed`. |
| Chat or stream after expiry or close | HTTP 409 `temporary_expired` or `temporary_closed`. The model is not called for that refusal. |

`transitions` on the record is `policy_check`, then `activation_pending`, then `active`. `closed` or `expired` is appended only after the transcript file is gone. A deletion that leaves the transcript stores `failed` and is not reported as closed.

## Privacy that this server enforces

While the chat is active:

- `GET /api/sessions` and `GET /api/sessions/search` omit it.
- Export returns HTTP 409 `temporary_not_exportable`.
- `POST /api/remember` returns HTTP 409 `temporary_memory_disabled`.
- The turn is not written to long-term vector memory, continuum ingest, Redis history, or the knowledge-graph extractor.
- The JSONL transcript still exists so the open chat can call `GET /api/session/{id}/messages`.

The tombstone stores no message text. After close, the session ownership claim is released. A later read of the message route sees an empty transcript, not the deleted text.

The six-hour retention loop also calls the same expiry deletion. It does not wait for the user's `retention_days` setting.

## What this does not do

- It does not delete backups, logs outside the session cascade, or a third-party index.
- It does not hide the chat from the process that is serving it.
- A same-OS-user can still read the transcript file until close or expiry. The server deletes that file when it finishes the chat.
- `redis_deleted` is true only when Redis is enabled. This environment does not claim Redis was running.
