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
        if entry["candidate_class"] != EXPECTED_CONTROL_CANDIDATE_CLASS:
            raise RegistrySchemaError(
                f"control {name!r} has candidate_class={entry['candidate_class']!r}, expected "
                f"{EXPECTED_CONTROL_CANDIDATE_CLASS!r} -- a control tagged with the wrong class is a "
                "wiring bug, not a legitimate data variation."
            )
        _require_hex40_revision(entry["exact_immutable_revision"], f"control {name!r}")
        _require_hex40_revision(entry["tokenizer_revision"], f"control {name!r} tokenizer_revision")
        if entry["stage0_status"] not in VALID_STAGE0_STATUSES:
            raise RegistrySchemaError(f"control {name!r} has unrecognized stage0_status={entry['stage0_status']!r}")

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
    if entry.get("runtime_qualification_status") != "QUALIFIED":
        return None

    for field in ("qualification_type", "qualification_manifest_path", "qualification_manifest_digest_sha256"):
        if not entry.get(field):
            raise RegistrySchemaError(
                f"QUALIFIED deployable candidate {name!r} is missing required manifest-linkage field {field!r}"
            )

    qualification_type = entry["qualification_type"]
    if qualification_type not in VALID_QUALIFICATION_TYPES:
        raise RegistrySchemaError(
            f"QUALIFIED deployable candidate {name!r} has unrecognized qualification_type {qualification_type!r}"
        )

    digest = entry["qualification_manifest_digest_sha256"]
    if not _HEX64_RE.match(digest):
        raise RegistrySchemaError(
            f"QUALIFIED deployable candidate {name!r} has a malformed qualification_manifest_digest_sha256 "
            f"(must be exactly 64 lowercase hex characters): {digest!r}"
        )

    manifest_root = Path(manifest_root).resolve()
    raw_path = entry["qualification_manifest_path"]
    candidate_path = (manifest_root / raw_path).resolve()
    try:
        candidate_path.relative_to(manifest_root)
    except ValueError:
        raise RegistrySchemaError(
            f"QUALIFIED deployable candidate {name!r} qualification_manifest_path {raw_path!r} resolves "
            "outside the repository-controlled manifest root -- rejected as a path-escape/symlink-ambiguity risk."
        )
    if not candidate_path.is_file():
        raise RegistrySchemaError(
            f"QUALIFIED deployable candidate {name!r} qualification_manifest_path {raw_path!r} does not exist"
        )

    try:
        manifest_data = load_manifest(candidate_path)
    except RuntimeQualificationManifestError as e:
        raise RegistrySchemaError(
            f"QUALIFIED deployable candidate {name!r} qualification manifest failed schema validation: {e}"
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
            f"QUALIFIED deployable candidate {name!r} qualification manifest identity mismatch: {e}"
        ) from e

    recomputed_digest = sha256_of_manifest(manifest_data)
    if recomputed_digest != digest:
        raise RegistrySchemaError(
            f"QUALIFIED deployable candidate {name!r} manifest digest mismatch: registry records "
            f"{digest!r}, recomputed {recomputed_digest!r} from the manifest's current content."
        )

    try:
        verify_evidence_artifacts_bytes(manifest_data, manifest_root)
    except RuntimeQualificationManifestError as e:
        raise RegistrySchemaError(
            f"QUALIFIED deployable candidate {name!r} strict evidence-artifact verification failed: {e}"
        ) from e

    return manifest_data


def verify_candidate_qualification_end_to_end(
    registry_path: Path,
    canonical_candidate_name: str,
    *,
    manifest_root: Path | None = None,
    require_qualified: bool = True,
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
    returning. With `require_qualified=False`, `manifest_data` is
    `None` for an UNQUALIFIED candidate, which has no manifest to
    return. Raises `RegistrySchemaError` on any failure (including "not
    QUALIFIED" when acceptance was requested), or `KeyError` if no
    candidate with that name exists in the registry."""
    registry = CandidateExecutionRegistry.load(registry_path, manifest_root=manifest_root)
    entry = registry.find_deployable(canonical_candidate_name)
    if require_qualified and entry.get("runtime_qualification_status") != "QUALIFIED":
        raise RegistrySchemaError(
            f"candidate {canonical_candidate_name!r} is not QUALIFIED "
            f"(runtime_qualification_status={entry.get('runtime_qualification_status')!r}) -- "
            "the qualification-acceptance API refuses to return a non-accepted candidate as if it were "
            "accepted. Pass require_qualified=False explicitly for a non-acceptance inspection workflow."
        )
    root = Path(manifest_root).resolve() if manifest_root is not None else _derive_manifest_root(Path(registry_path))
    manifest_data = verify_qualified_manifest_linkage(entry, root)
    return entry, manifest_data
