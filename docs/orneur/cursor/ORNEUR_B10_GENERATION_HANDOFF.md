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
| `GET /api/generations/{id}` as the owner | The record. A `running` record with no heartbeat for 30 seconds is reported as `interrupted_unknown`. |
| Same call as another account, or with no token when the owner is signed in | HTTP 404 |
| Expired or malformed bearer | HTTP 401 |
| `POST /api/generations/{id}/cancel` while cancellable and running | `cancel_accepted: true`, `code: "cancel_requested"`. The stream then finishes `cancelled` with `reason: "cancel_requested"` and stops taking chunks. |
| Cancel when the run is already terminal | `cancel_accepted: false`, state unchanged |
| Cancel when `cancellable` is false | `cancel_accepted: false`, `code: "generation_not_cancellable"` |
| `POST /api/stream` with the same `Idempotency-Key` and the same `session_id` after success | HTTP 200 JSON `generation_already_completed`. No second stream. |
| Same key while the first run is still `running` | HTTP 409 `generation_in_progress` |
| Same key after `cancelled` or `failed` | HTTP 409 `generation_not_reusable`. Send a new key for a new attempt. |
| Key shorter than 8 characters, or outside `[A-Za-z0-9_-]` | HTTP 400 `generation_rejected` |

`retry_eligible: true` means a new `/api/stream` is allowed. This server does not regenerate, branch, or replay the previous answer.

## Still not implemented

Message edit and immutable versions (B11), temporary-chat retention (B13), correlated multi-conversation streams (B14), and pin/share grants (B06/B09) are not in this change. Do not enable those controls.
