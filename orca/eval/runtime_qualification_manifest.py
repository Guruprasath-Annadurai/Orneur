"""
Genesis Runtime Qualification Manifest schema (Phase 21B.4.11.1, hardened
21B.4.11.2 for fail-closed protocol enforcement).

A candidate runtime smoke produces a large amount of one-off evidence --
exact revision, runtime versions, GPU topology, VRAM usage,
prompt/response hashes, billing deltas, cleanup confirmation. This
module defines a versioned, machine-readable manifest schema for that
evidence, plus a canonical-JSON SHA-256 digest so the registry can link
to it by content hash rather than duplicating it as prose.

Phase 21B.4.11.2 hardening:

- `evidence_protocol_generation` distinguishes the historical,
  narrowly-grandfathered Qwen3.8-27B manifest (`LEGACY_RECONCILED_V1`,
  which may omit a durable raw execution log because it genuinely no
  longer exists) from every future candidate smoke
  (`STRICT_RUNTIME_SMOKE_V2`, which MUST carry a durably preserved
  execution log and its SHA-256, or the candidate may not be marked
  QUALIFIED at all).
- `evidence_strength` must cover EXACTLY the locked
  `EVIDENCE_BEARING_FIELDS` set -- a manifest can no longer pass with
  provenance tags for only a subset of its evidence-bearing fields.
- Numeric evidence fields are type/finiteness/sign-checked (no bool
  masquerading as a number, no NaN/Inf, no negative values where a
  negative value is not semantically meaningful), and the
  metered/billed deltas are cross-checked arithmetically.
- Attempt-count/attempt-result/qualification-type consistency is
  enforced: a QUALIFIED manifest must have at least one SUCCEEDED
  attempt, a FAILED manifest must have none, and a FAILED attempt must
  carry a failure classification while a SUCCEEDED one must not.
- `source_repo_sha` must be a real 40-hex Git SHA; `created_at` must be
  a timezone-aware ISO-8601 timestamp under strict mode (a bare date is
  only permitted under the legacy generation, alongside an explicit
  `execution_time: "NOT_CAPTURED"` rather than a fabricated time).

This module performs SCHEMA validation only -- it makes no capability,
license, or frontier-class judgment, and it does not execute anything
itself. Nothing here downloads a model, starts a GPU, or runs
inference.
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

VALID_QUALIFICATION_TYPES = (
    "RUNTIME_LOAD_COMPATIBILITY_QUALIFIED",
    "PRODUCTION_SERVING_RUNTIME_QUALIFIED",
    "RUNTIME_QUALIFICATION_FAILED",
    "DEFERRED_FOR_COMPUTE",
)

QUALIFIED_TYPES = ("RUNTIME_LOAD_COMPATIBILITY_QUALIFIED", "PRODUCTION_SERVING_RUNTIME_QUALIFIED")

VALID_ATTEMPT_RESULTS = ("SUCCEEDED", "FAILED", "NOT_ATTEMPTED")

VALID_EVIDENCE_STRENGTHS = (
    "OBSERVED_LIVE",
    "DERIVED",
    "REPORTED_BY_CLAUDE",
    "REPOSITORY_VERIFIED",
    "OWNER_SCREENSHOT_VERIFIED",
    "NOT_CAPTURED",
)

# Phase 21B.4.11.2 §1: the ONLY grandfathered exception. A future
# manifest generation MUST be STRICT_RUNTIME_SMOKE_V2 -- adding a new
# generation name here is how any future relaxation would have to be
# made explicit, rather than silently reusing LEGACY_RECONCILED_V1.
EVIDENCE_PROTOCOL_LEGACY = "LEGACY_RECONCILED_V1"
EVIDENCE_PROTOCOL_STRICT = "STRICT_RUNTIME_SMOKE_V2"
VALID_EVIDENCE_PROTOCOL_GENERATIONS = (EVIDENCE_PROTOCOL_LEGACY, EVIDENCE_PROTOCOL_STRICT)

_NOT_PRESERVED_LOG_VALUES = frozenset({None, "", "NOT_PRESERVED", "NONE"})

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

_NONNEGATIVE_NUMERIC_FIELDS = (
    "peak_allocated_vram_gb",
    "peak_reserved_vram_gb",
    "load_time_seconds",
    "input_tokens",
    "output_tokens",
    "generation_latency_seconds",
    "tokens_per_second",
    "metered_before_usd",
    "metered_after_usd",
    "metered_delta_usd",
    "billed_before_usd",
    "billed_after_usd",
    "owner_billed_delta_usd",
)


class RuntimeQualificationManifestError(ValueError):
    """A runtime qualification manifest fails structural validation."""


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


def _require_number(data: dict, field: str, *, allow_zero: bool = True, strictly_positive: bool = False) -> None:
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeQualificationManifestError(f"{field} must be a real number, not {type(value).__name__}")
    if not math.isfinite(value):
        raise RuntimeQualificationManifestError(f"{field} must be finite (no NaN/Inf)")
    if strictly_positive and value <= 0:
        raise RuntimeQualificationManifestError(f"{field} must be > 0")
    if not strictly_positive and not allow_zero and value <= 0:
        raise RuntimeQualificationManifestError(f"{field} must be > 0")
    if value < 0:
        raise RuntimeQualificationManifestError(f"{field} must be >= 0")


def _require_int_at_least(data: dict, field: str, minimum: int) -> None:
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeQualificationManifestError(f"{field} must be an integer, not {type(value).__name__}")
    if value < minimum:
        raise RuntimeQualificationManifestError(f"{field} must be >= {minimum}")


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
    """Structural validation only. Raises RuntimeQualificationManifestError
    on any violation."""
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

    for field in ("synthetic_prompt_sha256", "decoded_response_sha256"):
        value = data[field]
        if not isinstance(value, str) or not _HEX64_RE.match(value):
            raise RuntimeQualificationManifestError(f"{field} must be exactly 64 lowercase hex characters (SHA-256)")

    attempt_1_result = data["attempt_1_result"]
    attempt_2_result = data["attempt_2_result"]
    for field, value in (("attempt_1_result", attempt_1_result), ("attempt_2_result", attempt_2_result)):
        if value not in VALID_ATTEMPT_RESULTS:
            raise RuntimeQualificationManifestError(f"{field} has unrecognized value {value!r}")

    # Benchmark/generated-code execution must never be true, and no
    # persistent Volume may be used, regardless of protocol generation.
    for field in ("benchmark_prompt_exposed", "genesis_eval_executed", "generated_output_executed"):
        if data[field] is not False:
            raise RuntimeQualificationManifestError(
                f"{field} must be false -- a runtime qualification manifest must never record benchmark/"
                "generated-code execution"
            )
    if data["persistent_volume_used"] is not False:
        raise RuntimeQualificationManifestError("persistent_volume_used must be false")

    # ── Phase 21B.4.11.2 §5: numeric type/finiteness/sign checks ──────
    _require_int_at_least(data, "gpu_count", 1)
    _require_int_at_least(data, "load_attempt_count", 1)
    _require_number(data, "vram_capacity_gb", strictly_positive=True)
    _require_number(data, "input_tokens")
    _require_number(data, "output_tokens")
    for field in _NONNEGATIVE_NUMERIC_FIELDS:
        _require_number(data, field)
    ttft = data["ttft_seconds"]
    if ttft != "NOT_CAPTURED":
        if isinstance(ttft, bool) or not isinstance(ttft, (int, float)) or not math.isfinite(ttft) or ttft < 0:
            raise RuntimeQualificationManifestError("ttft_seconds must be 'NOT_CAPTURED' or a finite number >= 0")

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

    # ── Phase 21B.4.11.2 §6: attempt-state consistency ────────────────
    if data["load_attempt_count"] == 1 and attempt_2_result != "NOT_ATTEMPTED":
        raise RuntimeQualificationManifestError("load_attempt_count==1 requires attempt_2_result==NOT_ATTEMPTED")
    if data["load_attempt_count"] >= 2 and attempt_2_result == "NOT_ATTEMPTED":
        raise RuntimeQualificationManifestError(
            "load_attempt_count>=2 requires attempt_2_result to not be NOT_ATTEMPTED"
        )
    attempts = (attempt_1_result, attempt_2_result)
    if qualification_type in QUALIFIED_TYPES and "SUCCEEDED" not in attempts:
        raise RuntimeQualificationManifestError(
            f"{qualification_type} requires at least one attempt to have SUCCEEDED"
        )
    if qualification_type == "RUNTIME_QUALIFICATION_FAILED" and "SUCCEEDED" in attempts:
        raise RuntimeQualificationManifestError("RUNTIME_QUALIFICATION_FAILED must not have any SUCCEEDED attempt")

    if attempt_1_result == "FAILED" and not data.get("attempt_1_failure_class"):
        raise RuntimeQualificationManifestError("attempt_1_result==FAILED requires attempt_1_failure_class to be set")
    if attempt_1_result == "SUCCEEDED" and data.get("attempt_1_failure_class"):
        raise RuntimeQualificationManifestError("attempt_1_result==SUCCEEDED must not carry a failure classification")
    if attempt_2_result == "FAILED" and not data.get("attempt_2_failure_class"):
        raise RuntimeQualificationManifestError("attempt_2_result==FAILED requires attempt_2_failure_class to be set")
    if attempt_2_result == "SUCCEEDED" and data.get("attempt_2_failure_class"):
        raise RuntimeQualificationManifestError("attempt_2_result==SUCCEEDED must not carry a failure classification")

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

    gate = data["billing_gate_reconciliation"]
    _require_fields(gate, ("billing_gate_at_time_of_execution", "owner_billed_result", "financial_impact"))

    # ── Phase 21B.4.11.2 §1/§2: protocol-generation-gated log/time rules ──
    protocol = data["evidence_protocol_generation"]
    if protocol not in VALID_EVIDENCE_PROTOCOL_GENERATIONS:
        raise RuntimeQualificationManifestError(f"unrecognized evidence_protocol_generation {protocol!r}")

    execution_time = data["execution_time"]
    if execution_time != "NOT_CAPTURED":
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
        if execution_time == "NOT_CAPTURED":
            raise RuntimeQualificationManifestError(
                "STRICT_RUNTIME_SMOKE_V2 requires execution_time to be an actual captured timestamp, "
                "not NOT_CAPTURED"
            )
        _require_tzaware_iso8601(data["created_at"], field="created_at")
    else:
        _require_legacy_created_at(data["created_at"])


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
