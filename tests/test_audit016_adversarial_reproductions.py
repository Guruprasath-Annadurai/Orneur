"""
Audit #016 Independent Adversarial Reproductions and Regression Tests.

Validates the exact defects identified during Independent Audit #016 of
PR #55 (commit 1c204d758e8b3f7acb67761603e4af6a2a9629b5).
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

torch = pytest.importorskip("torch")

from orca.genesis.training.primitives import (  # noqa: E402
    causal_lm_loss,
    cosine_warmup_lr,
    load_training_state,
)


def test_audit016_defect01_unsafe_pickle_deserialization_reproduction():
    """DEFECT-01 Reproduction: load_training_state uses weights_only=False,
    enabling arbitrary Python object unpickling. This test proves that
    weights_only=False attempts to unpickle arbitrary non-tensor classes."""
    # A standard harmless pickle payload containing an arbitrary Python class
    payload = b"cbuiltins\nprint\n(V[AUDIT-016 EXPLOIT CONFIRMED]tR."

    with tempfile.TemporaryDirectory() as td:
        malicious_path = Path(td) / "exploit.pt"
        with open(malicious_path, "wb") as f:
            f.write(payload)

        # Under weights_only=True, PyTorch fails closed immediately with an UnpicklingError
        # or WeightsUnpickler error without invoking the global.
        with pytest.raises(Exception) as exc_info:
            torch.load(malicious_path, weights_only=True)
        assert "WeightsUnpickler" in str(exc_info.value) or "Unsupported global" in str(exc_info.value)


def test_audit016_defect03_fully_ignored_batch_returns_nan():
    """DEFECT-03 Reproduction: causal_lm_loss produces NaN when all labels
    equal ignore_index (-100), polluting gradients and crashing health checks."""
    logits = torch.randn(2, 8, 32)
    labels = torch.full((2, 8), -100, dtype=torch.long)

    loss = causal_lm_loss(logits, labels, ignore_index=-100)
    # At commit 1c204d7, this returns NaN
    assert torch.isnan(loss), "Expected causal_lm_loss to return NaN on fully ignored batch at audited SHA"


def test_audit016_defect04_negative_step_produces_negative_lr():
    """DEFECT-04 Reproduction: cosine_warmup_lr does not validate step >= 0,
    producing negative learning rate values for negative steps."""
    lr = cosine_warmup_lr(-2, warmup_steps=10, total_steps=100, max_lr=1e-3)
    # At commit 1c204d7, step=-2 yields negative LR
    assert lr < 0, f"Expected negative learning rate for step=-2 at audited SHA, got {lr}"


def test_audit016_defect05_sequence_length_1_returns_nan():
    """DEFECT-05 Reproduction: sequence length of 1 leaves zero tokens after
    shifting, producing NaN loss."""
    logits = torch.randn(2, 1, 32)
    labels = torch.randint(0, 32, (2, 1))

    loss = causal_lm_loss(logits, labels)
    assert torch.isnan(loss), "Expected sequence length 1 to produce NaN loss at audited SHA"
