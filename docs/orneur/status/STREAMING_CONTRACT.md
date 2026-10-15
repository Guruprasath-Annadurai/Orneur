# ModelGateway streaming contract (Workstream A)

Scope: `orca/gateway/gateway.py::ModelGateway.stream()`. Verified only against deterministic in-process runtime doubles (`tests/test_gateway_stream_contract.py`); **no real model was involved.** Additive: no existing signature changed.

| Property | Behaviour | Test |
|---|---|---|
| Honest streaming | Chunks are forwarded as the runtime produces them (pull-based async generator); nothing is buffered or re-chunked, and no word-by-word replay is ever generated | `…pull_based…`, `…happy_path…` |
| First-token timeout | Bounded wait for the first chunk; a hung upstream raises `GenerationTimeoutError` (previously it waited forever) | `…never_sends_a_first_chunk…` |
| Idle timeout | New `TimeoutPolicy.stream_idle_timeout_s` (default 60 s) bounds silence between chunks; chunks already delivered stay delivered | `…stall_after_some_chunks…` |
| Total deadline | `total_request_timeout_s` now also bounds streams (previously only `generate()`) | `…total_request_deadline…` |
| Client stop / disconnect | Closing the stream (or cancelling the serving task) calls `runtime.cancel(request_id)`, closes the upstream generator, frees the concurrency slot, records a cancellation, and does **not** count as a circuit-breaker failure | `…client_stop…`, `…task_cancellation…` |
| Backpressure | Pull-based: a slow consumer can never make the gateway queue more than one chunk | `…pull_based…` |
| Serving identity | `InferenceChunk` gains optional `deployment_id`, `resolved_version`, `runtime`, stamped from the deployment that actually served the request, never from the requested alias | `…actual_serving_identity…` |
| Authorization | Untouched: the gateway does not authorize; `_authorize_inference` in the API still runs before any stream starts | `tests/test_a_serving_authorization.py` |

Failing-before evidence: with the previous implementation 6 of these 8 tests failed (the other 2 are characterization tests of already-correct behaviour).

**Not done / open:** the web `/api/stream` route streams through `orca.brain` backends (not this gateway) and discards the partial answer when the client disconnects; keeping an interrupted partial turn is a product decision. Structured SSE error codes for gateway timeouts are inherited from the existing error catalogue; no new codes were added.
