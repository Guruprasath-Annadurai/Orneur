# B-01 — Security and Cancellation Invariants

**Applies to Kernel streaming tip on branch `cursor/b01-kernel-incremental-streaming-1cdf`.**

## Raw-output boundary (mandatory)

`on_raw_delta` / `RawDeltaChannel` carry **unredacted** provider text.

| Must never | Enforcement |
|---|---|
| Browser / SSE yield of raw deltas | Claude must use `StreamRedactor` (Cursor does not wire SSE in this PR) |
| Persist raw to SQLite / JSONL / Redis | Persist only after redaction of the complete safe text |
| Log raw as content | Audit metadata only |
| Long-term / working memory contamination from cancelled partials | Kernel still only finalizes memory on successful COMPLETED path |

## Authentication / quota / authority (preserved)

This Kernel change does **not** alter:

- `get_current_user_optional` / fail-closed 401 behavior
- `_QuotaTicket` admit / consume / release
- `_TurnAuthority` acquire / heartbeat / release
- SQLite fencing epochs

Claude’s API patch must keep: authority held for the full streamed generation; consume quota on first billable output (existing AgentLoop stream policy); no false refund after billable chunks; no phantom commits on cancel.

## Cancellation

1. Cancelling the `kernel.execute` task propagates `CancelledError` through `await on_raw_delta` / gateway `__anext__`.
2. `contextlib.aclosing` + gateway `_stop_upstream` closes the runtime stream and releases the concurrency permit.
3. Tests assert `_active_streams == 0` after cancel — no leaked background generation.

## Model identity

Streaming path stamps `resolved_version` from gateway chunks / deployment (fixture preserves `llama3.2:1b` colon tag). No GENESIS/NOVUS/AETERNUM mislabel of third-party tags.

## Budget / planning

Planning, entitlement reconciliation, Truth Fabric routing, and abstention paths are unchanged. Streaming only replaces `generate` with `stream` inside `_answer_directly` when the optional hook is set.
