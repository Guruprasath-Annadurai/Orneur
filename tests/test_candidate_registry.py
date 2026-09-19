"""
Phase 21B.4.10: schema validation for the Genesis candidate execution
registry (orca.eval.candidate_registry). Validates the REAL registry
file this phase produced (structural checks only -- no capability/
license/frontier-class judgment) plus synthetic invalid fixtures proving
each validation rule actually fires.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import (
    REGISTRY_SCHEMA_VERSION,
    CandidateExecutionRegistry,
    RegistrySchemaError,
)

REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs" / "orneur" / "phase-21" / "GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
)


def _valid_data() -> dict:
    return json.loads(REGISTRY_PATH.read_text())


# ── the real registry file this phase produced ────────────────────────────


def test_real_registry_file_exists_and_is_valid_json():
    assert REGISTRY_PATH.exists()
    data = _valid_data()
    assert data["schema_version"] == REGISTRY_SCHEMA_VERSION


def test_real_registry_loads_and_validates_cleanly():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    assert len(registry.deployable_candidates) == 4
    assert len(registry.controls) == 3
    assert len(registry.frontier_references) == 6


def test_real_registry_deployable_names_match_the_locked_pool():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    names = {e["canonical_candidate_name"] for e in registry.deployable_candidates}
    assert names == {"Qwen3.8-27B", "Qwen3.8-Flash-Next", "Mistral Small 4", "GLM-5.3-Flash"}


def test_real_registry_control_names_match_the_locked_set():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    names = {e["canonical_candidate_name"] for e in registry.controls}
    assert names == {"Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4"}


def test_real_registry_frontier_reference_names_match_the_registered_set():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    names = {e["reference_name"] for e in registry.frontier_references}
    assert names == {
        "DeepSeek V4.1-Flash", "GLM-5.3 (flagship)", "Mistral Large 3",
        "MiniMax M3", "Qwen3.8-Max", "Kimi K3",
    }


def test_real_registry_no_deployable_candidate_uses_a_floating_tag():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    for entry in registry.deployable_candidates:
        assert entry["exact_immutable_revision"] not in ("main", "latest", "head", "", None)
        assert len(entry["exact_immutable_revision"]) >= 20  # a real commit-ish SHA, not a short label


def test_real_registry_qwen_max_is_mutable_hosted_api_with_no_pinned_revision():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    qwen_max = next(r for r in registry.frontier_references if r["reference_name"] == "Qwen3.8-Max")
    assert qwen_max["identity_type"] == "MUTABLE_HOSTED_API"
    assert "NOT_AVAILABLE" in qwen_max["exact_immutable_revision"]


def test_real_registry_find_deployable_and_eligible_helpers():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    qwen27b = registry.find_deployable("Qwen3.8-27B")
    assert qwen27b["organization"] == "Alibaba"
    with pytest.raises(KeyError):
        registry.find_deployable("does-not-exist")

    eligible = registry.eligible_for_runtime_smoke()
    assert all(e["stage0_status"] == "ELIGIBLE_FOR_RUNTIME_SMOKE" for e in eligible)
    assert any(e["canonical_candidate_name"] == "Qwen3.8-27B" for e in eligible)


# ── synthetic invalid fixtures proving each validation rule fires ────────


def test_unsupported_schema_version_rejected():
    data = _valid_data()
    data["schema_version"] = "some-other-version-v99"
    with pytest.raises(RegistrySchemaError, match="Unsupported"):
        CandidateExecutionRegistry.from_dict(data)


def test_missing_required_deployable_field_rejected():
    data = _valid_data()
    del data["deployable_candidates"][0]["license_identifier"]
    with pytest.raises(RegistrySchemaError, match="missing required field"):
        CandidateExecutionRegistry.from_dict(data)


def test_unrecognized_stage0_status_rejected():
    data = _valid_data()
    data["deployable_candidates"][0]["stage0_status"] = "TOTALLY_MADE_UP_STATUS"
    with pytest.raises(RegistrySchemaError, match="unrecognized"):
        CandidateExecutionRegistry.from_dict(data)


def test_floating_tag_revision_rejected_for_deployable_candidate():
    data = _valid_data()
    data["deployable_candidates"][0]["exact_immutable_revision"] = "main"
    with pytest.raises(RegistrySchemaError, match="non-pinned"):
        CandidateExecutionRegistry.from_dict(data)


def test_floating_tag_revision_rejected_for_control():
    data = _valid_data()
    data["controls"][0]["exact_immutable_revision"] = "latest"
    with pytest.raises(RegistrySchemaError, match="non-pinned"):
        CandidateExecutionRegistry.from_dict(data)


def test_unrecognized_identity_type_rejected():
    data = _valid_data()
    data["frontier_references"][0]["identity_type"] = "SOMETHING_ELSE"
    with pytest.raises(RegistrySchemaError, match="unrecognized"):
        CandidateExecutionRegistry.from_dict(data)


def test_mutable_api_reference_with_fake_pinned_revision_rejected():
    data = _valid_data()
    qwen_max = next(r for r in data["frontier_references"] if r["reference_name"] == "Qwen3.8-Max")
    qwen_max["exact_immutable_revision"] = "a" * 40  # looks pinned, but this is a mutable API entry
    with pytest.raises(RegistrySchemaError, match="mutable hosted API"):
        CandidateExecutionRegistry.from_dict(data)


def test_open_weight_reference_missing_revision_rejected():
    data = _valid_data()
    deepseek = next(r for r in data["frontier_references"] if r["reference_name"] == "DeepSeek V4.1-Flash")
    deepseek["exact_immutable_revision"] = "NOT_AVAILABLE"
    with pytest.raises(RegistrySchemaError, match="OPEN_WEIGHT"):
        CandidateExecutionRegistry.from_dict(data)


def test_unrecognized_availability_status_rejected():
    data = _valid_data()
    data["frontier_references"][0]["availability_status"] = "MADE_UP_STATUS"
    with pytest.raises(RegistrySchemaError, match="unrecognized"):
        CandidateExecutionRegistry.from_dict(data)


def test_missing_top_level_list_field_rejected():
    data = _valid_data()
    del data["controls"]
    with pytest.raises(RegistrySchemaError, match="controls"):
        CandidateExecutionRegistry.from_dict(data)
