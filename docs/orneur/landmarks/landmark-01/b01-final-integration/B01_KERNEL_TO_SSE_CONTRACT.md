# B-01 Kernel → SSE Contract

## Eligibility

- Backend: ollama
- Session doc_store count == 0 (live session probe; no premature allocate for docs>0)
- Otherwise: legacy await-Kernel path (AgentLoop / Truth Fabric / frontier)

## Event order (upstream Kernel-direct)

1. `session`
2. `generation`
3. `model` (`provisional: true` until CognitiveResult resolves)
4. `stream` `{delivery:"upstream", cancellable:true}`
5. `chunk*` (StreamRedactor-safe only) when Kernel answers via `on_raw_delta`
6. `model` (resolved, non-provisional) once CognitiveResult is known
7. `done` with `delivery:"upstream"`, `persisted`, final `model_identity`

## Kernel deferral → AgentLoop

If CognitiveResult has `output is None` (tools / plan deferral) and no raw
deltas were emitted, the same SSE generator continues with `agent.stream`
under the already-announced `upstream`/`cancellable` contract. It must not
emit `invalid_request` or invent a completed answer.

## Refusal protocol (honest)

Pre-stream on `/api/stream` still often uses **SSE error events** (model_access_denied, content_refused, quota, session_busy) — not solely HTTP JSON.  
Do not claim HTTP-JSON-only for this route. `/api/chat` remains JSON.

## Raw boundary

`on_raw_delta` / channel = unredacted. Browser/transcript/memory only see StreamRedactor output.
