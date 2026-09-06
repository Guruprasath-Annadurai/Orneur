"""
Frontier API passthrough runtime (OpenAI/Anthropic) -- wraps the existing,
already-correct orca/brain/backends.py Backend implementations rather than
reimplementing their request logic. The one thing this adapter must never
do is claim NATIVE_STREAMING: Phase 0 found this path's "streaming" is a
synchronous generate() call chunked by word after the fact
(orca/serve/api.py:677's own comment labels it "Fake-stream"). This
runtime declares BUFFERED_ONLY and Model Gateway callers decide how to
present that honestly to a client, rather than this adapter papering over
it with artificial chunk delays.
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from orca.brain.backends import build_backend
from orca.gateway.contracts import InferenceChunk, InferenceRequest, InferenceResponse, StreamingMode
from orca.gateway.errors import RequestCancelledError, RuntimeExecutionError
from orca.gateway.runtime import RuntimeCapabilities


class FrontierRuntime:
    def __init__(self, backend_name: str, api_key: str, deployment_id: str | None = None):
        self.backend_name = backend_name  # "openai" | "anthropic"
        self.api_key = api_key
        self.name = backend_name
        self.deployment_id = deployment_id or f"{backend_name}-passthrough"
        self._cancelled_requests: set[str] = set()

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            streaming=StreamingMode.BUFFERED_ONLY,   # honest -- see module docstring
            cancellation=False,   # the underlying SDK call is a single synchronous request; nothing to cancel mid-flight
            continuous_batching=False,
            prefix_cache=False,
            model_loading=False,   # not applicable to a hosted API
            model_unloading=False,
            quantization=False,
            logprobs=False,
            structured_output=False,
            embeddings=False,
            tool_calling=False,   # explicitly out of scope for this passthrough path -- see orca/serve/api.py's honest-scope docstring
            max_context=128000,   # a conservative default; not enforced here, the provider enforces its own limit
        )

    async def health(self) -> bool:
        return bool(self.api_key)

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        if request.request_id in self._cancelled_requests:
            raise RequestCancelledError()
        backend = build_backend(self.backend_name, request.model_version or request.model_id, api_key=self.api_key)
        t0 = time.monotonic()
        # The underlying SDK call is synchronous; run it off the event loop
        # thread so the gateway's own async timeout/cancellation machinery
        # isn't blocked by it (matches the existing pattern already used in
        # orca/serve/api.py's asyncio.to_thread call for this same backend).
        try:
            prompt = request.messages[-1]["content"] if request.messages else ""
            result = await asyncio.to_thread(
                backend.generate, prompt, request.system or "", request.max_tokens, request.temperature,
            )
        except Exception as e:
            raise RuntimeExecutionError(internal_detail=str(e))
        latency_ms = (time.monotonic() - t0) * 1000
        return InferenceResponse(
            request_id=request.request_id,
            model_id=request.model_id,
            resolved_version=result.model,
            runtime=self.backend_name,
            deployment_id=self.deployment_id,
            output=result.text,
            finish_reason="stop",
            prompt_tokens=result.input_tokens,
            completion_tokens=result.output_tokens,
            latency_ms=latency_ms,
            queue_latency_ms=0.0,
            model_latency_ms=latency_ms,
            trace_id=request.trace_id,
            data_left_infrastructure=result.data_left_infrastructure,
            cost_usd=result.cost_usd,
        )

    async def stream(self, request: InferenceRequest) -> AsyncIterator[InferenceChunk]:
        """
        Honest buffered "streaming": generates the full response first,
        then yields it word-by-word so callers built around an async-
        iterator interface still work -- but capabilities().streaming
        already told the caller this is BUFFERED_ONLY, so nothing here
        pretends this is real token-level generation. This mirrors the
        existing, already-labeled-fake behavior in orca/serve/api.py,
        moved behind the adapter boundary rather than duplicated at the
        API layer.
        """
        response = await self.generate(request)
        words = response.output.split(" ")
        for i, w in enumerate(words):
            if request.request_id in self._cancelled_requests:
                self._cancelled_requests.discard(request.request_id)
                yield InferenceChunk(request_id=request.request_id, sequence=i, delta="", finish_reason="cancelled", trace_id=request.trace_id)
                return
            delta = w if i == 0 else f" {w}"
            yield InferenceChunk(request_id=request.request_id, sequence=i, delta=delta, trace_id=request.trace_id)
            await asyncio.sleep(0)
        yield InferenceChunk(
            request_id=request.request_id, sequence=len(words), delta="", finish_reason="stop",
            prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
            trace_id=request.trace_id,
        )

    async def load_model(self, model_ref: str) -> bool:
        return False  # not supported -- hosted API, no local loading concept

    async def unload_model(self, model_ref: str) -> bool:
        return False

    async def cancel(self, request_id: str) -> bool:
        """
        Best-effort only: the underlying request may already be a
        completed synchronous call by the time this is invoked (see
        capabilities().cancellation=False) -- this only stops the
        word-by-word buffered-streaming loop above from yielding further
        chunks, not an in-flight API call.
        """
        self._cancelled_requests.add(request_id)
        return False
