"""
Phase 21B.4.1 (§9) TransformersModelAdapter tests -- entirely mocked at
the transformers.AutoModelForCausalLM/AutoTokenizer boundary, no real
model weights are downloaded or loaded anywhere in this file. A test
passing here is evidence the ADAPTER'S OWN LOGIC (revision forwarding,
config validation, chat-template rendering, timing capture, failure
capture, unload behavior) is correct -- it is NEVER evidence that any
real candidate (Qwen3, Mistral-Nemo, Phi-4) was actually evaluated.

`transformers`/`torch` are deliberately NOT installed in the main
deterministic CI job (same Phase 15.15 rationale as
tests/test_train_losses.py -- see .github/workflows/test.yml): patching
`transformers.AutoTokenizer.from_pretrained` requires the real
`transformers` module to be importable even though only fakes are ever
returned, and the fake tokenizer/model helpers below build real
`torch.Tensor` objects. This file therefore runs for real in the
dedicated `torch-loss-tests` job (which DOES install both), and
produces a legitimate SKIP -- never a collection ERROR or FAILURE --
everywhere else, including this project's own dev machines that may or
may not have these optional deps installed.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

from orca.eval.adapters.transformers_adapter import (
    AdapterLoadError,
    AdapterRevisionError,
    TransformersAdapterConfig,
    TransformersModelAdapter,
)


class _FakeTokenizer:
    chat_template = "{% for m in messages %}{{ m.content }}{% endfor %}"
    _commit_hash = "fake-tokenizer-commit-sha"

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        return "RENDERED::" + "|".join(m["content"] for m in messages)

    def __call__(self, text, return_tensors="pt"):
        import torch

        return {"input_ids": torch.tensor([[1, 2, 3]])}

    def decode(self, ids, skip_special_tokens=True):
        return "fake generated response text"


class _FakeModel:
    def __init__(self):
        self.config = types.SimpleNamespace(_commit_hash="fake-model-commit-sha")
        self.device = "cpu"
        self.generate_calls = []

    def to(self, device):
        return self

    def generate(self, **kwargs):
        import torch

        self.generate_calls.append(kwargs)
        return torch.tensor([[1, 2, 3, 4, 5, 6]])  # 3 extra "generated" tokens beyond input_len=3


def _valid_config(**overrides) -> TransformersAdapterConfig:
    defaults = dict(repo_id="test-org/test-model", revision="a" * 40, device="cpu")
    defaults.update(overrides)
    return TransformersAdapterConfig(**defaults)


# ── revision enforcement (§6) ───────────────────────────────────────────


def test_config_rejects_unpinned_model_revision():
    with pytest.raises(AdapterRevisionError):
        _valid_config(revision="main")


def test_config_rejects_empty_revision():
    with pytest.raises(AdapterRevisionError):
        _valid_config(revision="")


def test_config_rejects_unpinned_tokenizer_revision_even_if_model_is_pinned():
    with pytest.raises(AdapterRevisionError):
        _valid_config(revision="a" * 40, tokenizer_revision="latest")


def test_config_defaults_tokenizer_revision_to_model_revision():
    cfg = _valid_config(revision="a" * 40)
    assert cfg.resolved_tokenizer_revision == "a" * 40


def test_config_accepts_explicit_pinned_tokenizer_revision():
    cfg = _valid_config(revision="a" * 40, tokenizer_revision="b" * 40)
    assert cfg.resolved_tokenizer_revision == "b" * 40


# ── load() forwards exact revisions to both model and tokenizer ────────


def test_load_forwards_exact_revision_to_tokenizer_and_model():
    fake_tokenizer = _FakeTokenizer()
    fake_model = _FakeModel()

    with patch("transformers.AutoTokenizer.from_pretrained", return_value=fake_tokenizer) as mock_tok, \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=fake_model) as mock_model:
        adapter = TransformersModelAdapter(_valid_config(revision="deadbeef" * 5, device="cpu"))
        adapter.load()

    mock_tok.assert_called_once()
    assert mock_tok.call_args.kwargs["revision"] == "deadbeef" * 5
    mock_model.assert_called_once()
    assert mock_model.call_args.kwargs["revision"] == "deadbeef" * 5


def test_load_captures_resolved_identities_and_timing():
    with patch("transformers.AutoTokenizer.from_pretrained", return_value=_FakeTokenizer()), \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=_FakeModel()):
        adapter = TransformersModelAdapter(_valid_config())
        adapter.load()

    assert adapter.resolved_model_revision == "fake-model-commit-sha"
    assert adapter.resolved_tokenizer_revision == "fake-tokenizer-commit-sha"
    assert adapter.load_time_ms is not None and adapter.load_time_ms >= 0
    assert adapter.chat_template_digest is not None and adapter.chat_template_digest.startswith("sha256:")
    assert "transformers" in adapter.library_versions


def test_load_failure_raises_adapter_load_error_not_a_raw_exception():
    with patch("transformers.AutoTokenizer.from_pretrained", side_effect=OSError("repo not found")):
        adapter = TransformersModelAdapter(_valid_config())
        with pytest.raises(AdapterLoadError):
            adapter.load()


# ── generate() ────────────────────────────────────────────────────────


def test_generate_uses_native_chat_template_not_a_forced_raw_string():
    fake_tokenizer = _FakeTokenizer()
    with patch("transformers.AutoTokenizer.from_pretrained", return_value=fake_tokenizer), \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=_FakeModel()):
        adapter = TransformersModelAdapter(_valid_config())
        adapter.load()
        rendered = adapter.render_prompt("what is 2+2", system_instruction="you are a test assistant")

    assert rendered == "RENDERED::you are a test assistant|what is 2+2"


def test_generate_returns_structured_result_with_latency():
    with patch("transformers.AutoTokenizer.from_pretrained", return_value=_FakeTokenizer()), \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=_FakeModel()):
        adapter = TransformersModelAdapter(_valid_config())
        adapter.load()
        result = adapter.generate("test prompt", system_instruction="test system", config={"temperature": 0.0, "max_new_tokens": 32})

    assert result.text == "fake generated response text"
    assert result.error is None
    assert result.latency_ms >= 0


def test_generate_without_load_fails_closed():
    adapter = TransformersModelAdapter(_valid_config())
    result = adapter.generate("prompt", system_instruction="sys", config={})
    assert result.text is None
    assert result.error is not None


def test_generate_exception_is_captured_not_raised():
    fake_model = _FakeModel()
    fake_model.generate = MagicMock(side_effect=RuntimeError("CUDA out of memory"))
    with patch("transformers.AutoTokenizer.from_pretrained", return_value=_FakeTokenizer()), \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=fake_model):
        adapter = TransformersModelAdapter(_valid_config())
        adapter.load()
        result = adapter.generate("prompt", system_instruction="sys", config={})

    assert result.text is None
    assert result.error is not None
    assert "CUDA out of memory" in result.error


def test_generate_config_forwards_temperature_and_max_new_tokens():
    fake_model = _FakeModel()
    with patch("transformers.AutoTokenizer.from_pretrained", return_value=_FakeTokenizer()), \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=fake_model):
        adapter = TransformersModelAdapter(_valid_config())
        adapter.load()
        adapter.generate("prompt", system_instruction="sys", config={"temperature": 0.0, "max_new_tokens": 128, "top_p": 0.9})

    call_kwargs = fake_model.generate_calls[0]
    assert call_kwargs["max_new_tokens"] == 128
    assert call_kwargs["do_sample"] is False  # temperature=0.0 -> deterministic


# ── unload / resource cleanup ────────────────────────────────────────────


def test_unload_clears_model_and_tokenizer_references():
    with patch("transformers.AutoTokenizer.from_pretrained", return_value=_FakeTokenizer()), \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=_FakeModel()):
        adapter = TransformersModelAdapter(_valid_config())
        adapter.load()
        adapter.unload()

    assert adapter._model is None
    assert adapter._tokenizer is None
    assert adapter._loaded is False


def test_unload_is_safe_even_if_never_loaded():
    adapter = TransformersModelAdapter(_valid_config())
    adapter.unload()  # must not raise


def test_context_manager_loads_and_unloads():
    with patch("transformers.AutoTokenizer.from_pretrained", return_value=_FakeTokenizer()), \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=_FakeModel()):
        with TransformersModelAdapter(_valid_config()) as adapter:
            assert adapter._loaded is True
        assert adapter._loaded is False
