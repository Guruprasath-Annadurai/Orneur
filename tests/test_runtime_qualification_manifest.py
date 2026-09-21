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
    BILLING_GATE_CONFIRMED_ZERO,
    EVIDENCE_ARTIFACT_KEYS,
    EVIDENCE_BEARING_FIELDS,
    EVIDENCE_PROTOCOL_LEGACY,
    EVIDENCE_PROTOCOL_STRICT,
    MANIFEST_SCHEMA_VERSION,
    NOT_CAPTURED,
    RUNTIME_LOADED_WEIGHT_FILES_FIELD,
    RUNTIME_WORKER_MEMORY_FIELD,
    RuntimeQualificationManifestError,
    canonical_json_bytes,
    load_manifest,
    require_candidate_manifest,
    sha256_of_manifest,
    validate_manifest,
    verify_evidence_artifacts_bytes,
    verify_runtime_qualification_bundle,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
QWEN_MANIFEST_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_RUNTIME_QUALIFICATION_MANIFEST_QWEN3_8_27B.json"
MISTRAL_MANIFEST_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_RUNTIME_QUALIFICATION_MANIFEST_MISTRAL_SMALL_4.json"
MISTRAL_RETRY_MANIFEST_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_RUNTIME_QUALIFICATION_MANIFEST_MISTRAL_SMALL_4_RETRY.json"

_VALID_HEX40 = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
_VALID_HEX64 = "a" * 64

# In the base fixture below, cuda_version/ttft_seconds are the only
# evidence-bearing fields whose VALUE is the NOT_CAPTURED sentinel --
# their evidence_strength entries must therefore also read NOT_CAPTURED
# (Phase 21B.4.11.3 §6 consistency rule) rather than the generic
# REPORTED_BY_CLAUDE used for every other (real-valued) field.
_EVIDENCE_STRENGTH_DEFAULTS = {
    field: (NOT_CAPTURED if field in ("cuda_version", "ttft_seconds") else "REPORTED_BY_CLAUDE")
    for field in EVIDENCE_BEARING_FIELDS
}


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
        "deferral_reason": None,
        "runtime": "native-transformers",
        "runtime_versions": {"transformers": "5.17.0"},
        "python_version": "3.11",
        "pytorch_version": "2.14.0",
        "cuda_version": NOT_CAPTURED,
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
        "ttft_seconds": NOT_CAPTURED,
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
        "evidence_strength": dict(_EVIDENCE_STRENGTH_DEFAULTS),
    }


def _legacy_manifest() -> dict:
    data = _base_manifest()
    data["evidence_protocol_generation"] = EVIDENCE_PROTOCOL_LEGACY
    data["created_at"] = "2026-01-01"
    data["execution_time"] = NOT_CAPTURED
    data["raw_execution_log_artifact"] = "NOT_PRESERVED"
    return data


def _strict_manifest() -> dict:
    """A STRICT manifest with load_attempt_count > 0 (inherited from
    _base_manifest's load_attempt_count=1) -- an EXECUTED run, so it
    must carry a positively-confirmed, owner-verified $0 billing gate
    (Phase 21B.4.11.4 §2)."""
    data = _base_manifest()
    data["evidence_protocol_generation"] = EVIDENCE_PROTOCOL_STRICT
    data["created_at"] = "2026-01-01T12:00:00+00:00"
    data["execution_time"] = "2026-01-01T12:00:00+00:00"
    data["raw_execution_log_artifact"] = "logs/test-fixture-log.txt"
    data["raw_execution_log_sha256"] = _VALID_HEX64
    data["evidence_artifacts"] = {
        key: {"path": f"evidence/{key}.json", "sha256": _VALID_HEX64} for key in EVIDENCE_ARTIFACT_KEYS
    }
    data["billing_gate_reconciliation"] = {
        "billing_gate_at_time_of_execution": BILLING_GATE_CONFIRMED_ZERO,
        "owner_billed_result": "$0.00 REPORTED",
        "financial_impact": "NO_OWNER_CHARGE_OBSERVED",
    }
    data["evidence_strength"]["billing_gate_at_time_of_execution"] = "OWNER_SCREENSHOT_VERIFIED"
    return data


def _write_evidence_bundle(tmp_path: Path, manifest: dict) -> Path:
    """Writes real files under tmp_path matching every path/sha256 pair
    a STRICT manifest declares (raw_execution_log_artifact +
    evidence_artifacts), recomputes the actual SHA-256 of each file's
    real content, and patches the manifest's declared hashes to match
    -- so tests can exercise `verify_evidence_artifacts_bytes` against
    genuinely matching bytes, not merely format-valid placeholder hashes."""
    import hashlib

    def _write_and_hash(rel_path: str, content: bytes) -> str:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    manifest["raw_execution_log_sha256"] = _write_and_hash(
        manifest["raw_execution_log_artifact"], b"synthetic test execution log content\n"
    )
    for key in EVIDENCE_ARTIFACT_KEYS:
        entry = manifest["evidence_artifacts"][key]
        entry["sha256"] = _write_and_hash(entry["path"], f"synthetic {key} evidence\n".encode())
    return tmp_path


def _deferred_manifest() -> dict:
    """A STRICT DEFERRED_FOR_COMPUTE bundle: zero load attempts, zero
    GPU allocation, no generation -- every load/generation-phase field
    is honestly NOT_CAPTURED rather than a fabricated zero."""
    data = _strict_manifest()
    data["qualification_type"] = "DEFERRED_FOR_COMPUTE"
    data["deferral_reason"] = "Owner Modal $0 usage-limit dashboard evidence was not yet confirmed at execution time."
    # Deferred precisely BECAUSE the billing gate was not confirmed --
    # honestly reflect that rather than inheriting _strict_manifest()'s
    # CONFIRMED_ZERO_SPEND_LIMIT (which would contradict the deferral).
    data["billing_gate_reconciliation"] = {
        "billing_gate_at_time_of_execution": "NOT_INDEPENDENTLY_PROVEN",
        "owner_billed_result": "$0.00 REPORTED",
        "financial_impact": "NO_OWNER_CHARGE_OBSERVED",
    }
    data["evidence_strength"]["billing_gate_at_time_of_execution"] = NOT_CAPTURED
    data["load_attempt_count"] = 0
    data["attempt_1_result"] = "NOT_ATTEMPTED"
    data["attempt_1_failure_class"] = None
    data["attempt_2_result"] = "NOT_ATTEMPTED"
    data["attempt_2_failure_class"] = None
    for field in ("gpu_count", "vram_capacity_gb", "peak_allocated_vram_gb", "peak_reserved_vram_gb",
                  "load_time_seconds", "weight_file_shards", "runtime_materialized_tensor_count",
                  "input_tokens", "output_tokens", "generation_latency_seconds", "tokens_per_second",
                  "synthetic_prompt_sha256", "decoded_response_sha256"):
        data[field] = NOT_CAPTURED
        if field in EVIDENCE_BEARING_FIELDS:
            data["evidence_strength"][field] = NOT_CAPTURED
    return data


def _failed_before_generation_manifest() -> dict:
    """A STRICT RUNTIME_QUALIFICATION_FAILED bundle: one real load
    attempt happened (so GPU/load-phase fields ARE real), but it failed
    before ever reaching generation -- generation-phase fields are
    honestly NOT_CAPTURED, not a fabricated response hash."""
    data = _strict_manifest()
    data["qualification_type"] = "RUNTIME_QUALIFICATION_FAILED"
    data["attempt_1_result"] = "FAILED"
    data["attempt_1_failure_class"] = "MODEL_ARCHITECTURE_UNSUPPORTED"
    data["cleanup_status"] = "CONFIRMED_ZERO_ACTIVE_RESOURCES"
    data["active_resources_after"] = "NONE"
    for field in ("input_tokens", "output_tokens", "generation_latency_seconds", "tokens_per_second",
                  "synthetic_prompt_sha256", "decoded_response_sha256"):
        data[field] = NOT_CAPTURED
        if field in EVIDENCE_BEARING_FIELDS:
            data["evidence_strength"][field] = NOT_CAPTURED
    return data


# Backwards-compatible default fixture name used throughout this file.
_valid_manifest = _legacy_manifest


def test_valid_legacy_manifest_passes():
    validate_manifest(_legacy_manifest())  # must not raise


def test_valid_strict_manifest_passes():
    validate_manifest(_strict_manifest())  # must not raise


def test_valid_strict_deferred_bundle_passes():
    validate_manifest(_deferred_manifest())  # must not raise


def test_valid_strict_failed_before_generation_bundle_passes():
    validate_manifest(_failed_before_generation_manifest())  # must not raise


@pytest.mark.parametrize("field", ["peak_allocated_vram_gb", "peak_reserved_vram_gb", "load_time_seconds"])
def test_failed_result_may_record_not_captured_for_unmeasured_load_metrics(field):
    """Phase 21B.4.12.1 §2/§3/§4: a non-QUALIFIED attempted run (e.g.
    RUNTIME_QUALIFICATION_FAILED) may honestly record NOT_CAPTURED for
    peak_allocated_vram_gb/peak_reserved_vram_gb/load_time_seconds when
    the metric was never actually, correctly observed -- this must not
    raise even though load_attempt_count > 0."""
    data = _failed_before_generation_manifest()
    data[field] = NOT_CAPTURED
    data["evidence_strength"][field] = NOT_CAPTURED
    validate_manifest(data)  # must not raise


@pytest.mark.parametrize("field", ["peak_allocated_vram_gb", "peak_reserved_vram_gb", "load_time_seconds"])
def test_qualified_result_still_strictly_requires_real_load_metrics(field):
    """Phase 21B.4.12.1 §4: QUALIFIED executions still require these
    three fields to be genuinely-captured real numbers -- the
    FAILED-only sentinel relaxation must not weaken the QUALIFIED
    invariant."""
    data = _strict_manifest()  # qualification_type == RUNTIME_LOAD_COMPATIBILITY_QUALIFIED
    data[field] = NOT_CAPTURED
    data["evidence_strength"][field] = NOT_CAPTURED
    with pytest.raises(RuntimeQualificationManifestError, match=field):
        validate_manifest(data)


def test_vram_capacity_gb_still_strictly_required_for_any_attempted_load():
    """vram_capacity_gb is a topology/hardware fact, not a runtime
    measurement -- Phase 21B.4.12.1's sentinel relaxation for
    peak_allocated/reserved_vram_gb and load_time_seconds must not
    extend to it. A FAILED result still must not set it to
    NOT_CAPTURED while load_attempt_count > 0."""
    data = _failed_before_generation_manifest()
    data["vram_capacity_gb"] = NOT_CAPTURED
    data["evidence_strength"]["vram_capacity_gb"] = NOT_CAPTURED
    with pytest.raises(RuntimeQualificationManifestError, match="vram_capacity_gb"):
        validate_manifest(data)


# ── Phase 21B.4.12.4: QUALIFIED-multiprocess peak-VRAM alternate evidence ──

_VALID_RUNTIME_WORKER_MEMORY = {
    "source": "VLLM_WORKER_LOG",
    "per_gpu": {
        "consumed_memory_gib": 57.45,
        "peak_activation_gib": 0.54,
        "cudagraph_memory_gib": 0.08,
        "kv_cache_memory_gib": 60.84,
    },
    "workers_observed": 2,
}


def _qualified_manifest_with_not_captured_peak_vram() -> dict:
    """A QUALIFIED (attempted, successful) manifest with peak_allocated/
    reserved_vram_gb set to NOT_CAPTURED plus valid alternate
    runtime_worker_memory evidence -- the fixture this whole battery of
    tests mutates away from validity."""
    data = _strict_manifest()  # qualification_type == RUNTIME_LOAD_COMPATIBILITY_QUALIFIED
    data["peak_allocated_vram_gb"] = NOT_CAPTURED
    data["peak_reserved_vram_gb"] = NOT_CAPTURED
    data["evidence_strength"]["peak_allocated_vram_gb"] = NOT_CAPTURED
    data["evidence_strength"]["peak_reserved_vram_gb"] = NOT_CAPTURED
    data[RUNTIME_WORKER_MEMORY_FIELD] = json.loads(json.dumps(_VALID_RUNTIME_WORKER_MEMORY))
    return data


def test_qualified_multiprocess_not_captured_peak_vram_allowed_with_valid_alternate_evidence():
    validate_manifest(_qualified_manifest_with_not_captured_peak_vram())  # must not raise


def test_qualified_not_captured_peak_vram_rejected_without_alternate_evidence():
    """Deleting the alternate worker-memory evidence must cause
    rejection -- a QUALIFIED manifest must never leave peak GPU memory
    entirely unevidenced."""
    data = _qualified_manifest_with_not_captured_peak_vram()
    del data[RUNTIME_WORKER_MEMORY_FIELD]
    with pytest.raises(RuntimeQualificationManifestError, match="peak_allocated_vram_gb"):
        validate_manifest(data)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda d: d.__setitem__(RUNTIME_WORKER_MEMORY_FIELD, "not-a-mapping"), "must be a mapping"),
        (lambda d: d[RUNTIME_WORKER_MEMORY_FIELD].pop("source"), "source"),
        (lambda d: d[RUNTIME_WORKER_MEMORY_FIELD].__setitem__("source", ""), "source"),
        (lambda d: d[RUNTIME_WORKER_MEMORY_FIELD].__setitem__("per_gpu", "nope"), "per_gpu"),
        (lambda d: d[RUNTIME_WORKER_MEMORY_FIELD]["per_gpu"].pop("kv_cache_memory_gib"), "per_gpu"),
        (lambda d: d[RUNTIME_WORKER_MEMORY_FIELD].pop("workers_observed"), "workers_observed"),
        (lambda d: d[RUNTIME_WORKER_MEMORY_FIELD].__setitem__("workers_observed", 0), "workers_observed"),
        (lambda d: d[RUNTIME_WORKER_MEMORY_FIELD].__setitem__("workers_observed", 1.5), "workers_observed"),
    ],
)
def test_malformed_runtime_worker_memory_rejected(mutate, match):
    data = _qualified_manifest_with_not_captured_peak_vram()
    mutate(data)
    with pytest.raises(RuntimeQualificationManifestError, match=match):
        validate_manifest(data)


@pytest.mark.parametrize("field", ["consumed_memory_gib", "peak_activation_gib", "cudagraph_memory_gib", "kv_cache_memory_gib"])
@pytest.mark.parametrize("bad_value", [-1.0, float("nan"), float("inf"), "57.45"])
def test_negative_or_non_finite_worker_memory_values_rejected(field, bad_value):
    data = _qualified_manifest_with_not_captured_peak_vram()
    data[RUNTIME_WORKER_MEMORY_FIELD]["per_gpu"][field] = bad_value
    with pytest.raises(RuntimeQualificationManifestError, match=field):
        validate_manifest(data)


def test_qualified_manifest_still_strictly_requires_real_load_time_seconds():
    """Phase 21B.4.12.4 §5: the alternate-evidence relaxation for
    peak_allocated/reserved_vram_gb must NOT extend to load_time_seconds
    -- a QUALIFIED manifest still requires a genuine measurement there,
    with or without runtime_worker_memory present."""
    data = _qualified_manifest_with_not_captured_peak_vram()
    data["load_time_seconds"] = NOT_CAPTURED
    data["evidence_strength"]["load_time_seconds"] = NOT_CAPTURED
    with pytest.raises(RuntimeQualificationManifestError, match="load_time_seconds"):
        validate_manifest(data)


def test_runtime_worker_memory_and_loaded_weight_files_forbidden_when_zero_attempts():
    data = _deferred_manifest()
    data[RUNTIME_WORKER_MEMORY_FIELD] = json.loads(json.dumps(_VALID_RUNTIME_WORKER_MEMORY))
    with pytest.raises(RuntimeQualificationManifestError, match=RUNTIME_WORKER_MEMORY_FIELD):
        validate_manifest(data)

    data2 = _deferred_manifest()
    data2[RUNTIME_LOADED_WEIGHT_FILES_FIELD] = 7
    with pytest.raises(RuntimeQualificationManifestError, match=RUNTIME_LOADED_WEIGHT_FILES_FIELD):
        validate_manifest(data2)


def test_runtime_loaded_weight_files_must_be_positive_int_when_present():
    data = _strict_manifest()
    data[RUNTIME_LOADED_WEIGHT_FILES_FIELD] = 0
    with pytest.raises(RuntimeQualificationManifestError, match=RUNTIME_LOADED_WEIGHT_FILES_FIELD):
        validate_manifest(data)


def test_runtime_loaded_weight_files_distinct_from_repository_weight_file_shards():
    """weight_file_shards (a repository fact) and runtime_loaded_weight_
    files (a runtime-observed fact) must be independently settable and
    never conflated -- a manifest may legitimately record different
    values for each, as Mistral Small 4's real retry manifest does."""
    data = _strict_manifest()
    data["weight_file_shards"] = 3
    data[RUNTIME_LOADED_WEIGHT_FILES_FIELD] = 7
    validate_manifest(data)  # must not raise -- both values coexist honestly


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


def test_attempt_count_three_rejected():
    """Phase 21B.4.12 §1: no blind retry loops -- the manifest schema
    itself caps live model-load attempts at 2, mirroring the original
    Phase 21B.4.11 §9 policy."""
    data = _valid_manifest()
    data["load_attempt_count"] = 3
    data["attempt_1_result"] = "FAILED"
    data["attempt_1_failure_class"] = "OTHER"
    data["attempt_2_result"] = "FAILED"
    data["attempt_2_failure_class"] = "OTHER"
    with pytest.raises(RuntimeQualificationManifestError, match="load_attempt_count must be <= 2"):
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


def test_runtime_materialized_tensor_count_may_be_not_captured_even_with_attempted_load():
    """Phase 21B.4.12: not every runtime exposes an equivalent metric
    to Transformers' own per-tensor loading progress counter (e.g.
    vLLM's multiprocess tensor-parallel loader) -- this one metric may
    honestly be NOT_CAPTURED even when load_attempt_count > 0, unlike
    weight_file_shards (a repository fact, always obtainable)."""
    data = _failed_before_generation_manifest()
    data["runtime_materialized_tensor_count"] = NOT_CAPTURED
    data["evidence_strength"]["runtime_materialized_tensor_count"] = NOT_CAPTURED
    validate_manifest(data)  # must not raise
    assert data["load_attempt_count"] > 0
    assert data["weight_file_shards"] != NOT_CAPTURED  # still required to be real


def test_weight_file_shards_still_required_even_when_tensor_count_not_captured():
    data = _failed_before_generation_manifest()
    data["runtime_materialized_tensor_count"] = NOT_CAPTURED
    data["evidence_strength"]["runtime_materialized_tensor_count"] = NOT_CAPTURED
    data["weight_file_shards"] = NOT_CAPTURED
    with pytest.raises(RuntimeQualificationManifestError, match="weight_file_shards"):
        validate_manifest(data)


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


# ── Phase 21B.4.11.3 §1: ordinary (no-optional-arg) registry load is fail-closed ──


def test_ordinary_registry_load_auto_verifies_manifest_linkage():
    CandidateExecutionRegistry.load(str(REGISTRY_PATH))  # must not raise, no manifest_root passed


def test_ordinary_registry_load_fails_if_manifest_missing(tmp_path, monkeypatch):
    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    qwen["qualification_manifest_path"] = "docs/orneur/phase-21/DOES_NOT_EXIST.json"
    broken_registry = tmp_path / "registry.json"
    broken_registry.write_text(json.dumps(registry_data))
    monkeypatch.setattr(
        "orca.eval.candidate_registry._derive_manifest_root", lambda p: REPO_ROOT
    )
    with pytest.raises(RegistrySchemaError, match="does not exist"):
        CandidateExecutionRegistry.load(str(broken_registry))


def test_ordinary_registry_load_fails_on_digest_mismatch(tmp_path, monkeypatch):
    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    qwen["qualification_manifest_digest_sha256"] = "c" * 64
    broken_registry = tmp_path / "registry.json"
    broken_registry.write_text(json.dumps(registry_data))
    monkeypatch.setattr(
        "orca.eval.candidate_registry._derive_manifest_root", lambda p: REPO_ROOT
    )
    with pytest.raises(RegistrySchemaError, match="digest mismatch"):
        CandidateExecutionRegistry.load(str(broken_registry))


def test_ordinary_registry_load_fails_on_path_escape(tmp_path, monkeypatch):
    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    qwen["qualification_manifest_path"] = "../../../etc/passwd"
    broken_registry = tmp_path / "registry.json"
    broken_registry.write_text(json.dumps(registry_data))
    monkeypatch.setattr(
        "orca.eval.candidate_registry._derive_manifest_root", lambda p: REPO_ROOT
    )
    with pytest.raises(RegistrySchemaError, match="escape"):
        CandidateExecutionRegistry.load(str(broken_registry))


def test_ordinary_registry_load_fails_on_identity_mismatch(tmp_path, monkeypatch):
    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    qwen["exact_immutable_revision"] = "0" * 40
    broken_registry = tmp_path / "registry.json"
    broken_registry.write_text(json.dumps(registry_data))
    monkeypatch.setattr(
        "orca.eval.candidate_registry._derive_manifest_root", lambda p: REPO_ROOT
    )
    with pytest.raises(RegistrySchemaError, match="identity mismatch"):
        CandidateExecutionRegistry.load(str(broken_registry))


def test_from_dict_rejects_qualified_candidate_missing_manifest_metadata():
    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    del qwen["qualification_manifest_path"]
    with pytest.raises(RegistrySchemaError, match="missing required manifest-linkage"):
        CandidateExecutionRegistry.from_dict(registry_data)


def test_from_dict_rejects_qualified_candidate_with_malformed_digest():
    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    qwen["qualification_manifest_digest_sha256"] = "not-hex"
    with pytest.raises(RegistrySchemaError, match="malformed qualification_manifest_digest_sha256"):
        CandidateExecutionRegistry.from_dict(registry_data)


# ── Phase 21B.4.11.3 §2/§8: strict artifact byte verification ───────────


def test_strict_bundle_bytes_verify_when_files_match(tmp_path):
    manifest = _strict_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    validate_manifest(manifest)
    verify_evidence_artifacts_bytes(manifest, root)  # must not raise


def test_strict_bundle_missing_log_file_rejected(tmp_path):
    manifest = _strict_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    (root / manifest["raw_execution_log_artifact"]).unlink()
    validate_manifest(manifest)
    with pytest.raises(RuntimeQualificationManifestError, match="not a regular file or does not exist"):
        verify_evidence_artifacts_bytes(manifest, root)


def test_strict_bundle_log_hash_mismatch_rejected(tmp_path):
    manifest = _strict_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    (root / manifest["raw_execution_log_artifact"]).write_bytes(b"tampered content")
    validate_manifest(manifest)
    with pytest.raises(RuntimeQualificationManifestError, match="byte hash mismatch"):
        verify_evidence_artifacts_bytes(manifest, root)


def test_strict_bundle_artifact_path_escape_rejected(tmp_path):
    manifest = _strict_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    manifest["evidence_artifacts"]["billing_before"]["path"] = "../outside.json"
    validate_manifest(manifest)
    with pytest.raises(RuntimeQualificationManifestError, match="escape"):
        verify_evidence_artifacts_bytes(manifest, root)


@pytest.mark.parametrize("missing_key", EVIDENCE_ARTIFACT_KEYS)
def test_strict_bundle_missing_evidence_artifact_entry_rejected(missing_key):
    manifest = _strict_manifest()
    del manifest["evidence_artifacts"][missing_key]
    with pytest.raises(RuntimeQualificationManifestError, match="missing required entries"):
        validate_manifest(manifest)


def test_strict_bundle_artifact_byte_mismatch_for_one_of_the_six_rejected(tmp_path):
    manifest = _strict_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    (root / manifest["evidence_artifacts"]["cleanup"]["path"]).write_bytes(b"tampered")
    validate_manifest(manifest)
    with pytest.raises(RuntimeQualificationManifestError, match="evidence_artifacts.cleanup"):
        verify_evidence_artifacts_bytes(manifest, root)


# ── Phase 21B.4.11.3 §8: the single fail-closed high-level verifier ──────


def test_high_level_verifier_accepts_valid_strict_bundle(tmp_path):
    manifest = _strict_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    verify_runtime_qualification_bundle(
        manifest,
        candidate="Test-Candidate",
        repository="Org/Test-Candidate",
        revision=_VALID_HEX40,
        qualification_type="RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
        evidence_root=root,
    )  # must not raise


def test_high_level_verifier_refuses_strict_bundle_without_evidence_root():
    """Proves a caller cannot accidentally accept a QUALIFIED STRICT
    bundle by skipping byte verification (e.g. forgetting evidence_root)
    -- schema/identity checks alone are not enough for a strict manifest."""
    manifest = _strict_manifest()
    with pytest.raises(RuntimeQualificationManifestError, match="require evidence_root"):
        verify_runtime_qualification_bundle(
            manifest,
            candidate="Test-Candidate",
            repository="Org/Test-Candidate",
            revision=_VALID_HEX40,
            qualification_type="RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
        )


def test_high_level_verifier_rejects_strict_bundle_with_tampered_bytes(tmp_path):
    manifest = _strict_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    (root / manifest["evidence_artifacts"]["model_identity"]["path"]).write_bytes(b"tampered")
    with pytest.raises(RuntimeQualificationManifestError, match="byte hash mismatch"):
        verify_runtime_qualification_bundle(
            manifest,
            candidate="Test-Candidate",
            repository="Org/Test-Candidate",
            revision=_VALID_HEX40,
            qualification_type="RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
            evidence_root=root,
        )


def test_high_level_verifier_accepts_legacy_bundle_without_evidence_root():
    """The legacy Qwen-style bundle has no durable artifacts to
    byte-verify -- the high-level verifier must not demand evidence_root
    for it."""
    manifest = _legacy_manifest()
    verify_runtime_qualification_bundle(
        manifest,
        candidate="Test-Candidate",
        repository="Org/Test-Candidate",
        revision=_VALID_HEX40,
        qualification_type="RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
    )  # must not raise


# ── Phase 21B.4.11.3 §4: state-discriminated field requirements ─────────


def test_deferred_forced_to_invent_gpu_rejected():
    data = _deferred_manifest()
    data["gpu_count"] = 1  # a real GPU value contradicts zero load attempts
    with pytest.raises(RuntimeQualificationManifestError, match="gpu_count"):
        validate_manifest(data)


def test_deferred_forced_to_invent_response_hash_rejected():
    data = _deferred_manifest()
    data["decoded_response_sha256"] = _VALID_HEX64
    data["evidence_strength"]["decoded_response_sha256"] = "OBSERVED_LIVE"
    with pytest.raises(RuntimeQualificationManifestError, match="decoded_response_sha256 must be"):
        validate_manifest(data)


def test_failed_load_forced_to_invent_decoded_response_rejected():
    data = _failed_before_generation_manifest()
    data["decoded_response_sha256"] = _VALID_HEX64
    data["evidence_strength"]["decoded_response_sha256"] = "OBSERVED_LIVE"
    with pytest.raises(RuntimeQualificationManifestError, match="decoded_response_sha256 must be"):
        validate_manifest(data)


def test_qualified_run_missing_real_response_evidence_rejected():
    """A QUALIFIED manifest may never claim NOT_CAPTURED for its
    decoded_response_sha256 -- success implies a real response existed."""
    data = _strict_manifest()
    data["decoded_response_sha256"] = NOT_CAPTURED
    with pytest.raises(RuntimeQualificationManifestError, match="decoded_response_sha256"):
        validate_manifest(data)


def test_deferred_without_deferral_reason_rejected():
    data = _deferred_manifest()
    data["deferral_reason"] = None
    with pytest.raises(RuntimeQualificationManifestError, match="deferral_reason"):
        validate_manifest(data)


def test_non_deferred_with_deferral_reason_rejected():
    data = _legacy_manifest()
    data["deferral_reason"] = "should not be set for a QUALIFIED manifest"
    with pytest.raises(RuntimeQualificationManifestError, match="deferral_reason"):
        validate_manifest(data)


def test_deferred_with_nonzero_attempts_but_deferred_type_rejected():
    """DEFERRED_FOR_COMPUTE must not carry a SUCCEEDED attempt even if
    load_attempt_count is nonzero."""
    data = _deferred_manifest()
    data["load_attempt_count"] = 1
    data["attempt_1_result"] = "SUCCEEDED"
    data["gpu_count"] = 1
    data["vram_capacity_gb"] = 80
    data["peak_allocated_vram_gb"] = 10
    data["peak_reserved_vram_gb"] = 10
    data["load_time_seconds"] = 5
    data["weight_file_shards"] = 3
    data["runtime_materialized_tensor_count"] = 50
    with pytest.raises(RuntimeQualificationManifestError, match="must not have any SUCCEEDED attempt"):
        validate_manifest(data)


# ── Phase 21B.4.11.3 §6: evidence-strength / actual-value consistency ───


def test_evidence_strength_not_captured_with_real_value_rejected():
    data = _legacy_manifest()
    data["evidence_strength"]["weight_file_shards"] = NOT_CAPTURED  # value is 5, a real number
    with pytest.raises(RuntimeQualificationManifestError, match="carries a real value"):
        validate_manifest(data)


def test_weight_file_shards_zero_rejected():
    data = _legacy_manifest()
    data["weight_file_shards"] = 0
    with pytest.raises(RuntimeQualificationManifestError, match="weight_file_shards"):
        validate_manifest(data)


def test_weight_file_shards_negative_rejected():
    data = _legacy_manifest()
    data["weight_file_shards"] = -1
    with pytest.raises(RuntimeQualificationManifestError, match="weight_file_shards"):
        validate_manifest(data)


def test_weight_file_shards_bool_rejected():
    data = _legacy_manifest()
    data["weight_file_shards"] = True
    with pytest.raises(RuntimeQualificationManifestError, match="weight_file_shards"):
        validate_manifest(data)


def test_runtime_materialized_tensor_count_invalid_rejected():
    data = _legacy_manifest()
    data["runtime_materialized_tensor_count"] = -5
    with pytest.raises(RuntimeQualificationManifestError, match="runtime_materialized_tensor_count"):
        validate_manifest(data)


# ── Phase 21B.4.11.3 §9: legacy Qwen digest was recomputed honestly ──────


def test_real_qwen_manifest_has_deferral_reason_null():
    data = load_manifest(QWEN_MANIFEST_PATH)
    assert data["deferral_reason"] is None


def test_real_qwen_manifest_digest_matches_registry_after_migration():
    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    manifest_data = load_manifest(QWEN_MANIFEST_PATH)
    assert sha256_of_manifest(manifest_data) == qwen["qualification_manifest_digest_sha256"]


# ── Phase 21B.4.11.4 §1/§2/§7: billing-gate artifact binding ─────────────


def test_strict_executed_run_missing_billing_gate_artifact_rejected():
    data = _strict_manifest()
    del data["evidence_artifacts"]["billing_gate"]
    with pytest.raises(RuntimeQualificationManifestError, match="missing required entries"):
        validate_manifest(data)


def test_strict_billing_gate_artifact_wrong_hash_rejected(tmp_path):
    manifest = _strict_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    (root / manifest["evidence_artifacts"]["billing_gate"]["path"]).write_bytes(b"tampered")
    validate_manifest(manifest)
    with pytest.raises(RuntimeQualificationManifestError, match="evidence_artifacts.billing_gate"):
        verify_evidence_artifacts_bytes(manifest, root)


def test_strict_billing_gate_path_escape_rejected(tmp_path):
    manifest = _strict_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    manifest["evidence_artifacts"]["billing_gate"]["path"] = "../../outside-billing-gate.json"
    validate_manifest(manifest)
    with pytest.raises(RuntimeQualificationManifestError, match="escape"):
        verify_evidence_artifacts_bytes(manifest, root)


def test_executed_strict_run_with_billing_gate_reported_by_claude_rejected():
    data = _strict_manifest()
    data["evidence_strength"]["billing_gate_at_time_of_execution"] = "REPORTED_BY_CLAUDE"
    with pytest.raises(RuntimeQualificationManifestError, match="OWNER_SCREENSHOT_VERIFIED"):
        validate_manifest(data)


def test_executed_strict_run_with_billing_gate_derived_rejected():
    data = _strict_manifest()
    data["evidence_strength"]["billing_gate_at_time_of_execution"] = "DERIVED"
    with pytest.raises(RuntimeQualificationManifestError, match="OWNER_SCREENSHOT_VERIFIED"):
        validate_manifest(data)


def test_executed_strict_run_with_billing_gate_not_captured_rejected():
    data = _strict_manifest()
    data["evidence_strength"]["billing_gate_at_time_of_execution"] = NOT_CAPTURED
    with pytest.raises(RuntimeQualificationManifestError, match="OWNER_SCREENSHOT_VERIFIED"):
        validate_manifest(data)


def test_executed_strict_run_claiming_non_confirmed_spend_ceiling_rejected():
    data = _strict_manifest()
    data["billing_gate_reconciliation"]["billing_gate_at_time_of_execution"] = "NOT_INDEPENDENTLY_PROVEN"
    with pytest.raises(RuntimeQualificationManifestError, match="CONFIRMED_ZERO_SPEND_LIMIT"):
        validate_manifest(data)


def test_deferred_zero_attempt_bundle_does_not_require_billing_gate_confirmation():
    """A run deferred BECAUSE the billing gate was unconfirmed must not
    be forced to fabricate owner authorization just to validate."""
    data = _deferred_manifest()
    assert data["billing_gate_reconciliation"]["billing_gate_at_time_of_execution"] == "NOT_INDEPENDENTLY_PROVEN"
    validate_manifest(data)  # must not raise


def test_strict_synthetic_successful_bundle_with_real_billing_gate_artifact(tmp_path):
    manifest = _strict_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    validate_manifest(manifest)
    verify_evidence_artifacts_bytes(manifest, root)  # must not raise


def test_strict_failed_bundle_where_execution_was_properly_authorized(tmp_path):
    manifest = _failed_before_generation_manifest()
    root = _write_evidence_bundle(tmp_path, manifest)
    validate_manifest(manifest)
    verify_evidence_artifacts_bytes(manifest, root)  # must not raise


# ── Phase 21B.4.11.4 §5: the single end-to-end acceptance verifier ───────


def _write_broken_registry(tmp_path: Path, mutate) -> Path:
    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    mutate(qwen)
    broken = tmp_path / "registry.json"
    broken.write_text(json.dumps(registry_data))
    return broken


def test_end_to_end_verifier_accepts_real_qwen_candidate():
    from orca.eval.candidate_registry import verify_candidate_qualification_end_to_end
    entry, manifest = verify_candidate_qualification_end_to_end(REGISTRY_PATH, "Qwen3.8-27B", manifest_root=REPO_ROOT)
    assert entry["canonical_candidate_name"] == "Qwen3.8-27B"
    assert manifest["candidate"] == "Qwen3.8-27B"
    assert manifest is not None  # require_qualified=True default never returns a null manifest


def test_end_to_end_verifier_rejects_unqualified_candidate_by_default():
    """Phase 21B.4.12 §2: the acceptance API must never return
    (UNQUALIFIED entry, None) as if it were a successful acceptance --
    it must raise instead. Phase 21B.4.12.3: Mistral Small 4 became
    QUALIFIED via its live retry, so GLM-5.3-Flash (still genuinely
    UNQUALIFIED, no manifest linkage at all) is used here instead."""
    from orca.eval.candidate_registry import verify_candidate_qualification_end_to_end
    with pytest.raises(RegistrySchemaError, match="is not QUALIFIED"):
        verify_candidate_qualification_end_to_end(REGISTRY_PATH, "GLM-5.3-Flash", manifest_root=REPO_ROOT)


def test_end_to_end_verifier_allows_unqualified_inspection_when_explicitly_requested():
    """A non-acceptance inspection workflow may opt out of the
    fail-closed default explicitly. GLM-5.3-Flash has never been
    smoke-tested at all (no qualification_type/manifest linkage
    recorded), so the inspection path correctly returns None -- see
    test_verify_recorded_manifest_linkage_returns_real_manifest_for_failed_result
    below for the "linked FAILED record returns a real manifest, not
    None" case, using Mistral Small 4's historical Phase 21B.4.12
    FAILED manifest directly."""
    from orca.eval.candidate_registry import verify_candidate_qualification_end_to_end
    entry, manifest = verify_candidate_qualification_end_to_end(
        REGISTRY_PATH, "GLM-5.3-Flash", manifest_root=REPO_ROOT, require_qualified=False
    )
    assert entry["canonical_candidate_name"] == "GLM-5.3-Flash"
    assert entry["runtime_qualification_status"] != "QUALIFIED"
    assert manifest is None


def test_end_to_end_verifier_rejects_registry_digest_mismatch(tmp_path):
    from orca.eval.candidate_registry import verify_candidate_qualification_end_to_end
    broken = _write_broken_registry(tmp_path, lambda q: q.__setitem__("qualification_manifest_digest_sha256", "b" * 64))
    with pytest.raises(RegistrySchemaError, match="digest mismatch"):
        verify_candidate_qualification_end_to_end(broken, "Qwen3.8-27B", manifest_root=REPO_ROOT)


def test_end_to_end_verifier_rejects_registry_manifest_path_mismatch(tmp_path):
    from orca.eval.candidate_registry import verify_candidate_qualification_end_to_end
    broken = _write_broken_registry(
        tmp_path, lambda q: q.__setitem__("qualification_manifest_path", "docs/orneur/phase-21/DOES_NOT_EXIST.json")
    )
    with pytest.raises(RegistrySchemaError, match="does not exist"):
        verify_candidate_qualification_end_to_end(broken, "Qwen3.8-27B", manifest_root=REPO_ROOT)


def test_end_to_end_verifier_rejects_manifest_identity_mismatch(tmp_path):
    from orca.eval.candidate_registry import verify_candidate_qualification_end_to_end
    broken = _write_broken_registry(tmp_path, lambda q: q.__setitem__("exact_immutable_revision", "0" * 40))
    with pytest.raises(RegistrySchemaError, match="identity mismatch"):
        verify_candidate_qualification_end_to_end(broken, "Qwen3.8-27B", manifest_root=REPO_ROOT)


def test_end_to_end_verifier_rejects_valid_manifest_but_invalid_registry_linkage(tmp_path):
    """The manifest file itself is untouched and would validate fine on
    its own, but the registry's own recorded identity no longer matches
    it -- the end-to-end verifier must still fail closed."""
    from orca.eval.candidate_registry import verify_candidate_qualification_end_to_end
    broken = _write_broken_registry(tmp_path, lambda q: q.__setitem__("artifact_repository", "Qwen/Wrong-Repo"))
    # The real manifest on disk is fine in isolation:
    load_manifest(QWEN_MANIFEST_PATH)
    with pytest.raises(RegistrySchemaError, match="identity mismatch"):
        verify_candidate_qualification_end_to_end(broken, "Qwen3.8-27B", manifest_root=REPO_ROOT)


def test_end_to_end_verifier_rejects_valid_registry_linkage_but_tampered_strict_bytes(tmp_path):
    """Registry linkage (identity/digest) is fine, but a STRICT
    manifest's declared evidence-artifact bytes have been tampered --
    the end-to-end verifier must still fail closed via byte
    verification, not just schema/digest checks. Uses the real registry
    (so every other structural requirement -- exact name sets, all
    required fields -- is already satisfied) but repoints Qwen's
    manifest linkage at a synthetic STRICT manifest + evidence bundle."""
    from orca.eval.candidate_registry import verify_candidate_qualification_end_to_end

    manifest = _strict_manifest()
    manifest["candidate"] = "Qwen3.8-27B"
    manifest["artifact_repository"] = "Qwen/Qwen3.8-27B"
    manifest["exact_revision"] = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
    manifest["tokenizer_repository"] = "Qwen/Qwen3.8-27B"
    manifest["tokenizer_revision"] = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
    root = _write_evidence_bundle(tmp_path, manifest)
    manifest_rel_path = "synthetic_manifest.json"
    (root / manifest_rel_path).write_text(json.dumps(manifest))
    digest = sha256_of_manifest(manifest)

    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    qwen["qualification_manifest_path"] = manifest_rel_path
    qwen["qualification_manifest_digest_sha256"] = digest
    qwen["qualification_type"] = manifest["qualification_type"]
    registry_path = root / "registry.json"
    registry_path.write_text(json.dumps(registry_data))

    # Tamper with one evidence-artifact file's bytes AFTER the manifest
    # (and its digest) were finalized -- registry linkage/digest still
    # matches the manifest content, but the declared bytes no longer do.
    (root / manifest["evidence_artifacts"]["execution_log"]["path"]).write_bytes(b"tampered after the fact")

    with pytest.raises(RegistrySchemaError, match="strict evidence-artifact verification failed"):
        verify_candidate_qualification_end_to_end(registry_path, "Qwen3.8-27B", manifest_root=root)


# ── Phase 21B.4.12: the real, committed Mistral Small 4 FAILED manifest ──


def test_real_mistral_manifest_validates():
    data = load_manifest(MISTRAL_MANIFEST_PATH)
    require_candidate_manifest(
        data,
        candidate="Mistral Small 4",
        repository="mistralai/Mistral-Small-4-119B-2603",
        revision="a11f36bebf709121056b1dbcc943d1c6afbe494d",
        qualification_type="RUNTIME_QUALIFICATION_FAILED",
    )


def test_real_mistral_manifest_bytes_verify():
    data = load_manifest(MISTRAL_MANIFEST_PATH)
    verify_evidence_artifacts_bytes(data, REPO_ROOT)  # must not raise


def test_real_mistral_manifest_no_generation_evidence_fabricated():
    data = load_manifest(MISTRAL_MANIFEST_PATH)
    assert data["decoded_response_sha256"] == NOT_CAPTURED
    assert data["synthetic_prompt_sha256"] == NOT_CAPTURED
    assert data["output_tokens"] == NOT_CAPTURED


def test_real_mistral_manifest_load_evidence_is_real():
    data = load_manifest(MISTRAL_MANIFEST_PATH)
    assert data["gpu_count"] == 2
    assert data["weight_file_shards"] == 3


def test_real_mistral_manifest_load_time_not_captured_but_elapsed_preserved():
    """Phase 21B.4.12.1 §3: no durable log line proved exact
    model-weight-load completion time, so load_time_seconds is honestly
    NOT_CAPTURED -- the ~1076s figure is preserved separately as
    attempt_elapsed_seconds (total elapsed-to-failure), never mislabeled
    as a load-time measurement."""
    data = load_manifest(MISTRAL_MANIFEST_PATH)
    assert data["load_time_seconds"] == NOT_CAPTURED
    assert data["evidence_strength"]["load_time_seconds"] == NOT_CAPTURED
    assert data["attempt_elapsed_seconds"] == pytest.approx(1075.9235696792603)


def test_real_mistral_manifest_vram_metrics_not_captured():
    """Phase 21B.4.12.1 §2: the originally captured 0.0 values came from
    the parent Modal Function process, not the vLLM tensor-parallel
    worker processes that actually held the model in GPU memory -- a
    measurement from the wrong process is not honest evidence of the
    real magnitude, so both fields must now be NOT_CAPTURED."""
    data = load_manifest(MISTRAL_MANIFEST_PATH)
    assert data["peak_allocated_vram_gb"] == NOT_CAPTURED
    assert data["peak_reserved_vram_gb"] == NOT_CAPTURED
    assert data["evidence_strength"]["peak_allocated_vram_gb"] == NOT_CAPTURED
    assert data["evidence_strength"]["peak_reserved_vram_gb"] == NOT_CAPTURED


def test_real_mistral_manifest_does_not_overclaim_runtime_defect():
    """Phase 21B.4.12.1 §6: the manifest must not claim the CUDA failure
    proves there is no vLLM/runtime defect -- only the immediate root
    cause actually observed."""
    data = load_manifest(MISTRAL_MANIFEST_PATH)
    detail = data["attempt_2_failure_detail"]
    assert "Observed immediate root cause" in detail
    assert "No model defect or topology insufficiency was demonstrated" in detail


# ── Phase 21B.4.12.3: the real, committed Mistral Small 4 QUALIFIED retry manifest ──


def test_real_mistral_retry_manifest_validates():
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    require_candidate_manifest(
        data,
        candidate="Mistral Small 4",
        repository="mistralai/Mistral-Small-4-119B-2603",
        revision="a11f36bebf709121056b1dbcc943d1c6afbe494d",
        qualification_type="PRODUCTION_SERVING_RUNTIME_QUALIFIED",
    )


def test_real_mistral_retry_manifest_bytes_verify():
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    verify_evidence_artifacts_bytes(data, REPO_ROOT)  # must not raise


def test_real_mistral_retry_manifest_generation_evidence_is_real():
    """Unlike the historical FAILED manifest, this QUALIFIED retry
    manifest must carry genuinely-captured generation-phase evidence --
    no NOT_CAPTURED sentinels for input/output tokens, latency, or
    response hash."""
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert data["input_tokens"] == 24
    assert data["output_tokens"] == 3
    assert data["generation_latency_seconds"] > 0
    assert data["tokens_per_second"] > 0
    assert data["decoded_response_sha256"] != NOT_CAPTURED
    assert data["synthetic_prompt_sha256"] != NOT_CAPTURED


def test_real_mistral_retry_manifest_two_successful_attempts_recorded():
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert data["load_attempt_count"] == 2
    assert data["attempt_1_result"] == "SUCCEEDED"
    assert data["attempt_2_result"] == "SUCCEEDED"
    assert data["attempt_1_failure_class"] is None
    assert data["attempt_2_failure_class"] is None


def test_real_mistral_retry_manifest_image_digest_resolved_not_invented():
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    env = json.loads((REPO_ROOT / data["evidence_artifacts"]["runtime_environment"]["path"]).read_text())
    assert env["image"]["repository"] == "vllm/vllm-openai"
    assert env["image"]["tag"] == "v0.29.0"
    assert env["image"]["resolved_digest"].startswith("sha256:")
    assert env["image"]["entrypoint_cleared"] is True


def test_real_mistral_retry_manifest_billing_gate_fresh_and_confirmed():
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert data["billing_gate_reconciliation"]["billing_gate_at_time_of_execution"] == BILLING_GATE_CONFIRMED_ZERO
    assert data["evidence_strength"]["billing_gate_at_time_of_execution"] == "OWNER_SCREENSHOT_VERIFIED"
    assert data["owner_billed_delta_usd"] == 0
    assert data["billed_before_usd"] == 0
    assert data["billed_after_usd"] == 0


def test_real_mistral_retry_manifest_load_time_from_durable_vllm_log_line():
    """Phase 21B.4.12.1's NOT_CAPTURED load_time_seconds correction was
    specifically because no durable log line existed in the historical
    FAILED attempt -- this retry's harness captured vLLM's own durable
    'Loading weights took X seconds' log line, so load_time_seconds
    must now be a genuinely-sourced real number, not NOT_CAPTURED."""
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert data["load_time_seconds"] == pytest.approx(27.67)
    assert data["evidence_strength"]["load_time_seconds"] == "OBSERVED_LIVE"


def test_real_mistral_retry_manifest_source_repo_sha_matches_phase_start():
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert data["source_repo_sha"] == "eb693e66794751aa18735b3c7506ed4b77b7e733"


def test_registry_mistral_retry_manifest_digest_matches_registry_linkage():
    registry_data = json.loads(REGISTRY_PATH.read_text())
    mistral = next(
        e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Mistral Small 4"
    )
    retry_data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert sha256_of_manifest(retry_data) == mistral["qualification_manifest_digest_sha256"]
    assert mistral["qualification_manifest_path"].endswith("MISTRAL_SMALL_4_RETRY.json")


# ── Phase 21B.4.12.4: qualified-evidence semantics reconciliation ──


def test_real_mistral_retry_manifest_weight_file_shards_is_repository_fact():
    """Phase 21B.4.12.4 §6: weight_file_shards must reflect the
    repository's own published weight index (3), not the runtime's
    on-disk file selection (7) -- restored after Phase 21B.4.12.3
    mistakenly recorded the runtime-observed count in this field."""
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert data["weight_file_shards"] == 3
    assert data["evidence_strength"]["weight_file_shards"] == "REPOSITORY_VERIFIED"


def test_real_mistral_retry_manifest_runtime_loaded_weight_files_is_separate_fact():
    """Phase 21B.4.12.4 §7: the runtime-observed 7-file consolidated
    checkpoint load is recorded in its own field, never conflated with
    the repository's 3-shard HF index fact."""
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert data[RUNTIME_LOADED_WEIGHT_FILES_FIELD] == 7
    assert data["weight_file_shards"] != data[RUNTIME_LOADED_WEIGHT_FILES_FIELD]


def test_real_mistral_retry_manifest_peak_vram_not_captured_with_alternate_evidence():
    """Phase 21B.4.12.4 §3/§4: peak_allocated/reserved_vram_gb are
    NOT_CAPTURED (not a misleading wrong-process 0.0), justified by
    genuine structured runtime_worker_memory evidence sourced verbatim
    from the canonical attempt-2 log."""
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert data["peak_allocated_vram_gb"] == NOT_CAPTURED
    assert data["peak_reserved_vram_gb"] == NOT_CAPTURED
    assert data["evidence_strength"]["peak_allocated_vram_gb"] == NOT_CAPTURED
    assert data["evidence_strength"]["peak_reserved_vram_gb"] == NOT_CAPTURED
    worker_mem = data[RUNTIME_WORKER_MEMORY_FIELD]
    assert worker_mem["per_gpu"]["consumed_memory_gib"] == 57.45
    assert worker_mem["per_gpu"]["peak_activation_gib"] == 0.54
    assert worker_mem["per_gpu"]["cudagraph_memory_gib"] == 0.08
    assert worker_mem["per_gpu"]["kv_cache_memory_gib"] == 60.84
    assert worker_mem["workers_observed"] == 2


def test_real_mistral_retry_manifest_still_production_serving_qualified():
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert data["qualification_type"] == "PRODUCTION_SERVING_RUNTIME_QUALIFIED"
    assert data["load_time_seconds"] == pytest.approx(27.67)


def test_real_mistral_retry_manifest_all_seven_historical_artifacts_unchanged():
    """All seven Phase 21B.4.12.3 evidence-artifact files, plus the
    canonical execution log, must still byte-verify unchanged after the
    Phase 21B.4.12.4 semantics-only corrections -- no historical
    evidence bytes were touched."""
    data = load_manifest(MISTRAL_RETRY_MANIFEST_PATH)
    assert len(data["evidence_artifacts"]) == len(EVIDENCE_ARTIFACT_KEYS)
    verify_evidence_artifacts_bytes(data, REPO_ROOT)  # must not raise


def test_mistral_retry_end_to_end_verifier_passes_after_reconciliation():
    from orca.eval.candidate_registry import verify_candidate_qualification_end_to_end

    entry, manifest = verify_candidate_qualification_end_to_end(
        REGISTRY_PATH, "Mistral Small 4", manifest_root=REPO_ROOT, require_qualified=True
    )
    assert entry["runtime_qualification_status"] == "QUALIFIED"
    assert manifest["qualification_type"] == "PRODUCTION_SERVING_RUNTIME_QUALIFIED"
    assert manifest["weight_file_shards"] == 3
    assert manifest[RUNTIME_LOADED_WEIGHT_FILES_FIELD] == 7


def test_real_mistral_manifest_billing_gate_confirmed_for_executed_run():
    data = load_manifest(MISTRAL_MANIFEST_PATH)
    assert data["billing_gate_reconciliation"]["billing_gate_at_time_of_execution"] == BILLING_GATE_CONFIRMED_ZERO
    assert data["evidence_strength"]["billing_gate_at_time_of_execution"] == "OWNER_SCREENSHOT_VERIFIED"
    assert data["owner_billed_delta_usd"] == 0


def test_real_mistral_manifest_two_distinct_failure_classes_recorded():
    data = load_manifest(MISTRAL_MANIFEST_PATH)
    assert data["attempt_1_failure_class"] == "RUNTIME_VERSION_MISMATCH"
    assert data["attempt_2_failure_class"] == "CUDA_KERNEL_FAILURE"
    assert data["load_attempt_count"] == 2


def test_registry_mistral_entry_links_manifest_by_matching_digest():
    """Phase 21B.4.12.3: the registry now links Mistral Small 4 to its
    successful RETRY manifest (QUALIFIED), not the original FAILED
    manifest -- the historical FAILED manifest is preserved on disk
    (see the test_real_mistral_manifest_* tests above, which load it
    directly by its own fixed path) but is no longer the registry's
    current linkage target."""
    registry_data = json.loads(REGISTRY_PATH.read_text())
    mistral = next(
        e for e in registry_data["deployable_candidates"] if e["canonical_candidate_name"] == "Mistral Small 4"
    )
    manifest_data = load_manifest(REPO_ROOT / mistral["qualification_manifest_path"])
    assert sha256_of_manifest(manifest_data) == mistral["qualification_manifest_digest_sha256"]
    assert mistral["runtime_qualification_status"] == "QUALIFIED"
    assert mistral["qualification_type"] == "PRODUCTION_SERVING_RUNTIME_QUALIFIED"
    assert "RETRY" in mistral["qualification_manifest_path"]


def test_mistral_now_qualified_and_inspectable_end_to_end():
    """Phase 21B.4.12.3: Mistral Small 4's live retry succeeded --
    the registry now links to the QUALIFIED retry manifest, verifiable
    via both the require_qualified=True acceptance path and the
    require_qualified=False inspection path (which returns the same
    manifest for a QUALIFIED candidate, not just a non-QUALIFIED one)."""
    from orca.eval.candidate_registry import verify_candidate_qualification_end_to_end
    entry, manifest = verify_candidate_qualification_end_to_end(
        REGISTRY_PATH, "Mistral Small 4", manifest_root=REPO_ROOT, require_qualified=False
    )
    assert entry["runtime_qualification_status"] == "QUALIFIED"
    assert manifest is not None
    assert manifest["qualification_type"] == "PRODUCTION_SERVING_RUNTIME_QUALIFIED"
    assert manifest["candidate"] == "Mistral Small 4"
    assert sha256_of_manifest(manifest) == entry["qualification_manifest_digest_sha256"]

    entry2, manifest2 = verify_candidate_qualification_end_to_end(
        REGISTRY_PATH, "Mistral Small 4", manifest_root=REPO_ROOT, require_qualified=True
    )
    assert manifest2 is not None
    assert sha256_of_manifest(manifest2) == sha256_of_manifest(manifest)


def test_verify_recorded_manifest_linkage_returns_real_manifest_for_historical_failed_result():
    """Phase 21B.4.12.1 §5 behavior (a linked RUNTIME_QUALIFICATION_FAILED
    manifest returns fully verified, not None) is still exercised here
    using Mistral Small 4's historical Phase 21B.4.12 FAILED manifest
    directly -- that manifest and its evidence bundle remain byte-
    identical and independently verifiable on disk even though the
    registry's current linkage now points at the later successful
    retry (Phase 21B.4.12.3) instead."""
    from orca.eval.candidate_registry import verify_recorded_manifest_linkage

    historical_manifest = load_manifest(MISTRAL_MANIFEST_PATH)
    entry = {
        "canonical_candidate_name": "Mistral Small 4",
        "artifact_repository": historical_manifest["artifact_repository"],
        "exact_immutable_revision": historical_manifest["exact_revision"],
        "qualification_type": "RUNTIME_QUALIFICATION_FAILED",
        "qualification_manifest_path": "docs/orneur/phase-21/GENESIS_RUNTIME_QUALIFICATION_MANIFEST_MISTRAL_SMALL_4.json",
        "qualification_manifest_digest_sha256": sha256_of_manifest(historical_manifest),
    }
    manifest = verify_recorded_manifest_linkage(entry, REPO_ROOT)
    assert manifest is not None
    assert manifest["qualification_type"] == "RUNTIME_QUALIFICATION_FAILED"


def test_verify_recorded_manifest_linkage_returns_none_when_never_smoke_tested():
    from orca.eval.candidate_registry import verify_recorded_manifest_linkage

    entry = {
        "canonical_candidate_name": "Never-Smoke-Tested",
        "runtime_qualification_status": "UNQUALIFIED",
        "qualification_type": None,
        "qualification_manifest_path": None,
        "qualification_manifest_digest_sha256": None,
    }
    assert verify_recorded_manifest_linkage(entry, REPO_ROOT) is None


def test_tampered_failed_manifest_digest_mismatch_fails_closed(tmp_path):
    """Phase 21B.4.12.1 §8: a tampered FAILED manifest (content changed
    after its digest was recorded) must fail closed via the
    status-independent verifier, exactly like a tampered QUALIFIED one."""
    from orca.eval.candidate_registry import verify_recorded_manifest_linkage

    manifest = _failed_before_generation_manifest()
    manifest["candidate"] = "Mistral Small 4"
    manifest["artifact_repository"] = "mistralai/Mistral-Small-4-119B-2603"
    manifest["exact_revision"] = "a11f36bebf709121056b1dbcc943d1c6afbe494d"
    manifest["tokenizer_repository"] = "mistralai/Mistral-Small-4-119B-2603"
    manifest["tokenizer_revision"] = "a11f36bebf709121056b1dbcc943d1c6afbe494d"
    root = _write_evidence_bundle(tmp_path, manifest)
    digest = sha256_of_manifest(manifest)

    manifest_rel_path = "synthetic_failed_manifest.json"
    (root / manifest_rel_path).write_text(json.dumps(manifest))

    entry = {
        "canonical_candidate_name": "Mistral Small 4",
        "artifact_repository": manifest["artifact_repository"],
        "exact_immutable_revision": manifest["exact_revision"],
        "runtime_qualification_status": "UNQUALIFIED",
        "qualification_type": manifest["qualification_type"],
        "qualification_manifest_path": manifest_rel_path,
        "qualification_manifest_digest_sha256": digest,
    }

    # Tamper with the on-disk manifest content AFTER the digest was
    # recorded -- content still parses/validates, but no longer matches
    # the registry's declared digest.
    tampered = dict(manifest)
    tampered["attempt_1_failure_class"] = "SOMETHING_ELSE"
    (root / manifest_rel_path).write_text(json.dumps(tampered))

    with pytest.raises(RegistrySchemaError, match="manifest digest mismatch"):
        verify_recorded_manifest_linkage(entry, root)


def test_tampered_failed_manifest_artifact_bytes_fail_closed(tmp_path):
    """Phase 21B.4.12.1 §8: tampering with a FAILED manifest's declared
    evidence-artifact bytes (after the manifest itself was finalized)
    must fail closed via the status-independent verifier."""
    from orca.eval.candidate_registry import verify_recorded_manifest_linkage

    manifest = _failed_before_generation_manifest()
    manifest["candidate"] = "Mistral Small 4"
    manifest["artifact_repository"] = "mistralai/Mistral-Small-4-119B-2603"
    manifest["exact_revision"] = "a11f36bebf709121056b1dbcc943d1c6afbe494d"
    manifest["tokenizer_repository"] = "mistralai/Mistral-Small-4-119B-2603"
    manifest["tokenizer_revision"] = "a11f36bebf709121056b1dbcc943d1c6afbe494d"
    root = _write_evidence_bundle(tmp_path, manifest)
    digest = sha256_of_manifest(manifest)

    manifest_rel_path = "synthetic_failed_manifest.json"
    (root / manifest_rel_path).write_text(json.dumps(manifest))

    entry = {
        "canonical_candidate_name": "Mistral Small 4",
        "artifact_repository": manifest["artifact_repository"],
        "exact_immutable_revision": manifest["exact_revision"],
        "runtime_qualification_status": "UNQUALIFIED",
        "qualification_type": manifest["qualification_type"],
        "qualification_manifest_path": manifest_rel_path,
        "qualification_manifest_digest_sha256": digest,
    }

    (root / manifest["evidence_artifacts"]["execution_log"]["path"]).write_bytes(b"tampered after the fact")

    with pytest.raises(RegistrySchemaError, match="strict evidence-artifact verification failed"):
        verify_recorded_manifest_linkage(entry, root)
