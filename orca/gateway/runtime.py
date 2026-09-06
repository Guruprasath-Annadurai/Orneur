"""
The stable runtime contract every inference backend (Ollama, vLLM, SGLang,
TensorRT-LLM, frontier API passthrough, future runtimes) implements. Not
every runtime supports every feature -- RuntimeCapabilities represents
what's unsupported explicitly rather than faking it (e.g. frontier
passthrough must declare streaming=False, not silently pretend to stream).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from orca.gateway.contracts import InferenceChunk, InferenceRequest, InferenceResponse, StreamingMode


@dataclass(frozen=True)
class RuntimeCapabilities:
    streaming: StreamingMode
    cancellation: bool
    continuous_batching: bool
    prefix_cache: bool
    model_loading: bool
    model_unloading: bool
    quantization: bool
    logprobs: bool
    structured_output: bool
    embeddings: bool
    tool_calling: bool
    max_context: int


@runtime_checkable
class InferenceRuntime(Protocol):
    """
    Every method below may raise orca.gateway.errors.InferenceError
    subclasses. generate()/stream() are async so the gateway can enforce
    timeouts/cancellation uniformly regardless of the underlying runtime's
    own concurrency model.
    """

    name: str

    def capabilities(self) -> RuntimeCapabilities: ...

    async def health(self) -> bool: ...

    async def generate(self, request: InferenceRequest) -> InferenceResponse: ...

    def stream(self, request: InferenceRequest):
        """Returns an async iterator of InferenceChunk. Not declared `async def`
        here so implementations can be plain async generators."""
        ...

    async def load_model(self, model_ref: str) -> bool:
        """Returns False (not raises) if the runtime doesn't support explicit loading."""
        ...

    async def unload_model(self, model_ref: str) -> bool:
        """Returns False (not raises) if the runtime doesn't support explicit unloading."""
        ...

    async def cancel(self, request_id: str) -> bool:
        """Returns False (not raises) if the runtime doesn't support mid-flight cancellation."""
        ...
