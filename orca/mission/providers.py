"""
Phase 15.6 -- provider-neutral model interface (spec section 3).

This module intentionally knows nothing about Genesis, Novus,
Aeternum, or any specific vendor. It defines the shape every future
model backend must fill (`ModelProvider`), plus a deterministic
`MockProvider` used by this phase's own tests so Phase 15.6 never
requires a paid/live provider to pass.

Explicitly NOT done here, per the owner's spec (do not misrepresent
Phase 16's scope as done early):
  - no ORNEUR-native checkpoint is trained or claimed to exist;
  - no "Aeternum" or "Genesis" name is attached to any existing
    Ollama/local-model artifact;
  - no intelligence-routing ("ORNEUR Auto") logic is implemented --
    a caller picks a provider/model explicitly.

Provider secrets (API keys, tokens) are never part of `ProviderRequest`
/`ProviderResponse` -- a concrete provider implementation reads its own
credential from its own configuration/environment, never from a field
a model or mission record could see or serialize.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProviderErrorKind(str, Enum):
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    FAILURE = "FAILURE"


class ProviderError(Exception):
    def __init__(self, kind: ProviderErrorKind, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class ProviderTimeout(ProviderError):
    def __init__(self, message: str = "provider request timed out"):
        super().__init__(ProviderErrorKind.TIMEOUT, message)


class ProviderCancelled(ProviderError):
    def __init__(self, message: str = "provider request was cancelled"):
        super().__init__(ProviderErrorKind.CANCELLED, message)


class ProviderFailure(ProviderError):
    def __init__(self, message: str):
        super().__init__(ProviderErrorKind.FAILURE, message)


@dataclass(frozen=True)
class ProviderRequest:
    provider: str          # e.g. "mock", "ollama" -- never a secret
    model: str              # model identifier string, opaque to this layer
    purpose: str             # e.g. "code_generation", "review" -- for model_invocations.purpose
    prompt: str
    tool_capable: bool = False
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    usage: dict | None = None  # token counts etc, never secret material
    raw_finish_reason: str | None = None


class ModelProvider(Protocol):
    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        """Raises ProviderTimeout / ProviderCancelled / ProviderFailure
        on the corresponding real condition. Never returns a fabricated
        success on failure."""
        ...


@dataclass
class MockProvider:
    """Deterministic provider used by Phase 15.6's own tests (spec
    section 24: core tests must not require a paid provider). Never
    contacts a network; `fixed_response`/`fail_with` are set by the
    test itself."""
    fixed_response: str = "mock response"
    fail_with: ProviderError | None = None

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if self.fail_with is not None:
            raise self.fail_with
        return ProviderResponse(text=self.fixed_response, usage={"prompt_tokens": len(request.prompt.split())})


def build_model_invocation_record(
    *,
    id: str,
    mission_id: str | None,
    step_id: str | None,
    request: ProviderRequest,
    started_at: str,
    completed_at: str,
    outcome_summary: str,
    token_usage: dict | None = None,
) -> dict:
    """Shapes a row matching the existing `model_invocations` table
    (orca/mission/schema.py, Phase 15.2) -- no new schema needed for
    provider accounting. Caller persists this via ordinary INSERT;
    this function only builds the dict so the column shape lives in
    one place."""
    return {
        "id": id,
        "mission_id": mission_id,
        "step_id": step_id,
        "provider": request.provider,
        "model": request.model,
        "purpose": request.purpose,
        "started_at": started_at,
        "completed_at": completed_at,
        "token_usage": token_usage,
        "outcome_summary": outcome_summary,
    }
