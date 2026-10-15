"""Exception taxonomy. Every refusal carries a stable machine-readable `code`; none of them ever embeds private text."""
from __future__ import annotations


class EvalInfraError(Exception):
    code = "EVALINFRA_ERROR"

    def __init__(self, code: str = "", detail: str = ""):
        self.code = code or self.code
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class SchemaViolation(EvalInfraError, ValueError):
    pass


class AccessDeniedError(EvalInfraError, PermissionError):
    """Protected-evaluation access denied. `reasons` lists EVERY failed gate (the gate never short-circuits to a partial answer)."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("ACCESS_DENIED", ",".join(self.reasons))


class SplitViolation(EvalInfraError, ValueError):
    pass


class LeakageDetected(EvalInfraError, ValueError):
    pass


class ConfigMismatch(EvalInfraError, ValueError):
    pass


class BudgetExceeded(EvalInfraError, PermissionError):
    pass


class ChainCorrupt(EvalInfraError, ValueError):
    pass


class PreregViolation(EvalInfraError, ValueError):
    pass


class RatingError(EvalInfraError, ValueError):
    pass
