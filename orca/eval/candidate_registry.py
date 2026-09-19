"""
Genesis Candidate Execution Registry schema (Phase 21B.4.10, hardened
Phase 21B.4.10.1).

Loads and structurally validates `docs/orneur/phase-21/
GENESIS_CANDIDATE_EXECUTION_REGISTRY.json` -- the Stage-0 identity/
license/runtime eligibility qualification record for the deployable
candidate pool, controls, and frontier reference set. This module
performs SCHEMA validation only (required fields present, status enums
recognized, identity-type/revision consistency, exact registered name
sets) -- it makes no capability, license, or frontier-class judgment
itself; those are human-authored fields inside the registry JSON.
Nothing here downloads a model, calls an API, or evaluates a candidate.

Phase 21B.4.10.1 hardening (schema v1 -> v2):

- Deployable candidates' single conflated `stage0_status` field is
  replaced by four separate fields (`identity_status`, `license_status`,
  `runtime_qualification_status`, `runtime_smoke_eligibility`) so that
  "runtime not yet qualified" -- exactly what a runtime smoke test
  exists to resolve -- is never confused with "not eligible to attempt
  a smoke test." A structural invariant is enforced: a candidate with
  `identity_status=RESOLVED` and `license_status=CLEAR` MUST be
  `runtime_smoke_eligibility=ELIGIBLE` regardless of its (separate)
  runtime_qualification_status; a candidate with
  `license_status=LICENSE_REVIEW_REQUIRED` MUST be `BLOCKED`.
- The exact registered name sets (4 deployable candidates, 3 controls,
  6 frontier references) are locked in code and enforced -- a registry
  claiming a different candidate pool size or an unrecognized name is
  rejected, not silently accepted.
- Revision format is strictly validated: every OPEN_WEIGHT/deployable/
  control `exact_immutable_revision` must be exactly 40 lowercase hex
  characters (a real Git commit SHA) -- a value like `"abc123"` no
  longer passes merely for being nonempty and not `"main"`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

REGISTRY_SCHEMA_VERSION = "genesis-candidate-execution-registry-v2"

_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")

# Locked registered name sets (Phase 21B.4.10.1 §9) -- mirrors
# orca.eval.frontier_stats.REGISTERED_FRONTIER_REFERENCES /
# CONTROL_TARGET_SET, kept as separate constants here since this module
# must not import orca.eval.frontier_stats (no circular coupling
# between the registry schema and the statistics engine).
EXPECTED_DEPLOYABLE_NAMES = frozenset({
    "Qwen3.8-27B", "Qwen3.8-Flash-Next", "Mistral Small 4", "GLM-5.3-Flash",
})
EXPECTED_CONTROL_NAMES = frozenset({"Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4"})
EXPECTED_REFERENCE_NAMES = frozenset({
    "DeepSeek V4.1-Flash", "GLM-5.3 (flagship)", "Mistral Large 3",
    "MiniMax M3", "Qwen3.8-Max", "Kimi K3",
})

DEPLOYABLE_REQUIRED_FIELDS = (
    "candidate_class", "canonical_candidate_name", "organization", "artifact_repository",
    "exact_immutable_revision", "tokenizer_repository", "tokenizer_revision",
    "revision_timestamp", "architecture", "total_parameters", "active_parameters",
    "license_identifier", "license_source", "commercial_deployment_status",
    "fine_tuning_status", "redistribution_status", "distillation_teacher_use_status",
    "runtime_support", "weight_storage_envelope", "theoretical_gpu_count_80gb_class",
    "qualified_practical_topology", "zero_cash_access_status",
    "identity_status", "license_status", "runtime_qualification_status",
    "runtime_smoke_eligibility", "runtime_smoke_blocked_reason",
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

VALID_IDENTITY_STATUSES = ("RESOLVED", "IDENTITY_UNRESOLVED")
VALID_LICENSE_STATUSES = ("CLEAR", "LICENSE_REVIEW_REQUIRED")
VALID_RUNTIME_QUALIFICATION_STATUSES = ("UNQUALIFIED", "QUALIFIED")
VALID_RUNTIME_SMOKE_ELIGIBILITY = ("ELIGIBLE", "BLOCKED")

# Owner spec's example set is illustrative, not exhaustive -- any status
# a control record uses must be one of these.
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
    Phase 21B.4.10.1 schema -- a missing required field, an unrecognized
    status enum value, an identity_type/exact_immutable_revision
    combination that contradicts itself, a malformed (non-40-hex)
    revision, an unrecognized/duplicate/missing registered candidate
    name, or a runtime_smoke_eligibility value that contradicts its own
    identity_status/license_status."""


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
        return tuple(e for e in self.deployable_candidates if e["runtime_smoke_eligibility"] == "ELIGIBLE")


def _require_fields(entry: dict, required: tuple[str, ...], section: str) -> None:
    missing = [f for f in required if f not in entry]
    if missing:
        label = entry.get("canonical_candidate_name") or entry.get("reference_name") or "<unnamed>"
        raise RegistrySchemaError(f"{section} entry {label!r} missing required field(s): {missing}")


def _require_hex40_revision(revision, label: str) -> None:
    if not isinstance(revision, str) or not _HEX40_RE.match(revision):
        raise RegistrySchemaError(
            f"{label} has exact_immutable_revision={revision!r}, which is not a well-formed 40-character "
            "lowercase hex Git commit SHA -- a short/non-hex value never counts as a pinned revision."
        )


def _validate_deployable(entry: dict) -> None:
    _require_fields(entry, DEPLOYABLE_REQUIRED_FIELDS, "deployable_candidates")
    name = entry["canonical_candidate_name"]
    _require_hex40_revision(entry["exact_immutable_revision"], f"deployable candidate {name!r}")

    if entry["identity_status"] not in VALID_IDENTITY_STATUSES:
        raise RegistrySchemaError(f"deployable candidate {name!r} has unrecognized identity_status={entry['identity_status']!r}")
    if entry["license_status"] not in VALID_LICENSE_STATUSES:
        raise RegistrySchemaError(f"deployable candidate {name!r} has unrecognized license_status={entry['license_status']!r}")
    if entry["runtime_qualification_status"] not in VALID_RUNTIME_QUALIFICATION_STATUSES:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has unrecognized runtime_qualification_status="
            f"{entry['runtime_qualification_status']!r}"
        )
    if entry["runtime_smoke_eligibility"] not in VALID_RUNTIME_SMOKE_ELIGIBILITY:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has unrecognized runtime_smoke_eligibility="
            f"{entry['runtime_smoke_eligibility']!r}"
        )

    # Phase 21B.4.10.1's core structural fix: eligibility must follow
    # deterministically from identity/license status, never set
    # independently in a way that contradicts them.
    if entry["license_status"] == "LICENSE_REVIEW_REQUIRED" and entry["runtime_smoke_eligibility"] != "BLOCKED":
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has license_status=LICENSE_REVIEW_REQUIRED but "
            f"runtime_smoke_eligibility={entry['runtime_smoke_eligibility']!r} -- an unresolved license "
            "must block runtime smoke eligibility."
        )
    if entry["identity_status"] != "RESOLVED" and entry["runtime_smoke_eligibility"] != "BLOCKED":
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has identity_status={entry['identity_status']!r} (not RESOLVED) "
            f"but runtime_smoke_eligibility={entry['runtime_smoke_eligibility']!r} -- an unresolved identity "
            "must block runtime smoke eligibility."
        )
    if (
        entry["identity_status"] == "RESOLVED"
        and entry["license_status"] == "CLEAR"
        and entry["runtime_smoke_eligibility"] != "ELIGIBLE"
    ):
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has identity_status=RESOLVED and license_status=CLEAR but "
            f"runtime_smoke_eligibility={entry['runtime_smoke_eligibility']!r} -- runtime_qualification_status="
            "UNQUALIFIED is exactly what a runtime smoke test exists to resolve and must never, by itself, "
            "block eligibility to attempt one."
        )
    if entry["runtime_smoke_eligibility"] == "BLOCKED" and not entry.get("runtime_smoke_blocked_reason"):
        raise RegistrySchemaError(f"deployable candidate {name!r} is BLOCKED but has no runtime_smoke_blocked_reason")


def _validate(data: dict) -> None:
    if data.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise RegistrySchemaError(
            f"Unsupported registry schema_version={data.get('schema_version')!r} "
            f"(expected {REGISTRY_SCHEMA_VERSION!r})"
        )
    for key in ("deployable_candidates", "controls", "frontier_references"):
        if key not in data or not isinstance(data[key], list):
            raise RegistrySchemaError(f"Registry missing required list field {key!r}")

    # ── Structural hardening: exact registered name sets (Phase 21B.4.10.1 §9) ──
    deployable_names = [e.get("canonical_candidate_name") for e in data["deployable_candidates"]]
    if len(deployable_names) != len(EXPECTED_DEPLOYABLE_NAMES) or set(deployable_names) != EXPECTED_DEPLOYABLE_NAMES:
        raise RegistrySchemaError(
            f"deployable_candidates names {sorted(n for n in deployable_names if n)} do not exactly match the "
            f"registered set {sorted(EXPECTED_DEPLOYABLE_NAMES)}"
        )
    if len(set(deployable_names)) != len(deployable_names):
        raise RegistrySchemaError("deployable_candidates contains a duplicate canonical_candidate_name")

    control_names = [e.get("canonical_candidate_name") for e in data["controls"]]
    if len(control_names) != len(EXPECTED_CONTROL_NAMES) or set(control_names) != EXPECTED_CONTROL_NAMES:
        raise RegistrySchemaError(
            f"controls names {sorted(n for n in control_names if n)} do not exactly match the registered "
            f"set {sorted(EXPECTED_CONTROL_NAMES)}"
        )
    if len(set(control_names)) != len(control_names):
        raise RegistrySchemaError("controls contains a duplicate canonical_candidate_name")

    reference_names = [e.get("reference_name") for e in data["frontier_references"]]
    if len(reference_names) != len(EXPECTED_REFERENCE_NAMES) or set(reference_names) != EXPECTED_REFERENCE_NAMES:
        raise RegistrySchemaError(
            f"frontier_references names {sorted(n for n in reference_names if n)} do not exactly match the "
            f"registered set {sorted(EXPECTED_REFERENCE_NAMES)}"
        )
    if len(set(reference_names)) != len(reference_names):
        raise RegistrySchemaError("frontier_references contains a duplicate reference_name")

    for entry in data["deployable_candidates"]:
        _validate_deployable(entry)

    for entry in data["controls"]:
        _require_fields(entry, CONTROL_REQUIRED_FIELDS, "controls")
        name = entry["canonical_candidate_name"]
        _require_hex40_revision(entry["exact_immutable_revision"], f"control {name!r}")
        if entry["stage0_status"] not in VALID_STAGE0_STATUSES:
            raise RegistrySchemaError(f"control {name!r} has unrecognized stage0_status={entry['stage0_status']!r}")

    for entry in data["frontier_references"]:
        _require_fields(entry, REFERENCE_REQUIRED_FIELDS, "frontier_references")
        name = entry["reference_name"]
        if entry["identity_type"] not in VALID_IDENTITY_TYPES:
            raise RegistrySchemaError(f"frontier reference {name!r} has unrecognized identity_type={entry['identity_type']!r}")
        if entry["availability_status"] not in VALID_AVAILABILITY_STATUSES:
            raise RegistrySchemaError(
                f"frontier reference {name!r} has unrecognized availability_status={entry['availability_status']!r}"
            )
        revision = str(entry["exact_immutable_revision"])
        if entry["identity_type"] == "MUTABLE_HOSTED_API":
            if "NOT_AVAILABLE" not in revision:
                raise RegistrySchemaError(
                    f"frontier reference {name!r} is identity_type=MUTABLE_HOSTED_API but claims a "
                    f"real-looking pinned revision ({revision!r}) -- a mutable hosted API can never have "
                    "an immutable execution identity."
                )
        else:  # OPEN_WEIGHT
            _require_hex40_revision(entry["exact_immutable_revision"], f"frontier reference {name!r}")
