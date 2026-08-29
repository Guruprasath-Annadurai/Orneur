"""
Structured inference errors -- replaces the current serving path's mix of
raw exception messages and ad-hoc {"type": "error", "text": str(e)} SSE
payloads (see docs/orneur/phase-2/CURRENT_INFERENCE_PATH.md's "Error
handling" section) with a real, closed error-code taxonomy a client can
branch on.
"""
from __future__ import annotations

from enum import Enum


class InferenceErrorCode(str, Enum):
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_NOT_ROUTABLE = "MODEL_NOT_ROUTABLE"
    DEPLOYMENT_UNAVAILABLE = "DEPLOYMENT_UNAVAILABLE"
    QUEUE_FULL = "QUEUE_FULL"
    QUEUE_TIMEOUT = "QUEUE_TIMEOUT"
    GENERATION_TIMEOUT = "GENERATION_TIMEOUT"
    CONTEXT_TOO_LONG = "CONTEXT_TOO_LONG"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    WORKER_UNHEALTHY = "WORKER_UNHEALTHY"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    INVALID_PARAMETERS = "INVALID_PARAMETERS"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"


class InferenceError(Exception):
    """
    All Model Gateway / runtime adapter errors raise this (or a subclass),
    never a bare RuntimeError/ValueError, so a caller always gets a
    structured .code plus a message safe to show a client -- internal
    diagnostic detail goes in .internal_detail, which callers must NOT
    surface to end users (logs/traces only), matching the "never leak raw
    backend internals or secrets to clients" requirement.
    """
    def __init__(self, code: InferenceErrorCode, message: str, internal_detail: str = ""):
        self.code = code
        self.message = message
        self.internal_detail = internal_detail
        super().__init__(f"{code.value}: {message}")

    def to_client_payload(self) -> dict:
        """Safe to serialize directly into an API response -- no internal_detail."""
        return {"error_code": self.code.value, "message": self.message}


class ModelNotFoundError(InferenceError):
    def __init__(self, model_id: str, internal_detail: str = ""):
        super().__init__(InferenceErrorCode.MODEL_NOT_FOUND, f"Model '{model_id}' is not known.", internal_detail)


class ModelNotRoutableError(InferenceError):
    def __init__(self, model_id: str, reason: str, internal_detail: str = ""):
        super().__init__(InferenceErrorCode.MODEL_NOT_ROUTABLE, f"Model '{model_id}' cannot be routed: {reason}", internal_detail)


class DeploymentUnavailableError(InferenceError):
    def __init__(self, deployment_id: str, internal_detail: str = ""):
        super().__init__(InferenceErrorCode.DEPLOYMENT_UNAVAILABLE, f"Deployment '{deployment_id}' is unavailable.", internal_detail)


class QueueFullError(InferenceError):
    def __init__(self, internal_detail: str = ""):
        super().__init__(InferenceErrorCode.QUEUE_FULL, "The system is at capacity; please retry shortly.", internal_detail)


class QueueTimeoutError(InferenceError):
    def __init__(self, internal_detail: str = ""):
        super().__init__(InferenceErrorCode.QUEUE_TIMEOUT, "Request waited too long in queue.", internal_detail)


class GenerationTimeoutError(InferenceError):
    def __init__(self, internal_detail: str = ""):
        super().__init__(InferenceErrorCode.GENERATION_TIMEOUT, "Generation took too long.", internal_detail)


class ContextTooLongError(InferenceError):
    def __init__(self, estimated_tokens: int, limit: int, internal_detail: str = ""):
        super().__init__(
            InferenceErrorCode.CONTEXT_TOO_LONG,
            f"Request ({estimated_tokens} estimated tokens) exceeds this model's context limit ({limit}).",
            internal_detail,
        )


class RuntimeExecutionError(InferenceError):
    def __init__(self, message: str = "The model runtime encountered an error.", internal_detail: str = ""):
        super().__init__(InferenceErrorCode.RUNTIME_ERROR, message, internal_detail)


class WorkerUnhealthyError(InferenceError):
    def __init__(self, worker_id: str, internal_detail: str = ""):
        super().__init__(InferenceErrorCode.WORKER_UNHEALTHY, f"No healthy worker available for this request.", internal_detail)


class RequestCancelledError(InferenceError):
    def __init__(self, internal_detail: str = ""):
        super().__init__(InferenceErrorCode.REQUEST_CANCELLED, "The request was cancelled.", internal_detail)


class UnsupportedCapabilityError(InferenceError):
    def __init__(self, capability: str, runtime: str, internal_detail: str = ""):
        super().__init__(
            InferenceErrorCode.UNSUPPORTED_CAPABILITY,
            f"The '{runtime}' runtime does not support '{capability}'.",
            internal_detail,
        )


class InvalidParametersError(InferenceError):
    def __init__(self, message: str, internal_detail: str = ""):
        super().__init__(InferenceErrorCode.INVALID_PARAMETERS, message, internal_detail)


class CircuitOpenError(InferenceError):
    def __init__(self, deployment_id: str, internal_detail: str = ""):
        super().__init__(
            InferenceErrorCode.CIRCUIT_OPEN,
            "This model is temporarily unavailable due to repeated failures; please retry shortly.",
            internal_detail,
        )
