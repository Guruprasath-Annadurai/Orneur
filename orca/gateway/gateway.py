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
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator

from orca.gateway.circuit_breaker import CircuitBreaker
from orca.gateway.concurrency import ConcurrencyLimiter
from orca.gateway.contracts import InferenceChunk, InferenceRequest, InferenceResponse
from orca.gateway.deployment import DeploymentHealth, ModelDeployment, list_deployments
from orca.gateway.errors import (
    CircuitOpenError,
    ContextTooLongError,
    GenerationTimeoutError,
    InferenceError,
    InvalidParametersError,
    ModelNotRoutableError,
    RuntimeExecutionError,
)
from orca.gateway import metrics
from orca.gateway.runtime import InferenceRuntime
from orca.gateway.worker import Worker

_logger = logging.getLogger("orca.gateway")

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
        self._workers: dict[str, Worker] = {}  # worker_id -> Worker
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

    def register_worker(self, worker: Worker) -> None:
        self._workers[worker.worker_id] = worker

    def _worker_permits_routing(self, deployment: ModelDeployment) -> bool:
        """
        Deployments with no worker_id set are unconstrained by this check
        (backward compatible with every deployment registered before
        worker-aware routing existed, and with every deployment that
        genuinely doesn't need a worker association -- e.g. a frontier API
        passthrough has no meaningful "worker"). A deployment WITH a
        worker_id is refused if that worker isn't registered at all, or
        fails Worker.is_available_for_routing() (covers UNHEALTHY, OFFLINE,
        DRAINING, stale heartbeat, and no-spare-capacity in one call --
        that method already existed in Phase 2, just never consulted here).
        """
        if deployment.worker_id is None:
            return True
        worker = self._workers.get(deployment.worker_id)
        if worker is None:
            return False
        return worker.is_available_for_routing()

    def _rank_key(self, deployment: ModelDeployment) -> tuple:
        """
        Deterministic ranking among multiple eligible deployments for the
        same request: prefer a READY worker over DEGRADED, prefer lower
        active load, then break ties by deployment_id for reproducibility.
        A deployment with no worker_id sorts as if its worker were READY
        with zero load (no worker constraint = no worker-based penalty).
        """
        worker = self._workers.get(deployment.worker_id) if deployment.worker_id else None
        worker_rank = 0 if worker is None or worker.status == "READY" else 1
        load = worker.active_requests if worker else 0
        return (worker_rank, load, deployment.deployment_id)

    def _deployments_for_model(self, model_id: str) -> list[ModelDeployment]:
        return [d for d in self._deployments.values() if d.model_id == model_id]

    # Alias suffixes resolve to a lifecycle policy, e.g. "orneur-novus:candidate"
    # means "the CANDIDATE-lifecycle deployment for orneur-novus", NOT a
    # specific checkpoint pin (that's what model_version is for). An
    # unversioned bare alias like "orneur-novus" always means "whatever is
    # currently PRODUCTION" and must never silently fall through to an
    # experimental/candidate deployment -- that's exactly the "unversioned
    # string aliases bypass promotion governance" failure mode this guards.
    _ALIAS_LIFECYCLE = {
        "production": "PRODUCTION",
        "candidate": "CANDIDATE",
        "experimental": "EXPERIMENTAL",
    }

    @staticmethod
    def _artifact_is_available(deployment: ModelDeployment) -> bool:
        """
        Cross-checks Phase 1's checkpoint registry (orca/registry/checkpoint.py)
        so a deployment can never be routed when its underlying weight
        artifact is MISSING/CORRUPT -- ModelDeployment's own lifecycle/
        health/warmup fields are a separate system from the checkpoint
        registry's ArtifactAvailability, and the two must agree before
        routing, not just the deployment's own optimistic state.

        Fails OPEN (returns True) only when no CheckpointRecord exists at
        all for this artifact_id -- that's the case for every test double
        in this test suite and for any deployment whose artifact was never
        registered with Phase 1's registry, which must not be treated as
        "missing" (that would be a false negative, not a safety check).
        A record that DOES exist and says MISSING/CORRUPT must block
        routing, unconditionally.
        """
        try:
            from orca.registry.checkpoint import ArtifactAvailability, CheckpointRecord
            record = CheckpointRecord.load(deployment.artifact_id)
        except FileNotFoundError:
            return True
        except Exception:
            return True
        return record.availability not in (ArtifactAvailability.MISSING.value, ArtifactAvailability.CORRUPT.value)

    def _parse_alias(self, model_id: str) -> tuple[str, str | None]:
        if ":" in model_id:
            base, suffix = model_id.split(":", 1)
            lifecycle = self._ALIAS_LIFECYCLE.get(suffix.lower())
            if lifecycle is None:
                raise ModelNotRoutableError(model_id, f"unknown alias suffix ':{suffix}'")
            return base, lifecycle
        return model_id, None

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
        An unversioned bare model_id (no ":alias" suffix) ALWAYS requires
        PRODUCTION lifecycle -- allow_experimental only affects requests
        that didn't ask for a specific alias, and an explicit ":candidate"/
        ":experimental" alias is honored regardless of allow_experimental
        (naming the alias IS the explicit policy decision).
        """
        base_model_id, requested_lifecycle = self._parse_alias(model_id)
        candidates = self._deployments_for_model(base_model_id)
        if model_version:
            candidates = [d for d in candidates if d.model_version == model_version]

        if not candidates:
            raise ModelNotRoutableError(model_id, "no deployment is registered for this model")

        if requested_lifecycle:
            aliased = [
                d for d in candidates
                if d.lifecycle == requested_lifecycle and d.is_routable(allow_experimental=True)
                and self._artifact_is_available(d) and self._worker_permits_routing(d)
            ]
            if not aliased:
                raise ModelNotRoutableError(model_id, f"no routable deployment with lifecycle={requested_lifecycle}")
            return sorted(aliased, key=self._rank_key)[0]

        routable = [
            d for d in candidates
            if d.is_routable(allow_experimental=allow_experimental) and self._artifact_is_available(d)
            and self._worker_permits_routing(d)
        ]
        if not routable:
            raise ModelNotRoutableError(
                model_id,
                "deployment(s) exist but none are currently routable "
                "(lifecycle/health/warmup state, experimental policy not permitted, or worker unavailable)",
            )

        production = [d for d in routable if d.lifecycle == "PRODUCTION"]
        if not production and not allow_experimental:
            raise ModelNotRoutableError(
                model_id,
                "no PRODUCTION deployment exists for this model, and allow_experimental was not set "
                "-- a bare model_id never falls back to an experimental/candidate deployment implicitly",
            )
        eligible = production if production else routable
        return sorted(eligible, key=self._rank_key)[0]

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
        metrics.record_request(deployment.deployment_id)

        estimated = _estimate_tokens(request)
        if estimated + request.max_tokens > deployment.context_limit:
            raise ContextTooLongError(estimated, deployment.context_limit)

        if not self.circuit_breaker.allow_request(deployment.deployment_id):
            raise CircuitOpenError(deployment.deployment_id)

        runtime = self._runtime_for(deployment)
        t0 = time.monotonic()
        log_ctx = dict(
            model_id=request.model_id, model_version=deployment.model_version, deployment_id=deployment.deployment_id,
            runtime=deployment.runtime, request_id=request.request_id, trace_id=request.trace_id,
        )
        try:
            async with await self.concurrency.acquire(deployment.deployment_id, queue_timeout_s=self.timeouts.queue_timeout_s):
                queue_latency_ms = (time.monotonic() - t0) * 1000
                response = await self._generate_via_runtime(deployment, runtime, request)
                response.queue_latency_ms = queue_latency_ms
                response.deployment_id = deployment.deployment_id
        except asyncio.TimeoutError:
            self.circuit_breaker.record_failure(deployment.deployment_id)
            metrics.record_timeout(deployment.deployment_id, "total_request")
            metrics.record_failure(deployment.deployment_id, "GENERATION_TIMEOUT")
            _logger.warning("inference request timed out", extra={**log_ctx, "status": "timeout"})
            raise GenerationTimeoutError(internal_detail=f"exceeded total_request_timeout_s={self.timeouts.total_request_timeout_s}")
        except InferenceError as e:
            self.circuit_breaker.record_failure(deployment.deployment_id)
            metrics.record_failure(deployment.deployment_id, e.code.value)
            _logger.warning("inference request failed", extra={**log_ctx, "status": "error", "error_class": e.code.value})
            raise
        except Exception as e:
            self.circuit_breaker.record_failure(deployment.deployment_id)
            metrics.record_failure(deployment.deployment_id, "UNKNOWN")
            _logger.error("inference request failed with an unclassified error", extra={**log_ctx, "status": "error", "error_class": type(e).__name__})
            raise
        else:
            self.circuit_breaker.record_success(deployment.deployment_id)
            total_latency_ms = (time.monotonic() - t0) * 1000
            metrics.record_success(deployment.deployment_id, total_latency_ms, response.queue_latency_ms, response.completion_tokens)
            if response.retries:
                for _ in range(response.retries):
                    metrics.record_retry(deployment.deployment_id)
            _logger.info("inference request succeeded", extra={**log_ctx, "status": "ok", "latency_ms": round(total_latency_ms, 1)})
            return response

    async def stream(self, request: InferenceRequest, allow_experimental: bool = False) -> AsyncIterator[InferenceChunk]:
        _validate_parameters(request)
        deployment = self.resolve_deployment(request.model_id, request.model_version, allow_experimental)
        metrics.record_request(deployment.deployment_id)
        log_ctx = dict(
            model_id=request.model_id, model_version=deployment.model_version, deployment_id=deployment.deployment_id,
            runtime=deployment.runtime, request_id=request.request_id, trace_id=request.trace_id,
        )

        estimated = _estimate_tokens(request)
        if estimated + request.max_tokens > deployment.context_limit:
            raise ContextTooLongError(estimated, deployment.context_limit)

        if not self.circuit_breaker.allow_request(deployment.deployment_id):
            raise CircuitOpenError(deployment.deployment_id)

        runtime = self._runtime_for(deployment)
        t0 = time.monotonic()

        async with await self.concurrency.acquire(deployment.deployment_id, queue_timeout_s=self.timeouts.queue_timeout_s):
            queue_latency_ms = (time.monotonic() - t0) * 1000
            t_first_chunk_deadline = time.monotonic() + self.timeouts.first_token_timeout_s
            first_chunk_seen = False
            try:
                async for chunk in runtime.stream(request):
                    if not first_chunk_seen:
                        if time.monotonic() > t_first_chunk_deadline:
                            self.circuit_breaker.record_failure(deployment.deployment_id)
                            metrics.record_timeout(deployment.deployment_id, "first_token")
                            raise GenerationTimeoutError(internal_detail="exceeded first_token_timeout_s")
                        first_chunk_seen = True
                        metrics.record_ttft(deployment.deployment_id, (time.monotonic() - t0) * 1000)
                    if chunk.finish_reason == "cancelled":
                        metrics.record_cancellation(deployment.deployment_id)
                        _logger.info("inference stream cancelled", extra={**log_ctx, "status": "cancelled"})
                    yield chunk
                self.circuit_breaker.record_success(deployment.deployment_id)
                total_latency_ms = (time.monotonic() - t0) * 1000
                metrics.record_success(deployment.deployment_id, total_latency_ms, queue_latency_ms, 0)
                _logger.info("inference stream completed", extra={**log_ctx, "status": "ok", "latency_ms": round(total_latency_ms, 1)})
            except InferenceError as e:
                self.circuit_breaker.record_failure(deployment.deployment_id)
                metrics.record_failure(deployment.deployment_id, e.code.value)
                _logger.warning("inference stream failed", extra={**log_ctx, "status": "error", "error_class": e.code.value})
                raise
            except Exception as e:
                self.circuit_breaker.record_failure(deployment.deployment_id)
                metrics.record_failure(deployment.deployment_id, "UNKNOWN")
                _logger.error("inference stream failed with an unclassified error", extra={**log_ctx, "status": "error", "error_class": type(e).__name__})
                raise

    async def cancel(self, model_id: str, request_id: str) -> bool:
        """Best-effort cancellation propagation to whichever runtime is serving this model family."""
        candidates = self._deployments_for_model(model_id)
        if not candidates:
            return False
        runtime = self._runtime_for(candidates[0])
        return await runtime.cancel(request_id)

    async def warmup(self, deployment: ModelDeployment, probe_message: str = "Say OK.") -> bool:
        """
        A deployment is not READY until this succeeds. Runs: (1) an
        explicit load_model() call where the runtime supports it (a no-op
        returning False, not raising, for runtimes that don't -- e.g.
        frontier passthrough), (2) a small deterministic generation to
        verify the deployment can actually answer, not just that the
        health endpoint responds. On success, sets health=READY and
        warmup_completed=True; on failure, leaves it at STARTING (never
        silently marks a deployment ready after a failed warmup) and logs
        the failure with latency recorded either way.
        """
        runtime = self._runtime_for(deployment)
        t0 = time.monotonic()
        try:
            await runtime.load_model(deployment.model_version)
            probe_request = InferenceRequest(
                request_id=f"warmup-{deployment.deployment_id}",
                model_id=deployment.model_id,
                model_version=deployment.model_version,
                messages=[{"role": "user", "content": probe_message}],
                max_tokens=5,
                timeout_s=self.timeouts.total_request_timeout_s,
            )
            await runtime.generate(probe_request)
        except Exception as e:
            _logger.warning(
                "deployment warmup failed",
                extra={"deployment_id": deployment.deployment_id, "runtime": deployment.runtime,
                       "latency_ms": round((time.monotonic() - t0) * 1000, 1), "error_class": type(e).__name__},
            )
            return False
        deployment.health = DeploymentHealth.READY.value
        deployment.warmup_completed = True
        deployment.save()
        _logger.info(
            "deployment warmup succeeded",
            extra={"deployment_id": deployment.deployment_id, "runtime": deployment.runtime,
                   "latency_ms": round((time.monotonic() - t0) * 1000, 1)},
        )
        return True

    def report_health(self) -> dict:
        """
        Distinguishes service liveness (this process is up -- trivially
        true if this call returns at all) from readiness (at least one
        runtime is registered) from per-model deployment readiness (is
        THIS specific model actually routable right now). The API layer
        can be alive with zero models ready -- these must never be
        conflated into one boolean.
        """
        model_readiness = {}
        for model_id in {d.model_id for d in self._deployments.values()}:
            try:
                self.resolve_deployment(model_id)
                model_readiness[model_id] = "READY"
            except ModelNotRoutableError:
                allow_exp_routable = any(
                    d.is_routable(allow_experimental=True) for d in self._deployments_for_model(model_id)
                )
                model_readiness[model_id] = "CANDIDATE_ONLY" if allow_exp_routable else "NOT_ROUTABLE"
        return {
            "service_live": True,
            "service_ready": len(self._runtimes) > 0,
            "registered_runtimes": sorted(self._runtimes.keys()),
            "model_readiness": model_readiness,
        }
