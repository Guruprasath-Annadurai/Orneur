"""
Model-independent enforcement boundary between ORNEUR request handling and the Model Gateway.

    after request interpretation (last user message -> contract detection)
    BEFORE expensive model execution when deterministic execution is possible (no gateway call at all)
    BEFORE final user-visible emission when validation is required (strict generated contracts are buffered and validated)

Wraps ANY object exposing `async generate(request, allow_experimental=False)` (and optionally `stream`); it never inspects a model or deployment name. Opt-in: the default Gateway is
unchanged. Strict failures raise the typed `ContractViolationError`; FREE_TEXT requests pass straight through.
"""
from __future__ import annotations

import time
from typing import Any, AsyncIterator, Callable

from orca.gateway.contracts import InferenceChunk, InferenceRequest, InferenceResponse

from .engine import ContractEngine, ModelRequest
from .types import ContractResult, ContractType

RUNTIME_NAME = "orneur-contract-engine"


def contract_text_of(request: InferenceRequest) -> str | None:
    """The text a contract is derived from: the LAST user message (string content only)."""
    for m in reversed(request.messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else None
    return None


class ContractEnforcedGateway:
    def __init__(self, inner: Any, engine: ContractEngine | None = None, *, evidence_sink: Callable[[dict], None] | None = None):
        self.inner = inner
        self.engine = engine or ContractEngine()
        self.evidence_sink = evidence_sink

    def _record(self, result: ContractResult, request: InferenceRequest) -> None:
        if self.evidence_sink is not None:
            self.evidence_sink({"request_id": request.request_id, "trace_id": request.trace_id, **result.evidence.to_dict()})

    def _response(self, request: InferenceRequest, result: ContractResult, t0: float) -> InferenceResponse:
        return InferenceResponse(request_id=request.request_id, model_id=request.model_id, resolved_version="n/a", runtime=RUNTIME_NAME, deployment_id=RUNTIME_NAME,
                                 output=result.emit(), finish_reason="stop", prompt_tokens=0, completion_tokens=0, latency_ms=(time.monotonic() - t0) * 1000, queue_latency_ms=0.0,
                                 model_latency_ms=0.0, warnings=[f"contract:{result.spec.contract_type.value}:{result.evidence.execution_strategy}:{result.evidence.contract_status}"],
                                 trace_id=request.trace_id)

    async def generate(self, request: InferenceRequest, allow_experimental: bool = False) -> InferenceResponse:
        t0 = time.monotonic()
        text = contract_text_of(request)
        spec = self.engine.route(text, request.metadata) if text is not None else None
        if spec is None or spec.contract_type is ContractType.FREE_TEXT:
            return await self.inner.generate(request, allow_experimental)              # normal conversation: untouched
        captured: dict[str, InferenceResponse] = {}

        async def model_call(req: ModelRequest) -> str:
            attempt_request = request if req.feedback is None else _with_feedback(request, req.feedback)
            resp = await self.inner.generate(attempt_request, allow_experimental)
            captured["response"] = resp
            return resp.output

        result = await self.engine.aexecute(text, model_call, metadata=request.metadata)
        self._record(result, request)
        if result.evidence.model_calls and "response" in captured and result.satisfied:
            resp = captured["response"]
            resp.output = result.emit()                                                   # exactly the validated text
            resp.warnings = list(resp.warnings) + [f"contract:{result.spec.contract_type.value}:validated:{'with_recovery' if result.evidence.repair_attempted else 'first_attempt'}"]
            return resp
        return self._response(request, result, t0)                                        # deterministic emission, or raises ContractViolationError via emit()

    async def stream(self, request: InferenceRequest, allow_experimental: bool = False) -> AsyncIterator[InferenceChunk]:
        text = contract_text_of(request)
        spec = self.engine.route(text, request.metadata) if text is not None else None
        if spec is None or spec.contract_type is ContractType.FREE_TEXT:
            async for chunk in self.inner.stream(request, allow_experimental):
                yield chunk
            return
        resp = await self.generate(request, allow_experimental)                           # strict contracts are validated as a whole BEFORE anything is emitted
        yield InferenceChunk(request_id=request.request_id, sequence=0, delta=resp.output, finish_reason="stop", prompt_tokens=resp.prompt_tokens,
                             completion_tokens=resp.completion_tokens, trace_id=request.trace_id)


def _with_feedback(request: InferenceRequest, feedback: str) -> InferenceRequest:
    import dataclasses
    msgs = list(request.messages) + [{"role": "user", "content": feedback}]
    return dataclasses.replace(request, messages=msgs)
