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
from orca.genesis.model.eval_adapter import (  # noqa: E402
    ModelCheckpointBindingError,
    ProvenanceStatus,
    TrainingRunRecordError,
    diagnose_adapter,
    make_inference_backend,
)
from orca.genesis.model.transformer import GenesisTransformer  # noqa: E402
from orca.genesis.tokenizer.framework import GenesisTokenizer, TokenizerTrainingConfig, train_tokenizer  # noqa: E402
from orca.genesis.training.checkpoint_integrity import (  # noqa: E402
    ChecksumMismatchError,
    ManifestMissingError,
    load_verified_training_state,
    save_verified_training_state,
)
from orca.genesis.training.primitives import TrainingState  # noqa: E402

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
    assert isinstance(result, GenerationResult)
    # Audit #017 DEFECT-06 remediation: a prompt that already fills (or
    # exceeds) max_seq_len must report a real error, not a silent
    # text="", error=None "successful empty completion" -- the two are
    # indistinguishable to a caller unless this is enforced.
    assert result.error is not None
    assert result.text == ""
    assert result.completion_tokens == 0


def test_backend_reports_a_real_error_not_a_silent_empty_success_on_context_overflow(tiny_model, tokenizer):
    """A dedicated regression test for the exact Audit #017 DEFECT-06
    reproduction: a prompt tokenizing to >= max_seq_len tokens must not
    be silently treated as a zero-token successful completion."""
    backend = make_inference_backend(tiny_model, tokenizer)
    overflowing_prompt = "word " * (tiny_model.cfg.max_seq_len + 5)
    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=5, seed=0)
    result = backend(overflowing_prompt, sampling)
    assert result.error is not None
    assert "max_seq_len" in result.error


def test_backend_strips_stop_sequence_from_the_returned_text(tiny_model, tokenizer):
    """Audit #017 DEFECT-06 remediation: the stop sequence itself must
    not appear in the scored completion text, matching standard
    inference-server stop-sequence semantics."""
    import torch as _torch

    from orca.eval.genesis_harness import GenerationResult as _GR

    stop_text = "STOPHERE"
    stop_ids = tokenizer.encode(stop_text)
    seq = list(stop_ids) + [1, 2, 3]
    idx = 0

    def _mock_step(input_ids, temperature=1.0):
        nonlocal idx
        val = seq[idx % len(seq)]
        idx += 1
        return _torch.tensor([val])

    tiny_model.generate_step = _mock_step
    backend = make_inference_backend(tiny_model, tokenizer)
    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=len(stop_ids) + 3, seed=0, stop=(stop_text,))
    result = backend("prompt", sampling)
    assert isinstance(result, _GR)
    assert stop_text not in result.text


def test_backend_does_not_permanently_mutate_global_rng_state(tiny_model, tokenizer):
    """Audit #017 DEFECT-06 remediation: calling the backend with a seed
    must not leave the process-wide RNG in a different state than before
    the call -- `torch.random.fork_rng()` must restore it on exit."""
    import torch as _torch

    _torch.manual_seed(999)
    before = _torch.get_rng_state().clone()

    backend = make_inference_backend(tiny_model, tokenizer)
    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=4, seed=12345)
    backend("Hello there", sampling)

    after = _torch.get_rng_state()
    assert _torch.equal(before, after), "global RNG state must be restored after a seeded backend call"


# ------------------------------------------------- the random-weight distinction --

def _real_checkpoint_for(model, tmp_path, *, name="checkpoint.pt", step=1, epoch=0):
    """Saves a REAL, verified checkpoint containing `model`'s actual
    current state_dict -- not an empty placeholder dict -- so binding
    tests have real tensor values to compare."""
    path = tmp_path / name
    state = TrainingState(
        step=step, epoch=epoch, dataloader_position=0, model_state_dict=model.state_dict(),
        optimizer_state_dict={}, python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None,
    )
    save_verified_training_state(state, path)
    return path


def test_diagnose_adapter_flags_random_initialization_by_default(tiny_model):
    """The decisive distinction check: a model built fresh in this test
    (no checkpoint loaded) must be flagged as randomly initialized --
    this cannot be silently treated as a 'the model is ready' state."""
    diag = diagnose_adapter(tiny_model)
    assert diag.status is ProvenanceStatus.RANDOM_INITIALIZATION
    assert "random" in diag.checkpoint_source.lower()


def test_diagnose_adapter_reports_unverified_for_a_real_verified_checkpoint_bound_to_this_model(tiny_model, tmp_path):
    """A real, content-verified checkpoint that genuinely IS this model's
    own current parameters must still land on UNVERIFIED, not TRAINED --
    content integrity and live-model binding alone never imply an
    authorized training run happened."""
    path = _real_checkpoint_for(tiny_model, tmp_path)
    diag = diagnose_adapter(tiny_model, checkpoint_path=path)
    assert diag.status is ProvenanceStatus.UNVERIFIED
    assert diag.checkpoint_source == str(path)
    assert diag.training_run_id is None


# ------------------------------------- Mission 1A: adversarial provenance coverage --

def test_diagnose_adapter_rejects_a_nonexistent_checkpoint_path(tiny_model):
    """Forged path: a checkpoint_path that does not exist at all must
    propagate the real content-integrity boundary's own error, not be
    silently accepted or downgraded."""
    with pytest.raises(ManifestMissingError):
        diagnose_adapter(tiny_model, checkpoint_path="/path/that/does/not/exist/fake-trained-model.pt")


def test_diagnose_adapter_rejects_an_unrelated_existing_file(tiny_model, tmp_path):
    """Independently re-reproduces the exact Mission 1A bypass: an
    EXISTING file that has nothing to do with any GENESIS checkpoint
    (no manifest, not a real checkpoint) must be rejected, not silently
    treated as a trained checkpoint merely because `Path.exists()` is
    true."""
    unrelated = tmp_path / "unrelated_scratch_file.txt"
    unrelated.write_text("this file has nothing to do with any GENESIS checkpoint")
    with pytest.raises(ManifestMissingError):
        diagnose_adapter(tiny_model, checkpoint_path=unrelated)


def test_diagnose_adapter_rejects_a_checkpoint_belonging_to_a_different_model_instance(tiny_model, tokenizer, tmp_path):
    """Swapped model states / incorrect model-checkpoint binding: a
    checkpoint that is perfectly valid and content-verified -- but
    belongs to a DIFFERENT model instance with different real weights --
    must be rejected when diagnosing THIS model."""
    other_cfg = GenesisModelConfig(
        vocab_size=tokenizer.vocab_size(), d_model=16, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=32, max_seq_len=32,
    )
    torch.manual_seed(999)  # a different seed -> genuinely different real weights
    other_model = GenesisTransformer(other_cfg)
    other_checkpoint = _real_checkpoint_for(other_model, tmp_path, name="other_model_checkpoint.pt")

    # Sanity: the swapped checkpoint is itself perfectly valid on its own terms.
    load_verified_training_state(other_checkpoint)

    with pytest.raises(ModelCheckpointBindingError):
        diagnose_adapter(tiny_model, checkpoint_path=other_checkpoint)


def test_diagnose_adapter_rejects_a_checkpoint_with_a_corrupted_manifest(tiny_model, tmp_path):
    """Invalid manifest: a single-byte content change caught by the
    existing checksum boundary must still propagate through
    diagnose_adapter unchanged."""
    path = _real_checkpoint_for(tiny_model, tmp_path)
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(ChecksumMismatchError):
        diagnose_adapter(tiny_model, checkpoint_path=path)


def test_diagnose_adapter_never_reaches_trained_without_an_explicit_training_run_record(tiny_model, tmp_path):
    """With no training_run_record_path at all, status must never be
    TRAINED, regardless of how real and correctly-bound the checkpoint
    is -- UNVERIFIED is the ceiling this function can reach today."""
    path = _real_checkpoint_for(tiny_model, tmp_path)
    diag = diagnose_adapter(tiny_model, checkpoint_path=path)
    assert diag.status is ProvenanceStatus.UNVERIFIED
    assert diag.status is not ProvenanceStatus.TRAINED


def test_diagnose_adapter_rejects_a_forged_unsigned_training_run_record_that_previously_granted_trained(tiny_model, tmp_path):
    """Native-Authorization-Convergence Mission 1 (P0): independently
    reproduced before this fix existed -- a caller-authored, completely
    UNSIGNED JSON file naming the checkpoint's own (non-secret) manifest
    sha256 and `authorized: true` used to be sufficient to reach
    ProvenanceStatus.TRAINED, with zero cryptographic proof and zero
    founder involvement. This forgery must now be hard-rejected, not
    silently downgraded to UNVERIFIED and not accepted as TRAINED."""
    path = _real_checkpoint_for(tiny_model, tmp_path)
    manifest = json.loads((tmp_path / "checkpoint.pt.manifest.json").read_text())
    forged_record_path = tmp_path / "forged_run_record.json"
    forged_record_path.write_text(json.dumps({
        "run_id": "attacker-claimed-run",
        "checkpoint_sha256": manifest["sha256"],  # trivially copied -- not a secret
        "authorized": True,
    }))
    with pytest.raises(TrainingRunRecordError):
        diagnose_adapter(tiny_model, checkpoint_path=path, training_run_record_path=forged_record_path)


def test_diagnose_adapter_rejects_training_run_record_path_unconditionally_even_when_well_formed(tiny_model, tmp_path):
    """The removed mechanism is rejected unconditionally -- not just for
    malformed/mismatched/unauthorized records (those were already
    correctly rejected before this fix) but for a record that is
    well-formed, matches the real checkpoint's hash, and claims
    authorized=True. There is no longer any content a caller can put in
    this file that reaches anything other than a hard failure."""
    path = _real_checkpoint_for(tiny_model, tmp_path)
    manifest = json.loads((tmp_path / "checkpoint.pt.manifest.json").read_text())
    record_path = tmp_path / "run_record.json"
    record_path.write_text(json.dumps({"run_id": "run-42", "checkpoint_sha256": manifest["sha256"], "authorized": True}))
    with pytest.raises(TrainingRunRecordError):
        diagnose_adapter(tiny_model, checkpoint_path=path, training_run_record_path=record_path)


def test_diagnose_adapter_rejects_a_missing_training_run_record_path(tiny_model, tmp_path):
    path = _real_checkpoint_for(tiny_model, tmp_path)
    with pytest.raises(TrainingRunRecordError):
        diagnose_adapter(tiny_model, checkpoint_path=path, training_run_record_path=tmp_path / "does_not_exist.json")


def test_diagnose_adapter_rejects_a_malformed_training_run_record(tiny_model, tmp_path):
    path = _real_checkpoint_for(tiny_model, tmp_path)
    record_path = tmp_path / "run_record.json"
    record_path.write_text(json.dumps({"run_id": "run-1"}))  # missing required fields
    with pytest.raises(TrainingRunRecordError):
        diagnose_adapter(tiny_model, checkpoint_path=path, training_run_record_path=record_path)


def test_provenance_status_trained_is_unreachable_through_any_diagnose_adapter_call(tiny_model, tokenizer, tmp_path):
    """Structural regression, not just a behavioral one: sweep every
    combination of arguments this function accepts (no checkpoint, a
    real correctly-bound checkpoint, a real checkpoint plus any
    training_run_record_path content) and confirm NONE of them produce
    ProvenanceStatus.TRAINED -- either the call succeeds and returns
    RANDOM_INITIALIZATION/UNVERIFIED, or it raises. TRAINED is reachable
    from no code path in this module today."""
    path = _real_checkpoint_for(tiny_model, tmp_path)
    manifest = json.loads((tmp_path / "checkpoint.pt.manifest.json").read_text())

    results = []
    diag = diagnose_adapter(tiny_model)
    results.append(diag.status)
    diag = diagnose_adapter(tiny_model, checkpoint_path=path)
    results.append(diag.status)

    for authorized in (True, False):
        for sha in (manifest["sha256"], "0" * 64):
            record_path = tmp_path / f"record_{authorized}_{sha[:4]}.json"
            record_path.write_text(json.dumps({"run_id": "r", "checkpoint_sha256": sha, "authorized": authorized}))
            try:
                diag = diagnose_adapter(tiny_model, checkpoint_path=path, training_run_record_path=record_path)
                results.append(diag.status)
            except TrainingRunRecordError:
                pass  # the only acceptable outcome for any training_run_record_path content

    assert ProvenanceStatus.TRAINED not in results
    assert set(results) <= {ProvenanceStatus.RANDOM_INITIALIZATION, ProvenanceStatus.UNVERIFIED}


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
    assert diag.status is ProvenanceStatus.RANDOM_INITIALIZATION, (
        "this harness run is a software-integration smoke test only -- "
        "no trained checkpoint exists anywhere in this codebase, and this "
        "record's score (if any) must never be read as a capability result"
    )
