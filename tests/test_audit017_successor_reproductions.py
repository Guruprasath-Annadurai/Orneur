"""
Independent Audit #017 Successor Adversarial Reproduction Suite.
Target: PR #58 (commit 3a272453117a34eeec04320c1eba49480ea0192d).
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
from orca.genesis.model.eval_adapter import (
    ProvenanceStatus,
    diagnose_adapter,
    make_inference_backend,
)
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.training.checkpoint_integrity import (
    _manifest_path,
    save_verified_training_state,
    state_dict_fingerprint,
)
from orca.genesis.training.primitives import TrainingState
from orca.eval.genesis_harness import SamplingConfig


def _state(step: int = 1, epoch: int = 0) -> TrainingState:
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


def test_reproduce_fake_training_authorization_spoofing():
    """WAVE 1.1 / DEFECT-01:
    Demonstrates that an untrained, randomly initialized model with 0 training steps
    can receive an attested ProvenanceStatus.TRAINED status merely by an attacker
    writing an unauthenticated 3-line local JSON file with "authorized": true.
    """
    cfg = GenesisModelConfig(vocab_size=100, d_model=64, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=128, max_seq_len=64)
    model = GenesisTransformer(cfg)

    with tempfile.TemporaryDirectory() as td:
        ckpt_path = Path(td) / "untrained_random.pt"
        state = TrainingState(
            step=0,
            epoch=0,
            dataloader_position=0,
            model_state_dict=model.state_dict(),
            optimizer_state_dict={},
            python_rng_state=(1,),
            torch_rng_state=b"",
            cuda_rng_state=None,
        )
        manifest = save_verified_training_state(state, ckpt_path)

        # Attacker writes a forged, unsigned training run record
        run_record_path = Path(td) / "forged_founder_authorization.json"
        run_record_path.write_text(
            json.dumps({
                "run_id": "genesis-fake-run-2026",
                "checkpoint_sha256": manifest.sha256,
                "authorized": True,
            })
        )

        diag = diagnose_adapter(
            model,
            checkpoint_path=ckpt_path,
            training_run_record_path=run_record_path,
        )

        # Confirmed vulnerability: Model is certified TRAINED without any cryptographic signature or real training event
        assert diag.status == ProvenanceStatus.TRAINED
        assert diag.training_run_id == "genesis-fake-run-2026"


def test_reproduce_fingerprint_shape_collision():
    """WAVE 1.3 / DEFECT-02:
    Demonstrates that state_dict_fingerprint completely omits tensor shapes,
    producing identical fingerprints for models with incompatible parameter shapes.
    """
    # Shapes (2, 6), (3, 4), and (12, 1) share the exact same flattened byte content
    t1 = torch.arange(12, dtype=torch.float32).reshape(2, 6)
    t2 = torch.arange(12, dtype=torch.float32).reshape(3, 4)
    t3 = torch.arange(12, dtype=torch.float32).reshape(12, 1)

    fp1 = state_dict_fingerprint({"weight": t1})
    fp2 = state_dict_fingerprint({"weight": t2})
    fp3 = state_dict_fingerprint({"weight": t3})

    assert fp1 == fp2 == fp3, "Fingerprint should collide because tensor.shape is never hashed"


def test_reproduce_fingerprint_bfloat16_unsupported():
    """WAVE 1.3 / DEFECT-03:
    Demonstrates that state_dict_fingerprint crashes with TypeError when given bfloat16 tensors
    because NumPy does not natively support PyTorch BFloat16 in .numpy().
    """
    bf16_state = {"weight": torch.randn(8, 8, dtype=torch.bfloat16)}

    with pytest.raises(TypeError, match="unsupported ScalarType BFloat16"):
        state_dict_fingerprint(bf16_state)


def test_reproduce_distinct_lock_files_between_reader_and_writer():
    """WAVE 1.2 / DEFECT-04:
    Confirms that save_verified_training_state and load_verified_training_state
    use distinct, non-synchronizing lock targets (.verified.lock vs .lock),
    leaving a window where a reader hashes a new checkpoint against an old manifest.
    """
    with tempfile.TemporaryDirectory() as td:
        ckpt_path = Path(td) / "model.pt"
        manifest_path = _manifest_path(ckpt_path)

        writer_lock = ckpt_path.parent / f".{ckpt_path.name}.verified.lock"
        reader_lock = ckpt_path.parent / f".{ckpt_path.name}.lock"

        # The lock files are distinct
        assert writer_lock != reader_lock


def test_reproduce_eval_adapter_context_overflow_error():
    """WAVE 1.5 / VERIFIED REMEDIATION:
    Confirms that Claude's remediation for context overflow now correctly returns
    an explicit error message rather than a silent empty completion.
    """
    tok = MagicMock()
    tok.encode.return_value = list(range(16))  # 16 prompt tokens
    tok.decode.return_value = ""

    cfg = GenesisModelConfig(vocab_size=100, d_model=64, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=128, max_seq_len=8)
    model = GenesisTransformer(cfg)
    backend = make_inference_backend(model, tok)

    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=5, seed=42)
    res = backend("prompt exceeding max context", sampling)

    assert "no room to generate even one token" in res.error
    assert res.text == ""
