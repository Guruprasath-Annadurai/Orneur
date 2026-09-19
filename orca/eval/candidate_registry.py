"""
Genesis Candidate Execution Registry schema (Phase 21B.4.10).

Loads and structurally validates `docs/orneur/phase-21/
GENESIS_CANDIDATE_EXECUTION_REGISTRY.json` -- the Stage-0 identity/
license/runtime eligibility qualification record for the deployable
candidate pool, controls, and frontier reference set. This module
performs SCHEMA validation only (required fields present, status enums
recognized, identity-type/revision consistency) -- it makes no
capability, license, or frontier-class judgment itself; those are
human-authored fields inside the registry JSON. Nothing here downloads
a model, calls an API, or evaluates a candidate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REGISTRY_SCHEMA_VERSION = "genesis-candidate-execution-registry-v1"

DEPLOYABLE_REQUIRED_FIELDS = (
    "candidate_class", "canonical_candidate_name", "organization", "artifact_repository",
    "exact_immutable_revision", "tokenizer_repository", "tokenizer_revision",
    "revision_timestamp", "architecture", "total_parameters", "active_parameters",
    "license_identifier", "license_source", "commercial_deployment_status",
    "fine_tuning_status", "redistribution_status", "distillation_teacher_use_status",
    "runtime_support", "weight_storage_envelope", "theoretical_gpu_count_80gb_class",
    "qualified_practical_topology", "zero_cash_access_status", "stage0_status",
)

CONTROL_REQUIRED_FIELDS = (
    "candidate_class", "canonical_candidate_name", "organization", "artifact_repository",
    "exact_immutable_revision", "tokenizer_repository", "tokenizer_revision",
    "architecture", "total_parameters", "license_identifier", "stage0_status", "role",
)

REFERENCE_REQUIRED_FIELDS = (
    "reference_name", "organization", "identity_type", "artifact_repository",
    "exact_immutable_revision", "license_identifier", "zero_cash_access_status",
    "availability_status",
)

VALID_IDENTITY_TYPES = ("OPEN_WEIGHT", "MUTABLE_HOSTED_API")

# Owner spec §9's example set is illustrative, not exhaustive -- any
# status a candidate/control record uses must be one of these.
VALID_STAGE0_STATUSES = (
    "ELIGIBLE_FOR_RUNTIME_SMOKE",
    "LICENSE_REVIEW_REQUIRED",
    "RUNTIME_SUPPORT_UNQUALIFIED",
    "IDENTITY_UNRESOLVED",
    "DEFERRED_FOR_COMPUTE",
    "REFERENCE_UNAVAILABLE",
)

VALID_AVAILABILITY_STATUSES = ("REFERENCE_EXECUTION_DEFERRED", "AVAILABLE", "REFERENCE_UNAVAILABLE")


class RegistrySchemaError(ValueError):
    """The candidate execution registry JSON does not conform to the
    Phase 21B.4.10 schema -- a missing required field, an unrecognized
    status enum value, or an identity_type/exact_immutable_revision
    combination that contradicts itself (a MUTABLE_HOSTED_API entry
    claiming a real pinned revision, or an OPEN_WEIGHT entry with no
    resolvable revision)."""


@dataclass(frozen=True)
class CandidateExecutionRegistry:
    schema_version: str
    deployable_candidates: tuple[dict, ...]
    controls: tuple[dict, ...]
    frontier_references: tuple[dict, ...]

    @classmethod
    def load(cls, path: Path) -> "CandidateExecutionRegistry":
        data = json.loads(Path(path).read_text())
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "CandidateExecutionRegistry":
        _validate(data)
        return cls(
            schema_version=data["schema_version"],
            deployable_candidates=tuple(data["deployable_candidates"]),
            controls=tuple(data["controls"]),
            frontier_references=tuple(data["frontier_references"]),
        )

    def find_deployable(self, canonical_candidate_name: str) -> dict:
        for entry in self.deployable_candidates:
            if entry["canonical_candidate_name"] == canonical_candidate_name:
                return entry
        raise KeyError(f"No deployable candidate named {canonical_candidate_name!r} in registry")

    def eligible_for_runtime_smoke(self) -> tuple[dict, ...]:
        return tuple(e for e in self.deployable_candidates if e["stage0_status"] == "ELIGIBLE_FOR_RUNTIME_SMOKE")


def _require_fields(entry: dict, required: tuple[str, ...], section: str) -> None:
    missing = [f for f in required if f not in entry]
    if missing:
        label = entry.get("canonical_candidate_name") or entry.get("reference_name") or "<unnamed>"
        raise RegistrySchemaError(f"{section} entry {label!r} missing required field(s): {missing}")


def _validate(data: dict) -> None:
    if data.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise RegistrySchemaError(
            f"Unsupported registry schema_version={data.get('schema_version')!r} "
            f"(expected {REGISTRY_SCHEMA_VERSION!r})"
        )
    for key in ("deployable_candidates", "controls", "frontier_references"):
        if key not in data or not isinstance(data[key], list):
            raise RegistrySchemaError(f"Registry missing required list field {key!r}")

    for entry in data["deployable_candidates"]:
        _require_fields(entry, DEPLOYABLE_REQUIRED_FIELDS, "deployable_candidates")
        if entry["stage0_status"] not in VALID_STAGE0_STATUSES:
            raise RegistrySchemaError(
                f"deployable candidate {entry['canonical_candidate_name']!r} has unrecognized "
                f"stage0_status={entry['stage0_status']!r}"
            )
        if not entry["exact_immutable_revision"] or entry["exact_immutable_revision"] in ("main", "latest", "head"):
            raise RegistrySchemaError(
                f"deployable candidate {entry['canonical_candidate_name']!r} has a non-pinned "
                f"exact_immutable_revision={entry['exact_immutable_revision']!r} -- floating tags are "
                "never an execution identity."
            )

    for entry in data["controls"]:
        _require_fields(entry, CONTROL_REQUIRED_FIELDS, "controls")
        if entry["stage0_status"] not in VALID_STAGE0_STATUSES:
            raise RegistrySchemaError(
                f"control {entry['canonical_candidate_name']!r} has unrecognized "
                f"stage0_status={entry['stage0_status']!r}"
            )
        if not entry["exact_immutable_revision"] or entry["exact_immutable_revision"] in ("main", "latest", "head"):
            raise RegistrySchemaError(
                f"control {entry['canonical_candidate_name']!r} has a non-pinned "
                f"exact_immutable_revision={entry['exact_immutable_revision']!r}."
            )

    for entry in data["frontier_references"]:
        _require_fields(entry, REFERENCE_REQUIRED_FIELDS, "frontier_references")
        if entry["identity_type"] not in VALID_IDENTITY_TYPES:
            raise RegistrySchemaError(
                f"frontier reference {entry['reference_name']!r} has unrecognized "
                f"identity_type={entry['identity_type']!r}"
            )
        if entry["availability_status"] not in VALID_AVAILABILITY_STATUSES:
            raise RegistrySchemaError(
                f"frontier reference {entry['reference_name']!r} has unrecognized "
                f"availability_status={entry['availability_status']!r}"
            )
        revision = str(entry["exact_immutable_revision"])
        if entry["identity_type"] == "MUTABLE_HOSTED_API" and "NOT_AVAILABLE" not in revision:
            raise RegistrySchemaError(
                f"frontier reference {entry['reference_name']!r} is identity_type=MUTABLE_HOSTED_API "
                f"but claims a real-looking pinned revision ({revision!r}) -- a mutable hosted API can "
                "never have an immutable execution identity."
            )
        if entry["identity_type"] == "OPEN_WEIGHT" and (not revision or "NOT_AVAILABLE" in revision):
            raise RegistrySchemaError(
                f"frontier reference {entry['reference_name']!r} is identity_type=OPEN_WEIGHT but has "
                f"no resolvable exact_immutable_revision ({revision!r})."
            )
