"""
Tests for orca/brain/backends.py — the multi-backend abstraction behind
Orca's "bring-your-own-frontier-model" product thesis (docs/STARTUP_PLAN.md).

Covers the design properties that make this Orca-specific, not a generic
SDK wrapper: every backend reports real cost/token usage, self-hosted is
always $0 and never leaves the deployment, external APIs always report
data_left_infrastructure=True, and unknown-model cost lookups fail to 0
rather than fabricating a number.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from orca.brain.backends import (
    AnthropicBackend,
    Backend,
    BackendResponse,
    OllamaBackend,
    OpenAIBackend,
    build_backend,
    _estimate_cost,
    _OPENAI_PRICING_PER_MILLION,
    _ANTHROPIC_PRICING_PER_MILLION,
)


class TestCostEstimation:
    def test_known_model_computes_real_cost(self):
        cost = _estimate_cost(_OPENAI_PRICING_PER_MILLION, "gpt-4o", 1_000_000, 1_000_000)
        assert cost == pytest.approx(2.50 + 10.00)

    def test_unknown_model_returns_zero_not_a_fabricated_number(self):
        cost = _estimate_cost(_OPENAI_PRICING_PER_MILLION, "some-future-model-not-in-table", 1000, 1000)
        assert cost == 0.0

    def test_zero_tokens_costs_zero(self):
        cost = _estimate_cost(_OPENAI_PRICING_PER_MILLION, "gpt-4o", 0, 0)
        assert cost == 0.0


class TestOllamaBackend:
    def test_generate_reports_zero_cost_and_self_hosted(self):
        backend = OllamaBackend(model="orca-nano", host="http://localhost:11434")

        fake_response = MagicMock()
        fake_response.json.return_value = {
            "response": "4", "prompt_eval_count": 10, "eval_count": 3,
        }
        fake_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=fake_response):
            result = backend.generate("What is 2+2?")

        assert isinstance(result, BackendResponse)
        assert result.backend == "ollama"
        assert result.cost_usd == 0.0
        assert result.data_left_infrastructure is False
        assert result.input_tokens == 10
        assert result.output_tokens == 3

    def test_is_available_false_on_connection_error(self):
        backend = OllamaBackend(model="orca-nano")
        with patch("httpx.get", side_effect=ConnectionError("refused")):
            assert backend.is_available() is False


class TestOpenAIBackend:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="requires an API key"):
            OpenAIBackend(model="gpt-4o", api_key="")

    def test_generate_reports_real_cost_and_external_flag(self):
        backend = OpenAIBackend(model="gpt-4o", api_key="sk-fake-key")

        fake_message = MagicMock()
        fake_message.content = "4"
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_usage = MagicMock()
        fake_usage.prompt_tokens = 100
        fake_usage.completion_tokens = 20
        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        fake_completion.usage = fake_usage

        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_completion
        backend._client = fake_client

        result = backend.generate("What is 2+2?", system="Be concise.")

        assert result.backend == "openai"
        assert result.data_left_infrastructure is True
        assert result.input_tokens == 100
        assert result.output_tokens == 20
        assert result.cost_usd == pytest.approx(
            100 / 1_000_000 * 2.50 + 20 / 1_000_000 * 10.00
        )

        call_kwargs = fake_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["messages"][0] == {"role": "system", "content": "Be concise."}
        assert call_kwargs["messages"][1] == {"role": "user", "content": "What is 2+2?"}


class TestAnthropicBackend:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="requires an API key"):
            AnthropicBackend(model="claude-opus-4-8", api_key="")

    def test_generate_reports_real_cost_and_external_flag(self):
        backend = AnthropicBackend(model="claude-opus-4-8", api_key="sk-ant-fake")

        fake_text_block = MagicMock()
        fake_text_block.type = "text"
        fake_text_block.text = "4"
        fake_usage = MagicMock()
        fake_usage.input_tokens = 50
        fake_usage.output_tokens = 10
        fake_message = MagicMock()
        fake_message.content = [fake_text_block]
        fake_message.usage = fake_usage

        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_message
        backend._client = fake_client

        result = backend.generate("What is 2+2?")

        assert result.backend == "anthropic"
        assert result.data_left_infrastructure is True
        assert result.text == "4"
        assert result.cost_usd == pytest.approx(
            50 / 1_000_000 * 5.00 + 10 / 1_000_000 * 25.00
        )

    def test_missing_sdk_raises_clear_import_error(self):
        backend = AnthropicBackend(model="claude-opus-4-8", api_key="sk-ant-fake")
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(ImportError, match="pip install -e"):
                backend._get_client()


class TestBuildBackendFactory:
    def test_builds_ollama(self):
        b = build_backend("ollama", "orca-nano")
        assert isinstance(b, OllamaBackend)

    def test_builds_openai(self):
        b = build_backend("openai", "gpt-4o", api_key="sk-fake")
        assert isinstance(b, OpenAIBackend)

    def test_builds_anthropic(self):
        b = build_backend("anthropic", "claude-opus-4-8", api_key="sk-ant-fake")
        assert isinstance(b, AnthropicBackend)

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            build_backend("some-other-provider", "some-model")
