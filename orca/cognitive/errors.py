"""
Cognitive-layer errors -- normalized separately from orca/gateway/errors.py's
InferenceError taxonomy (Phase 3 spec §32). A Gateway error that surfaces
during Kernel execution is wrapped, never re-raised raw -- callers of the
Kernel should never need to know about InferenceErrorCode.
"""
from __future__ import annotations

from enum import Enum


class CognitiveErrorCode(str, Enum):
    INTENT_COMPILATION_FAILED = "INTENT_COMPILATION_FAILED"
    PLAN_INVALID = "PLAN_INVALID"
    OPERATION_UNAVAILABLE = "OPERATION_UNAVAILABLE"
    COGNITIVE_BUDGET_EXHAUSTED = "COGNITIVE_BUDGET_EXHAUSTED"
    MODEL_POLICY_UNSATISFIED = "MODEL_POLICY_UNSATISFIED"
    CONTEXT_ASSEMBLY_FAILED = "CONTEXT_ASSEMBLY_FAILED"
    COGNITIVE_EXECUTION_FAILED = "COGNITIVE_EXECUTION_FAILED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"


class CognitiveError(Exception):
    def __init__(self, code: CognitiveErrorCode, message: str, internal_detail: str | None = None):
        self.code = code
        self.message = message
        self.internal_detail = internal_detail
        super().__init__(f"[{code.value}] {message}")


class IntentCompilationFailedError(CognitiveError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(CognitiveErrorCode.INTENT_COMPILATION_FAILED, "Could not compile intent for this request.", internal_detail)


class PlanInvalidError(CognitiveError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(CognitiveErrorCode.PLAN_INVALID, "Cognitive plan failed validation.", internal_detail)


class OperationUnavailableError(CognitiveError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(CognitiveErrorCode.OPERATION_UNAVAILABLE, "A required operation is not available.", internal_detail)


class CognitiveBudgetExhaustedError(CognitiveError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(CognitiveErrorCode.COGNITIVE_BUDGET_EXHAUSTED, "Cognitive budget exhausted.", internal_detail)


class ModelPolicyUnsatisfiedError(CognitiveError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(CognitiveErrorCode.MODEL_POLICY_UNSATISFIED, "No deployment satisfies the requested model policy.", internal_detail)


class ContextAssemblyFailedError(CognitiveError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(CognitiveErrorCode.CONTEXT_ASSEMBLY_FAILED, "Failed to assemble cognitive context.", internal_detail)


class CognitiveExecutionFailedError(CognitiveError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(CognitiveErrorCode.COGNITIVE_EXECUTION_FAILED, "Cognitive execution failed.", internal_detail)


class InvalidStateTransitionError(CognitiveError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(CognitiveErrorCode.INVALID_STATE_TRANSITION, "Invalid cognitive state transition.", internal_detail)
