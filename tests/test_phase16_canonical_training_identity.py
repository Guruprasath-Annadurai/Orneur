"""
Phase 16 final closure: the fail-closed guards added in the previous closure
(finetune.train() / CloudTrainer.__init__ raising when base_model is None)
only caught the UNSELECTED case. They did nothing to stop a canonical family
config (family="aeternum"/"genesis"/"novus") from having its base_model
manually overridden to an arbitrary string while keeping its canonical
family identity -- e.g. `orneur train run --preset ultra --model
arbitrary/model` (orca/cli.py's `train_run`: `if model: cfg.base_model =
model`, with no re-validation). These tests reproduce that bypass first,
then verify the centralized `validate_training_identity()` fix.
"""
from __future__ import annotations

import pytest

from orca.train.config import TrainingConfig


def test_canonical_aeternum_cannot_be_trained_with_a_manually_injected_base_model():
    """(A) Manually overriding base_model on a canonical family config must
    still fail closed -- family="aeternum" + an arbitrary base_model is not
    a valid canonical Aeternum training request."""
    from orca.train.finetune import train

    cfg = TrainingConfig.preset("ultra")
    assert cfg.family == "aeternum"
    cfg.base_model = "some/arbitrary-model"  # the exact bypass reproduced

    with pytest.raises(ValueError, match="canonical|family|override"):
        train(cfg)


def test_cli_train_run_cannot_bypass_canonical_family_selection(monkeypatch):
    """(B) `orneur train run --preset ultra --model arbitrary/model` must not
    reach train() as canonical Aeternum -- the CLI's --model override must
    be rejected by the same centralized validator train() calls, not
    silently accepted."""
    from orca.train.finetune import train as real_train

    called = {"train": False}

    def _spy_train(cfg, **kwargs):
        called["train"] = True
        return real_train(cfg, **kwargs)

    monkeypatch.setattr("orca.train.finetune.train", _spy_train)

    from typer.testing import CliRunner
    from orca.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["train", "run", "--preset", "ultra", "--model", "some/arbitrary-model"])

    assert result.exit_code != 0
    assert "Training complete!" not in result.output
    # The rejection must be the canonical-identity ValueError raised by
    # train()'s centralized validator (caught cleanly by the CLI's own
    # `except ValueError` handler, hence SystemExit rather than a raw
    # traceback) -- NOT an unrelated ImportError from missing training deps
    # reached only because the identity check never ran (that would mean
    # the bypass silently proceeded past validation on any machine that
    # DOES have unsloth installed).
    lowered = result.output.lower()
    assert "canonical" in lowered or "override" in lowered or "no selected base model" in lowered
    assert "Missing training deps" not in result.output


@pytest.mark.parametrize("preset,family", [("nano", "genesis"), ("core", "novus")])
def test_genesis_and_novus_canonical_presets_cannot_silently_substitute_a_model(preset, family):
    """(C) Genesis/Novus canonical family presets also cannot silently
    substitute a different base model while retaining their canonical
    family identity."""
    from orca.train.finetune import train

    cfg = TrainingConfig.preset(preset)
    assert cfg.family == family
    cfg.base_model = "some/arbitrary-model"

    with pytest.raises(ValueError, match="canonical|family|override"):
        train(cfg)


def test_require_base_model_genuinely_participates_in_the_training_validation_path(monkeypatch):
    """(D) require_base_model() must genuinely be invoked by the real
    execution boundary, not merely produce a similar-looking error message
    checked separately. Proven by monkeypatching it and observing train()'s
    behavior change."""
    import orca.registry.model_spec as model_spec_mod
    from orca.train.finetune import train

    calls = []
    real_require_base_model = model_spec_mod.require_base_model

    def _spy(family):
        calls.append(family)
        return real_require_base_model(family)

    monkeypatch.setattr(model_spec_mod, "require_base_model", _spy)

    cfg = TrainingConfig.preset("nano")  # canonical, base_model correctly set
    cfg.base_model = "tampered/model"
    with pytest.raises(ValueError):
        train(cfg)

    assert "genesis" in calls, (
        "train() must call the CURRENT orca.registry.model_spec.require_base_model "
        "(picked up via monkeypatch), not a separately-imported reference frozen at "
        "import time, and not skip calling it entirely."
    )


def test_cloud_xl_cannot_register_output_under_a_reserved_native_model_name(monkeypatch):
    """(E) A generic/legacy cloud training job cannot be registered under a
    reserved native runtime identity (orca-nano/orca-core/orca-ultra) unless
    explicitly associated with and validated against that canonical family.
    Must fail BEFORE any SSH/network/GPU work."""
    import orca.train.cloud as cloud_mod

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("SSH/network must never be attempted for a rejected identity")

    monkeypatch.setattr(cloud_mod, "_ssh_run", _must_not_be_called)
    monkeypatch.setattr(cloud_mod, "_rsync_up", _must_not_be_called)
    monkeypatch.setattr(cloud_mod, "_rsync_down", _must_not_be_called)

    with pytest.raises(ValueError, match="reserved|canonical|native"):
        cloud_mod.CloudTrainer(ssh="ssh root@1.2.3.4", preset="cloud_xl", model_name="orca-ultra")


def test_reserved_native_model_names_cover_the_three_registered_families():
    from orca.registry.model_spec import RESERVED_NATIVE_MODEL_NAMES

    assert "orca-nano" in RESERVED_NATIVE_MODEL_NAMES
    assert "orca-core" in RESERVED_NATIVE_MODEL_NAMES
    assert "orca-ultra" in RESERVED_NATIVE_MODEL_NAMES


def test_canonical_family_config_with_correct_base_model_still_trains(monkeypatch):
    """Non-regression: a canonical family config that has NOT been tampered
    with must still reach real training work (not be rejected by the new
    validator) -- proven by letting it proceed past validation into the
    (mocked) unsloth import boundary."""
    from orca.train.finetune import train

    cfg = TrainingConfig.preset("nano")  # family="genesis", base_model correct, untouched
    with pytest.raises(ImportError):
        # No unsloth installed in this guard -- reaching _check_deps()'s
        # ImportError (not a ValueError) proves validate_training_identity()
        # passed for a correctly-configured canonical request.
        train(cfg)


def test_generic_experiment_config_with_explicit_base_model_still_trains():
    """Non-regression: a generic (family=None) config with an explicit,
    non-reserved base model and name is a legitimate experimental request
    and must not be rejected by the new validator."""
    from orca.train.finetune import train

    cfg = TrainingConfig(base_model="some/experimental-model", family=None, model_name="my-experiment")
    with pytest.raises(ImportError):
        train(cfg)
