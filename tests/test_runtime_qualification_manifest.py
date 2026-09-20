"""
Phase 21B.4.11.1/.2: tests for the versioned, fail-closed Genesis
Runtime Qualification Manifest schema
(orca.eval.runtime_qualification_manifest). All synthetic fixtures here
are fabricated test data -- no real candidate execution is performed by
this file. The exception is test_real_qwen_manifest_* /
test_registry_*, which validate the actual committed Qwen3.8-27B
manifest (the one narrow LEGACY_RECONCILED_V1 exception) and its digest
linkage from the real registry.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import (
    CandidateExecutionRegistry,
    RegistrySchemaError,
    verify_qualified_manifest_linkage,
)
from orca.eval.runtime_qualification_manifest import (
    EVIDENCE_BEARING_FIELDS,
    EVIDENCE_PROTOCOL_LEGACY,
    EVIDENCE_PROTOCOL_STRICT,
    MANIFEST_SCHEMA_VERSION,
    RuntimeQualificationManifestError,
    canonical_json_bytes,
    load_manifest,
    require_candidate_manifest,
    sha256_of_manifest,
    validate_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
QWEN_MANIFEST_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_RUNTIME_QUALIFICATION_MANIFEST_QWEN3_8_27B.json"

_VALID_HEX40 = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
_VALID_HEX64 = "a" * 64


def _base_manifest() -> dict:
    """A fully-populated manifest missing only evidence_protocol_generation
    -specific fields (raw log / execution_time / created_at format),
    which the strict/legacy builders below fill in differently."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "qualification_id": "test-fixture-2026-01-01",
        "candidate": "Test-Candidate",
        "artifact_repository": "Org/Test-Candidate",
        "exact_revision": _VALID_HEX40,
        "tokenizer_repository": "Org/Test-Candidate",
        "tokenizer_revision": _VALID_HEX40,
        "license_identifier": "apache-2.0",
        "qualification_type": "RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
        "runtime": "native-transformers",
        "runtime_versions": {"transformers": "5.17.0"},
        "python_version": "3.11",
        "pytorch_version": "2.14.0",
        "cuda_version": "NOT_CAPTURED",
        "transformers_version": "5.17.0",
        "trust_remote_code": True,
        "gpu_provider": "Modal",
        "gpu_model": "NVIDIA H200",
        "gpu_count": 1,
        "precision": "BF16",
        "vram_capacity_gb": 141,
        "peak_allocated_vram_gb": 10.0,
        "peak_reserved_vram_gb": 10.0,
        "weight_file_shards": 5,
        "runtime_materialized_tensor_count": 100,
        "load_attempt_count": 1,
        "attempt_1_result": "SUCCEEDED",
        "attempt_1_failure_class": None,
        "attempt_2_result": "NOT_ATTEMPTED",
        "attempt_2_failure_class": None,
        "load_time_seconds": 10.0,
        "synthetic_prompt_class": "TRIVIAL_SYNTHETIC_NON_BENCHMARK",
        "synthetic_prompt_sha256": _VALID_HEX64,
        "decoded_response_sha256": _VALID_HEX64,
        "input_tokens": 5,
        "output_tokens": 5,
        "generation_latency_seconds": 1.0,
        "ttft_seconds": "NOT_CAPTURED",
        "tokens_per_second": 5.0,
        "benchmark_prompt_exposed": False,
        "genesis_eval_executed": False,
        "generated_output_executed": False,
        "persistent_volume_used": False,
        "metered_before_usd": 0.0,
        "metered_after_usd": 0.1,
        "metered_delta_usd": 0.1,
        "billed_before_usd": 0.0,
        "billed_after_usd": 0.0,
        "owner_billed_delta_usd": 0.0,
        "cleanup_status": "CONFIRMED_ZERO_ACTIVE_RESOURCES",
        "active_resources_after": "NONE",
        "source_repo_sha": "0" * 40,
        "billing_gate_reconciliation": {
            "billing_gate_at_time_of_execution": "NOT_INDEPENDENTLY_PROVEN",
            "owner_billed_result": "$0.00 REPORTED",
            "financial_impact": "NO_OWNER_CHARGE_OBSERVED",
        },
        "evidence_strength": {field: "REPORTED_BY_CLAUDE" for field in EVIDENCE_BEARING_FIELDS},
    }


def _legacy_manifest() -> dict:
    data = _base_manifest()
    data["evidence_protocol_generation"] = EVIDENCE_PROTOCOL_LEGACY
    data["created_at"] = "2026-01-01"
    data["execution_time"] = "NOT_CAPTURED"
    data["raw_execution_log_artifact"] = "NOT_PRESERVED"
    return data


def _strict_manifest() -> dict:
    data = _base_manifest()
    data["evidence_protocol_generation"] = EVIDENCE_PROTOCOL_STRICT
    data["created_at"] = "2026-01-01T12:00:00+00:00"
    data["execution_time"] = "2026-01-01T12:00:00+00:00"
    data["raw_execution_log_artifact"] = "docs/orneur/phase-21/logs/test-fixture-log.txt"
    data["raw_execution_log_sha256"] = _VALID_HEX64
    return data


# Backwards-compatible default fixture name used throughout this file.
_valid_manifest = _legacy_manifest


def test_valid_legacy_manifest_passes():
    validate_manifest(_legacy_manifest())  # must not raise


def test_valid_strict_manifest_passes():
    validate_manifest(_strict_manifest())  # must not raise


def test_wrong_schema_version_rejected():
    data = _valid_manifest()
    data["schema_version"] = "some-other-version"
    with pytest.raises(RuntimeQualificationManifestError, match="Unsupported"):
        validate_manifest(data)


def test_missing_required_field_rejected():
    data = _valid_manifest()
    del data["gpu_model"]
    with pytest.raises(RuntimeQualificationManifestError, match="missing required field"):
        validate_manifest(data)


def test_malformed_exact_revision_rejected():
    data = _valid_manifest()
    data["exact_revision"] = "not-hex"
    with pytest.raises(RuntimeQualificationManifestError, match="exact_revision"):
        validate_manifest(data)


def test_malformed_tokenizer_revision_rejected():
    data = _valid_manifest()
    data["tokenizer_revision"] = "abc123"
    with pytest.raises(RuntimeQualificationManifestError, match="tokenizer_revision"):
        validate_manifest(data)


def test_unrecognized_qualification_type_rejected():
    data = _valid_manifest()
    data["qualification_type"] = "FRONTIER_CLASS"
    with pytest.raises(RuntimeQualificationManifestError, match="qualification_type"):
        validate_manifest(data)


def test_malformed_prompt_hash_rejected():
    data = _valid_manifest()
    data["synthetic_prompt_sha256"] = "too-short"
    with pytest.raises(RuntimeQualificationManifestError, match="synthetic_prompt_sha256"):
        validate_manifest(data)


def test_malformed_response_hash_rejected():
    data = _valid_manifest()
    data["decoded_response_sha256"] = "not64hexchars"
    with pytest.raises(RuntimeQualificationManifestError, match="decoded_response_sha256"):
        validate_manifest(data)


def test_unrecognized_attempt_result_rejected():
    data = _valid_manifest()
    data["attempt_1_result"] = "MAYBE"
    with pytest.raises(RuntimeQualificationManifestError, match="attempt_1_result"):
        validate_manifest(data)


@pytest.mark.parametrize(
    "field", ["benchmark_prompt_exposed", "genesis_eval_executed", "generated_output_executed"]
)
def test_benchmark_execution_fields_must_be_false(field):
    data = _valid_manifest()
    data[field] = True
    with pytest.raises(RuntimeQualificationManifestError, match=field):
        validate_manifest(data)


def test_nonzero_owner_billed_delta_rejected():
    data = _valid_manifest()
    data["owner_billed_delta_usd"] = 1.23
    with pytest.raises(RuntimeQualificationManifestError, match="owner_billed_delta_usd"):
        validate_manifest(data)


def test_persistent_volume_used_must_be_false():
    data = _valid_manifest()
    data["persistent_volume_used"] = True
    with pytest.raises(RuntimeQualificationManifestError, match="persistent_volume_used"):
        validate_manifest(data)


def test_unrecognized_evidence_strength_value_rejected():
    data = _valid_manifest()
    data["evidence_strength"]["exact_revision"] = "TOTALLY_MADE_UP"
    with pytest.raises(RuntimeQualificationManifestError, match="evidence_strength"):
        validate_manifest(data)


def test_empty_evidence_strength_rejected():
    data = _valid_manifest()
    data["evidence_strength"] = {}
    with pytest.raises(RuntimeQualificationManifestError, match="evidence_strength"):
        validate_manifest(data)


def test_incomplete_evidence_strength_map_rejected():
    """Phase 21B.4.11.2 §3/§10: a manifest with provenance tags for only
    a subset of the evidence-bearing fields must fail, not silently pass."""
    data = _valid_manifest()
    data["evidence_strength"] = {"exact_revision": "REPOSITORY_VERIFIED"}
    with pytest.raises(RuntimeQualificationManifestError, match="evidence_strength must cover exactly"):
        validate_manifest(data)


def test_evidence_strength_with_extra_unknown_field_rejected():
    data = _valid_manifest()
    data["evidence_strength"]["not_a_real_field"] = "OBSERVED_LIVE"
    with pytest.raises(RuntimeQualificationManifestError, match="evidence_strength must cover exactly"):
        validate_manifest(data)


def test_billing_gate_reconciliation_requires_subfields():
    data = _valid_manifest()
    data["billing_gate_reconciliation"] = {"owner_billed_result": "$0.00 REPORTED"}
    with pytest.raises(RuntimeQualificationManifestError, match="missing required field"):
        validate_manifest(data)


# ── Phase 21B.4.11.2 §1/§2: protocol generation + durable log rules ─────


def test_strict_manifest_without_durable_log_rejected():
    data = _strict_manifest()
    data["raw_execution_log_artifact"] = "NOT_PRESERVED"
    with pytest.raises(RuntimeQualificationManifestError, match="STRICT_RUNTIME_SMOKE_V2 requires a durably"):
        validate_manifest(data)


@pytest.mark.parametrize("bad_value", [None, "", "NONE"])
def test_strict_manifest_with_empty_log_artifact_rejected(bad_value):
    data = _strict_manifest()
    data["raw_execution_log_artifact"] = bad_value
    with pytest.raises(RuntimeQualificationManifestError, match="STRICT_RUNTIME_SMOKE_V2 requires a durably"):
        validate_manifest(data)


def test_strict_manifest_with_malformed_log_hash_rejected():
    data = _strict_manifest()
    data["raw_execution_log_sha256"] = "too-short"
    with pytest.raises(RuntimeQualificationManifestError, match="raw_execution_log_sha256"):
        validate_manifest(data)


def test_strict_manifest_missing_log_hash_rejected():
    data = _strict_manifest()
    del data["raw_execution_log_sha256"]
    with pytest.raises(RuntimeQualificationManifestError, match="raw_execution_log_sha256"):
        validate_manifest(data)


def test_strict_manifest_with_not_captured_execution_time_rejected():
    data = _strict_manifest()
    data["execution_time"] = "NOT_CAPTURED"
    with pytest.raises(RuntimeQualificationManifestError, match="execution_time to be an actual captured"):
        validate_manifest(data)


def test_strict_manifest_with_non_timezone_aware_timestamp_rejected():
    data = _strict_manifest()
    data["created_at"] = "2026-01-01T12:00:00"  # naive -- no tzinfo
    with pytest.raises(RuntimeQualificationManifestError, match="timezone-aware"):
        validate_manifest(data)


def test_legacy_manifest_allows_bare_date_created_at():
    data = _legacy_manifest()
    data["created_at"] = "2026-01-01"
    validate_manifest(data)  # must not raise


def test_legacy_manifest_with_not_preserved_log_still_valid():
    data = _legacy_manifest()
    validate_manifest(data)  # must not raise -- the one grandfathered exception


def test_unrecognized_evidence_protocol_generation_rejected():
    data = _valid_manifest()
    data["evidence_protocol_generation"] = "SOME_FUTURE_V3"
    with pytest.raises(RuntimeQualificationManifestError, match="evidence_protocol_generation"):
        validate_manifest(data)


# ── Phase 21B.4.11.2 §5: numeric/cross-field integrity ───────────────────


def test_nan_numeric_value_rejected():
    data = _valid_manifest()
    data["load_time_seconds"] = float("nan")
    with pytest.raises(RuntimeQualificationManifestError, match="finite"):
        validate_manifest(data)


def test_inf_numeric_value_rejected():
    data = _valid_manifest()
    data["peak_allocated_vram_gb"] = float("inf")
    with pytest.raises(RuntimeQualificationManifestError, match="finite"):
        validate_manifest(data)


def test_bool_used_as_numeric_value_rejected():
    data = _valid_manifest()
    data["load_time_seconds"] = True
    with pytest.raises(RuntimeQualificationManifestError, match="real number"):
        validate_manifest(data)


def test_negative_metered_value_rejected():
    data = _valid_manifest()
    data["metered_before_usd"] = -0.01
    with pytest.raises(RuntimeQualificationManifestError, match="metered_before_usd"):
        validate_manifest(data)


def test_zero_or_negative_vram_capacity_rejected():
    data = _valid_manifest()
    data["vram_capacity_gb"] = 0
    with pytest.raises(RuntimeQualificationManifestError, match="vram_capacity_gb"):
        validate_manifest(data)


def test_gpu_count_below_one_rejected():
    data = _valid_manifest()
    data["gpu_count"] = 0
    with pytest.raises(RuntimeQualificationManifestError, match="gpu_count"):
        validate_manifest(data)


def test_inconsistent_metered_delta_rejected():
    data = _valid_manifest()
    data["metered_before_usd"] = 0.0
    data["metered_after_usd"] = 1.0
    data["metered_delta_usd"] = 0.5  # should be 1.0
    with pytest.raises(RuntimeQualificationManifestError, match="metered_delta_usd"):
        validate_manifest(data)


def test_nonzero_billed_before_rejected():
    data = _valid_manifest()
    data["billed_before_usd"] = 0.01
    data["billed_after_usd"] = 0.01  # keep the delta arithmetic consistent (==0) so only the >0 check fires
    data["owner_billed_delta_usd"] = 0.0
    with pytest.raises(RuntimeQualificationManifestError, match="billed_before_usd"):
        validate_manifest(data)


def test_nonzero_billed_after_rejected():
    data = _valid_manifest()
    data["billed_after_usd"] = 0.01
    data["owner_billed_delta_usd"] = data["billed_after_usd"] - data["billed_before_usd"]
    with pytest.raises(RuntimeQualificationManifestError, match="billed_after_usd|owner_billed_delta_usd"):
        validate_manifest(data)


def test_inconsistent_owner_billed_delta_rejected():
    data = _valid_manifest()
    data["billed_before_usd"] = 0.0
    data["billed_after_usd"] = 0.0
    data["owner_billed_delta_usd"] = 0.5  # arithmetic says it should be 0
    with pytest.raises(RuntimeQualificationManifestError, match="owner_billed_delta_usd"):
        validate_manifest(data)


# ── Phase 21B.4.11.2 §6: attempt-state consistency ───────────────────────


def test_attempt_count_one_requires_attempt_2_not_attempted():
    data = _valid_manifest()
    data["load_attempt_count"] = 1
    data["attempt_2_result"] = "SUCCEEDED"
    with pytest.raises(RuntimeQualificationManifestError, match="load_attempt_count==1"):
        validate_manifest(data)


def test_attempt_count_two_requires_attempt_2_not_not_attempted():
    data = _valid_manifest()
    data["load_attempt_count"] = 2
    data["attempt_1_result"] = "FAILED"
    data["attempt_1_failure_class"] = "OTHER"
    data["attempt_2_result"] = "NOT_ATTEMPTED"
    with pytest.raises(RuntimeQualificationManifestError, match="load_attempt_count>=2"):
        validate_manifest(data)


def test_qualified_result_with_no_successful_attempt_rejected():
    data = _valid_manifest()
    data["attempt_1_result"] = "FAILED"
    data["attempt_1_failure_class"] = "OTHER"
    data["qualification_type"] = "RUNTIME_LOAD_COMPATIBILITY_QUALIFIED"
    with pytest.raises(RuntimeQualificationManifestError, match="at least one attempt to have SUCCEEDED"):
        validate_manifest(data)


def test_failed_qualification_type_with_successful_attempt_rejected():
    data = _valid_manifest()
    data["qualification_type"] = "RUNTIME_QUALIFICATION_FAILED"
    data["attempt_1_result"] = "SUCCEEDED"  # contradicts a FAILED qualification
    # A FAILED-type manifest is not itself required to satisfy the
    # QUALIFIED-only cleanup/active-resource invariants, so this
    # fixture only needs to be internally consistent enough to reach
    # the attempt-state check.
    with pytest.raises(RuntimeQualificationManifestError, match="RUNTIME_QUALIFICATION_FAILED must not"):
        validate_manifest(data)


def test_failed_attempt_without_failure_class_rejected():
    data = _valid_manifest()
    # Use a FAILED qualification_type so the "at least one SUCCEEDED
    # attempt" invariant for QUALIFIED types doesn't fire first --
    # isolates the failure-class-required-on-FAILED check.
    data["qualification_type"] = "RUNTIME_QUALIFICATION_FAILED"
    data["attempt_1_result"] = "FAILED"
    data["attempt_1_failure_class"] = None
    with pytest.raises(RuntimeQualificationManifestError, match="attempt_1_failure_class"):
        validate_manifest(data)


def test_successful_attempt_with_contradictory_failure_class_rejected():
    data = _valid_manifest()
    data["attempt_1_result"] = "SUCCEEDED"
    data["attempt_1_failure_class"] = "MODEL_LOAD_OOM"
    with pytest.raises(RuntimeQualificationManifestError, match="must not carry a failure classification"):
        validate_manifest(data)


# ── Phase 21B.4.11.2 §7: QUALIFIED result invariants ─────────────────────


def test_qualified_result_with_nonzero_active_resources_rejected():
    data = _valid_manifest()
    data["active_resources_after"] = "1 GPU container still running"
    with pytest.raises(RuntimeQualificationManifestError, match="active_resources_after to indicate NONE"):
        validate_manifest(data)


def test_qualified_result_without_confirmed_cleanup_rejected():
    data = _valid_manifest()
    data["cleanup_status"] = "UNKNOWN"
    with pytest.raises(RuntimeQualificationManifestError, match="cleanup_status"):
        validate_manifest(data)


# ── Phase 21B.4.11.2 §8: source_repo_sha / timestamp format ──────────────


def test_malformed_source_repo_sha_rejected():
    data = _valid_manifest()
    data["source_repo_sha"] = "not-a-sha"
    with pytest.raises(RuntimeQualificationManifestError, match="source_repo_sha"):
        validate_manifest(data)


# ── canonical digest ──────────────────────────────────────────────────


def test_canonical_digest_is_deterministic_regardless_of_key_order():
    data = _valid_manifest()
    reordered = dict(reversed(list(data.items())))
    assert sha256_of_manifest(data) == sha256_of_manifest(reordered)


def test_canonical_digest_changes_if_content_changes():
    data = _valid_manifest()
    mutated = copy.deepcopy(data)
    mutated["load_time_seconds"] = 5.0
    mutated["metered_after_usd"] = 0.15
    mutated["metered_delta_usd"] = 0.15
    assert sha256_of_manifest(data) != sha256_of_manifest(mutated)


def test_canonical_json_bytes_has_no_whitespace_padding():
    data = _valid_manifest()
    raw = canonical_json_bytes(data)
    assert b": " not in raw
    assert b", " not in raw


# ── require_candidate_manifest ───────────────────────────────────────


def test_require_candidate_manifest_accepts_matching_candidate():
    data = _valid_manifest()
    require_candidate_manifest(
        data,
        candidate="Test-Candidate",
        repository="Org/Test-Candidate",
        revision=_VALID_HEX40,
        qualification_type="RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
    )  # must not raise


def test_require_candidate_manifest_rejects_wrong_candidate():
    data = _valid_manifest()
    with pytest.raises(RuntimeQualificationManifestError, match="candidate"):
        require_candidate_manifest(
            data,
            candidate="Different-Candidate",
            repository="Org/Test-Candidate",
            revision=_VALID_HEX40,
            qualification_type="RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
        )


def test_require_candidate_manifest_rejects_wrong_repository():
    data = _valid_manifest()
    with pytest.raises(RuntimeQualificationManifestError, match="artifact_repository"):
        require_candidate_manifest(
            data,
            candidate="Test-Candidate",
            repository="Org/Different-Repo",
            revision=_VALID_HEX40,
            qualification_type="RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
        )


def test_require_candidate_manifest_rejects_wrong_revision():
    data = _valid_manifest()
    with pytest.raises(RuntimeQualificationManifestError, match="exact_revision"):
        require_candidate_manifest(
            data,
            candidate="Test-Candidate",
            repository="Org/Test-Candidate",
            revision="0" * 40,
            qualification_type="RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
        )


def test_require_candidate_manifest_rejects_wrong_qualification_type():
    data = _valid_manifest()
    with pytest.raises(RuntimeQualificationManifestError, match="qualification_type"):
        require_candidate_manifest(
            data,
            candidate="Test-Candidate",
            repository="Org/Test-Candidate",
            revision=_VALID_HEX40,
            qualification_type="PRODUCTION_SERVING_RUNTIME_QUALIFIED",
        )


# ── the real, committed Qwen3.8-27B manifest + registry linkage ─────────


def test_real_qwen_manifest_validates():
    data = load_manifest(QWEN_MANIFEST_PATH)  # raises on any structural violation
    require_candidate_manifest(
        data,
        candidate="Qwen3.8-27B",
        repository="Qwen/Qwen3.8-27B",
        revision="1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
        qualification_type="RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
    )


def test_real_qwen_manifest_is_explicitly_legacy_grandfathered():
    data = load_manifest(QWEN_MANIFEST_PATH)
    assert data["evidence_protocol_generation"] == EVIDENCE_PROTOCOL_LEGACY
    assert data["raw_execution_log_artifact"].startswith("NOT_PRESERVED")
    assert data["execution_time"] == "NOT_CAPTURED"


def test_real_qwen_manifest_billing_gate_not_overclaimed():
    data = load_manifest(QWEN_MANIFEST_PATH)
    gate = data["billing_gate_reconciliation"]
    assert gate["billing_gate_at_time_of_execution"] == "NOT_INDEPENDENTLY_PROVEN"
    assert data["owner_billed_delta_usd"] == 0
    assert data["billed_before_usd"] == 0
    assert data["billed_after_usd"] == 0


def test_real_qwen_manifest_shard_terminology_corrected():
    data = load_manifest(QWEN_MANIFEST_PATH)
    assert data["weight_file_shards"] == 18
    assert data["runtime_materialized_tensor_count"] == 1184


def test_registry_no_longer_calls_1184_a_shard_count():
    registry_text = REGISTRY_PATH.read_text()
    assert "1184 weight shards" not in registry_text


def test_registry_qwen_entry_links_manifest_by_matching_digest():
    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(
        e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B"
    )
    manifest_path = REPO_ROOT / qwen["qualification_manifest_path"]
    manifest_data = load_manifest(manifest_path)
    assert sha256_of_manifest(manifest_data) == qwen["qualification_manifest_digest_sha256"]
    assert qwen["qualification_type"] == manifest_data["qualification_type"] == "RUNTIME_LOAD_COMPATIBILITY_QUALIFIED"


def test_registry_still_validates_with_manifest_linkage_fields():
    CandidateExecutionRegistry.load(str(REGISTRY_PATH))  # must not raise


def test_registry_manifest_linkage_enforced_with_manifest_root():
    CandidateExecutionRegistry.load(str(REGISTRY_PATH), manifest_root=REPO_ROOT)  # must not raise


# ── Phase 21B.4.11.2 §4/§10: generic registry -> manifest enforcement ────


def _qwen_entry() -> dict:
    registry_data = json.loads(REGISTRY_PATH.read_text())
    return next(
        e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B"
    )


def test_unqualified_candidate_needs_no_manifest():
    entry = {"canonical_candidate_name": "Something-Unqualified", "runtime_qualification_status": "UNQUALIFIED"}
    verify_qualified_manifest_linkage(entry, REPO_ROOT)  # must not raise -- returns immediately


def test_qualified_candidate_without_manifest_path_rejected():
    entry = _qwen_entry()
    del entry["qualification_manifest_path"]
    with pytest.raises(RegistrySchemaError, match="qualification_manifest_path"):
        verify_qualified_manifest_linkage(entry, REPO_ROOT)


def test_qualified_candidate_with_malformed_digest_rejected():
    entry = _qwen_entry()
    entry["qualification_manifest_digest_sha256"] = "not-hex"
    with pytest.raises(RegistrySchemaError, match="malformed qualification_manifest_digest_sha256"):
        verify_qualified_manifest_linkage(entry, REPO_ROOT)


def test_qualified_candidate_manifest_path_escape_rejected():
    entry = _qwen_entry()
    entry["qualification_manifest_path"] = "../../../etc/passwd"
    with pytest.raises(RegistrySchemaError, match="escape"):
        verify_qualified_manifest_linkage(entry, REPO_ROOT)


def test_qualified_candidate_manifest_digest_mismatch_rejected():
    entry = _qwen_entry()
    entry["qualification_manifest_digest_sha256"] = "b" * 64
    with pytest.raises(RegistrySchemaError, match="digest mismatch"):
        verify_qualified_manifest_linkage(entry, REPO_ROOT)


def test_qualified_candidate_manifest_candidate_mismatch_rejected():
    entry = _qwen_entry()
    entry["canonical_candidate_name"] = "Not-Qwen"
    with pytest.raises(RegistrySchemaError, match="identity mismatch"):
        verify_qualified_manifest_linkage(entry, REPO_ROOT)


def test_qualified_candidate_manifest_repository_mismatch_rejected():
    entry = _qwen_entry()
    entry["artifact_repository"] = "Qwen/Different-Repo"
    with pytest.raises(RegistrySchemaError, match="identity mismatch"):
        verify_qualified_manifest_linkage(entry, REPO_ROOT)


def test_qualified_candidate_manifest_revision_mismatch_rejected():
    entry = _qwen_entry()
    entry["exact_immutable_revision"] = "0" * 40
    with pytest.raises(RegistrySchemaError, match="identity mismatch"):
        verify_qualified_manifest_linkage(entry, REPO_ROOT)


def test_qualified_candidate_missing_qualification_type_rejected():
    entry = _qwen_entry()
    del entry["qualification_type"]
    with pytest.raises(RegistrySchemaError, match="qualification_type"):
        verify_qualified_manifest_linkage(entry, REPO_ROOT)


def test_qualified_candidate_valid_manifest_passes():
    entry = _qwen_entry()
    verify_qualified_manifest_linkage(entry, REPO_ROOT)  # must not raise
