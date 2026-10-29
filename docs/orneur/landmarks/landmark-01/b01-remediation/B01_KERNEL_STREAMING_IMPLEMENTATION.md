# B-01 — Kernel Streaming Implementation

**Base (PR #134 exact candidate):** `8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`  
**Corrective branch:** `cursor/b01-kernel-incremental-streaming-1cdf`  
**Scope owner:** Cursor (Kernel + gateway integration + tests + Claude handoff)  
**Not closed until:** Claude wires `/api/stream` + Antigravity retests the combined candidate.

## Root cause

`CognitiveKernel._answer_directly()` always called `ModelGateway.generate()`.  
`/api/stream` awaited `_run_cognitive_kernel()` to completion **before** opening the SSE body, then labelled the whole answer `delivery: "replayed"` / `cancellable: false`.

## Architecture boundaries

| Owner | Owns | Does not own |
|---|---|---|
| Cursor (this PR) | `CognitiveRequest.on_raw_delta`, `RawDeltaChannel`, `_answer_directly` → `gateway.stream()`, Kernel tests, Claude handoff docs | `_stream_dispatch` redesign, `conversation.html`, FE |
| Claude | Start SSE before Kernel finishes; drain raw deltas through `StreamRedactor`; set `delivery`/`cancellable`; stop/disconnect cancel | Second inference runtime, SQLite SoT changes |
| Antigravity | Independent retest of combined candidate | Self-cert of Cursor engineering |

## Implementation

1. **`CognitiveRequest.on_raw_delta`** (`orca/cognitive/contracts.py`) — optional `Callable[[str], Awaitable[None]]`. Default `None` preserves generate path.
2. **`orca/cognitive/streaming.py`** — documents the **raw-output security boundary**; `RawDeltaChannel` is a bounded (`maxsize`, default 64) asyncio queue that **never silently drops** deltas (producer blocks when full).
3. **`CognitiveKernel._answer_directly`** — when the hook is set:
   - same tier resolution, conversation context, `InferenceRequest` (with `stream=True`);
   - `async with contextlib.aclosing(gateway.stream(...))`;
   - await hook for each non-empty `InferenceChunk.delta`;
   - accumulate full text + finish/usage/resolved_version for `CognitiveResult`;
   - cancellation / error acloses upstream (no leaked generation tasks).
4. When the hook is absent: unchanged `gateway.generate()`.

## Explicit non-goals (this Cursor wave)

- No simulated tokenisation of a completed string.
- No second ModelGateway / runtime.
- No edit of Claude’s frontend branch.
- No merge of PR #132 into PR #134.
- No change to SQLite fencing / `_QuotaTicket` / `_TurnAuthority` SoT.
