"""Model-family contracts stay inside honest statuses."""
from __future__ import annotations

import pytest

from orca.genesis.model.config import GenesisModelConfig
from orca.genesis.model.family_registry import (
    FORBIDDEN_STATUSES,
    ModelFamilyContractError,
    ModelFamilyRecord,
    assert_parameter_count,
    contract_fields,
    default_registry,
)


def test_default_registry_does_not_claim_a_trained_model():
    registry = default_registry()
    assert set(registry) == {"GENESIS", "NOVUS", "AETERNUM"}
    assert registry["GENESIS"].status == "INTERFACE_ONLY"
    assert registry["NOVUS"].status == "NOT_AVAILABLE"
    assert registry["AETERNUM"].status == "NOT_AVAILABLE"
    for record in registry.values():
        assert record.status not in FORBIDDEN_STATUSES
        assert record.checkpoint_digest is None
        assert record.training_run_id is None


@pytest.mark.parametrize("status", sorted(FORBIDDEN_STATUSES))
def test_forbidden_statuses_are_rejected(status):
    with pytest.raises(ModelFamilyContractError):
        ModelFamilyRecord(family="GENESIS", status=status, architecture_id="genesis-arch-v1")


def test_evidence_record_is_not_acceptance_and_still_needs_digests():
    with pytest.raises(ModelFamilyContractError, match="checkpoint_digest"):
        ModelFamilyRecord(family="NOVUS", status="EVIDENCE_RECORDED_NOT_ACCEPTED")
    record = ModelFamilyRecord(
        family="NOVUS",
        status="EVIDENCE_RECORDED_NOT_ACCEPTED",
        checkpoint_digest="abc",
        training_run_id="run-1",
        eval_report_digest="def",
        notes="recorded evidence is not acceptance and not a frontier claim",
    )
    assert record.status == "EVIDENCE_RECORDED_NOT_ACCEPTED"


def test_parameter_count_must_match_the_config():
    cfg = GenesisModelConfig(
        vocab_size=32, d_model=16, n_layers=1, n_heads=2, n_kv_heads=2, d_ff=32, max_seq_len=8,
    )
    assert_parameter_count(cfg, cfg.total_parameters())
    with pytest.raises(ModelFamilyContractError, match="claimed parameter count"):
        assert_parameter_count(cfg, cfg.total_parameters() + 1)


def test_each_family_publishes_its_contract_fields():
    assert "tokenizer_binding" in contract_fields("GENESIS")
    assert "tool_schema_eval" in contract_fields("NOVUS")
    assert "calibration_metric" in contract_fields("AETERNUM")
