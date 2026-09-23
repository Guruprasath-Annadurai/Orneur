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

Phase 21B.4.15 hardening (schema v2 -> v3): `runtime_qualification_status`
is RETAINED (many callers and manifest-linkage checks depend on it as
"does this candidate have ANY accepted, manifest-linked qualification
record") but is now explicitly DEPRECATED for direct interpretation as
"production-serving qualified" -- it is true for both a candidate that
merely loaded and generated through native Transformers
(RUNTIME_LOAD_COMPATIBILITY_QUALIFIED) and one actually served through a
production inference engine over a real network/API path
(PRODUCTION_SERVING_RUNTIME_QUALIFIED), and a reader who only checks this
one field cannot tell those apart. Four new, separately-validated fields
make every qualification dimension explicit: `load_compatibility_status`,
`production_serving_status`, `financial_acceptance_status`,
`capability_status` (valid values: `VALID_LOAD_COMPATIBILITY_STATUSES`,
`VALID_PRODUCTION_SERVING_STATUSES`, `VALID_FINANCIAL_ACCEPTANCE_STATUSES`,
`VALID_CAPABILITY_STATUSES`). `_validate_deployable` enforces cross-field
invariants tying these to `qualification_type` and to each other (a
candidate can never claim `production_serving_status=QUALIFIED` without a
linked `PRODUCTION_SERVING_RUNTIME_QUALIFIED` manifest, never claim it
alongside a failed financial gate, etc.). `verify_candidate_qualification_
end_to_end()` gained a `require_production_serving` parameter (default
`False`, backwards compatible) for callers that specifically need
production-serving acceptance rather than any qualified type.

Phase 21B.4.16 hardening (schema v3 -> v4): controls gain their own,
deliberately SMALLER admission-dimension set (they are never production-
serving-qualified foundation candidates, so they get no
`production_serving_status`/`financial_acceptance_status`/
`capability_status`): `identity_status`, `license_status` (both reusing
the deployable enums), `control_admission_status` (ADMITTED/BLOCKED/
REVIEW_REQUIRED), `runtime_preflight_status` (READY/BLOCKED/
INCONCLUSIVE/NOT_TESTED), `runtime_qualification_status` (its own
smaller enum: NOT_TESTED/QUALIFIED/FAILED/INCONCLUSIVE -- distinct from
the deployable one), `runtime_smoke_eligibility`/
`runtime_smoke_blocked_reason` (reusing the deployable enum/pattern).
`stage0_status` is RETAINED for backwards compatibility (existing
`VALID_STAGE0_STATUSES` values, still validated) but its semantics are
now documented as a coarse LEGACY summary field, never the canonical
source of truth -- the new dimensions above are canonical.
`_validate_control()` enforces the same admission-follows-identity/
license discipline as deployable candidates, PLUS a structural
invariant unique to controls: a control entry may never carry any
deployable-only field (`qualification_type`,
`load_compatibility_status`, `production_serving_status`,
`financial_acceptance_status`, `capability_status`, or the manifest-
linkage fields) and must carry the exact locked `role` text -- both
checks exist specifically so a control can never be structurally
misread as a deployable Genesis foundation candidate, a frontier
reference, or a selected Genesis foundation.

Phase 21B.4.17 hardening (schema v4 -> v5): frontier-reference entries
gain eight new required fields (`identity_status`,
`license_or_terms_status`, `reference_evaluation_admission_status`,
`teacher_use_status`, `teacher_use_evidence_reference`,
`access_preflight_status`, `evidence_retention_status`,
`mutable_identity_status`) validated by `_validate_reference()`. The
central design decision is that REFERENCE-EVALUATION admission and
TEACHER/DISTILLATION admission are separate, independently-tracked
decisions -- a reference may be permitted to participate in Genesis
frontier COMPARISON while being blocked from use as a distillation
teacher, and the schema must never let one imply the other. Cross-field
invariants: `reference_evaluation_admission_status=ADMITTED` requires
`identity_status=RESOLVED` AND `license_or_terms_status=CLEAR` AND
acceptable `evidence_retention_status` AND a non-BLOCKED
`access_preflight_status`; `teacher_use_status=ADMITTED` requires a
non-empty `teacher_use_evidence_reference`; `mutable_identity_status`
must be `FIXED_IMMUTABLE` for OPEN_WEIGHT references and
`MUTABLE_REFERENCE_IDENTITY` for MUTABLE_HOSTED_API references (a
hosted API can never claim a fixed immutable identity it does not
provider-expose).

Phase 21B.4.18 hardening (schema v5 -> v6): independent audit of Phase
21B.4.17.2 noted that `compute_admission_quorum()` and this module's own
`_validate_reference()` could still trust a reference's
`access_preflight_status` string without machine-proving the underlying
evidence -- a forged or stale status string could silently count toward
the locked Genesis frontier execution quorum. Six new required fields
close this: `automated_evaluation_status`, `private_holdout_status`,
`access_path_identified`, `model_identity_attributable`,
`non_financial_blocker_status`, `full_protocol_access_validation`. The
smallest robust fix (deliberately not a schema redesign) is that
`_validate_reference()` now calls the SAME fail-closed function the
quorum engine uses,
`orca.eval.frontier_reference_admission_quorum.validate_full_protocol_
access_readiness()`, against these six fields (plus the four already-
required admission fields) whenever `access_preflight_status` claims a
counting status (`QUALIFIED_FOR_FUTURE_EXECUTION` or
`PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK`) -- a reference cannot
even load into a valid registry claiming readiness its own recorded
evidence does not support. `full_protocol_access_validation` is an
audit-trail field only (PASSED/FAILED/NOT_ATTEMPTED); it must agree with
live re-validation (PASSED only when access_preflight_status claims a
counting status AND validation actually passes) but is NEVER itself
trusted as the source of truth -- `compute_admission_quorum()` always
re-derives readiness from the underlying evidence fields at count time,
so a hand-edited `full_protocol_access_validation=PASSED` with no
supporting evidence can never inflate the quorum (see
`frontier_reference_admission_quorum.py`'s Phase 21B.4.18 docstring
addendum and its quorum tamper tests).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

REGISTRY_SCHEMA_VERSION = "genesis-candidate-execution-registry-v6"

_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

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

# Phase 21B.4.11 §5A hardening: the expected candidate_class value per
# section -- a deployable candidate accidentally tagged with the
# control class (or vice versa) is a wiring bug, not a legitimate data
# variation.
EXPECTED_DEPLOYABLE_CANDIDATE_CLASS = "DEPLOYABLE_GENESIS_FOUNDATION_CANDIDATE"
EXPECTED_CONTROL_CANDIDATE_CLASS = "CONTROL_SMALL_BASELINE"

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
    # Phase 21B.4.15 §6: explicit, separately-validated qualification
    # dimensions -- see the module docstring addendum below for why
    # runtime_qualification_status alone is not sufficient.
    "load_compatibility_status", "production_serving_status",
    "financial_acceptance_status", "capability_status",
)

CONTROL_REQUIRED_FIELDS = (
    "candidate_class", "canonical_candidate_name", "organization", "artifact_repository",
    "exact_immutable_revision", "tokenizer_repository", "tokenizer_revision",
    "architecture", "total_parameters", "license_identifier", "stage0_status", "role",
    # Phase 21B.4.16 §9: explicit control-admission dimensions, mirroring
    # the deployable-candidate hardening from Phase 21B.4.15 but kept
    # deliberately smaller -- controls are never production-serving-
    # qualified foundation candidates, so they get no
    # production_serving_status/financial_acceptance_status/
    # capability_status fields at all (§10: a control entry must never be
    # structurally capable of being read as a deployable finalist).
    "identity_status", "license_status", "control_admission_status",
    "runtime_preflight_status", "runtime_qualification_status",
    "runtime_smoke_eligibility", "runtime_smoke_blocked_reason",
)

# Fields that only ever belong on a DEPLOYABLE_GENESIS_FOUNDATION_CANDIDATE
# entry. Phase 21B.4.16 §10 structural invariant: a control entry must
# never carry any of these, which would let it be misread as a
# deployable finalist despite candidate_class/role saying otherwise.
_DEPLOYABLE_ONLY_FIELDS = (
    "qualification_type", "qualification_manifest_path", "qualification_manifest_digest_sha256",
    "load_compatibility_status", "production_serving_status",
    "financial_acceptance_status", "capability_status",
)

VALID_CONTROL_ADMISSION_STATUSES = ("ADMITTED", "BLOCKED", "REVIEW_REQUIRED")
VALID_RUNTIME_PREFLIGHT_STATUSES = ("READY", "BLOCKED", "INCONCLUSIVE", "NOT_TESTED")
VALID_CONTROL_RUNTIME_QUALIFICATION_STATUSES = ("NOT_TESTED", "QUALIFIED", "FAILED", "INCONCLUSIVE")

REQUIRED_CONTROL_ROLE_TEXT = "CONTROL / SMALL BASELINE -- never a candidate finalist"

REFERENCE_REQUIRED_FIELDS = (
    "reference_name", "organization", "identity_type", "artifact_repository",
    "exact_immutable_revision", "license_identifier", "zero_cash_access_status",
    "availability_status",
    # Phase 21B.4.17 §21: the smallest robust extension needed to
    # distinguish reference-evaluation admission from teacher/
    # distillation admission, and to make evidence-retention and
    # access-preflight status machine-checkable rather than implied by
    # prose in zero_cash_access_status/availability_status.
    "identity_status", "license_or_terms_status",
    "reference_evaluation_admission_status", "teacher_use_status",
    "teacher_use_evidence_reference", "access_preflight_status",
    "evidence_retention_status", "mutable_identity_status",
    # Phase 21B.4.18 §7/§8: machine-enforced promotion-gate evidence
    # dimensions -- see the module docstring addendum for why a naked
    # access_preflight_status string is no longer sufficient by itself.
    "automated_evaluation_status", "private_holdout_status",
    "access_path_identified", "model_identity_attributable",
    "non_financial_blocker_status", "full_protocol_access_validation",
)

VALID_IDENTITY_TYPES = ("OPEN_WEIGHT", "MUTABLE_HOSTED_API")

# Phase 21B.4.17 §21/§22: frontier-reference-specific status enums.
# Deliberately NOT copied from the deployable/control schemas verbatim
# -- a frontier reference is neither a deployable finalist nor a
# control, and conflating "this reference may be COMPARED against" with
# "this reference may be used to TRAIN/distill a candidate" would be a
# real compliance defect (§10: these are separate decisions with
# separate evidence requirements).
VALID_REFERENCE_TERMS_STATUSES = ("CLEAR", "REVIEW_REQUIRED", "SEPARATE_PERMISSION_REQUIRED")
VALID_REFERENCE_EVALUATION_ADMISSION_STATUSES = ("ADMITTED", "BLOCKED", "REVIEW_REQUIRED")
VALID_TEACHER_USE_STATUSES = ("ADMITTED", "BLOCKED", "NOT_EVALUATED")
VALID_ACCESS_PREFLIGHT_STATUSES = (
    "QUALIFIED_FOR_FUTURE_EXECUTION",
    "PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK",
    "UNQUALIFIED",
    "BLOCKED",
    "NOT_TESTED",
)
VALID_EVIDENCE_RETENTION_STATUSES = ("PERMITTED", "PROHIBITED", "REVIEW_REQUIRED", "NOT_APPLICABLE")
# FIXED_IMMUTABLE: identity is a pinned artifact revision that never
# changes underneath ORNEUR (OPEN_WEIGHT references only).
# MUTABLE_REFERENCE_IDENTITY: no provider-exposed immutable version
# exists -- two calls at different times cannot be assumed to hit the
# same underlying model (§8). This does not by itself disqualify a
# reference; it changes reproducibility treatment.
VALID_MUTABLE_IDENTITY_STATUSES = ("FIXED_IMMUTABLE", "MUTABLE_REFERENCE_IDENTITY")

# Phase 21B.4.18 §7/§8: promotion-gate evidence dimension enums.
VALID_AUTOMATED_EVALUATION_STATUSES = ("CLEAR", "BLOCKED", "REVIEW_REQUIRED", "NOT_EVALUATED")
VALID_PRIVATE_HOLDOUT_STATUSES = ("PERMITTED", "REVIEW_REQUIRED", "BLOCKED", "NOT_EVALUATED")
# Audit-trail only -- never trusted as the source of truth for quorum
# counting. See the module docstring's Phase 21B.4.18 addendum.
VALID_FULL_PROTOCOL_ACCESS_VALIDATION_STATUSES = ("PASSED", "FAILED", "NOT_ATTEMPTED")

VALID_IDENTITY_STATUSES = ("RESOLVED", "IDENTITY_UNRESOLVED")
VALID_LICENSE_STATUSES = ("CLEAR", "LICENSE_REVIEW_REQUIRED", "SEPARATE_LICENSE_REQUIRED")
VALID_RUNTIME_QUALIFICATION_STATUSES = ("UNQUALIFIED", "QUALIFIED")
VALID_RUNTIME_SMOKE_ELIGIBILITY = ("ELIGIBLE", "BLOCKED")

# Phase 21B.4.15 §6: explicit qualification dimensions. These exist
# because `runtime_qualification_status == "QUALIFIED"` alone is
# dangerously coarse -- it is true for BOTH a candidate that merely
# loaded and generated through native Transformers
# (RUNTIME_LOAD_COMPATIBILITY_QUALIFIED) AND one actually served through
# a production inference engine over a real network/API path
# (PRODUCTION_SERVING_RUNTIME_QUALIFIED). A reader (or a caller of
# `verify_candidate_qualification_end_to_end`) who only checks
# `runtime_qualification_status` cannot tell those apart. These four
# fields make that distinction explicit and machine-validated; see
# `_validate_deployable`'s cross-field invariants below for how they are
# kept consistent with `qualification_type` and each other.
VALID_LOAD_COMPATIBILITY_STATUSES = ("NOT_TESTED", "QUALIFIED", "FAILED", "INCONCLUSIVE")
VALID_PRODUCTION_SERVING_STATUSES = (
    "NOT_TESTED", "QUALIFIED", "FAILED", "INCONCLUSIVE", "DEFERRED",
    # Phase 21B.4.15: a distinct, honest state for GLM-5.3-Flash's exact
    # situation -- the serving path was genuinely technically successful
    # (server ready, real HTTP generation) but formal acceptance was
    # blocked by a hard, unrelated financial-gate violation. Neither
    # FAILED (implies a technical/model/runtime defect, which did not
    # occur) nor DEFERRED (implies the attempt simply hasn't happened
    # yet) honestly describes this. Never implies QUALIFIED.
    "TECHNICALLY_SUCCEEDED_FINANCIAL_GATE_FAILED",
)
VALID_FINANCIAL_ACCEPTANCE_STATUSES = (
    "NOT_APPLICABLE", "NOT_TESTED", "ZERO_OWNER_CASH_PASSED", "ZERO_OWNER_CASH_FAILED", "DEFERRED",
)
# Phase 21B.4.15.2 §10 semantics note: ZERO_OWNER_CASH_PASSED means the
# qualifying EXECUTION produced no incremental owner-billed cost
# (owner_billed_delta_usd == 0 for that run's manifest) -- it does NOT
# mean the provider account has never had any billed cost in its
# history. A candidate whose qualifying run achieved a zero delta on an
# account that separately carries a nonzero historical baseline (from an
# unrelated prior incident, e.g. GLM-5.3-Flash's Phase 21B.4.13 $3.52
# violation) is still ZERO_OWNER_CASH_PASSED. Conversely,
# ZERO_OWNER_CASH_FAILED records that THIS candidate's own qualifying
# execution caused new owner cost, independent of the account's prior
# history. These two facts (account history vs. per-execution delta)
# are deliberately not conflated into one field.
VALID_CAPABILITY_STATUSES = (
    "UNPROVEN", "EVALUATED", "FRONTIER_CLASS_ON_LOCKED_PROTOCOL", "FAILED_FRONTIER_GATE", "INCONCLUSIVE",
)

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
    def load(cls, path: Path, manifest_root: Path | None = None) -> "CandidateExecutionRegistry":
        """Loads and schema-validates the registry, then (Phase
        21B.4.11.3 §1) ALWAYS enforces that every QUALIFIED deployable
        candidate links to a real, schema-valid, digest-matching
        runtime qualification manifest -- this is not optional and
        cannot be silently skipped by a caller who forgets to pass
        `manifest_root`. When `manifest_root` is omitted, it is derived
        from the registry file's own location via
        `_derive_manifest_root()` (the nearest ancestor directory
        containing `.git`); pass it explicitly only to override that
        default (e.g. in a test fixture with its own throwaway repo
        layout). `from_dict()` alone (used by synthetic-fixture tests
        with no real filesystem backing) still does not perform this
        filesystem-backed check, since it has no directory to resolve
        manifest paths against -- but `from_dict()`/`_validate_deployable`
        DO structurally require a QUALIFIED entry to carry its
        manifest-linkage metadata regardless."""
        path = Path(path)
        data = json.loads(path.read_text())
        registry = cls.from_dict(data)
        root = Path(manifest_root).resolve() if manifest_root is not None else _derive_manifest_root(path)
        for entry in registry.deployable_candidates:
            verify_qualified_manifest_linkage(entry, root)
        return registry

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
    if entry["candidate_class"] != EXPECTED_DEPLOYABLE_CANDIDATE_CLASS:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has candidate_class={entry['candidate_class']!r}, expected "
            f"{EXPECTED_DEPLOYABLE_CANDIDATE_CLASS!r} -- a deployable candidate tagged with the wrong "
            "class is a wiring bug, not a legitimate data variation."
        )
    _require_hex40_revision(entry["exact_immutable_revision"], f"deployable candidate {name!r}")
    _require_hex40_revision(entry["tokenizer_revision"], f"deployable candidate {name!r} tokenizer_revision")

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

    # Phase 21B.4.11.3 §1: a structural (filesystem-free) check that
    # runs even for synthetic from_dict() fixtures -- a QUALIFIED
    # candidate must carry its manifest-linkage metadata, or the
    # registry itself is internally inconsistent regardless of whether
    # any file actually exists on disk. Filesystem-backed verification
    # (does the manifest exist, does its digest match) happens
    # separately in verify_qualified_manifest_linkage(), which
    # CandidateExecutionRegistry.load() now always calls for every
    # file-backed load.
    if entry.get("runtime_qualification_status") == "QUALIFIED":
        for field in ("qualification_type", "qualification_manifest_path", "qualification_manifest_digest_sha256"):
            if not entry.get(field):
                raise RegistrySchemaError(
                    f"deployable candidate {name!r} is QUALIFIED but missing required manifest-linkage "
                    f"field {field!r}"
                )
        digest = entry["qualification_manifest_digest_sha256"]
        if not _HEX64_RE.match(digest):
            raise RegistrySchemaError(
                f"deployable candidate {name!r} has a malformed qualification_manifest_digest_sha256 "
                f"(must be exactly 64 lowercase hex characters): {digest!r}"
            )

    # ── Phase 21B.4.15 §6/§23: explicit qualification-dimension fields ──
    # and the cross-field invariants that make it structurally
    # impossible to confuse load compatibility with production serving,
    # or to claim acceptance a candidate's actual evidence does not
    # support.
    if entry["load_compatibility_status"] not in VALID_LOAD_COMPATIBILITY_STATUSES:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has unrecognized load_compatibility_status="
            f"{entry['load_compatibility_status']!r}"
        )
    if entry["production_serving_status"] not in VALID_PRODUCTION_SERVING_STATUSES:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has unrecognized production_serving_status="
            f"{entry['production_serving_status']!r}"
        )
    if entry["financial_acceptance_status"] not in VALID_FINANCIAL_ACCEPTANCE_STATUSES:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has unrecognized financial_acceptance_status="
            f"{entry['financial_acceptance_status']!r}"
        )
    if entry["capability_status"] not in VALID_CAPABILITY_STATUSES:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has unrecognized capability_status={entry['capability_status']!r}"
        )

    qualification_type = entry.get("qualification_type")

    # Invalid state (§23): production_serving_status=QUALIFIED without an
    # actual PRODUCTION_SERVING_RUNTIME_QUALIFIED linked manifest. This is
    # the exact ambiguity this phase exists to close -- a candidate that
    # only achieved RUNTIME_LOAD_COMPATIBILITY_QUALIFIED (e.g. Qwen3.8-27B)
    # can never claim production_serving_status=QUALIFIED.
    if entry["production_serving_status"] == "QUALIFIED":
        from orca.eval.runtime_qualification_manifest import PRODUCTION_SERVING_TYPE

        if qualification_type != PRODUCTION_SERVING_TYPE:
            raise RegistrySchemaError(
                f"deployable candidate {name!r} has production_serving_status=QUALIFIED but "
                f"qualification_type={qualification_type!r} (must be {PRODUCTION_SERVING_TYPE!r}) -- "
                "production-serving qualification can never be claimed without a linked, accepted "
                "PRODUCTION_SERVING_RUNTIME_QUALIFIED manifest."
            )
        if entry.get("runtime_qualification_status") != "QUALIFIED":
            raise RegistrySchemaError(
                f"deployable candidate {name!r} has production_serving_status=QUALIFIED but "
                f"runtime_qualification_status={entry.get('runtime_qualification_status')!r} -- "
                "production serving qualification requires an accepted, manifest-linked runtime "
                "qualification record."
            )

    # Invalid state (§23): load_compatibility_status=QUALIFIED without any
    # qualifying evidence linkage at all.
    if entry["load_compatibility_status"] == "QUALIFIED" and not entry.get("qualification_manifest_path"):
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has load_compatibility_status=QUALIFIED but no "
            "qualification_manifest_path -- load compatibility can never be claimed without linked evidence."
        )

    # A TECHNICALLY_SUCCEEDED_FINANCIAL_GATE_FAILED production-serving
    # result (GLM-5.3-Flash's exact situation) must never simultaneously
    # claim financial acceptance passed, and must never claim formal
    # production-serving QUALIFIED -- those would directly contradict
    # the whole reason this state exists.
    if entry["production_serving_status"] == "TECHNICALLY_SUCCEEDED_FINANCIAL_GATE_FAILED":
        if entry["financial_acceptance_status"] != "ZERO_OWNER_CASH_FAILED":
            raise RegistrySchemaError(
                f"deployable candidate {name!r} has production_serving_status="
                "TECHNICALLY_SUCCEEDED_FINANCIAL_GATE_FAILED but financial_acceptance_status="
                f"{entry['financial_acceptance_status']!r} (must be ZERO_OWNER_CASH_FAILED) -- this "
                "state exists specifically to record a financial-gate failure."
            )

    # Invalid state (§23): financial_acceptance_status=ZERO_OWNER_CASH_FAILED
    # can never coexist with production_serving_status=QUALIFIED -- a
    # candidate cannot be formally production-serving qualified while its
    # own financial gate is recorded as failed.
    if (
        entry["financial_acceptance_status"] == "ZERO_OWNER_CASH_FAILED"
        and entry["production_serving_status"] == "QUALIFIED"
    ):
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has financial_acceptance_status=ZERO_OWNER_CASH_FAILED and "
            "production_serving_status=QUALIFIED simultaneously -- a failed zero-owner-cash gate can "
            "never coexist with formal production-serving acceptance."
        )

    # Invalid state (§23): capability escalated beyond UNPROVEN without a
    # recorded evidence reference for that claim -- no such evaluation
    # evidence system exists yet in this registry, so no candidate may
    # currently claim anything beyond UNPROVEN/INCONCLUSIVE without one.
    if entry["capability_status"] in ("EVALUATED", "FRONTIER_CLASS_ON_LOCKED_PROTOCOL", "FAILED_FRONTIER_GATE"):
        if not entry.get("capability_evidence_reference"):
            raise RegistrySchemaError(
                f"deployable candidate {name!r} has capability_status={entry['capability_status']!r} but no "
                "capability_evidence_reference -- a capability claim beyond UNPROVEN/INCONCLUSIVE must cite "
                "the locked evaluation evidence that established it."
            )


def _validate_control(entry: dict) -> None:
    """Phase 21B.4.16 §9/§10: control-admission dimensions and the
    structural invariant that a control entry can never be misread as a
    deployable Genesis foundation candidate, a frontier reference, or a
    selected Genesis foundation."""
    _require_fields(entry, CONTROL_REQUIRED_FIELDS, "controls")
    name = entry["canonical_candidate_name"]
    if entry["candidate_class"] != EXPECTED_CONTROL_CANDIDATE_CLASS:
        raise RegistrySchemaError(
            f"control {name!r} has candidate_class={entry['candidate_class']!r}, expected "
            f"{EXPECTED_CONTROL_CANDIDATE_CLASS!r} -- a control tagged with the wrong class is a "
            "wiring bug, not a legitimate data variation."
        )
    if entry.get("role") != REQUIRED_CONTROL_ROLE_TEXT:
        raise RegistrySchemaError(
            f"control {name!r} has role={entry.get('role')!r}, expected exactly "
            f"{REQUIRED_CONTROL_ROLE_TEXT!r} -- a control's role text is a structural guard against it "
            "being misread as a candidate finalist, not free-form prose."
        )
    for forbidden_field in _DEPLOYABLE_ONLY_FIELDS:
        if forbidden_field in entry:
            raise RegistrySchemaError(
                f"control {name!r} carries deployable-only field {forbidden_field!r} -- a control entry "
                "must never be structurally capable of being read as a deployable finalist (Phase "
                "21B.4.16 §10)."
            )
    _require_hex40_revision(entry["exact_immutable_revision"], f"control {name!r}")
    _require_hex40_revision(entry["tokenizer_revision"], f"control {name!r} tokenizer_revision")
    if entry["stage0_status"] not in VALID_STAGE0_STATUSES:
        raise RegistrySchemaError(f"control {name!r} has unrecognized stage0_status={entry['stage0_status']!r}")

    if entry["identity_status"] not in VALID_IDENTITY_STATUSES:
        raise RegistrySchemaError(f"control {name!r} has unrecognized identity_status={entry['identity_status']!r}")
    if entry["license_status"] not in VALID_LICENSE_STATUSES:
        raise RegistrySchemaError(f"control {name!r} has unrecognized license_status={entry['license_status']!r}")
    if entry["control_admission_status"] not in VALID_CONTROL_ADMISSION_STATUSES:
        raise RegistrySchemaError(
            f"control {name!r} has unrecognized control_admission_status="
            f"{entry['control_admission_status']!r}"
        )
    if entry["runtime_preflight_status"] not in VALID_RUNTIME_PREFLIGHT_STATUSES:
        raise RegistrySchemaError(
            f"control {name!r} has unrecognized runtime_preflight_status="
            f"{entry['runtime_preflight_status']!r}"
        )
    if entry["runtime_qualification_status"] not in VALID_CONTROL_RUNTIME_QUALIFICATION_STATUSES:
        raise RegistrySchemaError(
            f"control {name!r} has unrecognized runtime_qualification_status="
            f"{entry['runtime_qualification_status']!r}"
        )
    if entry["runtime_smoke_eligibility"] not in VALID_RUNTIME_SMOKE_ELIGIBILITY:
        raise RegistrySchemaError(
            f"control {name!r} has unrecognized runtime_smoke_eligibility="
            f"{entry['runtime_smoke_eligibility']!r}"
        )

    # Cross-field invariants -- mirror the deployable-candidate discipline
    # from Phase 21B.4.10.1/21B.4.15: admission/eligibility must follow
    # deterministically from identity/license, never be set independently.
    if entry["license_status"] == "LICENSE_REVIEW_REQUIRED":
        if entry["control_admission_status"] == "ADMITTED":
            raise RegistrySchemaError(
                f"control {name!r} has license_status=LICENSE_REVIEW_REQUIRED but "
                "control_admission_status=ADMITTED -- an unresolved license can never admit a control."
            )
        if entry["runtime_smoke_eligibility"] != "BLOCKED":
            raise RegistrySchemaError(
                f"control {name!r} has license_status=LICENSE_REVIEW_REQUIRED but "
                f"runtime_smoke_eligibility={entry['runtime_smoke_eligibility']!r} -- an unresolved "
                "license must block runtime smoke eligibility."
            )
    if entry["identity_status"] != "RESOLVED":
        if entry["control_admission_status"] == "ADMITTED":
            raise RegistrySchemaError(
                f"control {name!r} has identity_status={entry['identity_status']!r} (not RESOLVED) but "
                "control_admission_status=ADMITTED -- unresolved identity can never admit a control."
            )
        if entry["runtime_smoke_eligibility"] != "BLOCKED":
            raise RegistrySchemaError(
                f"control {name!r} has identity_status={entry['identity_status']!r} (not RESOLVED) but "
                f"runtime_smoke_eligibility={entry['runtime_smoke_eligibility']!r} -- unresolved identity "
                "must block runtime smoke eligibility."
            )
    if entry["control_admission_status"] == "BLOCKED" and not entry.get("runtime_smoke_blocked_reason"):
        raise RegistrySchemaError(
            f"control {name!r} is control_admission_status=BLOCKED but has no runtime_smoke_blocked_reason"
        )
    if entry["control_admission_status"] == "ADMITTED" and entry["runtime_smoke_eligibility"] != "ELIGIBLE":
        raise RegistrySchemaError(
            f"control {name!r} has control_admission_status=ADMITTED but "
            f"runtime_smoke_eligibility={entry['runtime_smoke_eligibility']!r} -- an admitted control must "
            "be eligible for a future runtime smoke."
        )
    # Phase 21B.4.16 §25.I: no control is runtime-qualified by THIS phase
    # -- a data-fact assertion about the current registry content, not a
    # permanent code-level ban (a future, separately-authorized runtime
    # phase may legitimately set this to QUALIFIED/FAILED once real GPU
    # evidence exists).
    if entry["runtime_qualification_status"] != "NOT_TESTED" and not entry.get("runtime_qualification_evidence_reference"):
        raise RegistrySchemaError(
            f"control {name!r} has runtime_qualification_status="
            f"{entry['runtime_qualification_status']!r} but no runtime_qualification_evidence_reference -- "
            "a non-NOT_TESTED runtime qualification claim must cite the evidence that established it."
        )


def _validate_reference(entry: dict) -> None:
    """Phase 21B.4.17 §21/§22: frontier-reference admission and access
    fail-closed cross-field invariants. Reference-evaluation admission
    and teacher/distillation admission are deliberately independent
    decisions (§10) -- a reference may be REFERENCE_EVALUATION_ADMITTED
    while TEACHER_USE_BLOCKED, and this function must never let one
    imply the other."""
    _require_fields(entry, REFERENCE_REQUIRED_FIELDS, "frontier_references")
    name = entry["reference_name"]

    if entry["identity_type"] not in VALID_IDENTITY_TYPES:
        raise RegistrySchemaError(f"frontier reference {name!r} has unrecognized identity_type={entry['identity_type']!r}")
    if entry["availability_status"] not in VALID_AVAILABILITY_STATUSES:
        raise RegistrySchemaError(
            f"frontier reference {name!r} has unrecognized availability_status={entry['availability_status']!r}"
        )
    if entry["identity_status"] not in VALID_IDENTITY_STATUSES:
        raise RegistrySchemaError(f"frontier reference {name!r} has unrecognized identity_status={entry['identity_status']!r}")
    if entry["license_or_terms_status"] not in VALID_REFERENCE_TERMS_STATUSES:
        raise RegistrySchemaError(
            f"frontier reference {name!r} has unrecognized license_or_terms_status={entry['license_or_terms_status']!r}"
        )
    if entry["reference_evaluation_admission_status"] not in VALID_REFERENCE_EVALUATION_ADMISSION_STATUSES:
        raise RegistrySchemaError(
            f"frontier reference {name!r} has unrecognized reference_evaluation_admission_status="
            f"{entry['reference_evaluation_admission_status']!r}"
        )
    if entry["teacher_use_status"] not in VALID_TEACHER_USE_STATUSES:
        raise RegistrySchemaError(f"frontier reference {name!r} has unrecognized teacher_use_status={entry['teacher_use_status']!r}")
    if entry["access_preflight_status"] not in VALID_ACCESS_PREFLIGHT_STATUSES:
        raise RegistrySchemaError(
            f"frontier reference {name!r} has unrecognized access_preflight_status={entry['access_preflight_status']!r}"
        )
    if entry["evidence_retention_status"] not in VALID_EVIDENCE_RETENTION_STATUSES:
        raise RegistrySchemaError(
            f"frontier reference {name!r} has unrecognized evidence_retention_status={entry['evidence_retention_status']!r}"
        )
    if entry["mutable_identity_status"] not in VALID_MUTABLE_IDENTITY_STATUSES:
        raise RegistrySchemaError(
            f"frontier reference {name!r} has unrecognized mutable_identity_status={entry['mutable_identity_status']!r}"
        )
    if entry["automated_evaluation_status"] not in VALID_AUTOMATED_EVALUATION_STATUSES:
        raise RegistrySchemaError(
            f"frontier reference {name!r} has unrecognized automated_evaluation_status="
            f"{entry['automated_evaluation_status']!r}"
        )
    if entry["private_holdout_status"] not in VALID_PRIVATE_HOLDOUT_STATUSES:
        raise RegistrySchemaError(
            f"frontier reference {name!r} has unrecognized private_holdout_status={entry['private_holdout_status']!r}"
        )
    if not isinstance(entry["access_path_identified"], bool):
        raise RegistrySchemaError(
            f"frontier reference {name!r} has non-boolean access_path_identified={entry['access_path_identified']!r}"
        )
    if not isinstance(entry["model_identity_attributable"], bool):
        raise RegistrySchemaError(
            f"frontier reference {name!r} has non-boolean model_identity_attributable="
            f"{entry['model_identity_attributable']!r}"
        )
    if not entry.get("non_financial_blocker_status"):
        raise RegistrySchemaError(f"frontier reference {name!r} has empty non_financial_blocker_status")
    if entry["full_protocol_access_validation"] not in VALID_FULL_PROTOCOL_ACCESS_VALIDATION_STATUSES:
        raise RegistrySchemaError(
            f"frontier reference {name!r} has unrecognized full_protocol_access_validation="
            f"{entry['full_protocol_access_validation']!r}"
        )

    revision = str(entry["exact_immutable_revision"])
    if entry["identity_type"] == "MUTABLE_HOSTED_API":
        if "NOT_AVAILABLE" not in revision:
            raise RegistrySchemaError(
                f"frontier reference {name!r} is identity_type=MUTABLE_HOSTED_API but claims a "
                f"real-looking pinned revision ({revision!r}) -- a mutable hosted API can never have "
                "an immutable execution identity."
            )
        # §22.D: a mutable hosted API can never claim a fixed immutable
        # identity unless the provider actually exposes one -- which,
        # for a MUTABLE_HOSTED_API entry, is precisely what the branch
        # above already established is not the case here.
        if entry["mutable_identity_status"] != "MUTABLE_REFERENCE_IDENTITY":
            raise RegistrySchemaError(
                f"frontier reference {name!r} is identity_type=MUTABLE_HOSTED_API but mutable_identity_status="
                f"{entry['mutable_identity_status']!r} -- must be MUTABLE_REFERENCE_IDENTITY unless the "
                "provider actually exposes an immutable version identifier."
            )
    else:  # OPEN_WEIGHT
        # §22.E: an open-weight reference must have a valid pinned
        # immutable revision -- and, symmetrically, cannot claim the
        # mutable-identity status a hosted API alone is permitted.
        _require_hex40_revision(entry["exact_immutable_revision"], f"frontier reference {name!r}")
        if entry["mutable_identity_status"] != "FIXED_IMMUTABLE":
            raise RegistrySchemaError(
                f"frontier reference {name!r} is identity_type=OPEN_WEIGHT but mutable_identity_status="
                f"{entry['mutable_identity_status']!r} -- must be FIXED_IMMUTABLE."
            )

    # §22.A/§22.B: REFERENCE_EVALUATION_ADMITTED requires identity
    # resolved AND terms clear AND evidence-retention acceptable AND
    # access-preflight not blocked. license/terms REVIEW_REQUIRED (or
    # SEPARATE_PERMISSION_REQUIRED) can never coexist with an ADMITTED
    # evaluation-admission claim -- this is enforced structurally, not
    # left to prose.
    if entry["reference_evaluation_admission_status"] == "ADMITTED":
        if entry["identity_status"] != "RESOLVED":
            raise RegistrySchemaError(
                f"frontier reference {name!r} is reference_evaluation_admission_status=ADMITTED but "
                f"identity_status={entry['identity_status']!r} -- admission requires resolved identity."
            )
        if entry["license_or_terms_status"] != "CLEAR":
            raise RegistrySchemaError(
                f"frontier reference {name!r} is reference_evaluation_admission_status=ADMITTED but "
                f"license_or_terms_status={entry['license_or_terms_status']!r} -- admission requires clear terms."
            )
        if entry["evidence_retention_status"] not in ("PERMITTED", "NOT_APPLICABLE"):
            raise RegistrySchemaError(
                f"frontier reference {name!r} is reference_evaluation_admission_status=ADMITTED but "
                f"evidence_retention_status={entry['evidence_retention_status']!r} -- admission requires "
                "acceptable evidence-retention terms."
            )
        if entry["access_preflight_status"] == "BLOCKED":
            raise RegistrySchemaError(
                f"frontier reference {name!r} is reference_evaluation_admission_status=ADMITTED but "
                "access_preflight_status=BLOCKED -- admission requires a non-blocked access path."
            )

    # §22.C: teacher/distillation admission requires explicit evidence,
    # never inferred merely because evaluation use is permitted.
    if entry["teacher_use_status"] == "ADMITTED" and not entry.get("teacher_use_evidence_reference"):
        raise RegistrySchemaError(
            f"frontier reference {name!r} is teacher_use_status=ADMITTED but has no "
            "teacher_use_evidence_reference -- teacher/distillation admission must cite explicit permission evidence."
        )

    # Phase 21B.4.18 §7/§8: a reference cannot even LOAD into a valid
    # registry while claiming a counting access_preflight_status unless
    # its own recorded evidence fields actually pass the same fail-closed
    # validator the quorum engine uses. This is a schema-level defense in
    # depth on top of compute_admission_quorum()'s own independent
    # re-validation (which never trusts this field either) -- see the
    # module docstring's Phase 21B.4.18 addendum.
    from orca.eval.frontier_reference_admission_quorum import (
        _COUNTING_ACCESS_PREFLIGHT_STATUSES,
        AccessReadinessError,
        validate_full_protocol_access_readiness,
    )

    claims_counting_status = entry["access_preflight_status"] in _COUNTING_ACCESS_PREFLIGHT_STATUSES
    if claims_counting_status:
        try:
            validate_full_protocol_access_readiness(
                entry["access_preflight_status"],
                reference_evaluation_admission_status=entry["reference_evaluation_admission_status"],
                license_or_terms_status=entry["license_or_terms_status"],
                evidence_retention_status=entry["evidence_retention_status"],
                automated_evaluation_status=entry["automated_evaluation_status"],
                private_holdout_status=entry["private_holdout_status"],
                access_path_identified=entry["access_path_identified"],
                model_identity_attributable=entry["model_identity_attributable"],
                non_financial_blocker_status=entry["non_financial_blocker_status"],
            )
        except AccessReadinessError as e:
            raise RegistrySchemaError(
                f"frontier reference {name!r} claims access_preflight_status="
                f"{entry['access_preflight_status']!r} but fails full-protocol access validation against its "
                f"own recorded evidence fields: {e}"
            ) from e
        if entry["full_protocol_access_validation"] != "PASSED":
            raise RegistrySchemaError(
                f"frontier reference {name!r} claims a counting access_preflight_status and validates, but "
                f"full_protocol_access_validation={entry['full_protocol_access_validation']!r} != PASSED -- "
                "the recorded audit-trail field must agree with live validation."
            )
    elif entry["full_protocol_access_validation"] == "PASSED":
        raise RegistrySchemaError(
            f"frontier reference {name!r} has access_preflight_status={entry['access_preflight_status']!r} "
            "(not a counting status) but full_protocol_access_validation=PASSED -- PASSED must never be "
            "recorded for a reference that does not claim full-protocol readiness."
        )


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
        _validate_control(entry)

    # Phase 21B.4.11 §5A: reject accidental duplicate/cross-wired
    # candidate identities -- two different candidates (deployable or
    # control) must never share the same artifact_repository, and no
    # deployable candidate may accidentally reuse a control's identity
    # or vice versa.
    repo_owners: dict[str, str] = {}
    for section, key in (("deployable_candidates", "canonical_candidate_name"), ("controls", "canonical_candidate_name")):
        for entry in data[section]:
            repo = entry["artifact_repository"]
            name = entry[key]
            if repo in repo_owners:
                raise RegistrySchemaError(
                    f"artifact_repository {repo!r} is claimed by both {repo_owners[repo]!r} and {name!r} -- "
                    "a duplicate or cross-wired candidate identity."
                )
            repo_owners[repo] = name

    for entry in data["frontier_references"]:
        _validate_reference(entry)


def _derive_manifest_root(registry_path: Path) -> Path:
    """Phase 21B.4.11.3 §1: derive the repository-controlled manifest
    root from the registry file's own location, so `load()` never needs
    a caller-supplied security-relevant argument to perform manifest
    verification by default. Walks up from the registry file looking
    for the nearest ancestor containing a `.git` directory (the
    repository root marker) -- fails closed (raises) rather than
    silently guessing a wrong root if none is found."""
    current = Path(registry_path).resolve().parent
    for _ in range(15):
        if (current / ".git").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    raise RegistrySchemaError(
        f"could not derive a repository-controlled manifest root from registry path {registry_path!r} "
        "(no ancestor directory containing .git was found) -- pass manifest_root explicitly"
    )


def _verify_manifest_linkage(entry: dict, manifest_root: Path) -> dict:
    """Shared linkage-verification body (Phase 21B.4.11.2 §4, hardened
    21B.4.12.1 §5): resolves and fully verifies whatever manifest a
    registry entry declares -- schema-valid, identity-matching,
    digest-matching, and (for a STRICT_RUNTIME_SMOKE_V2 manifest) with
    every declared evidence artifact byte-verified against its declared
    hash. Deliberately status-agnostic: it verifies exactly the same
    integrity chain whether the linked manifest's own
    `qualification_type` is a QUALIFIED type or
    RUNTIME_QUALIFICATION_FAILED -- a failed-result manifest is never
    "less verified" than a qualified one, only differently interpreted
    by its caller. Callers are responsible for deciding, from the
    entry's `runtime_qualification_status` and `qualification_type`,
    whether verified linkage should be treated as acceptance."""
    # Imported locally to avoid a module-level import cycle risk and to
    # keep this registry module's top-level import surface unchanged
    # for callers that never touch manifest linkage.
    from orca.eval.runtime_qualification_manifest import (
        RuntimeQualificationManifestError,
        VALID_QUALIFICATION_TYPES,
        load_manifest,
        require_candidate_manifest,
        sha256_of_manifest,
        verify_evidence_artifacts_bytes,
    )

    name = entry["canonical_candidate_name"]

    for field in ("qualification_type", "qualification_manifest_path", "qualification_manifest_digest_sha256"):
        if not entry.get(field):
            raise RegistrySchemaError(
                f"deployable candidate {name!r} is missing required manifest-linkage field {field!r}"
            )

    qualification_type = entry["qualification_type"]
    if qualification_type not in VALID_QUALIFICATION_TYPES:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has unrecognized qualification_type {qualification_type!r}"
        )

    digest = entry["qualification_manifest_digest_sha256"]
    if not _HEX64_RE.match(digest):
        raise RegistrySchemaError(
            f"deployable candidate {name!r} has a malformed qualification_manifest_digest_sha256 "
            f"(must be exactly 64 lowercase hex characters): {digest!r}"
        )

    manifest_root = Path(manifest_root).resolve()
    raw_path = entry["qualification_manifest_path"]
    candidate_path = (manifest_root / raw_path).resolve()
    try:
        candidate_path.relative_to(manifest_root)
    except ValueError:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} qualification_manifest_path {raw_path!r} resolves "
            "outside the repository-controlled manifest root -- rejected as a path-escape/symlink-ambiguity risk."
        )
    if not candidate_path.is_file():
        raise RegistrySchemaError(
            f"deployable candidate {name!r} qualification_manifest_path {raw_path!r} does not exist"
        )

    try:
        manifest_data = load_manifest(candidate_path)
    except RuntimeQualificationManifestError as e:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} qualification manifest failed schema validation: {e}"
        ) from e

    try:
        require_candidate_manifest(
            manifest_data,
            candidate=name,
            repository=entry["artifact_repository"],
            revision=entry["exact_immutable_revision"],
            qualification_type=qualification_type,
        )
    except RuntimeQualificationManifestError as e:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} qualification manifest identity mismatch: {e}"
        ) from e

    recomputed_digest = sha256_of_manifest(manifest_data)
    if recomputed_digest != digest:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} manifest digest mismatch: registry records "
            f"{digest!r}, recomputed {recomputed_digest!r} from the manifest's current content."
        )

    try:
        verify_evidence_artifacts_bytes(manifest_data, manifest_root)
    except RuntimeQualificationManifestError as e:
        raise RegistrySchemaError(
            f"deployable candidate {name!r} strict evidence-artifact verification failed: {e}"
        ) from e

    return manifest_data


def verify_qualified_manifest_linkage(entry: dict, manifest_root: Path) -> dict | None:
    """Phase 21B.4.11.2 §4: a generic (non-Qwen-specific) enforcement
    that every QUALIFIED deployable candidate links to a real,
    schema-valid, identity-matching, digest-matching runtime
    qualification manifest -- and (Phase 21B.4.11.4 §5/§6), for a
    STRICT_RUNTIME_SMOKE_V2 manifest, that its declared evidence
    artifacts' actual bytes match their declared hashes, using
    `manifest_root` as the evidence root as well (the same
    repository-controlled directory both are resolved under). Returns
    the loaded, fully-verified manifest dict for QUALIFIED candidates
    (or `None` for UNQUALIFIED ones, which need no manifest at all).
    `manifest_root` is the repository-controlled root that every
    `qualification_manifest_path` (and, for STRICT manifests, every
    evidence-artifact path) must resolve underneath -- a path that
    escapes it (via `..` or a symlink) is rejected outright rather than
    silently followed."""
    if entry.get("runtime_qualification_status") != "QUALIFIED":
        return None
    return _verify_manifest_linkage(entry, manifest_root)


def verify_recorded_manifest_linkage(entry: dict, manifest_root: Path) -> dict | None:
    """Phase 21B.4.12.1 §5: a status-independent counterpart to
    `verify_qualified_manifest_linkage` for candidates whose registry
    entry records a manifest linkage without being QUALIFIED -- most
    notably a RUNTIME_QUALIFICATION_FAILED result (a failed live smoke
    is still a real, fully-evidenced execution that deserves complete
    verification, not a bare inspection). Runs the identical integrity
    chain as the QUALIFIED path (schema validation, candidate-identity
    match, canonical-digest match, and byte-verified evidence
    artifacts) regardless of the linked manifest's own
    `qualification_type`. Returns the verified manifest dict whenever
    the entry carries any manifest-linkage metadata at all, or `None`
    only when the entry has genuinely never been smoke-tested (no
    `qualification_type`/`qualification_manifest_path`/
    `qualification_manifest_digest_sha256` recorded) -- never `None`
    for a linked failure record."""
    has_linkage = any(
        entry.get(field)
        for field in ("qualification_type", "qualification_manifest_path", "qualification_manifest_digest_sha256")
    )
    if not has_linkage:
        return None
    return _verify_manifest_linkage(entry, manifest_root)


def verify_candidate_qualification_end_to_end(
    registry_path: Path,
    canonical_candidate_name: str,
    *,
    manifest_root: Path | None = None,
    require_qualified: bool = True,
    require_production_serving: bool = False,
) -> tuple[dict, dict | None]:
    """Phase 21B.4.11.4 §5, hardened 21B.4.12 §2: the SINGLE public
    acceptance API for a candidate's runtime-qualification claim. By
    default (`require_qualified=True`, the fail-closed default) this
    function ALSO requires `runtime_qualification_status == "QUALIFIED"`
    and raises `RegistrySchemaError` otherwise -- an UNQUALIFIED,
    BLOCKED, or otherwise-not-yet-qualified candidate can never be
    returned as if it were accepted. A caller that genuinely needs to
    *inspect* a candidate's registry entry without asserting
    acceptance (e.g. a status dashboard, not a go/no-go gate) must pass
    `require_qualified=False` explicitly -- there is no default that
    silently allows an UNQUALIFIED candidate to look like an accepted
    one. One call establishes:

      1.  the registry itself is structurally valid (schema, name sets,
          candidate_class, revision formats, cross-wiring checks --
          everything `CandidateExecutionRegistry.load()` already does);
      2.  the named candidate exists in the registry;
      3.  if QUALIFIED, its qualification-linkage metadata is present
          and well-formed;
      4.  `qualification_manifest_path` exists and is contained under
          `manifest_root` (no path escape/symlink ambiguity);
      5.  the manifest's bytes parse and pass full schema validation
          (`validate_manifest` -- qualification-state invariants,
          zero-owner-cash billing invariants, billing-gate-for-executed-
          runs invariant, cleanup invariant, all included);
      6.  the manifest's canonical SHA-256 equals the registry's
          `qualification_manifest_digest_sha256`;
      7.  the manifest's candidate/repository/revision/qualification_type
          match the registry entry's own fields;
      8.  for a STRICT_RUNTIME_SMOKE_V2 manifest, every declared
          evidence-artifact file (including `billing_gate`) exists under
          `manifest_root` and its actual bytes hash to the declared
          SHA-256.

    A caller needing "is this candidate's qualification acceptable"
    never has to separately remember `CandidateExecutionRegistry.load()`
    plus `verify_runtime_qualification_bundle()` -- this single call
    performs the entire chain (steps 1-4 and 6-8 by delegating to
    `CandidateExecutionRegistry.load()` and `verify_qualified_manifest_
    linkage()`, which this function does not duplicate; step 5 happens
    inside manifest loading, which those call transitively).

    Returns `(registry_entry, manifest_data)`. With the default
    `require_qualified=True`, `manifest_data` is always a real manifest
    dict (never `None`) because a non-QUALIFIED candidate raises before
    returning. With `require_qualified=False`, `manifest_data` is the
    fully-verified manifest dict for ANY candidate that records a
    manifest linkage -- including a RUNTIME_QUALIFICATION_FAILED result
    (Phase 21B.4.12.1 §5: a failed live smoke's evidence is verified in
    full, not treated as absent) -- and `None` only for a candidate that
    has genuinely never been smoke-tested at all. Raises
    `RegistrySchemaError` on any failure (including "not QUALIFIED" when
    acceptance was requested, or a tampered/mismatched linked manifest
    regardless of qualification_type), or `KeyError` if no candidate
    with that name exists in the registry.

    `require_production_serving` (Phase 21B.4.15, default `False` for
    backwards compatibility): when `True`, ALSO requires
    `production_serving_status == "QUALIFIED"` (which, via
    `_validate_deployable`'s cross-field invariant, can only be true
    alongside `qualification_type == PRODUCTION_SERVING_RUNTIME_QUALIFIED`).
    This closes the exact ambiguity `runtime_qualification_status` alone
    cannot: `require_qualified=True` by itself accepts ANY qualified
    type, including a candidate that only achieved
    RUNTIME_LOAD_COMPATIBILITY_QUALIFIED (e.g. Qwen3.8-27B) -- a caller
    that specifically needs "this candidate has been production-serving
    qualified" must pass `require_production_serving=True` explicitly;
    there is no default that silently treats load-compatibility evidence
    as production-serving acceptance."""
    registry = CandidateExecutionRegistry.load(registry_path, manifest_root=manifest_root)
    entry = registry.find_deployable(canonical_candidate_name)
    if require_qualified and entry.get("runtime_qualification_status") != "QUALIFIED":
        raise RegistrySchemaError(
            f"candidate {canonical_candidate_name!r} is not QUALIFIED "
            f"(runtime_qualification_status={entry.get('runtime_qualification_status')!r}) -- "
            "the qualification-acceptance API refuses to return a non-accepted candidate as if it were "
            "accepted. Pass require_qualified=False explicitly for a non-acceptance inspection workflow."
        )
    if require_production_serving and entry.get("production_serving_status") != "QUALIFIED":
        raise RegistrySchemaError(
            f"candidate {canonical_candidate_name!r} is not production-serving qualified "
            f"(production_serving_status={entry.get('production_serving_status')!r}) -- "
            "load-compatibility evidence alone is never treated as production-serving acceptance."
        )
    root = Path(manifest_root).resolve() if manifest_root is not None else _derive_manifest_root(Path(registry_path))
    if require_qualified:
        manifest_data = verify_qualified_manifest_linkage(entry, root)
    else:
        manifest_data = verify_recorded_manifest_linkage(entry, root)
    return entry, manifest_data
