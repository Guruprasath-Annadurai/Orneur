"""
The Model Gateway -- the single point cognitive/application code calls for
inference, ties together everything else in orca/gateway/: deployment
lookup + lifecycle/health eligibility, per-deployment circuit breaking,
per-deployment concurrency/backpressure, timeout categories, request/
parameter validation, and structured errors. Runtime selection (Ollama vs.
frontier vs. future runtimes) happens here, keyed off ModelDeployment.runtime
-- cognitive code never imports or names a runtime directly.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator

from orca.gateway.circuit_breaker import CircuitBreaker
from orca.gateway.concurrency import ConcurrencyLimiter
from orca.gateway.contracts import InferenceChunk, InferenceRequest, InferenceResponse
from orca.gateway.deployment import ModelDeployment, list_deployments
from orca.gateway.errors import (
    CircuitOpenError,
    ContextTooLongError,
    GenerationTimeoutError,
    InvalidParametersError,
    ModelNotRoutableError,
    RuntimeExecutionError,
)
from orca.gateway.runtime import InferenceRuntime

# Rough estimate only -- no tokenizer dependency at this layer. Deliberately
# conservative (over-estimates) so a request that's actually borderline
# fails safely here rather than silently overflowing the runtime's own
# context window. A future phase can wire a real per-model tokenizer count.
_CHARS_PER_TOKEN_ESTIMATE = 3.2


@dataclass
class TimeoutPolicy:
    queue_timeout_s: float = 30.0
    first_token_timeout_s: float = 30.0
    total_request_timeout_s: float = 180.0


def _estimate_tokens(request: InferenceRequest) -> int:
    total_chars = len(request.system or "")
    for m in request.messages:
        total_chars += len(m.get("content", ""))
    return int(total_chars / _CHARS_PER_TOKEN_ESTIMATE)


def _validate_parameters(request: InferenceRequest) -> None:
    if not (0.0 <= request.temperature <= 2.0):
        raise InvalidParametersError(f"temperature {request.temperature} must be in [0.0, 2.0]")
    if not (0.0 <= request.top_p <= 1.0):
        raise InvalidParametersError(f"top_p {request.top_p} must be in [0.0, 1.0]")
    if request.max_tokens <= 0:
        raise InvalidParametersError(f"max_tokens {request.max_tokens} must be positive")


class ModelGateway:
    def __init__(
        self,
        circuit_breaker: CircuitBreaker | None = None,
        concurrency: ConcurrencyLimiter | None = None,
        timeout_policy: TimeoutPolicy | None = None,
    ):
        self._runtimes: dict[str, InferenceRuntime] = {}
        self._deployments: dict[str, ModelDeployment] = {}  # deployment_id -> deployment
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.concurrency = concurrency or ConcurrencyLimiter()
        self.timeouts = timeout_policy or TimeoutPolicy()

    def register_runtime(self, name: str, runtime: InferenceRuntime) -> None:
        self._runtimes[name] = runtime

    def register_deployment(self, deployment: ModelDeployment) -> None:
        self._deployments[deployment.deployment_id] = deployment
        self.concurrency.configure(
            deployment.deployment_id, max_concurrency=deployment.max_concurrency, max_queue_depth=deployment.max_concurrency * 4,
        )

    def _deployments_for_model(self, model_id: str) -> list[ModelDeployment]:
        return [d for d in self._deployments.values() if d.model_id == model_id]

    def resolve_deployment(self, model_id: str, model_version: str | None = None, allow_experimental: bool = False) -> ModelDeployment:
        """
        The routing-safety gate. Raises ModelNotRoutableError -- never
        silently substitutes a different family's model -- when:
          - no deployment exists at all for this model_id (Aeternum today:
            it has a family definition in orca/registry/model_spec.py but
            zero registered deployments, since no checkpoint exists to
            deploy)
          - deployments exist but none pass ModelDeployment.is_routable()
            under the caller's policy
        """
        candidates = self._deployments_for_model(model_id)
        if model_version:
            candidates = [d for d in candidates if d.model_version == model_version]

        if not candidates:
            raise ModelNotRoutableError(model_id, "no deployment is registered for this model")

        routable = [d for d in candidates if d.is_routable(allow_experimental=allow_experimental)]
        if not routable:
            raise ModelNotRoutableError(
                model_id,
                "deployment(s) exist but none are currently routable "
                "(lifecycle/health/warmup state, or experimental policy not permitted)",
            )

        production = [d for d in routable if d.lifecycle == "PRODUCTION"]
        return production[0] if production else routable[0]

    def _runtime_for(self, deployment: ModelDeployment) -> InferenceRuntime:
        runtime = self._runtimes.get(deployment.runtime)
        if runtime is None:
            raise RuntimeExecutionError(f"No runtime registered for '{deployment.runtime}'")
        return runtime

    async def _generate_via_runtime(self, deployment: ModelDeployment, runtime: InferenceRuntime, request: InferenceRequest) -> InferenceResponse:
        return await asyncio.wait_for(runtime.generate(request), timeout=self.timeouts.total_request_timeout_s)

    async def generate(self, request: InferenceRequest, allow_experimental: bool = False) -> InferenceResponse:
        _validate_parameters(request)
        deployment = self.resolve_deployment(request.model_id, request.model_version, allow_experimental)

        estimated = _estimate_tokens(request)
        if estimated + request.max_tokens > deployment.context_limit:
            raise ContextTooLongError(estimated, deployment.context_limit)

        if not self.circuit_breaker.allow_request(deployment.deployment_id):
            raise CircuitOpenError(deployment.deployment_id)

        runtime = self._runtime_for(deployment)
        t0 = time.monotonic()
        try:
            async with await self.concurrency.acquire(deployment.deployment_id, queue_timeout_s=self.timeouts.queue_timeout_s):
                queue_latency_ms = (time.monotonic() - t0) * 1000
                response = await self._generate_via_runtime(deployment, runtime, request)
                response.queue_latency_ms = queue_latency_ms
                response.deployment_id = deployment.deployment_id
        except asyncio.TimeoutError:
            self.circuit_breaker.record_failure(deployment.deployment_id)
            raise GenerationTimeoutError(internal_detail=f"exceeded total_request_timeout_s={self.timeouts.total_request_timeout_s}")
        except Exception:
            self.circuit_breaker.record_failure(deployment.deployment_id)
            raise
        else:
            self.circuit_breaker.record_success(deployment.deployment_id)
            return response

    async def stream(self, request: InferenceRequest, allow_experimental: bool = False) -> AsyncIterator[InferenceChunk]:
        _validate_parameters(request)
        deployment = self.resolve_deployment(request.model_id, request.model_version, allow_experimental)

        estimated = _estimate_tokens(request)
        if estimated + request.max_tokens > deployment.context_limit:
            raise ContextTooLongError(estimated, deployment.context_limit)

        if not self.circuit_breaker.allow_request(deployment.deployment_id):
            raise CircuitOpenError(deployment.deployment_id)

        runtime = self._runtime_for(deployment)
        t_acquire_start = time.monotonic()

        async with await self.concurrency.acquire(deployment.deployment_id, queue_timeout_s=self.timeouts.queue_timeout_s):
            t_first_chunk_deadline = time.monotonic() + self.timeouts.first_token_timeout_s
            first_chunk_seen = False
            try:
                async for chunk in runtime.stream(request):
                    if not first_chunk_seen:
                        if time.monotonic() > t_first_chunk_deadline:
                            self.circuit_breaker.record_failure(deployment.deployment_id)
                            raise GenerationTimeoutError(internal_detail="exceeded first_token_timeout_s")
                        first_chunk_seen = True
                    yield chunk
                self.circuit_breaker.record_success(deployment.deployment_id)
            except Exception:
                self.circuit_breaker.record_failure(deployment.deployment_id)
                raise

    async def cancel(self, model_id: str, request_id: str) -> bool:
        """Best-effort cancellation propagation to whichever runtime is serving this model family."""
        candidates = self._deployments_for_model(model_id)
        if not candidates:
            return False
        runtime = self._runtime_for(candidates[0])
        return await runtime.cancel(request_id)
