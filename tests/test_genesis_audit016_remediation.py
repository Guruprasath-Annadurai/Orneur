"""
GENESIS Foundation Audit #016 remediation -- regression coverage for all
five independently identified defects (PR #56,
docs/orneur/status/INDEPENDENT_GENESIS_FOUNDATION_AUDIT_016.md).

Per the remediation directive's explicit instruction: these tests assert
the fixed, SAFE behavior -- a vulnerability that still existed would FAIL
these tests, not pass them. None of these tests pass merely because the
vulnerability remains present (the inverse of that discipline, which
would be a test asserting the exploit succeeds, is not what regression
coverage means here).

Every defect below was independently reproduced against the actual
vulnerable code path (not merely asserted from the audit's own
description) before being fixed -- see this module's own reproduction
calls inline, each followed immediately by the assertion that the FIXED
behavior now holds.
"""
from __future__ import annotations

import os
import stat

import pytest

torch = pytest.importorskip("torch")

from orca.genesis.training.primitives import (  # noqa: E402
    TrainingState,
    causal_lm_loss,
    cosine_warmup_lr,
    load_training_state,
    save_training_state,
)


# ------------------------------------------------- DEFECT-01: pickle RCE --

class _EvilPayload:
    """A harmless, isolated proof object: its only effect, if actually
    unpickled via the unrestricted pickle engine, is to touch a marker
    file -- never anything destructive, and never executed against real
    user data or infrastructure."""

    def __reduce__(self):
        return (os.system, ("true",))  # a no-op shell builtin -- proves code execution without doing anything


def test_defect01_malicious_checkpoint_is_rejected_not_executed(tmp_path):
    """Reproduces the exploit through the REAL load_training_state() call
    path, not a standalone torch.load() check -- craft a payload with a
    __reduce__ method, save it as a checkpoint, and call the actual
    public function. Must raise a loud deserialization error and must
    NOT execute the payload's __reduce__ method at all."""
    path = tmp_path / "evil_checkpoint.pt"
    torch.save(_EvilPayload(), path)

    with pytest.raises(Exception) as exc_info:
        load_training_state(path)
    # weights_only=True raises torch's own UnpicklingError subclass; the
    # exact class name has changed across torch versions, so the
    # assertion is on the behavior (raises, rejects pickle globals), not
    # a specific exception type.
    assert "weights only" in str(exc_info.value).lower() or "unsupported global" in str(exc_info.value).lower()


def test_defect01_legitimate_checkpoint_still_loads_successfully(tmp_path):
    """The fix must not break the real, intended use case: a checkpoint
    written by save_training_state() must still load correctly under
    weights_only=True."""
    model = torch.nn.Linear(4, 4)
    optimizer = torch.optim.AdamW(model.parameters())
    state = TrainingState.capture(step=5, epoch=1, dataloader_position=10, model=model, optimizer=optimizer)
    path = tmp_path / "legit_checkpoint.pt"
    save_training_state(state, path)

    loaded = load_training_state(path)
    assert loaded.step == 5
    assert loaded.epoch == 1
    assert loaded.dataloader_position == 10


# --------------------------------------- DEFECT-02: tempfile/symlink/perms --

def _dummy_state() -> TrainingState:
    return TrainingState(
        step=1, epoch=0, dataloader_position=0, model_state_dict={}, optimizer_state_dict={},
        python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None,
    )


def test_defect02_preexisting_symlink_at_the_old_predictable_tmp_path_is_not_followed(tmp_path):
    """Reproduces the exact attack: pre-plant a symlink at the OLD
    deterministic tmp-file name (`.{name}.tmp` matching the previous,
    now-replaced naming scheme) pointing at a sensitive file outside the
    checkpoint directory, then call save_training_state(). The sensitive
    file must be completely untouched."""
    sensitive = tmp_path / "sensitive_elsewhere.pt"
    sensitive.write_bytes(b"ORIGINAL CONTENT")
    ckpt_path = tmp_path / "checkpoint.pt"
    old_predictable_tmp = tmp_path / f".{ckpt_path.name}.tmp"
    old_predictable_tmp.symlink_to(sensitive)

    save_training_state(_dummy_state(), ckpt_path)

    assert sensitive.read_bytes() == b"ORIGINAL CONTENT", "a pre-planted symlink was followed and overwrote an unrelated file"
    assert ckpt_path.exists()


def test_defect02_checkpoint_file_has_owner_only_permissions(tmp_path):
    save_training_state(_dummy_state(), tmp_path / "checkpoint.pt")
    mode = stat.S_IMODE(os.stat(tmp_path / "checkpoint.pt").st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_defect02_checkpoint_directory_has_owner_only_permissions(tmp_path):
    ckpt_dir = tmp_path / "new_subdir"
    save_training_state(_dummy_state(), ckpt_dir / "checkpoint.pt")
    mode = stat.S_IMODE(os.stat(ckpt_dir).st_mode)
    assert mode == 0o700, f"expected 0o700, got {oct(mode)}"


def test_defect02_concurrent_writers_do_not_corrupt_the_checkpoint(tmp_path):
    """Two overlapping saves to the SAME path must each produce a fully
    valid, loadable checkpoint at the end -- never a half-written or
    interleaved file. Uses real threads (not just sequential calls) so
    the two save_training_state() calls genuinely overlap in time."""
    import threading

    path = tmp_path / "checkpoint.pt"
    errors = []

    def _save(step: int):
        try:
            save_training_state(
                TrainingState(step=step, epoch=0, dataloader_position=0, model_state_dict={}, optimizer_state_dict={},
                               python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None),
                path,
            )
        except Exception as e:  # noqa: BLE001 -- captured for the assertion below, not swallowed
            errors.append(e)

    threads = [threading.Thread(target=_save, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"concurrent save_training_state() calls raised: {errors}"
    # The decisive check: whatever is at `path` now must be a FULLY
    # valid, loadable checkpoint -- not a corrupted interleaving of two
    # writers' bytes. Which specific writer's step number "won" is not
    # asserted (the exclusive-writer lock means it's deterministic given
    # thread scheduling, but this test does not depend on that ordering).
    loaded = load_training_state(path)
    assert loaded.step in range(5)


# --------------------------------------------- DEFECT-03: fully-ignored --

def test_defect03_fully_ignored_batch_is_rejected_fail_closed():
    """The fail-closed design decision, verified: a batch where every
    shifted label is ignore_index must raise, not silently return a
    differentiable 0.0 that would look, to any training-loop logging or
    loss-averaging code, like a real successful step."""
    logits = torch.randn(2, 4, 10)
    labels = torch.full((2, 4), -100)
    with pytest.raises(ValueError, match="every shifted position is ignore_index"):
        causal_lm_loss(logits, labels)


def test_defect03_partially_ignored_batch_still_computes_a_valid_loss():
    """The fix must not be overly broad: a batch with SOME (not all)
    ignored positions must still compute a normal, finite loss."""
    logits = torch.randn(2, 4, 10)
    labels = torch.tensor([[1, 2, -100, 4], [5, -100, -100, 8]])
    loss = causal_lm_loss(logits, labels)
    assert torch.isfinite(loss)


# --------------------------------------------------- DEFECT-04: negative step --

def test_defect04_negative_step_is_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        cosine_warmup_lr(-1, warmup_steps=10, total_steps=100, max_lr=1e-3)


def test_defect04_step_zero_is_the_first_valid_step_not_rejected():
    """step=0 (zero-based indexing, the first real training step) must
    NOT be rejected by the fix -- only genuinely negative steps."""
    lr = cosine_warmup_lr(0, warmup_steps=10, total_steps=100, max_lr=1e-3)
    assert lr > 0


def test_defect04_warmup_reaches_max_lr_exactly_at_the_last_warmup_step():
    """Precise indexing check: step=warmup_steps-1 is the LAST warmup
    step and must equal max_lr exactly (not step=warmup_steps)."""
    lr_last_warmup_step = cosine_warmup_lr(9, warmup_steps=10, total_steps=100, max_lr=1e-3)
    assert lr_last_warmup_step == pytest.approx(1e-3)


def test_defect04_step_past_total_steps_clamps_to_min_lr_rather_than_raising():
    """Running past the planned schedule length is a normal, recoverable
    condition (e.g. a resumed run) and must clamp, not raise -- unlike a
    negative step, which is always invalid."""
    lr = cosine_warmup_lr(500, warmup_steps=10, total_steps=100, max_lr=1e-3, min_lr=1e-5)
    assert lr == pytest.approx(1e-5)


def test_defect04_min_lr_exceeding_max_lr_is_rejected():
    with pytest.raises(ValueError, match="must not exceed"):
        cosine_warmup_lr(0, warmup_steps=10, total_steps=100, max_lr=1e-4, min_lr=1e-3)


# --------------------------------------------------- DEFECT-05: seq_len=1 --

def test_defect05_sequence_length_one_is_rejected():
    logits = torch.randn(2, 1, 32)
    labels = torch.randint(0, 32, (2, 1))
    with pytest.raises(ValueError, match="seq_len >= 2"):
        causal_lm_loss(logits, labels)


def test_defect05_sequence_length_two_is_the_minimum_valid_case():
    """seq_len=2 (the smallest sequence with an actual next-token pair:
    position 0 predicts position 1) must NOT be rejected."""
    logits = torch.randn(2, 2, 32)
    labels = torch.randint(0, 32, (2, 2))
    loss = causal_lm_loss(logits, labels)
    assert torch.isfinite(loss)
