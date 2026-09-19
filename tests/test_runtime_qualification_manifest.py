"""
Phase 21B.4.11.1: tests for the versioned Genesis Runtime Qualification
Manifest schema (orca.eval.runtime_qualification_manifest). All
synthetic fixtures here are fabricated test data -- no real candidate
execution is performed by this file. The one exception is
test_real_qwen_manifest_* below, which validates the actual committed
Qwen3.8-27B manifest and its digest linkage from the real registry.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import CandidateExecutionRegistry
from orca.eval.runtime_qualification_manifest import (
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


def _valid_manifest() -> dict:
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
        "load_attempt_count": 1,
        "attempt_1_result": "SUCCEEDED",
        "attempt_1_failure_class": None,
        "attempt_2_result": "NOT_ATTEMPTED",
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
        "created_at": "2026-01-01",
        "source_repo_sha": "0" * 40,
        "billing_gate_reconciliation": {
            "billing_gate_at_time_of_execution": "NOT_INDEPENDENTLY_PROVEN",
            "owner_billed_result": "$0.00 REPORTED",
            "financial_impact": "NO_OWNER_CHARGE_OBSERVED",
        },
        "raw_execution_log_artifact": "NOT_PRESERVED",
        "evidence_strength": {"exact_revision": "REPOSITORY_VERIFIED"},
    }


def test_valid_manifest_passes():
    validate_manifest(_valid_manifest())  # must not raise


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
    data["evidence_strength"] = {"exact_revision": "TOTALLY_MADE_UP"}
    with pytest.raises(RuntimeQualificationManifestError, match="evidence_strength"):
        validate_manifest(data)


def test_empty_evidence_strength_rejected():
    data = _valid_manifest()
    data["evidence_strength"] = {}
    with pytest.raises(RuntimeQualificationManifestError, match="evidence_strength"):
        validate_manifest(data)


def test_billing_gate_reconciliation_requires_subfields():
    data = _valid_manifest()
    data["billing_gate_reconciliation"] = {"owner_billed_result": "$0.00 REPORTED"}
    with pytest.raises(RuntimeQualificationManifestError, match="missing required field"):
        validate_manifest(data)


# ── canonical digest ──────────────────────────────────────────────────


def test_canonical_digest_is_deterministic_regardless_of_key_order():
    data = _valid_manifest()
    reordered = dict(reversed(list(data.items())))
    assert sha256_of_manifest(data) == sha256_of_manifest(reordered)


def test_canonical_digest_changes_if_content_changes():
    data = _valid_manifest()
    mutated = copy.deepcopy(data)
    mutated["load_time_seconds"] = 999.0
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


def test_real_qwen_manifest_billing_gate_not_overclaimed():
    data = load_manifest(QWEN_MANIFEST_PATH)
    gate = data["billing_gate_reconciliation"]
    assert gate["billing_gate_at_time_of_execution"] == "NOT_INDEPENDENTLY_PROVEN"
    assert data["owner_billed_delta_usd"] == 0


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
