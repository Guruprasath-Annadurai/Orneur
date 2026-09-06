"""
Typed inference request/response contracts -- the normalized shape every
runtime adapter (Ollama, frontier APIs, future vLLM/SGLang/etc.) produces
and consumes, so cognitive/application code never has to know which
backend actually served a request.

Deliberately does not duplicate orca/serve/api.py's ChatRequest (that's an
HTTP-layer, session-oriented model with model_variant/session_id concerns
that belong to the API surface, not the inference layer) -- InferenceRequest
is what the Model Gateway actually receives after that layer has resolved
a session and a deployment target.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Iterable


class StreamingMode(str, Enum):
    """
    Phase 0 found real streaming (Ollama) sitting behind the same interface
    as fake, word-chunked streaming (frontier passthrough) -- callers had no
    way to tell the difference. A runtime must declare which one it is;
    the gateway/caller decides what to do with that fact, but it is never
    hidden.
    """
    NATIVE_STREAMING = "NATIVE_STREAMING"
    BUFFERED_ONLY = "BUFFERED_ONLY"


class RequestPriority(str, Enum):
    INTERACTIVE = "INTERACTIVE"
    AGENT = "AGENT"
    BACKGROUND = "BACKGROUND"
    EVALUATION = "EVALUATION"
    TRAINING_SUPPORT = "TRAINING_SUPPORT"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class InferenceRequest:
    request_id: str
    model_id: str                      # canonical family/alias, e.g. "orneur-novus" or "orneur-novus:candidate"
    messages: list[dict]                # [{"role": ..., "content": ...}, ...] -- integrates with the existing message-array shape used throughout orca/brain
    trace_id: str | None = None
    model_version: str | None = None    # explicit version/checkpoint pin; None = resolve via policy (see gateway routing)
    system: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.7
    top_p: float = 0.9
    stop: list[str] = field(default_factory=list)
    seed: int | None = None
    stream: bool = False
    timeout_s: float | None = None       # total_request_timeout override; None = gateway default
    priority: RequestPriority = RequestPriority.INTERACTIVE
    tenant_id: str | None = None
    session_id: str | None = None
    capability_context: dict = field(default_factory=dict)  # e.g. {"requires_tool_calling": True}
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)


@dataclass
class InferenceResponse:
    request_id: str
    model_id: str
    resolved_version: str
    runtime: str                 # "ollama" | "openai" | "anthropic" | future runtimes
    deployment_id: str
    output: str
    finish_reason: str            # "stop" | "length" | "cancelled" | "error"
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    queue_latency_ms: float
    model_latency_ms: float
    retries: int = 0
    warnings: list[str] = field(default_factory=list)
    trace_id: str | None = None
    data_left_infrastructure: bool = False
    cost_usd: float = 0.0


@dataclass
class InferenceChunk:
    request_id: str
    sequence: int
    delta: str
    finish_reason: str | None = None    # set on the final chunk only
    prompt_tokens: int | None = None    # populated when the runtime reports it (often only on the final chunk)
    completion_tokens: int | None = None
    trace_id: str | None = None


InferenceStream = AsyncIterator[InferenceChunk]
