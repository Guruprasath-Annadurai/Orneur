"""
Genesis Runtime Qualification Manifest schema (Phase 21B.4.11.1).

A candidate runtime smoke (Phase 21B.4.11 and beyond) produces a large
amount of one-off evidence -- exact revision, runtime versions, GPU
topology, VRAM usage, prompt/response hashes, billing deltas, cleanup
confirmation. Phase 21B.4.10.1/.11 stored this as a single free-form
string on the candidate registry entry (`qualification_evidence`),
which is not machine-checkable and cannot be independently verified or
diffed. This module defines a versioned, machine-readable manifest
schema for that evidence instead, plus a canonical-JSON SHA-256 digest
so the registry can link to it by content hash rather than duplicating
it as prose.

This module performs SCHEMA validation only -- it makes no capability,
license, or frontier-class judgment, and it does not execute anything
itself. Nothing here downloads a model, starts a GPU, or runs
inference.
"""
from __future__ import annotations

import hashlib
import json
import re
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

VALID_ATTEMPT_RESULTS = ("SUCCEEDED", "FAILED", "NOT_ATTEMPTED")

VALID_EVIDENCE_STRENGTHS = (
    "OBSERVED_LIVE",
    "DERIVED",
    "REPORTED_BY_CLAUDE",
    "REPOSITORY_VERIFIED",
    "OWNER_SCREENSHOT_VERIFIED",
    "NOT_CAPTURED",
)

REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version",
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
    "source_repo_sha",
    "billing_gate_reconciliation",
    "raw_execution_log_artifact",
    "evidence_strength",
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

    if data["qualification_type"] not in VALID_QUALIFICATION_TYPES:
        raise RuntimeQualificationManifestError(
            f"unrecognized qualification_type {data['qualification_type']!r}"
        )

    for field in ("synthetic_prompt_sha256", "decoded_response_sha256"):
        value = data[field]
        if not _HEX64_RE.match(value):
            raise RuntimeQualificationManifestError(f"{field} must be exactly 64 lowercase hex characters (SHA-256)")

    for field in ("attempt_1_result", "attempt_2_result"):
        if data[field] not in VALID_ATTEMPT_RESULTS:
            raise RuntimeQualificationManifestError(f"{field} has unrecognized value {data[field]!r}")

    # Phase 21B.4.11.1 §8: no benchmark-execution field may be true, and
    # a qualification manifest must never claim owner billing occurred.
    for field in ("benchmark_prompt_exposed", "genesis_eval_executed", "generated_output_executed"):
        if data[field] is not False:
            raise RuntimeQualificationManifestError(
                f"{field} must be false -- a runtime qualification manifest must never record benchmark/"
                "generated-code execution"
            )
    if data["owner_billed_delta_usd"] != 0:
        raise RuntimeQualificationManifestError(
            "owner_billed_delta_usd must be exactly 0 for accepted runtime-smoke evidence"
        )
    if data["persistent_volume_used"] is not False:
        raise RuntimeQualificationManifestError("persistent_volume_used must be false")

    evidence_strength = data["evidence_strength"]
    if not isinstance(evidence_strength, dict) or not evidence_strength:
        raise RuntimeQualificationManifestError("evidence_strength must be a non-empty mapping")
    bad = {k: v for k, v in evidence_strength.items() if v not in VALID_EVIDENCE_STRENGTHS}
    if bad:
        raise RuntimeQualificationManifestError(f"evidence_strength has unrecognized value(s): {bad}")

    gate = data["billing_gate_reconciliation"]
    _require_fields(gate, ("billing_gate_at_time_of_execution", "owner_billed_result", "financial_impact"))


def load_manifest(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text())
    validate_manifest(data)
    return data


def require_candidate_manifest(data: dict, *, candidate: str, repository: str, revision: str, qualification_type: str) -> None:
    """Phase 21B.4.11.1 §8's candidate-specific assertions, split out so
    a caller (e.g. the registry linkage) can assert the manifest it
    links to actually describes the candidate it claims to."""
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
