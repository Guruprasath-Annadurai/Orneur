"""
Phase 21B.4.10/.10.1: schema validation for the Genesis candidate
execution registry (orca.eval.candidate_registry). Validates the REAL
registry file this phase produced (structural checks only -- no
capability/license/frontier-class judgment) plus synthetic invalid
fixtures proving each validation rule actually fires.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import (
    EXPECTED_CONTROL_NAMES,
    EXPECTED_DEPLOYABLE_NAMES,
    EXPECTED_REFERENCE_NAMES,
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


def _deployable(data: dict, name: str) -> dict:
    return next(e for e in data["deployable_candidates"] if e["canonical_candidate_name"] == name)


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
    assert names == EXPECTED_DEPLOYABLE_NAMES


def test_real_registry_control_names_match_the_locked_set():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    names = {e["canonical_candidate_name"] for e in registry.controls}
    assert names == EXPECTED_CONTROL_NAMES


def test_real_registry_frontier_reference_names_match_the_registered_set():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    names = {e["reference_name"] for e in registry.frontier_references}
    assert names == EXPECTED_REFERENCE_NAMES


def test_real_registry_no_deployable_candidate_uses_a_floating_tag():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    for entry in registry.deployable_candidates:
        assert entry["exact_immutable_revision"] not in ("main", "latest", "head", "", None)
        assert len(entry["exact_immutable_revision"]) == 40


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
    names = {e["canonical_candidate_name"] for e in eligible}
    assert names == {"Qwen3.8-27B", "Mistral Small 4", "GLM-5.3-Flash"}


def test_real_registry_qwen_flash_next_is_blocked_by_license():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    flash_next = registry.find_deployable("Qwen3.8-Flash-Next")
    assert flash_next["license_status"] == "LICENSE_REVIEW_REQUIRED"
    assert flash_next["runtime_smoke_eligibility"] == "BLOCKED"
    assert flash_next["runtime_smoke_blocked_reason"]


def test_real_registry_runtime_unqualified_candidates_are_still_eligible():
    """The Phase 21B.4.10.1 fix in one assertion: runtime_qualification_
    status=UNQUALIFIED must never, by itself, block runtime_smoke_
    eligibility -- that would make runtime qualification unresolvable."""
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    for name in ("Qwen3.8-27B", "Mistral Small 4", "GLM-5.3-Flash"):
        entry = registry.find_deployable(name)
        assert entry["runtime_qualification_status"] == "UNQUALIFIED"
        assert entry["runtime_smoke_eligibility"] == "ELIGIBLE"


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


def test_floating_tag_revision_rejected_for_deployable_candidate():
    data = _valid_data()
    data["deployable_candidates"][0]["exact_immutable_revision"] = "main"
    with pytest.raises(RegistrySchemaError, match="not a well-formed"):
        CandidateExecutionRegistry.from_dict(data)


def test_short_non_hex_revision_rejected():
    data = _valid_data()
    data["deployable_candidates"][0]["exact_immutable_revision"] = "abc123"
    with pytest.raises(RegistrySchemaError, match="not a well-formed"):
        CandidateExecutionRegistry.from_dict(data)


def test_floating_tag_revision_rejected_for_control():
    data = _valid_data()
    data["controls"][0]["exact_immutable_revision"] = "latest"
    with pytest.raises(RegistrySchemaError, match="not a well-formed"):
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
    with pytest.raises(RegistrySchemaError, match="not a well-formed"):
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


def test_wrong_deployable_candidate_count_rejected():
    data = _valid_data()
    del data["deployable_candidates"][0]
    with pytest.raises(RegistrySchemaError, match="do not exactly match"):
        CandidateExecutionRegistry.from_dict(data)


def test_unrecognized_deployable_candidate_name_rejected():
    data = _valid_data()
    data["deployable_candidates"][0]["canonical_candidate_name"] = "Some Fabricated Model"
    with pytest.raises(RegistrySchemaError, match="do not exactly match"):
        CandidateExecutionRegistry.from_dict(data)


def test_duplicate_deployable_candidate_name_rejected():
    data = _valid_data()
    dup = copy.deepcopy(data["deployable_candidates"][0])
    data["deployable_candidates"][1] = dup  # collide with entry[0]'s name, drop entry[1]'s real name
    with pytest.raises(RegistrySchemaError):
        CandidateExecutionRegistry.from_dict(data)


def test_wrong_control_count_rejected():
    data = _valid_data()
    del data["controls"][0]
    with pytest.raises(RegistrySchemaError, match="do not exactly match"):
        CandidateExecutionRegistry.from_dict(data)


def test_wrong_reference_count_rejected():
    data = _valid_data()
    del data["frontier_references"][0]
    with pytest.raises(RegistrySchemaError, match="do not exactly match"):
        CandidateExecutionRegistry.from_dict(data)


# ── runtime_smoke_eligibility structural invariants (Phase 21B.4.10.1) ──


def test_license_review_required_forces_blocked_eligibility():
    data = _valid_data()
    entry = _deployable(data, "Qwen3.8-27B")  # currently CLEAR/ELIGIBLE
    entry["license_status"] = "LICENSE_REVIEW_REQUIRED"
    entry["runtime_smoke_eligibility"] = "ELIGIBLE"  # contradicts the license status
    with pytest.raises(RegistrySchemaError, match="must block runtime smoke eligibility"):
        CandidateExecutionRegistry.from_dict(data)


def test_unresolved_identity_forces_blocked_eligibility():
    data = _valid_data()
    entry = _deployable(data, "Qwen3.8-27B")
    entry["identity_status"] = "IDENTITY_UNRESOLVED"
    entry["runtime_smoke_eligibility"] = "ELIGIBLE"
    with pytest.raises(RegistrySchemaError, match="must block runtime smoke eligibility"):
        CandidateExecutionRegistry.from_dict(data)


def test_resolved_identity_and_clear_license_forces_eligible():
    data = _valid_data()
    entry = _deployable(data, "Qwen3.8-27B")  # identity RESOLVED, license CLEAR
    entry["runtime_smoke_eligibility"] = "BLOCKED"
    entry["runtime_smoke_blocked_reason"] = "arbitrary reason that should not be allowed to force BLOCKED"
    with pytest.raises(RegistrySchemaError, match="must never, by itself, block eligibility"):
        CandidateExecutionRegistry.from_dict(data)


def test_blocked_without_reason_rejected():
    data = _valid_data()
    entry = _deployable(data, "Qwen3.8-Flash-Next")  # legitimately BLOCKED
    entry["runtime_smoke_blocked_reason"] = None
    with pytest.raises(RegistrySchemaError, match="no runtime_smoke_blocked_reason"):
        CandidateExecutionRegistry.from_dict(data)


def test_unrecognized_runtime_smoke_eligibility_value_rejected():
    data = _valid_data()
    entry = _deployable(data, "Qwen3.8-27B")
    entry["runtime_smoke_eligibility"] = "MAYBE"
    with pytest.raises(RegistrySchemaError, match="unrecognized runtime_smoke_eligibility"):
        CandidateExecutionRegistry.from_dict(data)


# ── Phase 21B.4.11 §5A: candidate_class, tokenizer_revision, cross-wiring ──


def test_deployable_wrong_candidate_class_rejected():
    data = _valid_data()
    entry = _deployable(data, "Qwen3.8-27B")
    entry["candidate_class"] = "CONTROL_SMALL_BASELINE"  # a control's class, wrongly applied
    with pytest.raises(RegistrySchemaError, match="candidate_class"):
        CandidateExecutionRegistry.from_dict(data)


def test_control_wrong_candidate_class_rejected():
    data = _valid_data()
    data["controls"][0]["candidate_class"] = "DEPLOYABLE_GENESIS_FOUNDATION_CANDIDATE"
    with pytest.raises(RegistrySchemaError, match="candidate_class"):
        CandidateExecutionRegistry.from_dict(data)


def test_deployable_malformed_tokenizer_revision_rejected():
    data = _valid_data()
    entry = _deployable(data, "Qwen3.8-27B")
    entry["tokenizer_revision"] = "not-a-real-revision"
    with pytest.raises(RegistrySchemaError, match="tokenizer_revision"):
        CandidateExecutionRegistry.from_dict(data)


def test_control_malformed_tokenizer_revision_rejected():
    data = _valid_data()
    data["controls"][0]["tokenizer_revision"] = "abc123"
    with pytest.raises(RegistrySchemaError, match="tokenizer_revision"):
        CandidateExecutionRegistry.from_dict(data)


def test_duplicate_artifact_repository_across_deployable_and_control_rejected():
    """Simulates a wiring bug: a control accidentally claims the same
    artifact_repository as a deployable candidate."""
    data = _valid_data()
    qwen27b_repo = _deployable(data, "Qwen3.8-27B")["artifact_repository"]
    data["controls"][0]["artifact_repository"] = qwen27b_repo
    with pytest.raises(RegistrySchemaError, match="cross-wired"):
        CandidateExecutionRegistry.from_dict(data)


def test_duplicate_artifact_repository_across_two_deployables_rejected():
    data = _valid_data()
    repo_a = data["deployable_candidates"][0]["artifact_repository"]
    data["deployable_candidates"][1]["artifact_repository"] = repo_a
    with pytest.raises(RegistrySchemaError, match="cross-wired"):
        CandidateExecutionRegistry.from_dict(data)
