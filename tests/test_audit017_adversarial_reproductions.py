"""
Independent Audit #017 Adversarial Reproduction Suite.
Target: PR #58 (commit 368f7d9acb3de1cffd8996cba98149c160904926).
Auditor: Antigravity / Gemini.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

torch = pytest.importorskip("torch")
spm = pytest.importorskip("sentencepiece")

from orca.genesis.model.config import GenesisModelConfig
from orca.genesis.model.eval_adapter import diagnose_adapter, make_inference_backend
from orca.genesis.model.scaling import CORRECTED_SCALING_TIERS, estimate_training_memory, resolve_corrected_tier
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.training.checkpoint_integrity import (
    _manifest_path,
    load_verified_training_state,
    save_verified_training_state,
)
from orca.genesis.training.primitives import TrainingState
from orca.eval.genesis_harness import SamplingConfig


def _dummy_state(step: int = 1, epoch: int = 0) -> TrainingState:
    return TrainingState(
        step=step,
        epoch=epoch,
        dataloader_position=0,
        model_state_dict={},
        optimizer_state_dict={},
        python_rng_state=(1,),
        torch_rng_state=b"",
        cuda_rng_state=None,
    )


def test_reproduce_defect01_manifest_predictable_tmp_follows_symlink_overwriting_target(tmp_path):
    """DEFECT-01 (High Security):
    save_verified_training_state uses deterministic temporary filename
    f".{manifest_path.name}.tmp" and calls tmp.write_text().
    If an attacker pre-creates a symlink at that path pointing to a sensitive file,
    the sensitive file is overwritten.
    """
    sensitive_file = tmp_path / "sensitive_victim.txt"
    sensitive_file.write_text("TOP SECRET CONTENT")

    ckpt_path = tmp_path / "checkpoint.pt"
    manifest_tmp = tmp_path / f".{ckpt_path.name}.manifest.json.tmp"

    # Pre-create symlink
    os.symlink(sensitive_file, manifest_tmp)

    # Invoke save_verified_training_state
    save_verified_training_state(_dummy_state(step=1), ckpt_path)

    # Verify sensitive file was overwritten
    content = sensitive_file.read_text()
    assert "TOP SECRET CONTENT" not in content
    assert "genesis-ckpt-v1" in content


def test_reproduce_defect02_manifest_unvalidated_architecture_and_format_versions(tmp_path):
    """DEFECT-02 (Medium Security / Integrity):
    load_verified_training_state deserializes the manifest but never validates
    format_version or architecture_version against expected constants.
    """
    ckpt_path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_dummy_state(step=1), ckpt_path)

    mpath = _manifest_path(ckpt_path)
    m = json.loads(mpath.read_text())
    m["format_version"] = "unsupported-incompatible-v999"
    m["architecture_version"] = "genesis-incompatible-v999"
    mpath.write_text(json.dumps(m))

    # Should raise ValueError or VersionMismatchError, but currently succeeds silently
    loaded = load_verified_training_state(ckpt_path)
    assert loaded.step == 1  # Vulnerability: succeeded without version validation


def test_reproduce_defect03_manifest_step_and_epoch_mismatch_not_detected(tmp_path):
    """DEFECT-03 (Medium Integrity):
    load_verified_training_state does not verify that manifest.step and manifest.epoch
    match the deserialized TrainingState.step and epoch.
    """
    ckpt_path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_dummy_state(step=10, epoch=2), ckpt_path)

    mpath = _manifest_path(ckpt_path)
    m = json.loads(mpath.read_text())
    m["step"] = 999999
    m["epoch"] = 8888
    mpath.write_text(json.dumps(m))

    # Hash still matches, so load_verified_training_state succeeds, silently ignoring discrepancy
    loaded = load_verified_training_state(ckpt_path)
    assert loaded.step == 10
    # Manifest claimed step 999999, but loaded state is step 10 without any warning or error


def test_reproduce_defect04_eval_adapter_checkpoint_source_spoofing():
    """DEFECT-04 (Provenance / Verification Bypass):
    diagnose_adapter marks a model as is_randomly_initialized=False whenever
    checkpoint_source is provided, without validating if the path exists, if the
    weights were loaded, or if the model is genuinely trained.
    """
    cfg = GenesisModelConfig(vocab_size=100, d_model=64, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=128, max_seq_len=64)
    fresh_random_model = GenesisTransformer(cfg)

    # Caller passes a spoofed checkpoint source string
    diag = diagnose_adapter(fresh_random_model, checkpoint_source="s3://orneur-fake/genesis-trained-model.pt")

    # Flaw: Randomly initialized model is reported as NOT randomly initialized
    assert diag.is_randomly_initialized is False
    assert diag.checkpoint_source == "s3://orneur-fake/genesis-trained-model.pt"


def test_reproduce_defect05_eval_adapter_long_prompt_silent_empty_completion():
    """DEFECT-05 (Evaluation Robustness):
    When prompt length >= max_seq_len, make_inference_backend returns an empty
    completion with error=None rather than truncating or raising an error.
    """
    tok = MagicMock()
    tok.encode.return_value = list(range(16))  # 16 prompt tokens
    tok.decode.return_value = ""

    cfg = GenesisModelConfig(vocab_size=100, d_model=64, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=128, max_seq_len=8)
    model = GenesisTransformer(cfg)
    backend = make_inference_backend(model, tok)

    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=5, seed=42)
    res = backend("long prompt exceeding 8 tokens", sampling)

    assert res.text == ""
    assert res.error is None
    assert res.completion_tokens == 0
    assert res.prompt_tokens == 16


def test_reproduce_defect06_eval_adapter_stop_token_retained_in_output():
    """DEFECT-06 (Evaluation Precision):
    When stop token triggers loop break, the stop token is retained in res.text
    rather than stripped.
    """
    tok = MagicMock()
    tok.encode.return_value = [1]
    tok.decode.side_effect = lambda ids: "".join({10: "def foo():", 11: "\n    return 42", 12: "\n```"}.get(i, "") for i in ids)

    cfg = GenesisModelConfig(vocab_size=100, d_model=64, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=128, max_seq_len=32)
    model = GenesisTransformer(cfg)

    seq = [10, 11, 12]
    idx = 0
    def mock_step(input_ids, temperature=1.0):
        nonlocal idx
        val = seq[idx]
        idx += 1
        return torch.tensor([val])

    model.generate_step = mock_step
    backend = make_inference_backend(model, tok)

    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=10, seed=42, stop=("\n```",))
    res = backend("prompt", sampling)

    # Flaw: The stop token '\n```' remains in the generated text
    assert res.text.endswith("\n```")


def test_reproduce_scaling_10m_embedding_dominance_and_logits_memory_gap():
    """AUDIT 2 Analysis:
    Verify 10M tier parameter allocation and demonstrate the memory disparity
    between estimate_training_memory and actual vocabulary logits allocation.
    """
    tier_10m = CORRECTED_SCALING_TIERS[0]
    cfg = resolve_corrected_tier(tier_10m)
    b = cfg.breakdown()
    total = cfg.total_parameters()

    # Embedding dominance
    embed_pct = b["embedding"] / total
    assert embed_pct > 0.88, f"10M tier embedding should be ~89%, got {embed_pct:.2%}"

    # Memory calculation comparison
    mem = estimate_training_memory(cfg, batch_size=4, seq_len=4096)
    estimated_acts = mem.activations_estimate

    # Logits tensor alone in FP32 (batch_size * seq_len * vocab_size * 4 bytes)
    logits_bytes = 4 * 4096 * cfg.vocab_size * 4
    assert logits_bytes > estimated_acts * 30, (
        f"Logits alone ({logits_bytes / 1e9:.2f} GB) is over 30x larger than "
        f"estimated activations ({estimated_acts / 1e6:.2f} MB)"
    )
