"""
Genesis Runtime Qualification Manifest schema.
Phase 21B.4.11.1: versioned schema + canonical-JSON digest, replacing
free-form registry prose.
Phase 21B.4.11.2: evidence_protocol_generation (legacy vs. strict),
full evidence_strength coverage, numeric/attempt-state/cross-field
invariants.
Phase 21B.4.11.3: state-discriminated field requirements (QUALIFIED /
RUNTIME_QUALIFICATION_FAILED / DEFERRED_FOR_COMPUTE no longer share one
success-only field set -- a FAILED-before-generation or
DEFERRED_FOR_COMPUTE manifest is never forced to fabricate a response
hash, VRAM number, or GPU allocation it never had), structured
`evidence_artifacts` for STRICT_RUNTIME_SMOKE_V2 (billing-before,
model-identity, runtime-environment, execution-log, cleanup,
billing-after, each a real file verified byte-for-byte against its
declared SHA-256 -- not merely a filename/hash pair whose format looks
right), and a single fail-closed `verify_runtime_qualification_bundle()`
entry point so future candidate code cannot accidentally accept a
QUALIFIED bundle by skipping one verification step.

This module performs SCHEMA validation (`validate_manifest`) and, when
given a controlled evidence root, ACTUAL ARTIFACT-BYTE verification
(`verify_evidence_artifacts_bytes`) -- it makes no capability, license,
or frontier-class judgment, and it does not execute anything itself.
Nothing here downloads a model, starts a GPU, or runs inference.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from pathlib import Path

MANIFEST_SCHEMA_VERSION = "genesis-runtime-qualification-manifest-v1"

_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

NOT_CAPTURED = "NOT_CAPTURED"

VALID_QUALIFICATION_TYPES = (
    "RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
    "PRODUCTION_SERVING_RUNTIME_QUALIFIED",
    "RUNTIME_QUALIFICATION_FAILED",
    "DEFERRED_FOR_COMPUTE",
)

QUALIFIED_TYPES = ("RUNTIME_LOAD_COMPATIBILITY_QUALIFIED", "PRODUCTION_SERVING_RUNTIME_QUALIFIED")
DEFERRED_TYPE = "DEFERRED_FOR_COMPUTE"
FAILED_TYPE = "RUNTIME_QUALIFICATION_FAILED"

VALID_ATTEMPT_RESULTS = ("SUCCEEDED", "FAILED", "NOT_ATTEMPTED")

VALID_EVIDENCE_STRENGTHS = (
    "OBSERVED_LIVE",
    "DERIVED",
    "REPORTED_BY_CLAUDE",
    "REPOSITORY_VERIFIED",
    "OWNER_SCREENSHOT_VERIFIED",
    NOT_CAPTURED,
)

# Phase 21B.4.11.2 §1: the ONLY grandfathered exception. A future
# manifest generation MUST be STRICT_RUNTIME_SMOKE_V2 -- adding a new
# generation name here is how any future relaxation would have to be
# made explicit, rather than silently reusing LEGACY_RECONCILED_V1.
EVIDENCE_PROTOCOL_LEGACY = "LEGACY_RECONCILED_V1"
EVIDENCE_PROTOCOL_STRICT = "STRICT_RUNTIME_SMOKE_V2"
VALID_EVIDENCE_PROTOCOL_GENERATIONS = (EVIDENCE_PROTOCOL_LEGACY, EVIDENCE_PROTOCOL_STRICT)

_NOT_PRESERVED_LOG_VALUES = frozenset({None, "", "NOT_PRESERVED", "NONE"})

# Phase 21B.4.11.3 §3: the six durable evidence categories a
# STRICT_RUNTIME_SMOKE_V2 manifest must bind to real, byte-verified
# files before a candidate may be marked QUALIFIED.
EVIDENCE_ARTIFACT_KEYS = (
    "billing_gate",
    "billing_before",
    "model_identity",
    "runtime_environment",
    "execution_log",
    "cleanup",
    "billing_after",
)

# Phase 21B.4.11.4 §2: the ONLY value of billing_gate_at_time_of_execution
# that authorizes a STRICT executed (load_attempt_count > 0) run. Any
# other value -- including the historical NOT_INDEPENDENTLY_PROVEN --
# means the owner-paid spend ceiling was not confirmed at $0 for this
# specific execution, and a GPU run may not be accepted as QUALIFIED
# (or FAILED-after-a-real-attempt) on that basis.
BILLING_GATE_CONFIRMED_ZERO = "CONFIRMED_ZERO_SPEND_LIMIT"

REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version",
    "evidence_protocol_generation",
    "qualification_id",
    "candidate",
    "artifact_repository",
    "exact_revision",
    "tokenizer_repository",
    "tokenizer_revision",
    "license_identifier",
    "qualification_type",
    "deferral_reason",
    "runtime",
    "runtime_versions",
    "python_version",
    "pytorch_version",
    "cuda_version",
    "transformers_version",
    "trust_remote_code",
    "gpu_provider",
    "gpu_model",
    "gpu_count",
    "precision",
    "vram_capacity_gb",
    "peak_allocated_vram_gb",
    "peak_reserved_vram_gb",
    "weight_file_shards",
    "runtime_materialized_tensor_count",
    "load_attempt_count",
    "attempt_1_result",
    "attempt_1_failure_class",
    "attempt_2_result",
    "attempt_2_failure_class",
    "load_time_seconds",
    "synthetic_prompt_class",
    "synthetic_prompt_sha256",
    "decoded_response_sha256",
    "input_tokens",
    "output_tokens",
    "generation_latency_seconds",
    "ttft_seconds",
    "tokens_per_second",
    "benchmark_prompt_exposed",
    "genesis_eval_executed",
    "generated_output_executed",
    "persistent_volume_used",
    "metered_before_usd",
    "metered_after_usd",
    "metered_delta_usd",
    "billed_before_usd",
    "billed_after_usd",
    "owner_billed_delta_usd",
    "cleanup_status",
    "active_resources_after",
    "created_at",
    "execution_time",
    "source_repo_sha",
    "billing_gate_reconciliation",
    "raw_execution_log_artifact",
    "evidence_strength",
)

# Phase 21B.4.11.2 §3: the locked set of evidence-bearing fields.
# evidence_strength must cover EXACTLY this set -- no more, no fewer --
# so a manifest can no longer pass with provenance tags for only a
# small subset of what it claims as evidence. Purely structural/
# identity fields (schema_version, qualification_id, candidate names,
# repository strings, revision hashes -- already format-validated
# elsewhere) and free-form narrative fields are intentionally excluded.
EVIDENCE_BEARING_FIELDS = frozenset({
    "exact_revision",
    "tokenizer_revision",
    "license_identifier",
    "weight_file_shards",
    "runtime_materialized_tensor_count",
    "gpu_model",
    "gpu_count",
    "vram_capacity_gb",
    "peak_allocated_vram_gb",
    "peak_reserved_vram_gb",
    "load_time_seconds",
    "input_tokens",
    "output_tokens",
    "generation_latency_seconds",
    "decoded_response_sha256",
    "synthetic_prompt_sha256",
    "tokens_per_second",
    "ttft_seconds",
    "cuda_version",
    "metered_before_usd",
    "metered_after_usd",
    "billed_before_usd",
    "billed_after_usd",
    "billing_gate_at_time_of_execution",
    "cleanup_status",
    "active_resources_after",
})

# Phase 21B.4.11.3 §6: fields whose manifest VALUE (not merely its
# evidence_strength tag) is legitimately allowed to be the literal
# sentinel NOT_CAPTURED -- and whose evidence_strength MUST then also
# read NOT_CAPTURED, never the reverse mismatch of one without the
# other. Descriptive/always-real fields (exact_revision, gpu_model,
# billing_gate_at_time_of_execution, billed/metered dollar amounts,
# cleanup_status, active_resources_after) are intentionally excluded --
# those are never legitimately "absent," only ever a real value.
_SENTINEL_ELIGIBLE_FIELDS = frozenset({
    "cuda_version",
    "ttft_seconds",
    "weight_file_shards",
    "runtime_materialized_tensor_count",
    "gpu_count",
    "vram_capacity_gb",
    "peak_allocated_vram_gb",
    "peak_reserved_vram_gb",
    "load_time_seconds",
    "input_tokens",
    "output_tokens",
    "generation_latency_seconds",
    "tokens_per_second",
    "synthetic_prompt_sha256",
    "decoded_response_sha256",
})

# Load-phase fields: legitimately NOT_CAPTURED only when zero load
# attempts were made at all (DEFERRED_FOR_COMPUTE with load_attempt_count==0).
_LOAD_PHASE_NUMERIC_FIELDS = (
    "vram_capacity_gb",
    "peak_allocated_vram_gb",
    "peak_reserved_vram_gb",
    "load_time_seconds",
)
_LOAD_PHASE_INT_FIELDS = ("weight_file_shards", "runtime_materialized_tensor_count")

# Generation-phase fields: legitimately NOT_CAPTURED whenever the
# qualification_type isn't one of the QUALIFIED types (a FAILED attempt
# may never have reached generation; a DEFERRED run never attempted it).
_GENERATION_PHASE_NUMERIC_FIELDS = ("input_tokens", "output_tokens", "generation_latency_seconds", "tokens_per_second")
_GENERATION_PHASE_HASH_FIELDS = ("synthetic_prompt_sha256", "decoded_response_sha256")


class RuntimeQualificationManifestError(ValueError):
    """A runtime qualification manifest fails structural or artifact-
    byte verification."""


def canonical_json_bytes(data: dict) -> bytes:
    """The exact byte sequence whose SHA-256 digest is the manifest's
    content hash -- sorted keys, no extraneous whitespace, so the
    digest is reproducible regardless of how the JSON was formatted on
    disk."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_of_manifest(data: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()


def _require_fields(entry: dict, fields: tuple[str, ...]) -> None:
    missing = [f for f in fields if f not in entry]
    if missing:
        raise RuntimeQualificationManifestError(f"manifest missing required field(s): {missing}")


def _require_number(data: dict, field: str, *, strictly_positive: bool = False, allow_sentinel: bool = False) -> None:
    value = data[field]
    if allow_sentinel and value == NOT_CAPTURED:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeQualificationManifestError(f"{field} must be a real number, not {type(value).__name__}")
    if not math.isfinite(value):
        raise RuntimeQualificationManifestError(f"{field} must be finite (no NaN/Inf)")
    if strictly_positive and value <= 0:
        raise RuntimeQualificationManifestError(f"{field} must be > 0")
    if value < 0:
        raise RuntimeQualificationManifestError(f"{field} must be >= 0")


def _require_int_at_least(data: dict, field: str, minimum: int, *, allow_sentinel: bool = False) -> None:
    value = data[field]
    if allow_sentinel and value == NOT_CAPTURED:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeQualificationManifestError(f"{field} must be an integer, not {type(value).__name__}")
    if value < minimum:
        raise RuntimeQualificationManifestError(f"{field} must be >= {minimum}")


def _require_hash(data: dict, field: str, *, allow_sentinel: bool = False) -> None:
    value = data[field]
    if allow_sentinel and value == NOT_CAPTURED:
        return
    if not isinstance(value, str) or not _HEX64_RE.match(value):
        raise RuntimeQualificationManifestError(
            f"{field} must be exactly 64 lowercase hex characters (SHA-256)"
            + (f", or {NOT_CAPTURED!r}" if allow_sentinel else "")
        )


def _require_tzaware_iso8601(value, *, field: str) -> None:
    if not isinstance(value, str):
        raise RuntimeQualificationManifestError(f"{field} must be a string, not {type(value).__name__}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as e:
        raise RuntimeQualificationManifestError(f"{field} must be a valid ISO-8601 datetime: {value!r}") from e
    if parsed.tzinfo is None:
        raise RuntimeQualificationManifestError(f"{field} must be timezone-aware (got a naive datetime): {value!r}")


def _require_legacy_created_at(value) -> None:
    """Under the legacy generation, created_at may be a bare date
    (when the exact execution time genuinely was not preserved) or a
    full ISO-8601 datetime (naive or timezone-aware)."""
    if not isinstance(value, str):
        raise RuntimeQualificationManifestError(f"created_at must be a string, not {type(value).__name__}")
    try:
        date.fromisoformat(value)
        return
    except ValueError:
        pass
    try:
        datetime.fromisoformat(value)
    except ValueError as e:
        raise RuntimeQualificationManifestError(f"created_at must be a valid ISO-8601 date or datetime: {value!r}") from e


def validate_manifest(data: dict) -> None:
    """Structural (and, for STRICT manifests, artifact-shape but not
    yet byte-level) validation. Raises RuntimeQualificationManifestError
    on any violation. Use `verify_evidence_artifacts_bytes` separately
    (or `verify_runtime_qualification_bundle`) to check that a STRICT
    manifest's declared artifacts actually exist on disk with matching
    content -- this function alone never touches the filesystem."""
    if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RuntimeQualificationManifestError(
            f"Unsupported schema_version {data.get('schema_version')!r}, expected {MANIFEST_SCHEMA_VERSION!r}"
        )
    _require_fields(data, REQUIRED_TOP_LEVEL_FIELDS)

    if not _HEX40_RE.match(data["exact_revision"]):
        raise RuntimeQualificationManifestError("exact_revision must be exactly 40 lowercase hex characters")
    if not _HEX40_RE.match(data["tokenizer_revision"]):
        raise RuntimeQualificationManifestError("tokenizer_revision must be exactly 40 lowercase hex characters")
    if not _HEX40_RE.match(data["source_repo_sha"]):
        raise RuntimeQualificationManifestError("source_repo_sha must be exactly 40 lowercase hex characters")

    qualification_type = data["qualification_type"]
    if qualification_type not in VALID_QUALIFICATION_TYPES:
        raise RuntimeQualificationManifestError(f"unrecognized qualification_type {qualification_type!r}")

    # ── Phase 21B.4.11.3 §4/§9: deferral_reason discipline ────────────
    deferral_reason = data["deferral_reason"]
    if qualification_type == DEFERRED_TYPE:
        if not deferral_reason or not isinstance(deferral_reason, str):
            raise RuntimeQualificationManifestError("DEFERRED_FOR_COMPUTE requires a non-empty deferral_reason")
    elif deferral_reason:
        raise RuntimeQualificationManifestError(
            "deferral_reason must be null/empty unless qualification_type==DEFERRED_FOR_COMPUTE"
        )

    attempt_1_result = data["attempt_1_result"]
    attempt_2_result = data["attempt_2_result"]
    for field, value in (("attempt_1_result", attempt_1_result), ("attempt_2_result", attempt_2_result)):
        if value not in VALID_ATTEMPT_RESULTS:
            raise RuntimeQualificationManifestError(f"{field} has unrecognized value {value!r}")

    # Benchmark/generated-code execution must never be true, and no
    # persistent Volume may be used, regardless of protocol generation
    # or qualification_type.
    for field in ("benchmark_prompt_exposed", "genesis_eval_executed", "generated_output_executed"):
        if data[field] is not False:
            raise RuntimeQualificationManifestError(
                f"{field} must be false -- a runtime qualification manifest must never record benchmark/"
                "generated-code execution"
            )
    if data["persistent_volume_used"] is not False:
        raise RuntimeQualificationManifestError("persistent_volume_used must be false")

    # ── Phase 21B.4.11.3 §4: load_attempt_count, gated by DEFERRED ────
    min_attempts = 0 if qualification_type == DEFERRED_TYPE else 1
    _require_int_at_least(data, "load_attempt_count", min_attempts)
    load_attempt_count = data["load_attempt_count"]
    zero_attempts = load_attempt_count == 0
    not_qualified = qualification_type not in QUALIFIED_TYPES

    if zero_attempts:
        if attempt_1_result != "NOT_ATTEMPTED" or attempt_2_result != "NOT_ATTEMPTED":
            raise RuntimeQualificationManifestError(
                "load_attempt_count==0 requires both attempt_1_result and attempt_2_result to be NOT_ATTEMPTED"
            )
    else:
        if load_attempt_count == 1 and attempt_2_result != "NOT_ATTEMPTED":
            raise RuntimeQualificationManifestError("load_attempt_count==1 requires attempt_2_result==NOT_ATTEMPTED")
        if load_attempt_count >= 2 and attempt_2_result == "NOT_ATTEMPTED":
            raise RuntimeQualificationManifestError(
                "load_attempt_count>=2 requires attempt_2_result to not be NOT_ATTEMPTED"
            )

    attempts = (attempt_1_result, attempt_2_result)
    if qualification_type in QUALIFIED_TYPES and "SUCCEEDED" not in attempts:
        raise RuntimeQualificationManifestError(
            f"{qualification_type} requires at least one attempt to have SUCCEEDED"
        )
    if qualification_type == FAILED_TYPE and "SUCCEEDED" in attempts:
        raise RuntimeQualificationManifestError(f"{FAILED_TYPE} must not have any SUCCEEDED attempt")
    if qualification_type == DEFERRED_TYPE and "SUCCEEDED" in attempts:
        raise RuntimeQualificationManifestError(f"{DEFERRED_TYPE} must not have any SUCCEEDED attempt")

    if attempt_1_result == "FAILED" and not data.get("attempt_1_failure_class"):
        raise RuntimeQualificationManifestError("attempt_1_result==FAILED requires attempt_1_failure_class to be set")
    if attempt_1_result == "SUCCEEDED" and data.get("attempt_1_failure_class"):
        raise RuntimeQualificationManifestError("attempt_1_result==SUCCEEDED must not carry a failure classification")
    if attempt_2_result == "FAILED" and not data.get("attempt_2_failure_class"):
        raise RuntimeQualificationManifestError("attempt_2_result==FAILED requires attempt_2_failure_class to be set")
    if attempt_2_result == "SUCCEEDED" and data.get("attempt_2_failure_class"):
        raise RuntimeQualificationManifestError("attempt_2_result==SUCCEEDED must not carry a failure classification")

    # ── Phase 21B.4.11.3 §4/§6: state-discriminated numeric/hash fields ──
    # These are REQUIRED to be the sentinel (not merely permitted to be)
    # when the corresponding phase never happened -- otherwise a caller
    # could invent a real-looking value for a phase that never ran, as
    # long as it also (falsely) tagged evidence_strength to match.
    if zero_attempts:
        for field in ("gpu_count",) + _LOAD_PHASE_NUMERIC_FIELDS + _LOAD_PHASE_INT_FIELDS:
            if data[field] != NOT_CAPTURED:
                raise RuntimeQualificationManifestError(
                    f"{field} must be {NOT_CAPTURED!r} when load_attempt_count==0 -- no load was ever attempted"
                )
    else:
        _require_int_at_least(data, "gpu_count", 1)
        _require_number(data, "vram_capacity_gb", strictly_positive=True)
        for field in _LOAD_PHASE_NUMERIC_FIELDS[1:]:  # peak_allocated/reserved, load_time
            _require_number(data, field)
        for field in _LOAD_PHASE_INT_FIELDS:
            _require_int_at_least(data, field, 1)

    if not_qualified:
        for field in _GENERATION_PHASE_NUMERIC_FIELDS + _GENERATION_PHASE_HASH_FIELDS:
            if data[field] != NOT_CAPTURED:
                raise RuntimeQualificationManifestError(
                    f"{field} must be {NOT_CAPTURED!r} when qualification_type is not QUALIFIED -- "
                    "no generation evidence exists for a FAILED or DEFERRED run"
                )
    else:
        for field in _GENERATION_PHASE_NUMERIC_FIELDS:
            _require_number(data, field)
        for field in _GENERATION_PHASE_HASH_FIELDS:
            _require_hash(data, field)
    ttft = data["ttft_seconds"]
    if ttft != NOT_CAPTURED:
        if isinstance(ttft, bool) or not isinstance(ttft, (int, float)) or not math.isfinite(ttft) or ttft < 0:
            raise RuntimeQualificationManifestError(f"ttft_seconds must be {NOT_CAPTURED!r} or a finite number >= 0")

    for field in ("metered_before_usd", "metered_after_usd", "metered_delta_usd",
                  "billed_before_usd", "billed_after_usd", "owner_billed_delta_usd"):
        _require_number(data, field)

    # ── Phase 21B.4.11.2 §5: metered/billed cross-field arithmetic ────
    if not math.isclose(
        data["metered_after_usd"] - data["metered_before_usd"], data["metered_delta_usd"], abs_tol=1e-9
    ):
        raise RuntimeQualificationManifestError(
            "metered_after_usd - metered_before_usd must equal metered_delta_usd"
        )
    if not math.isclose(
        data["billed_after_usd"] - data["billed_before_usd"], data["owner_billed_delta_usd"], abs_tol=1e-9
    ):
        raise RuntimeQualificationManifestError(
            "billed_after_usd - billed_before_usd must equal owner_billed_delta_usd"
        )
    if data["owner_billed_delta_usd"] != 0:
        raise RuntimeQualificationManifestError(
            "owner_billed_delta_usd must be exactly 0 for accepted runtime-smoke evidence"
        )
    if data["billed_before_usd"] != 0 or data["billed_after_usd"] != 0:
        raise RuntimeQualificationManifestError(
            "billed_before_usd and billed_after_usd must both be exactly 0 -- ORNEUR's zero-owner-cash "
            "policy applies to every accepted qualification manifest, not only QUALIFIED ones"
        )

    # ── Phase 21B.4.11.2 §7: QUALIFIED result invariants ──────────────
    if qualification_type in QUALIFIED_TYPES:
        if data["cleanup_status"] != "CONFIRMED_ZERO_ACTIVE_RESOURCES":
            raise RuntimeQualificationManifestError(
                f"{qualification_type} requires cleanup_status==CONFIRMED_ZERO_ACTIVE_RESOURCES"
            )
        active = data["active_resources_after"]
        if not isinstance(active, str) or not active.upper().startswith("NONE"):
            raise RuntimeQualificationManifestError(
                f"{qualification_type} requires active_resources_after to indicate NONE"
            )

    # ── evidence_strength: exact coverage of EVIDENCE_BEARING_FIELDS ──
    evidence_strength = data["evidence_strength"]
    if not isinstance(evidence_strength, dict) or not evidence_strength:
        raise RuntimeQualificationManifestError("evidence_strength must be a non-empty mapping")
    bad_values = {k: v for k, v in evidence_strength.items() if v not in VALID_EVIDENCE_STRENGTHS}
    if bad_values:
        raise RuntimeQualificationManifestError(f"evidence_strength has unrecognized value(s): {bad_values}")
    missing_evidence = EVIDENCE_BEARING_FIELDS - set(evidence_strength.keys())
    extra_evidence = set(evidence_strength.keys()) - EVIDENCE_BEARING_FIELDS
    if missing_evidence or extra_evidence:
        raise RuntimeQualificationManifestError(
            "evidence_strength must cover exactly the locked evidence-bearing field set -- "
            f"missing={sorted(missing_evidence)}, extra={sorted(extra_evidence)}"
        )

    # Phase 21B.4.11.3 §6: a sentinel-eligible field's VALUE and its
    # evidence_strength TAG must agree on absence -- neither may claim
    # NOT_CAPTURED while the other carries something concrete.
    for field in _SENTINEL_ELIGIBLE_FIELDS:
        value = data[field]
        strength = evidence_strength[field]
        value_is_nc = value == NOT_CAPTURED
        if value_is_nc and strength != NOT_CAPTURED:
            raise RuntimeQualificationManifestError(
                f"{field} has value {NOT_CAPTURED} but evidence_strength={strength!r} -- must also be {NOT_CAPTURED}"
            )
        if strength == NOT_CAPTURED and not value_is_nc:
            raise RuntimeQualificationManifestError(
                f"{field} has evidence_strength={NOT_CAPTURED} but carries a real value ({value!r}) -- "
                "a field cannot claim no evidence while providing a concrete value"
            )

    gate = data["billing_gate_reconciliation"]
    _require_fields(gate, ("billing_gate_at_time_of_execution", "owner_billed_result", "financial_impact"))

    # ── Phase 21B.4.11.4 §2: a STRICT manifest that actually executed a
    # load attempt (load_attempt_count > 0) must be backed by a
    # positively-confirmed, owner-verified $0 spend ceiling -- never
    # merely a Claude-reported, derived, or absent claim. This is
    # checked here (independent of the artifact-bytes section below)
    # because it is a schema-level authorization requirement, not
    # merely a file-existence one.
    protocol = data["evidence_protocol_generation"]
    if protocol == EVIDENCE_PROTOCOL_STRICT and not zero_attempts:
        if gate["billing_gate_at_time_of_execution"] != BILLING_GATE_CONFIRMED_ZERO:
            raise RuntimeQualificationManifestError(
                "a STRICT_RUNTIME_SMOKE_V2 manifest with load_attempt_count>0 requires "
                f"billing_gate_reconciliation.billing_gate_at_time_of_execution == {BILLING_GATE_CONFIRMED_ZERO!r} "
                f"(got {gate['billing_gate_at_time_of_execution']!r}) -- an executed GPU run may never be "
                "accepted without a positively confirmed owner $0 spend ceiling."
            )
        billing_gate_strength = evidence_strength.get("billing_gate_at_time_of_execution")
        if billing_gate_strength != "OWNER_SCREENSHOT_VERIFIED":
            raise RuntimeQualificationManifestError(
                "a STRICT_RUNTIME_SMOKE_V2 manifest with load_attempt_count>0 requires "
                "evidence_strength['billing_gate_at_time_of_execution'] == 'OWNER_SCREENSHOT_VERIFIED' "
                f"(got {billing_gate_strength!r}) -- REPORTED_BY_CLAUDE, DERIVED, and NOT_CAPTURED may "
                "never authorize a GPU execution."
            )

    # ── Phase 21B.4.11.2 §1/§2, hardened 21B.4.11.3 §3, 21B.4.11.4 §1: protocol-generation-gated rules ──
    if protocol not in VALID_EVIDENCE_PROTOCOL_GENERATIONS:
        raise RuntimeQualificationManifestError(f"unrecognized evidence_protocol_generation {protocol!r}")

    execution_time = data["execution_time"]
    if execution_time != NOT_CAPTURED:
        _require_tzaware_iso8601(execution_time, field="execution_time")

    if protocol == EVIDENCE_PROTOCOL_STRICT:
        if data["raw_execution_log_artifact"] in _NOT_PRESERVED_LOG_VALUES:
            raise RuntimeQualificationManifestError(
                "STRICT_RUNTIME_SMOKE_V2 requires a durably preserved raw_execution_log_artifact -- "
                "NOT_PRESERVED/NONE/empty is permitted only under evidence_protocol_generation="
                f"{EVIDENCE_PROTOCOL_LEGACY!r}"
            )
        log_hash = data.get("raw_execution_log_sha256")
        if not isinstance(log_hash, str) or not _HEX64_RE.match(log_hash):
            raise RuntimeQualificationManifestError(
                "STRICT_RUNTIME_SMOKE_V2 requires raw_execution_log_sha256 as exactly 64 lowercase hex characters"
            )
        if execution_time == NOT_CAPTURED:
            raise RuntimeQualificationManifestError(
                "STRICT_RUNTIME_SMOKE_V2 requires execution_time to be an actual captured timestamp, "
                f"not {NOT_CAPTURED}"
            )
        _require_tzaware_iso8601(data["created_at"], field="created_at")

        # Phase 21B.4.11.3 §3: the six durable evidence-artifact bindings.
        artifacts = data.get("evidence_artifacts")
        if not isinstance(artifacts, dict):
            raise RuntimeQualificationManifestError("STRICT_RUNTIME_SMOKE_V2 requires an evidence_artifacts mapping")
        missing_keys = [k for k in EVIDENCE_ARTIFACT_KEYS if k not in artifacts]
        if missing_keys:
            raise RuntimeQualificationManifestError(
                f"STRICT_RUNTIME_SMOKE_V2 evidence_artifacts missing required entries: {missing_keys}"
            )
        for key in EVIDENCE_ARTIFACT_KEYS:
            entry = artifacts[key]
            if not isinstance(entry, dict) or "path" not in entry or "sha256" not in entry:
                raise RuntimeQualificationManifestError(
                    f"evidence_artifacts.{key} must be a mapping with 'path' and 'sha256'"
                )
            if not isinstance(entry["path"], str) or not entry["path"]:
                raise RuntimeQualificationManifestError(f"evidence_artifacts.{key}.path must be a non-empty string")
            if not isinstance(entry["sha256"], str) or not _HEX64_RE.match(entry["sha256"]):
                raise RuntimeQualificationManifestError(
                    f"evidence_artifacts.{key}.sha256 must be exactly 64 lowercase hex characters"
                )
    else:
        _require_legacy_created_at(data["created_at"])


def _verify_artifact_bytes(path_str: str, expected_sha256: str, *, evidence_root: Path, label: str) -> None:
    root = Path(evidence_root).resolve()
    raw_candidate = root / path_str
    if raw_candidate.is_symlink():
        raise RuntimeQualificationManifestError(f"{label} artifact path {path_str!r} is a symlink -- rejected")
    candidate = raw_candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise RuntimeQualificationManifestError(
            f"{label} artifact path {path_str!r} resolves outside the controlled evidence root -- "
            "rejected as a path-escape/symlink-ambiguity risk."
        )
    if not candidate.is_file():
        raise RuntimeQualificationManifestError(f"{label} artifact {path_str!r} is not a regular file or does not exist")
    actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise RuntimeQualificationManifestError(
            f"{label} artifact byte hash mismatch: manifest declares {expected_sha256!r}, actual content hashes to {actual!r}"
        )


def verify_evidence_artifacts_bytes(data: dict, evidence_root: Path) -> None:
    """Phase 21B.4.11.3 §2/§3: for a STRICT_RUNTIME_SMOKE_V2 manifest,
    resolve every declared artifact path under `evidence_root`, reject
    path escape/symlinks, require a real regular file, and recompute
    its SHA-256 against the manifest's declared hash. A no-op for
    LEGACY_RECONCILED_V1 manifests (their historical artifacts
    genuinely no longer exist and are not fabricated here). Assumes
    `validate_manifest(data)` has already passed."""
    if data["evidence_protocol_generation"] != EVIDENCE_PROTOCOL_STRICT:
        return
    _verify_artifact_bytes(
        data["raw_execution_log_artifact"], data["raw_execution_log_sha256"],
        evidence_root=evidence_root, label="raw_execution_log",
    )
    for key in EVIDENCE_ARTIFACT_KEYS:
        entry = data["evidence_artifacts"][key]
        _verify_artifact_bytes(entry["path"], entry["sha256"], evidence_root=evidence_root, label=f"evidence_artifacts.{key}")


def load_manifest(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text())
    validate_manifest(data)
    return data


def require_candidate_manifest(data: dict, *, candidate: str, repository: str, revision: str, qualification_type: str) -> None:
    """Phase 21B.4.11.1's candidate-specific assertions, split out so a
    caller (e.g. the registry linkage) can assert the manifest it links
    to actually describes the candidate it claims to."""
    validate_manifest(data)
    if data["candidate"] != candidate:
        raise RuntimeQualificationManifestError(f"manifest candidate {data['candidate']!r} != expected {candidate!r}")
    if data["artifact_repository"] != repository:
        raise RuntimeQualificationManifestError(
            f"manifest artifact_repository {data['artifact_repository']!r} != expected {repository!r}"
        )
    if data["exact_revision"] != revision:
        raise RuntimeQualificationManifestError(
            f"manifest exact_revision {data['exact_revision']!r} != expected {revision!r}"
        )
    if data["qualification_type"] != qualification_type:
        raise RuntimeQualificationManifestError(
            f"manifest qualification_type {data['qualification_type']!r} != expected {qualification_type!r}"
        )


def verify_runtime_qualification_bundle(
    manifest_data: dict,
    *,
    candidate: str,
    repository: str,
    revision: str,
    qualification_type: str,
    evidence_root: Path | None = None,
) -> None:
    """Phase 21B.4.11.3 §8: the ONE fail-closed entry point future
    candidate code should call -- schema validation, candidate-identity
    assertions, and (for STRICT manifests) actual artifact-byte
    verification, all in a single call that cannot be partially
    skipped. A STRICT manifest without `evidence_root` is refused
    outright rather than silently accepted on format checks alone."""
    require_candidate_manifest(
        manifest_data, candidate=candidate, repository=repository, revision=revision,
        qualification_type=qualification_type,
    )
    if manifest_data["evidence_protocol_generation"] == EVIDENCE_PROTOCOL_STRICT:
        if evidence_root is None:
            raise RuntimeQualificationManifestError(
                "STRICT_RUNTIME_SMOKE_V2 manifests require evidence_root to verify actual artifact bytes -- "
                "refusing to accept a strict bundle on schema/format checks alone"
            )
        verify_evidence_artifacts_bytes(manifest_data, evidence_root)
