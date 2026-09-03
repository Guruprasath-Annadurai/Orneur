"""
Ollama runtime adapter -- the ONE place Ollama-specific request/response
syntax lives, so cognitive/application code depends only on the
InferenceRuntime protocol from here on. Wraps and normalizes the real,
already-proven behavior from orca/brain/providers.py's OrcaBrain (retry-
once-before-any-output timeout handling, real per-token streaming) rather
than rewriting it -- this adapter is new, but the underlying request/retry
logic it encodes is not a novel design, it's the same logic verified
working in providers.py, restated behind the new interface.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncIterator

import httpx

from orca.gateway.contracts import InferenceChunk, InferenceRequest, InferenceResponse, StreamingMode
from orca.gateway.errors import (
    DeploymentUnavailableError,
    GenerationTimeoutError,
    RequestCancelledError,
    RuntimeExecutionError,
)
from orca.gateway.runtime import RuntimeCapabilities


class OllamaRuntime:
    name = "ollama"

    def __init__(self, host: str, deployment_id: str = "ollama-local", timeout_s: float = 120.0):
        self.host = host.rstrip("/")
        self.deployment_id = deployment_id
        self.timeout_s = timeout_s
        self._cancelled_requests: set[str] = set()

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            streaming=StreamingMode.NATIVE_STREAMING,
            cancellation=True,   # cooperative -- see stream()'s cancellation check between chunks
            continuous_batching=False,
            prefix_cache=False,
            model_loading=True,   # via an empty-prompt warmup generate call
            model_unloading=True,  # via keep_alive=0
            quantization=False,   # not something this adapter controls -- baked into the GGUF already
            logprobs=False,
            structured_output=False,
            embeddings=False,   # separate /api/embeddings endpoint, out of scope for this adapter
            tool_calling=False,  # Orca's own AgentLoop implements tool-use above this layer, not via Ollama's native tool-calling API
            max_context=8192,   # a default; actual per-model context comes from ModelDeployment.context_limit
        )

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{self.host}/api/tags", timeout=5)
                r.raise_for_status()
                return True
        except Exception:
            return False

    def _payload(self, request: InferenceRequest, stream: bool) -> dict:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend(request.messages)
        options = {
            "temperature": request.temperature,
            "num_predict": request.max_tokens,
            "top_p": request.top_p,
        }
        if request.stop:
            options["stop"] = request.stop
        if request.seed is not None:
            options["seed"] = request.seed
        return {"model": request.model_version or request.model_id, "messages": messages, "stream": stream, "options": options}

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        """
        Non-streaming path. Retries once on a pre-output timeout, matching
        OrcaBrain.complete()'s proven behavior -- a real fix for a real
        34%-timeout-rate incident documented in orca/brain/providers.py.
        """
        payload = self._payload(request, stream=False)
        timeout = request.timeout_s or self.timeout_s
        t0 = time.monotonic()
        last_error: Exception | None = None
        retries = 0

        for attempt in range(2):
            if request.request_id in self._cancelled_requests:
                raise RequestCancelledError()
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
                    r.raise_for_status()
                    data = r.json()
                    latency_ms = (time.monotonic() - t0) * 1000
                    return InferenceResponse(
                        request_id=request.request_id,
                        model_id=request.model_id,
                        resolved_version=payload["model"],
                        runtime=self.name,
                        deployment_id=self.deployment_id,
                        output=data.get("message", {}).get("content", ""),
                        finish_reason="stop" if data.get("done") else "length",
                        prompt_tokens=data.get("prompt_eval_count", 0),
                        completion_tokens=data.get("eval_count", 0),
                        latency_ms=latency_ms,
                        queue_latency_ms=0.0,
                        model_latency_ms=latency_ms,
                        retries=retries,
                        trace_id=request.trace_id,
                        data_left_infrastructure=False,
                    )
            except httpx.ConnectError as e:
                raise DeploymentUnavailableError(self.deployment_id, internal_detail=str(e))
            except httpx.TimeoutException as e:
                last_error = e
                retries += 1
                continue
            except asyncio.CancelledError:
                # Only convert to the domain-specific RequestCancelledError
                # for a request this runtime was explicitly told to cancel
                # via cancel(request_id) -- that is the one case where a
                # caller wants a stable, catchable exception type rather
                # than bare CancelledError. Any OTHER CancelledError delivery
                # (an enclosing asyncio.wait_for()'s own deadline expiring,
                # or an external task.cancel()) must be re-raised as-is:
                # asyncio.wait_for()/asyncio.timeout() only convert their own
                # expiry into TimeoutError when a genuine CancelledError
                # propagates out of the awaited coroutine -- swallowing it
                # here and substituting a different exception type silently
                # defeated every caller's deadline handling (Gateway's
                # total_request_timeout_s, CognitiveCourt's COURT_DEADLINE_S,
                # TruthFabric's *_TIMEOUT_S), turning a clean, expected
                # timeout into an unhandled exception under real load. Real
                # bug found via Phase 11.2 live-suite root-cause evidence,
                # not environmental flakiness.
                if request.request_id in self._cancelled_requests:
                    raise RequestCancelledError()
                raise
        raise GenerationTimeoutError(internal_detail=f"timed out after {retries} retries: {last_error}")

    async def stream(self, request: InferenceRequest) -> AsyncIterator[InferenceChunk]:
        """
        Real per-token streaming (unlike the frontier runtime's honestly-
        labeled fake streaming). Cancellation is cooperative: cancel()
        marks the request_id; this loop checks it between chunks and stops
        cleanly, closing the underlying HTTP stream rather than leaving it
        open after the caller has stopped consuming.
        """
        payload = self._payload(request, stream=True)
        timeout = request.timeout_s or self.timeout_s
        sequence = 0
        yielded_any = False

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", f"{self.host}/api/chat", json=payload, timeout=timeout) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if request.request_id in self._cancelled_requests:
                            self._cancelled_requests.discard(request.request_id)
                            yield InferenceChunk(
                                request_id=request.request_id, sequence=sequence, delta="",
                                finish_reason="cancelled", trace_id=request.trace_id,
                            )
                            return
                        if not line:
                            continue
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        done = chunk.get("done", False)
                        if content:
                            yielded_any = True
                            yield InferenceChunk(
                                request_id=request.request_id, sequence=sequence, delta=content,
                                finish_reason=None, trace_id=request.trace_id,
                            )
                            sequence += 1
                        if done:
                            yield InferenceChunk(
                                request_id=request.request_id, sequence=sequence, delta="",
                                finish_reason="stop",
                                prompt_tokens=chunk.get("prompt_eval_count"),
                                completion_tokens=chunk.get("eval_count"),
                                trace_id=request.trace_id,
                            )
                            return
        except httpx.ConnectError as e:
            raise DeploymentUnavailableError(self.deployment_id, internal_detail=str(e))
        except httpx.TimeoutException as e:
            if yielded_any:
                raise GenerationTimeoutError(internal_detail=f"timed out mid-stream after partial output: {e}")
            raise GenerationTimeoutError(internal_detail=f"timed out before any output: {e}")

    async def load_model(self, model_ref: str) -> bool:
        """Forces Ollama to load the model into memory via a minimal, deterministic generate call."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self.host}/api/generate",
                    json={"model": model_ref, "prompt": "", "stream": False},
                    timeout=self.timeout_s,
                )
                r.raise_for_status()
                return True
        except Exception:
            return False

    async def unload_model(self, model_ref: str) -> bool:
        """keep_alive=0 tells Ollama to evict the model from memory immediately after this no-op call."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self.host}/api/generate",
                    json={"model": model_ref, "prompt": "", "stream": False, "keep_alive": 0},
                    timeout=self.timeout_s,
                )
                r.raise_for_status()
                return True
        except Exception:
            return False

    async def cancel(self, request_id: str) -> bool:
        """
        Cooperative cancellation: marks the request so the next chunk-check
        in stream() (or the next retry-loop iteration in generate()) stops
        cleanly. This does NOT abort Ollama's own in-progress computation
        server-side (Ollama's API has no cancel endpoint) -- it stops OUR
        side from continuing to read/relay it, which is what the client
        actually experiences as cancellation, and is an honest limitation
        matching capabilities().cancellation's real scope.
        """
        self._cancelled_requests.add(request_id)
        return True
