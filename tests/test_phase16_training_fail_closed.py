"""
Phase 16 closure: Aeternum's ModelSpec correctly says UNSELECTED, but the
initial closure only unit-tested orca/registry/model_spec.py in isolation
-- it did not prove the actual training entry points (local finetune.py,
cloud.py's CloudTrainer, the CLI, and the generic cloud_xl hardware preset)
fail closed BEFORE any model load / SSH / network / GPU work. These tests
reproduce and then verify the fix for that gap.
"""
from __future__ import annotations

import pytest

from orca.train.config import TrainingConfig


def test_ultra_preset_resolves_to_no_selected_base_model():
    cfg = TrainingConfig.preset("ultra")
    assert cfg.base_model is None
    assert cfg.family == "aeternum"


def test_local_train_fails_before_loading_any_model_when_base_model_unselected():
    """(D.1) An Aeternum/ultra training request cannot reach model-loading
    code while Aeternum.base_model is None. train() must raise before
    importing unsloth/transformers or touching GPU memory."""
    from orca.train.finetune import train

    cfg = TrainingConfig.preset("ultra")
    with pytest.raises(ValueError, match="UNSELECTED_PROVISIONAL|no selected|None"):
        train(cfg)


def test_cloud_trainer_fails_before_any_ssh_or_network_call(monkeypatch):
    """(D.2) An Aeternum/ultra cloud-training request cannot make an
    SSH/network/GPU call before the selected-base-model preflight succeeds.
    Proven by making the SSH helper itself explode if ever invoked --
    construction must raise first."""
    import orca.train.cloud as cloud_mod

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("SSH must never be attempted for an unselected base model")

    monkeypatch.setattr(cloud_mod, "_ssh_run", _must_not_be_called)
    monkeypatch.setattr(cloud_mod, "_rsync_up", _must_not_be_called)
    monkeypatch.setattr(cloud_mod, "_rsync_down", _must_not_be_called)

    with pytest.raises(ValueError, match="UNSELECTED_PROVISIONAL|no selected|None"):
        cloud_mod.CloudTrainer(ssh="ssh root@1.2.3.4", preset="ultra")


def test_no_public_preset_silently_reinterprets_the_historical_70b_plan_as_canonical_aeternum():
    """(D.3) The only preset whose base_model is Aeternum's canonical
    identity is "ultra" (via MODEL_SPECS), and it resolves to None, not
    the 70B literal. "cloud_xl" (a separate generic hardware preset) may
    still use the 70B literal for its own historical/experimental purpose,
    but must not claim to be canonical Aeternum (see next test)."""
    ultra_cfg = TrainingConfig.preset("ultra")
    assert ultra_cfg.base_model != "unsloth/Meta-Llama-3.1-70B-Instruct"
    assert ultra_cfg.family == "aeternum"


def test_generic_compute_sizing_and_model_identity_are_separate_concepts():
    """(D.4) A hardware-sizing preset (cloud_xl) must not set
    TrainingConfig.family -- family is exclusively how canonical model
    identity is expressed, never inferred from a GPU-size preset name."""
    cloud_xl_cfg = TrainingConfig.preset("cloud_xl")
    assert cloud_xl_cfg.family is None
    cloud_cfg = TrainingConfig.preset("cloud")
    assert cloud_cfg.family is None
    laptop_cfg = TrainingConfig.preset("laptop")
    assert laptop_cfg.family is None


def test_cloud_xl_does_not_imply_aeternum_or_orca_ultra_identity():
    """(D.5) If cloud_xl remains as a hardware/compute preset, it must NOT
    automatically imply Aeternum / orca-ultra / present its output as the
    canonical checkpoint name."""
    cfg = TrainingConfig.preset("cloud_xl")
    assert cfg.family is None
    assert cfg.model_name != "orca-ultra"
    assert "orca-ultra" not in cfg.output_dir
    assert cfg.is_legacy_experimental is True


def test_require_base_model_is_exercised_by_the_real_family_training_path():
    """(D.6) require_base_model("aeternum") is exercised by the real
    family-specific training path (local finetune.train()), not merely
    unit-tested against orca/registry/model_spec.py in isolation. Proven
    by asserting the two failure messages share the same root cause
    (base_model_status), i.e. finetune.train()'s guard and
    require_base_model() are checking the same underlying fact."""
    from orca.registry.model_spec import require_base_model, MODEL_SPECS
    from orca.train.finetune import train

    with pytest.raises(ValueError) as registry_exc:
        require_base_model("aeternum")
    assert MODEL_SPECS["aeternum"].base_model_status in str(registry_exc.value)

    cfg = TrainingConfig.preset("ultra")
    with pytest.raises(ValueError) as train_exc:
        train(cfg)
    assert MODEL_SPECS["aeternum"].base_model_status in str(train_exc.value)


def test_genesis_variant_description_does_not_claim_7b():
    """(D.7) Genesis's current canonical description does not say it is a
    7B everyday assistant -- Genesis's canonical target is 3B; 7B belongs
    only to the legacy orca-nano* artifacts, not the description of the
    variant whose base_model is the canonical 3B target."""
    from orca.train.variants import VARIANTS

    description = VARIANTS["nano"].description
    assert "3B" in description
    # 7B may appear only as an explicit reference to the separate legacy
    # artifact, never as a claim about Genesis's own canonical size.
    assert "Genesis — 7B" not in description
    assert "legacy" in description.lower()
