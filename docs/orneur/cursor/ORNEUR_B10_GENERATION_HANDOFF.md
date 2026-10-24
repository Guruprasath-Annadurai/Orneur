# B10 / B12 generation handoff for the Claude frontend

No file under `orca/serve/web/` was edited. The Stop control can stay a browser abort until it uses the routes below. Do not relabel that abort as `stopped_confirmed`.

## New events and routes

On the local `/api/stream` path, after the `session` event:

```json
{"type":"generation","generation_id":"<32 hex>","session_id":"...","state":"running","cancel_requested":false,"delivery":"upstream","cancellable":true,"retry_eligible":false,"terminal":false,"reason":null}
```

`done` also includes `generation_id`. A replayed kernel answer on this same path uses `delivery: "replayed"` and `cancellable: false`. The frontier passthrough path does not emit a generation id.

| Call | Result |
|---|---|
| `GET /api/generations/{id}` as the owner | The stored record. `cancelled` and `completed` appear only after `finish` wrote them. A stored `running` record whose heartbeat is older than 30 seconds is reported as `interrupted_unknown`. That word is an observation. It is not stored, and it is not `cancelled`. |
| Same call as another account, or with no token when the owner is signed in | HTTP 404 |
| Expired or malformed bearer | HTTP 401 |
| `POST /api/generations/{id}/cancel` while cancellable and `running` | `cancel_accepted: true`, `code: "cancel_requested"`, `state` still `running`. The route sets a flag. It does not mean the worker has stopped. Read `GET` after the stream ends. The worker then stores `cancelled` with `reason: "cancel_requested"` and stops taking further chunks. A chunk already yielded is not recalled. |
| Cancel when the run is already terminal | `cancel_accepted: false`, `code: "generation_already_terminal"`, stored state unchanged |
| Cancel when `cancellable` is false | `cancel_accepted: false`, `code: "generation_not_cancellable"` |
| Live request with more than 30 seconds between chunks | The request holds a live lock and refreshes the heartbeat every 5 seconds. `GET` stays `running` while that heartbeat is current. |
| `POST /api/stream` with the same `Idempotency-Key`, same session, and same message, model, and session | HTTP 200 JSON `generation_already_completed` after success. No second stream. |
| Same key and same body while the first run is still `running` | HTTP 409 `generation_in_progress` |
| Same key and same body after `cancelled` or `failed` | HTTP 409 `generation_not_reusable`. Send a new key for a new attempt. |
| Same key with a different message or model | HTTP 422 `idempotency_mismatch`. The first generation id is returned. No second generation is created. |
| Key shorter than 8 characters, or outside `[A-Za-z0-9_-]` | HTTP 400 `generation_rejected` |

`retry_eligible: true` means a new `/api/stream` is allowed. This server does not regenerate, branch, or replay the previous answer. Do not label a run stopped from the cancel response alone. `state: "cancelled"` on `GET` is the terminal claim.

A crash after the idempotency key file is durable and before the generation record leaves the reserved id in place. The next request with the same key and the same body republishes that id and may stream. It does not mint a second generation.

## Still not implemented

Message edit and immutable versions (B11), temporary-chat retention (B13), correlated multi-conversation streams (B14), and pin/share grants (B06/B09) are not in this change. Do not enable those controls.
