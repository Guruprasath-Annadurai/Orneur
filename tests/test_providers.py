"""Phase 15.6 -- provider-neutral abstraction, MockProvider only (no
paid/live provider required to pass, per spec section 24)."""
from __future__ import annotations

import pytest

from orca.mission.providers import (
    MockProvider,
    ProviderCancelled,
    ProviderFailure,
    ProviderRequest,
    ProviderTimeout,
    build_model_invocation_record,
)


def test_mock_provider_returns_deterministic_response():
    provider = MockProvider(fixed_response="hello")
    req = ProviderRequest(provider="mock", model="mock-1", purpose="test", prompt="hi")
    resp = provider.invoke(req)
    assert resp.text == "hello"
    assert resp.usage["prompt_tokens"] == 1


def test_mock_provider_raises_timeout():
    provider = MockProvider(fail_with=ProviderTimeout())
    with pytest.raises(ProviderTimeout):
        provider.invoke(ProviderRequest(provider="mock", model="m", purpose="p", prompt="x"))


def test_mock_provider_raises_failure_not_fake_success():
    provider = MockProvider(fail_with=ProviderFailure("boom"))
    with pytest.raises(ProviderFailure):
        provider.invoke(ProviderRequest(provider="mock", model="m", purpose="p", prompt="x"))


def test_mock_provider_raises_cancelled():
    provider = MockProvider(fail_with=ProviderCancelled())
    with pytest.raises(ProviderCancelled):
        provider.invoke(ProviderRequest(provider="mock", model="m", purpose="p", prompt="x"))


def test_provider_request_never_carries_a_secret_field():
    # Structural guarantee: ProviderRequest's declared fields are all
    # non-secret by construction (provider/model/purpose/prompt/
    # tool_capable/timeout_seconds) -- there is no api_key/token field
    # to accidentally serialize.
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(ProviderRequest)}
    assert field_names == {"provider", "model", "purpose", "prompt", "tool_capable", "timeout_seconds"}


def test_build_model_invocation_record_matches_schema_shape():
    req = ProviderRequest(provider="mock", model="mock-1", purpose="code_generation", prompt="hi")
    row = build_model_invocation_record(
        id="mi_1", mission_id="m1", step_id=None, request=req,
        started_at="2026-01-01T00:00:00Z", completed_at="2026-01-01T00:00:01Z",
        outcome_summary="ok", token_usage={"prompt_tokens": 1},
    )
    assert set(row.keys()) == {
        "id", "mission_id", "step_id", "provider", "model", "purpose",
        "started_at", "completed_at", "token_usage", "outcome_summary",
    }
    assert row["provider"] == "mock"
