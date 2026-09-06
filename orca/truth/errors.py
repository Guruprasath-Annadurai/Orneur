"""Truth Fabric error taxonomy -- normalized separately from
orca/gateway/errors.py's InferenceError and orca/cognitive/errors.py's
CognitiveError, same pattern."""
from __future__ import annotations

from enum import Enum


class TruthErrorCode(str, Enum):
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    SEARCH_FAILED = "SEARCH_FAILED"
    FETCH_REFUSED = "FETCH_REFUSED"          # e.g. SSRF-risk URL, oversized document
    BUDGET_EXHAUSTED = "TRUTH_BUDGET_EXHAUSTED"
    TIMEOUT = "TRUTH_TIMEOUT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class TruthError(Exception):
    def __init__(self, code: TruthErrorCode, message: str, internal_detail: str | None = None):
        self.code = code
        self.message = message
        self.internal_detail = internal_detail
        super().__init__(f"[{code.value}] {message}")


class RetrievalFailedError(TruthError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(TruthErrorCode.RETRIEVAL_FAILED, "Retrieval failed.", internal_detail)


class SearchFailedError(TruthError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(TruthErrorCode.SEARCH_FAILED, "Search failed.", internal_detail)


class FetchRefusedError(TruthError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(TruthErrorCode.FETCH_REFUSED, "Fetch was refused.", internal_detail)


class TruthBudgetExhaustedError(TruthError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(TruthErrorCode.BUDGET_EXHAUSTED, "Truth Fabric budget exhausted.", internal_detail)


class TruthTimeoutError(TruthError):
    def __init__(self, internal_detail: str | None = None):
        super().__init__(TruthErrorCode.TIMEOUT, "Truth Fabric operation timed out.", internal_detail)
