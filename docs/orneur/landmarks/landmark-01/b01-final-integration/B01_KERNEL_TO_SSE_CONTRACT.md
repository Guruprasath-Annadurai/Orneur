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
5. `chunk*` (StreamRedactor-safe only)
6. `done` with `delivery:"upstream"`, `persisted`, final `model_identity`

## Refusal protocol (honest)

Pre-stream on `/api/stream` still often uses **SSE error events** (model_access_denied, content_refused, quota, session_busy) — not solely HTTP JSON.  
Do not claim HTTP-JSON-only for this route. `/api/chat` remains JSON.

## Raw boundary

`on_raw_delta` / channel = unredacted. Browser/transcript/memory only see StreamRedactor output.
