# Runtime Interface (`orca/gateway/runtime.py`)

## The protocol

Every backend implements `InferenceRuntime`: `capabilities()`, `health()`, `generate()`, `stream()`, `load_model()`, `unload_model()`, `cancel()`. Not every runtime supports every feature — `load_model`/`unload_model`/`cancel` return `False` (never raise) when unsupported, and `RuntimeCapabilities` declares the honest feature set up front so the gateway (or a future scheduler) can make routing decisions off real capability data rather than assuming.

## RuntimeCapabilities — what's declared for each current adapter

| Capability | OllamaRuntime | FrontierRuntime |
|---|---|---|
| `streaming` | `NATIVE_STREAMING` | `BUFFERED_ONLY` |
| `cancellation` | `True` (cooperative) | `False` |
| `continuous_batching` | `False` | `False` |
| `model_loading` / `model_unloading` | `True` (via Ollama's warmup-generate / `keep_alive:0` trick) | `False` |
| `tool_calling` | `False` (AgentLoop's tool-use lives above this layer) | `False` |
| `embeddings` | `False` (separate endpoint, out of scope) | `False` |

Nothing here is aspirational — every `True` is backed by working, tested code; every `False` is a real, disclosed limitation, not a placeholder for "not implemented yet."

## OllamaRuntime (`ollama_runtime.py`)

The single place Ollama-specific request/response syntax lives from now on. Wraps and normalizes the already-proven logic from `orca/brain/providers.py`'s `OrcaBrain` — same retry-once-before-any-output timeout handling (fixing the real, previously-documented 34%-timeout incident), same real per-token SSE parsing — rather than reimplementing it. `cancel()` is real but cooperative: Ollama's API has no server-side cancel endpoint, so `cancel(request_id)` marks the request and `stream()` checks between chunks, closing the client-side connection cleanly rather than continuing to relay tokens the caller no longer wants. Verified against this machine's real, live Ollama instance (not just mocked): `tests/test_gateway_ollama_runtime.py`'s 4 live tests cover real health checks, real generation, real streaming, and real cooperative cancellation, auto-skipping if no Ollama instance is reachable.

## FrontierRuntime (`frontier_runtime.py`)

Delegates to the existing, already-correct `orca/brain/backends.py` Backend implementations rather than reimplementing OpenAI/Anthropic request logic. Declares `BUFFERED_ONLY` — this is the module that makes Phase 0's finding ("frontier streaming is fake, already labeled as such in its own code comment") an explicit, structural fact instead of a hidden implementation detail. Its `stream()` method performs the same honest word-chunking `orca/serve/api.py` already does, moved behind the adapter boundary.

## Adding a future runtime (vLLM, SGLang, TensorRT-LLM, etc.)

Per instruction, no full cluster or fake runtime was built this phase — but the shape is exactly: implement `InferenceRuntime`, declare real `RuntimeCapabilities` (do not claim a capability the runtime doesn't actually have), register it with `ModelGateway.register_runtime(name, instance)`, and point a `ModelDeployment.runtime` field at that name. No change to `gateway.py`, cognitive code, or any existing runtime adapter is required.
