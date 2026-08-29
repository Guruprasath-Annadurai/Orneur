"""
Canonical Orneur model identities must be able to map to legacy installed
Ollama names during migration, but that mapping must NEVER blur the fact
that legacy orca-nano* checkpoints are 7B while the canonical future
Genesis target is 3B -- a caller resolving "orneur-genesis" must be able to
tell, from the registry entry alone, which parameter class it's actually
getting.
"""
from __future__ import annotations

from orca.registry.model_registry import ModelRegistry
from orca.registry.model_spec import MODEL_SPECS


def test_legacy_genesis_alias_is_registered_and_distinguishable_from_canonical_target(tmp_path):
    """
    This exercises the real registry state populated by
    scripts/import_historical_checkpoints.py against an isolated copy, not
    the live ~/.orca/registry/ -- confirms the *mechanism*, not this
    machine's current live data.
    """
    from orca.registry.checkpoint import CheckpointRecord

    reg = ModelRegistry(state_path=tmp_path / "state.json")
    legacy = CheckpointRecord(
        checkpoint_id="orca-nano-v7", model_id="orneur-genesis", run_id="legacy",
        step_or_epoch="unknown", base_model="unsloth/Qwen2.5-7B-Instruct",
        dataset_manifest_ids=[], training_config_summary="legacy",
        optimizer_state_available=False, scheduler_state_available=False,
        tokenizer_identity="unsloth/Qwen2.5-7B-Instruct",
        artifact_path="ollama://orca-nano-v7", artifact_checksum="x",
        legacy_ollama_name="orca-nano-v7",
    )
    reg.register(legacy, family="genesis", ollama_alias="orca-nano-v7")

    entry = reg.lookup("orca-nano-v7")
    assert entry.ollama_alias == "orca-nano-v7"
    assert legacy.base_model == "unsloth/Qwen2.5-7B-Instruct"
    assert legacy.base_model != MODEL_SPECS["genesis"].base_model  # canonical target is 3B -- must differ
    assert "7B" in MODEL_SPECS["genesis"].legacy_note


def test_canonical_genesis_target_is_3b_not_the_legacy_alias():
    spec = MODEL_SPECS["genesis"]
    assert spec.parameter_class == "3B"
    assert all(name.startswith("orca-nano") for name in spec.legacy_ollama_names)
    # The spec's own base_model must never accidentally equal a legacy 7B string.
    assert "7B" not in spec.base_model and "7b" not in spec.base_model.lower()


def test_aeternum_has_a_legacy_alias_but_it_was_never_actually_trained():
    spec = MODEL_SPECS["aeternum"]
    assert spec.legacy_ollama_names == ["orca-ultra"]
    assert "never" in spec.legacy_note.lower() or "no trained checkpoint" in spec.legacy_note.lower()
