# ORNEUR backend API contract (versioned for Claude UI)

**Schema:** `orneur.backend.api/1`  
**Source of truth:** `orca/serve/api.py`, `orca/auth/routes.py`  
**Claude UI files are not edited here.** Wire the frontend to this contract; do not invent model output.

This is an engineering contract, not production acceptance and not a training grant.

## Auth

Bearer token from `POST /api/auth/signup` or `POST /api/auth/login`. Optional-auth routes still enforce session ownership when a token is present.

## Conversations (`orneur.conversation/1`)

| Method | Path | Ownership | Notes |
|---|---|---|---|
| GET | `/api/sessions` | caller | list |
| GET | `/api/session/{id}` | 404 if not owner | load |
| PATCH | `/api/session/{id}/title` | required | rename |
| GET | `/api/session/{id}/messages` | required | durable messages |
| GET | `/api/sessions/search?q=` | required | search |
| GET | `/api/session/{id}/export` | required | JSON export |
| DELETE | `/api/session/{id}` | required | delete |
| POST | `/api/session/{id}/save` | required | persist |

The UI may still use client-side export; the server export is the durable contract.

## Streaming (`POST /api/stream`)

SSE events, in order when successful:

1. `session` — `{type, session_id}`
2. `model` — `{type, identity}` (`model_identity` disclosure)
3. optional `rag` / `thinking`
4. `stream` — `{type, delivery, cancellable}`
   - `delivery=upstream`, `cancellable=true`: chunks are live; closing the HTTP connection cancels upstream generation (G-026 kernel-direct and AgentLoop paths).
   - `delivery=replayed`, `cancellable=false`: the answer already existed (Truth Fabric / frontier generate). Do not present a stop control that cannot stop generation.
5. one or more `chunk` — `{type, text}` (`replayed: true` only on the replayed path)
6. `done` — `{type, message_id, delivery, model_identity, sources, source_summary, citation_compliance, ...}`

Errors are SSE `error` events with catalog `code` values, not fake completions.

`POST /api/chat` remains a completed-response route (kernel still `generate()`s).

## Models

`GET /api/models` discloses availability and lifecycle. Missing inference providers must be reported as unavailable, never filled with fabricated answers.

## Not in this contract

- Native-model training
- GPU execution
- Acceptance ledger rows
- Claude-owned files under `orca/serve/web/`
