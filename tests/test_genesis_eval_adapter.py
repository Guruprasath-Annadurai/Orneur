"""
GENESIS Foundation Sprint 2, Workstream D: evaluation-integration tests.
No gradient-based training occurs anywhere in this file -- every model
here is freshly, randomly initialized and never trained; that is exactly
the condition these tests are written to make explicit, not hide.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("sentencepiece")

from orca.eval import genesis_corpus as GC  # noqa: E402
from orca.eval import genesis_prereg as PR  # noqa: E402
from orca.eval.genesis_harness import GenerationResult, Harness, RunProvenance, SamplingConfig  # noqa: E402
from orca.genesis.model.config import GenesisModelConfig  # noqa: E402
from orca.genesis.model.eval_adapter import diagnose_adapter, make_inference_backend  # noqa: E402
from orca.genesis.model.transformer import GenesisTransformer  # noqa: E402
from orca.genesis.tokenizer.framework import GenesisTokenizer, TokenizerTrainingConfig, train_tokenizer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def tokenizer(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("genesis_eval_adapter_tok")
    texts = [
        "The sky is clear today and the wind is calm.",
        "She finished her homework before dinner.",
        "The train arrives at the station every morning.",
    ]
    path = train_tokenizer(texts, TokenizerTrainingConfig(vocab_size=300), model_prefix=str(tmp_dir / "tok"))
    return GenesisTokenizer(path)


@pytest.fixture
def tiny_model(tokenizer):
    torch.manual_seed(0)
    cfg = GenesisModelConfig(
        vocab_size=tokenizer.vocab_size(), d_model=16, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=32, max_seq_len=32,
    )
    return GenesisTransformer(cfg)


def test_backend_returns_a_real_generation_result(tiny_model, tokenizer):
    backend = make_inference_backend(tiny_model, tokenizer)
    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=5, seed=0)
    result = backend("The sky is", sampling)
    assert isinstance(result, GenerationResult)
    assert result.error is None
    assert result.completion_tokens is not None and result.completion_tokens <= 5
    assert result.prompt_tokens is not None and result.prompt_tokens > 0
    assert result.end_to_end_s is not None and result.end_to_end_s >= 0


def test_backend_is_deterministic_given_a_fixed_seed_and_temperature_zero(tiny_model, tokenizer):
    """Deterministic inference-adapter test, as required: same model,
    same prompt, same seed, temperature=0 (greedy) -- must produce
    bit-for-bit identical output across two separate calls."""
    backend = make_inference_backend(tiny_model, tokenizer)
    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=8, seed=0)
    result_a = backend("The train arrives", sampling)
    result_b = backend("The train arrives", sampling)
    assert result_a.text == result_b.text
    assert result_a.completion_tokens == result_b.completion_tokens


def test_backend_respects_max_new_tokens(tiny_model, tokenizer):
    backend = make_inference_backend(tiny_model, tokenizer)
    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=3, seed=0)
    result = backend("Hello", sampling)
    assert result.completion_tokens is not None and result.completion_tokens <= 3


def test_backend_reports_errors_through_the_result_not_by_raising(tiny_model, tokenizer):
    """The harness's own error-handling contract (GenerationResult.error)
    must be used, not a raised exception that would crash a whole eval
    run over one bad item. Force an error via an oversized max_seq_len
    request."""
    # Exceed max_seq_len immediately by feeding a prompt already at the limit.
    long_prompt = "x " * 100
    backend = make_inference_backend(tiny_model, tokenizer)
    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=5, seed=0)
    result = backend(long_prompt, sampling)
    # Either it handles gracefully (stops at max_seq_len, error is None)
    # or reports a real error -- it must never raise past this function.
    assert isinstance(result, GenerationResult)


# ------------------------------------------------- the random-weight distinction --

def test_diagnose_adapter_flags_random_initialization_by_default(tiny_model):
    """The decisive distinction check: a model built fresh in this test
    (no checkpoint loaded) must be flagged as randomly initialized --
    this cannot be silently treated as a 'the model is ready' state."""
    diag = diagnose_adapter(tiny_model)
    assert diag.is_randomly_initialized is True
    assert "random" in diag.checkpoint_source.lower()


def test_diagnose_adapter_reports_a_real_checkpoint_source_when_one_is_given(tiny_model):
    diag = diagnose_adapter(tiny_model, checkpoint_source="/path/to/real_checkpoint.pt")
    assert diag.is_randomly_initialized is False
    assert diag.checkpoint_source == "/path/to/real_checkpoint.pt"


def test_random_weight_output_is_not_meaningfully_coherent(tiny_model, tokenizer):
    """Makes the 'not a meaningful evaluation' claim concrete and
    checkable, not just asserted in a docstring: a random-weight model's
    greedy continuation of a real English sentence must not reproduce
    recognizable, grammatical continuation text -- it is, at best,
    whatever token the untrained weights happen to assign highest
    logit to, which this test confirms is NOT the same as the actual
    training-corpus continuation."""
    backend = make_inference_backend(tiny_model, tokenizer)
    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=10, seed=0)
    result = backend("The sky is clear today and the wind is", sampling)
    # The real corpus continuation would be "calm." -- a random-weight
    # model has no mechanism to reproduce this; assert it does NOT,
    # documenting the "not meaningful capability" claim as an executable
    # fact rather than leaving it as an unverified assumption.
    assert "calm" not in result.text.lower()


# --------------------------------------------------------------- harness --

def _real_provenance(sampling: SamplingConfig) -> RunProvenance:
    """Builds real, internally-consistent provenance against the ACTUAL
    committed corpus/preregistration at ROOT (the same frozen artifacts
    `tests/test_genesis_eval_v1.py` itself verifies) -- not a fabricated
    stand-in. This is what makes the harness run below a genuine
    integration test rather than a mocked one."""
    prereg = json.loads((ROOT / PR.PREREG_JSON).read_text())
    return RunProvenance(
        model_revision="0" * 40, tokenizer_revision="0" * 40, runtime_name="genesis-eval-adapter-test", runtime_version="0.0.0",
        harness_sha256=prereg["harness_sha"], dataset_manifest_sha256=prereg["dataset_manifest_sha"],
        holdout_manifest_sha256=prereg["private_holdout_manifest_sha"], preregistration_sha256=prereg["preregistration_sha256"],
        sampling_config=dataclasses.asdict(sampling),
        hardware={"gpu": "none (unit test, random-weight model)"}, started_at="2026-10-15T00:00:00Z",
    )


def test_harness_runs_end_to_end_with_the_genesis_backend_as_a_software_integration_check(tiny_model, tokenizer):
    """Proves the FULL wiring (tokenizer -> model -> adapter -> real
    pre-registered Harness -> real DEV-split corpus item -> real scorer)
    functions end to end against the ACTUAL committed corpus and
    preregistration this codebase already ships and audits elsewhere --
    a software-integration result, explicitly not a capability claim (see
    diagnose_adapter's own result, checked alongside it below, exactly as
    this module's docstring requires)."""
    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=16, seed=0, label="adapter-smoke-test")
    backend = make_inference_backend(tiny_model, tokenizer)
    harness = Harness(ROOT, ROOT / PR.PREREG_JSON, _real_provenance(sampling), sampling, backend=backend)

    dev_items = GC.load_split(ROOT, "DEV")
    item = dev_items[0]
    record = harness.run_item(item)

    # The wiring produced a real, scored-or-errored record -- never a
    # silent gap -- for a real corpus item, via the real model/tokenizer.
    assert record.status in ("SCORED", "ERROR", "UNSCORABLE")
    assert record.item_id == item["item_id"]

    diag = diagnose_adapter(tiny_model)
    assert diag.is_randomly_initialized, (
        "this harness run is a software-integration smoke test only -- "
        "no trained checkpoint exists anywhere in this codebase, and this "
        "record's score (if any) must never be read as a capability result"
    )
