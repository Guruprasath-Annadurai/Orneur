"""
Guards against the exact bug this module exists to fix: orca/train/variants.py
and orca/train/config.py each declared Genesis's base model independently and
silently disagreed (variants.py's docstring said Qwen2.5-3B while its code
said 7B; config.py's preset said 3B). See
docs/orneur/phase-0/GENESIS_MODEL_IDENTITY.md.
"""
from __future__ import annotations

import pytest

from orca.registry.model_spec import MODEL_SPECS, ModelSpec, LifecycleState, get_spec


def test_all_three_families_are_defined():
    assert set(MODEL_SPECS.keys()) == {"genesis", "novus", "aeternum"}


def test_genesis_canonical_future_target_is_3b():
    assert MODEL_SPECS["genesis"].parameter_class == "3B"
    assert "3B" in MODEL_SPECS["genesis"].base_model


def test_genesis_legacy_note_documents_7b_reality():
    note = MODEL_SPECS["genesis"].legacy_note
    assert "7B" in note or "7.6B" in note
    assert "orca-nano" in " ".join(MODEL_SPECS["genesis"].legacy_ollama_names)


def test_novus_base_model_is_llama_3_1_8b():
    assert MODEL_SPECS["novus"].parameter_class == "8B"
    assert "Llama-3.1-8B" in MODEL_SPECS["novus"].base_model


def test_aeternum_has_no_legacy_note_claiming_a_real_checkpoint():
    assert "no trained checkpoint" in MODEL_SPECS["aeternum"].legacy_note.lower()


def test_get_spec_resolves_aliases():
    assert get_spec("nano").family == "genesis"
    assert get_spec("core").family == "novus"
    assert get_spec("ultra").family == "aeternum"
    assert get_spec("orca-nano").family == "genesis"
    assert get_spec("orneur-genesis").family == "genesis"


def test_get_spec_rejects_unknown_family():
    with pytest.raises(ValueError):
        get_spec("not-a-real-family")


def test_variants_and_config_agree_with_model_spec():
    """
    THE regression guard: both files must resolve to MODEL_SPECS, not a
    duplicated literal, so they cannot silently diverge again.
    """
    from orca.train.variants import VARIANTS
    from orca.train.config import TrainingConfig

    for tier, family in [("nano", "genesis"), ("core", "novus"), ("ultra", "aeternum")]:
        expected = MODEL_SPECS[family].base_model
        assert VARIANTS[tier].base_model == expected, (
            f"variants.py['{tier}'] base_model diverged from MODEL_SPECS['{family}']"
        )
        assert TrainingConfig.preset(tier).base_model == expected, (
            f"config.py preset('{tier}') base_model diverged from MODEL_SPECS['{family}']"
        )


def test_model_spec_is_immutable():
    """A ModelSpec is frozen -- accidental in-place mutation must fail loudly."""
    with pytest.raises(Exception):
        MODEL_SPECS["genesis"].base_model = "something-else"


def test_lifecycle_state_enum_has_expected_values():
    expected = {
        "EXPERIMENTAL", "TRAINED", "EVALUATING", "CANDIDATE",
        "APPROVED", "PRODUCTION", "REJECTED", "RETIRED",
    }
    assert {s.value for s in LifecycleState} == expected


def test_aeternum_base_model_is_unselected_not_legacy_70b():
    """Owner Phase 16 closure correction: the old Llama-3.1-70B plan is
    legacy/stale, not the current canonical Aeternum training target.
    Aeternum's base model must be explicitly UNSELECTED (None), not
    silently defaulted to the historical 70B literal -- fail closed rather
    than let a future trainer quietly train toward a stale target."""
    spec = MODEL_SPECS["aeternum"]
    assert spec.base_model is None
    assert spec.base_model_status == "UNSELECTED_PROVISIONAL"


def test_aeternum_legacy_note_documents_70b_as_stale_not_planned():
    note = MODEL_SPECS["aeternum"].legacy_note.lower()
    assert "70b" in note
    assert "legacy" in note or "stale" in note
    assert "no trained checkpoint" in note


def test_aeternum_has_provisional_size_hypothesis_not_a_lock():
    spec = MODEL_SPECS["aeternum"]
    assert "14b" in spec.provisional_parameter_hypothesis.lower()
    assert "not" in spec.provisional_parameter_hypothesis.lower() or "provisional" in spec.provisional_parameter_hypothesis.lower()


def test_genesis_and_novus_base_models_remain_selected():
    """Only Aeternum's base model is unselected -- Genesis/Novus keep their
    real, already-in-use V1 exploration targets."""
    assert MODEL_SPECS["genesis"].base_model_status == "SELECTED"
    assert MODEL_SPECS["novus"].base_model_status == "SELECTED"
    assert MODEL_SPECS["genesis"].base_model is not None
    assert MODEL_SPECS["novus"].base_model is not None


def test_require_base_model_fails_closed_for_aeternum():
    from orca.registry.model_spec import require_base_model

    with pytest.raises(ValueError):
        require_base_model("aeternum")
    # Genesis/Novus still resolve normally.
    assert require_base_model("genesis") == MODEL_SPECS["genesis"].base_model


def test_no_family_role_implies_a_permanent_size_ceiling():
    """Roles must describe cognitive specialization, not a size tier --
    guards against the 'small/medium/large chatbot' framing the owner
    explicitly rejected."""
    for family, spec in MODEL_SPECS.items():
        role_lower = spec.role.lower()
        assert "chatbot" not in role_lower
