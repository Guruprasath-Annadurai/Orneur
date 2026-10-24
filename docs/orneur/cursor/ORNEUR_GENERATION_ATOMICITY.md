# Generation-state atomicity

This note is the descendant of PR #92. It does not accept any requirement, does not authorize a merge, and does not change `docs/orneur/acceptance/acceptance_ledger.json`.

Preserved heads, not rewritten:

- PR #91 `0637b5ad9b068e74a850a91a11fd41dc83d1f7b3`
- PR #92 `4910a5e3c172d3437da7944c2196848e669d760b`

## Status

**ENGINEERING CANDIDATE — INDEPENDENT REQUALIFICATION PENDING**

`cancelled` and `completed` are stored only by `finish`, after the worker stops or the output is done. A cancel request sets `cancel_requested`. The HTTP cancel response keeps `state: "running"` until a later `GET` shows the stored terminal state. This document does not declare security qualification.

## Root cause on PR #92

`touch`, `request_cancel`, and `finish` each read the JSON, changed a copy, and wrote it back with no shared file lock. Two writers could each read `cancel_requested: false` and the later write dropped the flag. `finish` had the same last-writer window, so a completion could replace a cancellation or the reverse. `request_cancel` also called `finish(..., reason="stale_worker")` when the derived view was `interrupted_unknown`, which stored `cancelled` without the worker having stopped.

Measured on the unmodified `4910a5e3` module, in this workspace, on 24 October 2026 (IST): four threads called `touch` while `request_cancel` ran. The stored flag was missing in 23 of 30 trials. An earlier trial on the same module lost 27 of 30. A completion racing a cancel finished as `completed` / `done` when the completion write landed last.

## What changed

Every read-modify-write of one generation record takes an exclusive `fcntl` lock on `<id>.lock` for the whole transition.

- `touch` updates `updated_at` only while `state` is `running`. It does not clear `cancel_requested`.
- `request_cancel` sets the flag only. It does not call `finish` and does not store `cancelled`.
- `finish` moves `running` to `completed`, `cancelled`, or `failed` once. A second `finish` returns the stored record.
- `public` may report `interrupted_unknown` when a stored `running` record has a heartbeat older than 30 seconds. It does not write that word.
- The streaming request holds `<id>.live` and calls `touch` every 5 seconds until the response finishes, so a chunk longer than 30 seconds stays `running`.
- `done` is emitted only when `finish("completed")` returns a record whose stored state is `completed`.
- An idempotency key stores `request_hash` (sha256 of message, session id, and model variant). A different body is HTTP 422 `idempotency_mismatch`. The key file and the record are published under the key lock. If the process dies after the key file and before the record, the same key and body republish the reserved id. An unreadable record is not overwritten.
- Owner checks are unchanged: `check_session_access` and `record["user_id"] == caller`.

## The ten cases

| Case | Result |
|---|---|
| Cancel racing heartbeats | Flag stays true. Stored state stays `running`. |
| Cancel racing completion | One terminal state remains. The other `finish` does not overwrite it. |
| Duplicate cancels | Every caller sees `cancel_accepted: true` and `state: "running"`. |
| Two processes | Each process cancels and then touches. The parent still reads `cancel_requested: true`. |
| Crash during publication | `publish_fault="after-idempotency-reserve"` leaves the key. The retry reuses that generation id. |
| Chunk gap over 30 seconds | A live heartbeat keeps `state: "running"`. A stopped heartbeat is observed as `interrupted_unknown` and is not stored as `cancelled`. |
| Same idempotency key | One record. One caller gets `created: true`, the other `false`. |
| Same key, different body | `GenerationMismatch`. The stored hash is unchanged. The stream route returns 422 and does not open a second model stream. |
| Cancel after disconnect | `finish(cancelled, reason=client_disconnected)` stays cancelled when a later completion arrives. |
| Restart | A second process reads the stored `failed` state, `retry_eligible: true`, and `terminal: true`. |

## Limitations

- A chunk already yielded cannot be recalled.
- The frontier passthrough path still has no generation id.
- `interrupted_unknown` is derived from `updated_at`. It is not a stored cancel.
- `worker_alive` is the live-lock observation. It is separate from the derived state.
- The same OS user can still rewrite their own generation file. The server does not do that.
- Stream idempotency does not cache model text. `/api/chat` idempotency remains the separate sqlite cache.
- `begin` on `/api/stream` still runs after planning. A repeated key avoids a second stream. It does not skip the planning that already ran on that request.
- Same-OS-user binding edits are unchanged from PR #91. This patch does not weaken them and does not requalify them.
