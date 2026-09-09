"""
Phase 15.10 -- Production Proof: ORNEUR Code's first-class, typed,
machine-readable + human-readable evidence artifact (spec sections
17-20), hardened by Phase 15.10.1's integrity closure.

Production Proof answers: "Exactly what has been proven about this
software revision, what has NOT been proven, what evidence supports
each claim, what remains blocked, and what release state is honestly
justified?" It is never a marketing summary, a model-generated
confidence statement, a plain test log, a boolean "ready", or a
collection of caller-supplied PASS flags.

Core invariant, enforced structurally throughout this module:
    MISSING EVIDENCE != PASS.
    IMPLEMENTED != VERIFIED.
    COURT ACCEPT != DEPLOYMENT AUTHORITY.
    ENGINEERING_READY != PUBLISHED.
    A VerificationRecord may contribute to a category ONLY when its own
    mission/revision/category (and requirement, where applicable) all
    genuinely match -- never merely because a caller filed it under
    that category's parameter.

This module does NOT invent a new verification truth rule. Requirement
results are derived exclusively via `orca.mission.verification_
aggregation.evaluate_requirement_completion_for_mission()` (Phase
15.9.4's single authoritative mission-critical aggregation function),
and every other VerificationRecord-backed category (build, security,
authority, tests) is aggregated via the SAME `aggregate_outcomes()`
rule the Verification Engine and the Cognitive Court already use --
through the ONE centralized `evaluate_scoped_category()`/
`evaluate_scoped_test_category()` evaluators (Phase 15.10.1 closure
item 1), not scattered ad hoc checks.

PHASE 15.10.1 CLOSURE: an independent audit found several integrity
gaps capable of producing false readiness or contradictory durable
state in the original Phase 15.10 implementation -- category-untagged
record reuse (a single UNIT_TEST record could satisfy build, security,
AND requirement evidence simultaneously), a Court snapshot trusted for
ACCEPT without checking it was made for THIS mission/revision, a
caller-settable `durable=True` on a Court snapshot with no durable
store behind it, a naked `anti_gaming_analysis_performed: bool` with no
evidence identity, two naked release-promotion booleans
(`submission_ready_satisfied`/`release_candidate_satisfied`), bare
`ProofCategory(PASS, ...)` construction with no evidence reference, a
stale-deployment/untested-rollback trust gap, and a durable
`overall_status` column that silently mislabeled a blocked proof as
`ENGINEERING_READY` because its CHECK constraint predates this phase.
Every one of these is closed below; see PHASE15_EVIDENCE.md's own
"PHASE 15.10.1" section for the full audit trail and proving tests.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from orca.mission.anti_gaming import AntiGamingFinding, Severity
from orca.mission.cognitive_court import CourtDecision, CourtVerdict
from orca.mission.code_mode import LaunchReadiness
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import (
    RequiredVerificationScope,
    ScopeError,
    aggregate_outcomes,
    evaluate_requirement_completion_for_mission,
)

PROOF_SCHEMA_VERSION = "15.10.1"
GENERATOR_ID = "orca.mission.production_proof"
GENERATOR_VERSION = "1.1.0"

#: The real VerificationRecord `.category` string each proof category
#: must be tagged with to count (spec 15.10.1 item 1) -- matches the
#: `category` values `orca.mission.verifiers` concrete verifiers
#: already emit (BuildVerifier="BUILD", UnitTestVerifier="UNIT_TEST",
#: SecurityVerifier="SECURITY", AuthorityVerifier="SECURITY_TEST"...
#: verifier_id disambiguates; category itself is the binding key here).
CATEGORY_BUILD = "BUILD"
CATEGORY_UNIT_TEST = "UNIT_TEST"
CATEGORY_INTEGRATION_TEST = "INTEGRATION_TEST"
CATEGORY_E2E_TEST = "E2E_TEST"
CATEGORY_SECURITY = "SECURITY"
CATEGORY_AUTHORITY = "AUTHORITY"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductionProofError(Exception):
    pass


def _pid() -> str:
    return f"proof_{uuid.uuid4().hex[:16]}"


def _require_nonempty(value: str, *, field_name: str) -> None:
    if not (value or "").strip():
        raise ProductionProofError(
            f"Production Proof: {field_name!r} must be a non-empty string on the "
            f"mission-critical evaluation path."
        )


def _validate_scope_keys(scope: RequiredVerificationScope, *, requirement_id: str) -> None:
    """Malformed-scope-input hardening (Phase 15.10 closure item 4,
    unchanged this closure): an empty string inside `criterion_ids`/
    `requirement_level_categories` would collapse into a bare `""` or
    `"category:"` aggregation key. `RequiredVerificationScope.__post_
    init__` already forbids a wholly EMPTY scope (Phase 15.9.4); this
    adds the narrower check that no individual key is itself blank,
    and that criterion_ids/requirement_level_categories never share a
    literal name (which would silently collapse two distinct required
    checks into one aggregation key)."""
    for cid in scope.criterion_ids:
        if not (cid or "").strip():
            raise ProductionProofError(
                f"Production Proof: requirement {requirement_id!r} has a blank criterion_id "
                f"inside its RequiredVerificationScope."
            )
    for cat in scope.requirement_level_categories:
        if not (cat or "").strip():
            raise ProductionProofError(
                f"Production Proof: requirement {requirement_id!r} has a blank "
                f"requirement_level_category inside its RequiredVerificationScope."
            )
    combined = scope.criterion_ids | scope.requirement_level_categories
    if len(combined) != len(scope.criterion_ids) + len(scope.requirement_level_categories):
        raise ProductionProofError(
            f"Production Proof: requirement {requirement_id!r} has a criterion_id and a "
            f"requirement_level_category sharing the same literal name -- this would "
            f"silently collapse two distinct required checks into one aggregation key."
        )


# ── Secret redaction (spec section 26) ───────────────────────────────

_SECRET_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(?i)\b(postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?)://[^:\s]+:[^@\s]+@\S+"),
    re.compile(r"(?i)\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|authorization)\s*[:=]\s*['\"]?[A-Za-z0-9\-_./+=]{8,}['\"]?"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.]{10,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)


def redact_secrets(text: str | None) -> str | None:
    """Best-effort scrubber. Not a substitute for the verifiers' own
    bounded-output discipline -- an additional layer, since a
    persisted proof must NEVER contain a raw secret."""
    if text is None:
        return None
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _sanitize_value(value):
    """Phase 15.10.1 closure item 10: a single, robust, RECURSIVE
    sanitize pass applied to the fully-assembled `ProductionProof`
    before it is returned from `generate_production_proof()` -- not
    only at rendering time. Walks every dataclass/tuple/dict/string
    reachable from the proof and redacts every string field, so the
    canonical object that gets HASHED and PERSISTED is already safe;
    there is no path where the hash is computed over secret-containing
    content while the stored/rendered forms differ. `Enum` members
    (which are also `str` subclasses in this codebase, e.g.
    `VerificationOutcome`) are left untouched -- redacting one would
    silently break identity/equality with the real enum member."""
    if isinstance(value, Enum):
        return value
    if isinstance(value, str):
        return redact_secrets(value) or ""
    if isinstance(value, tuple):
        return tuple(_sanitize_value(v) for v in value)
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        changes = {f.name: _sanitize_value(getattr(value, f.name)) for f in fields(value)}
        return replace(value, **changes)
    return value


# ── Category outcome helpers (spec section 2) ────────────────────────
# PASS / FAIL / UNVERIFIED / NOT_APPLICABLE / ERROR / CANCELLED /
# TIMED_OUT are reused directly from Phase 15.8's VerificationOutcome
# -- no narrower proof-category enum is invented (spec item 2).

@dataclass(frozen=True)
class ProofCategory:
    status: VerificationOutcome
    summary: str
    evidence_refs: tuple[str, ...] = ()
    not_applicable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is VerificationOutcome.NOT_APPLICABLE and not (self.not_applicable_reason or "").strip():
            raise ProductionProofError(
                "ProofCategory: NOT_APPLICABLE requires a non-empty not_applicable_reason -- "
                "it may never be the default for a merely-unchecked category."
            )
        if self.status is VerificationOutcome.PASS and not self.evidence_refs:
            raise ProductionProofError(
                "ProofCategory: a PASS status requires at least one real evidence_ref -- "
                "a bare ProofCategory(status=PASS, ...) with no underlying evidence source "
                "is rejected (Phase 15.10.1 closure item 6). Construct it from a real "
                "VerificationRecord, evidence artifact id, command/execution reference, "
                "artifact hash, scanner report, benchmark record, or deployment observation."
            )


def evidence_backed_pass(summary: str, *, evidence_refs: tuple[str, ...]) -> ProofCategory:
    """The ONLY sanctioned way to construct a PASS `ProofCategory` from
    something other than a `VerificationRecord` tuple -- the caller
    MUST supply at least one real evidence reference (an artifact id,
    a command/execution reference, an artifact hash, a scanner-report
    id, a benchmark-record id, or a deployment-observation id).
    `evidence_refs` is validated non-empty by `ProofCategory.__post_
    init__` itself; this helper exists only for a clear call-site name."""
    if not evidence_refs:
        raise ProductionProofError(
            "evidence_backed_pass() requires at least one real evidence_ref (spec item 6)."
        )
    return ProofCategory(status=VerificationOutcome.PASS, summary=redact_secrets(summary) or "", evidence_refs=evidence_refs)


def not_applicable_category(reason: str) -> ProofCategory:
    return ProofCategory(status=VerificationOutcome.NOT_APPLICABLE, summary=reason, not_applicable_reason=reason)


def unverified_category(reason: str) -> ProofCategory:
    return ProofCategory(status=VerificationOutcome.UNVERIFIED, summary=redact_secrets(reason) or "")


def failed_category(reason: str, *, evidence_refs: tuple[str, ...] = ()) -> ProofCategory:
    return ProofCategory(status=VerificationOutcome.FAIL, summary=redact_secrets(reason) or "", evidence_refs=evidence_refs)


# ── Centralized scoped-category evaluator (Phase 15.10.1 closure item 1) ──
# THE single place that decides whether a VerificationRecord may
# contribute to a given proof category. A record counts ONLY when its
# OWN `category`, `mission_id`, and `revision` fields all genuinely
# match what this category/proof actually requires -- never merely
# because a caller passed it into a given parameter. Reuses the exact
# non-vacuous `aggregate_outcomes()` rule used everywhere else in this
# package once the scoped set is established.

def _filter_scoped_records(
    records: tuple[VerificationRecord, ...], *, expected_category: str, mission_id: str, revision: str,
) -> tuple[VerificationRecord, ...]:
    return tuple(
        r for r in records
        if r.category == expected_category and r.mission_id == mission_id and r.revision == revision
    )


def evaluate_scoped_category(
    records: tuple[VerificationRecord, ...], *, expected_category: str, mission_id: str, revision: str,
    not_run_summary: str,
) -> ProofCategory:
    """Filters `records` to those whose OWN `category`/`mission_id`/
    `revision` genuinely match this category's requirements, THEN
    aggregates via `aggregate_outcomes()`. A record supplied under
    `build_records=` whose real `category` is `"UNIT_TEST"` (or whose
    `mission_id`/`revision` is stale/cross-mission) never contributes
    -- it is silently excluded from the scoped set, and if that leaves
    zero records, the category is UNVERIFIED, exactly as if nothing
    had been supplied at all."""
    _require_nonempty(mission_id, field_name="mission_id")
    _require_nonempty(revision, field_name="revision")
    scoped = _filter_scoped_records(records, expected_category=expected_category, mission_id=mission_id, revision=revision)
    if not scoped:
        if records:
            summary = (
                f"{len(records)} verification record(s) supplied, but none matched "
                f"category={expected_category!r}/mission={mission_id!r}/revision={revision!r}"
            )
            return ProofCategory(status=VerificationOutcome.UNVERIFIED, summary=redact_secrets(summary) or "")
        return ProofCategory(status=VerificationOutcome.UNVERIFIED, summary=redact_secrets(not_run_summary) or "")
    status = aggregate_outcomes(tuple(r.outcome for r in scoped))
    summary = redact_secrets(f"{len(scoped)} scoped verification record(s): " + ", ".join(r.id for r in scoped)) or ""
    return ProofCategory(status=status, summary=summary, evidence_refs=tuple(r.id for r in scoped))


@dataclass(frozen=True)
class TestCategoryResult:
    status: VerificationOutcome
    collected: int | None
    passed: int | None
    failed: int | None
    skipped: int | None
    errors: int | None
    duration_seconds: float | None
    revision: str | None
    evidence_refs: tuple[str, ...] = ()
    summary: str = ""


def evaluate_scoped_test_category(
    records: tuple[VerificationRecord, ...], *, expected_category: str, mission_id: str, revision: str,
    collected: int | None = None, passed: int | None = None, failed: int | None = None,
    skipped: int | None = None, errors: int | None = None, duration_seconds: float | None = None,
) -> TestCategoryResult:
    """The test-evidence sibling of `evaluate_scoped_category()` --
    same category/mission/revision binding, plus the 0-collected
    defense-in-depth check (spec section 10): a UNIT_TEST record can
    never satisfy `expected_category="INTEGRATION_TEST"`, and vice
    versa."""
    _require_nonempty(mission_id, field_name="mission_id")
    _require_nonempty(revision, field_name="revision")
    scoped = _filter_scoped_records(records, expected_category=expected_category, mission_id=mission_id, revision=revision)
    if not scoped:
        note = "not run -- zero verification records supplied for this test category"
        if records:
            note = (
                f"{len(records)} record(s) supplied, but none matched "
                f"category={expected_category!r}/mission={mission_id!r}/revision={revision!r}"
            )
        return TestCategoryResult(
            status=VerificationOutcome.UNVERIFIED, collected=collected, passed=passed, failed=failed,
            skipped=skipped, errors=errors, duration_seconds=duration_seconds, revision=revision,
            summary=redact_secrets(note) or "",
        )
    status = aggregate_outcomes(tuple(r.outcome for r in scoped))
    if collected == 0 and status is VerificationOutcome.PASS:
        status = VerificationOutcome.UNVERIFIED
    summary = f"collected={collected} passed={passed} failed={failed} skipped={skipped} errors={errors}"
    return TestCategoryResult(
        status=status, collected=collected, passed=passed, failed=failed, skipped=skipped,
        errors=errors, duration_seconds=duration_seconds, revision=revision,
        evidence_refs=tuple(r.id for r in scoped) if status is VerificationOutcome.PASS else (),
        summary=redact_secrets(summary) or "",
    )


# ── Regression evidence (spec section 11, Phase 15.10.1 closure item 11) ──

@dataclass(frozen=True)
class RegressionResult:
    baseline_revision: str | None
    candidate_revision: str | None
    baseline_collected: int | None
    candidate_collected: int | None
    new_tests: tuple[str, ...] = ()
    removed_tests: tuple[str, ...] = ()
    new_failures: tuple[str, ...] = ()
    resolved_failures: tuple[str, ...] = ()
    known_pre_existing_failures: tuple[str, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        claims_needing_baseline = (
            self.new_tests or self.removed_tests or self.resolved_failures or self.known_pre_existing_failures
        )
        if claims_needing_baseline and self.baseline_revision is None:
            raise ProductionProofError(
                "RegressionResult: new_tests/removed_tests/resolved_failures/"
                "known_pre_existing_failures require a real baseline_revision -- a failure "
                "cannot be labeled 'pre-existing' (or a test labeled new/removed) with no "
                "baseline evidence at all (spec item 11)."
            )

    @property
    def status(self) -> VerificationOutcome:
        if self.baseline_revision is None or self.candidate_revision is None:
            return VerificationOutcome.UNVERIFIED
        if self.new_failures:
            return VerificationOutcome.FAIL
        return VerificationOutcome.PASS


def not_run_regression() -> RegressionResult:
    return RegressionResult(
        baseline_revision=None, candidate_revision=None, baseline_collected=None, candidate_collected=None,
        notes="regression comparison not performed for this proof",
    )


def _bind_regression_to_revision(regression: RegressionResult, *, revision: str) -> RegressionResult:
    """Phase 15.10.1 closure item 11: `candidate_revision` must equal
    `proof.revision` or the regression claim does not apply to THIS
    proof -- discarded down to UNVERIFIED (via the existing `status`
    property's `candidate_revision is None` branch) rather than
    silently counted."""
    if regression.candidate_revision is not None and regression.candidate_revision != revision:
        return RegressionResult(
            baseline_revision=regression.baseline_revision, candidate_revision=None,
            baseline_collected=regression.baseline_collected, candidate_collected=regression.candidate_collected,
            notes=(
                f"regression candidate_revision {regression.candidate_revision!r} does not match "
                f"proof revision {revision!r} -- discarded, cannot count for this proof"
            ),
        )
    return regression


# ── Requirement results (spec section 5) ─────────────────────────────

@dataclass(frozen=True)
class RequirementResult:
    requirement_id: str
    scope_keys: tuple[str, ...]
    outcome: VerificationOutcome
    contributing_record_ids: tuple[str, ...]
    missing_keys: tuple[str, ...]
    limitations: str | None = None


def _requirement_results(
    *, required_requirement_ids: tuple[str, ...],
    required_scopes_by_requirement: dict[str, RequiredVerificationScope],
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    mission_id: str, revision: str,
) -> tuple[RequirementResult, ...]:
    results: list[RequirementResult] = []
    for req_id in required_requirement_ids:
        _require_nonempty(req_id, field_name="requirement_id")
        if req_id not in required_scopes_by_requirement:
            raise ProductionProofError(
                f"Production Proof: no explicit RequiredVerificationScope for required "
                f"requirement {req_id!r} -- unknown expected verification scope must fail "
                f"closed, never be silently inferred (spec section 3)."
            )
        scope = required_scopes_by_requirement[req_id]
        _validate_scope_keys(scope, requirement_id=req_id)
        records = records_by_requirement.get(req_id, ())
        outcome, contributing = evaluate_requirement_completion_for_mission(
            records, requirement_id=req_id, current_revision=revision, mission_id=mission_id,
            required_scope=scope,
        )
        latest_keys_present = {
            (r.criterion_id or f"category:{r.category}")
            for r in records
            if r.requirement_id == req_id and r.mission_id == mission_id and r.revision == revision
        }
        missing = tuple(sorted(scope.keys - latest_keys_present))
        results.append(RequirementResult(
            requirement_id=req_id, scope_keys=tuple(sorted(scope.keys)), outcome=outcome,
            contributing_record_ids=tuple(r.id for r in contributing), missing_keys=missing,
        ))
    return tuple(results)


# ── Cognitive Court snapshot (spec section 7, Phase 15.10.1 items 2-3) ──

@dataclass(frozen=True)
class CourtSnapshot:
    decision_id: str
    mission_id: str
    revision: str
    risk_level: str
    roles_invoked: tuple[str, ...]
    verdict: str
    findings_considered: tuple[str, ...]
    verification_refs: tuple[str, ...]
    reasoning_summary: str
    durable: bool
    evidence_source: str
    context_bound: bool


def court_snapshot_from_decision(decision: CourtDecision, *, mission_id: str, revision: str) -> CourtSnapshot:
    """Phase 15.10.1 closure item 2: independently proves
    `decision.mission_id == mission_id` and `decision.revision ==
    revision` (mirroring `court_mission_gate`'s own defense-in-depth
    binding) -- `context_bound=False` for a stale-revision or
    cross-mission ACCEPT, and the effective verdict used everywhere
    else in this module is gated on `context_bound`, not on the raw
    `verdict` string alone (see `_court_effectively_accepted()`).

    Closure item 3: `durable` is now ALWAYS `False` and
    `evidence_source` is ALWAYS `"IN_PROCESS_SNAPSHOT"` -- there is no
    parameter through which a caller can manufacture durability. No
    durable `CourtDecision` store exists yet; when one does, a genuine
    durable reference that actually resolves will be required, not a
    caller-supplied boolean."""
    context_bound = decision.mission_id == mission_id and decision.revision == revision
    return CourtSnapshot(
        decision_id=decision.decision_id, mission_id=decision.mission_id, revision=decision.revision,
        risk_level=decision.risk_level.value, roles_invoked=tuple(r.value for r in decision.roles_invoked),
        verdict=decision.verdict.value, findings_considered=decision.findings_considered,
        verification_refs=decision.verification_refs,
        reasoning_summary=redact_secrets(decision.reasoning_summary) or "",
        durable=False, evidence_source="IN_PROCESS_SNAPSHOT", context_bound=context_bound,
    )


def no_court_snapshot(reason: str) -> CourtSnapshot:
    return CourtSnapshot(
        decision_id="", mission_id="", revision="", risk_level="", roles_invoked=(),
        verdict="NOT_EVALUATED", findings_considered=(), verification_refs=(),
        reasoning_summary=reason, durable=False, evidence_source="IN_PROCESS_SNAPSHOT", context_bound=False,
    )


def _court_effectively_accepted(court: CourtSnapshot) -> bool:
    """THE single place that decides whether a Court snapshot may
    support readiness: verdict ACCEPT alone is insufficient -- it must
    ALSO be bound to the current mission/revision."""
    return court.verdict == CourtVerdict.ACCEPT.value and court.context_bound


# ── Anti-test-gaming evidence (spec section 8, Phase 15.10.1 item 4) ─

@dataclass(frozen=True)
class AntiGamingAnalysisEvidence:
    """Replaces the naked `anti_gaming_analysis_performed: bool` --
    the proof must know an analysis genuinely ran, for THIS
    mission/revision, not merely that a caller asserted it did."""
    analysis_id: str
    mission_id: str
    baseline_revision: str
    candidate_revision: str
    detector_ids: tuple[str, ...]
    findings: tuple[AntiGamingFinding, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty(self.analysis_id, field_name="analysis_id")
        _require_nonempty(self.mission_id, field_name="mission_id")
        _require_nonempty(self.baseline_revision, field_name="baseline_revision")
        _require_nonempty(self.candidate_revision, field_name="candidate_revision")


@dataclass(frozen=True)
class AntiGamingSnapshot:
    analysis_performed: bool
    analysis_id: str | None
    baseline_revision: str | None
    candidate_revision: str | None
    blocking_finding_ids: tuple[str, ...]
    critical_finding_ids: tuple[str, ...]
    total_findings: int
    detector_ids: tuple[str, ...]


def anti_gaming_snapshot(
    evidence: AntiGamingAnalysisEvidence | None, *, mission_id: str, revision: str,
) -> AntiGamingSnapshot:
    """`evidence=None` -> ANALYSIS NOT PERFORMED. Evidence supplied but
    for a different mission or a `candidate_revision` that does not
    match this proof's revision -> STALE/CROSS-MISSION, cannot count
    (treated identically to "not performed" for this proof). Evidence
    matching this exact mission/revision, even with ZERO findings,
    correctly reads as "NO FINDINGS AFTER ANALYSIS" (`analysis_
    performed=True, total_findings=0`) -- distinct from "not
    performed"."""
    if evidence is None:
        return AntiGamingSnapshot(
            analysis_performed=False, analysis_id=None, baseline_revision=None, candidate_revision=None,
            blocking_finding_ids=(), critical_finding_ids=(), total_findings=0, detector_ids=(),
        )
    context_bound = evidence.mission_id == mission_id and evidence.candidate_revision == revision
    if not context_bound:
        return AntiGamingSnapshot(
            analysis_performed=False, analysis_id=evidence.analysis_id,
            baseline_revision=evidence.baseline_revision, candidate_revision=evidence.candidate_revision,
            blocking_finding_ids=(), critical_finding_ids=(), total_findings=0, detector_ids=evidence.detector_ids,
        )
    blocking = tuple(f.finding_id for f in evidence.findings if f.blocking)
    critical = tuple(f.finding_id for f in evidence.findings if f.severity is Severity.CRITICAL)
    return AntiGamingSnapshot(
        analysis_performed=True, analysis_id=evidence.analysis_id,
        baseline_revision=evidence.baseline_revision, candidate_revision=evidence.candidate_revision,
        blocking_finding_ids=blocking, critical_finding_ids=critical, total_findings=len(evidence.findings),
        detector_ids=evidence.detector_ids,
    )


# ── Deployment / rollback evidence (spec sections 19-21, item 7) ────

class DeploymentState(str, Enum):
    NOT_DEPLOYED = "NOT_DEPLOYED"
    STAGING_DEPLOYED = "STAGING_DEPLOYED"
    PRODUCTION_DEPLOYED = "PRODUCTION_DEPLOYED"


@dataclass(frozen=True)
class DeploymentResult:
    state: DeploymentState
    revision: str | None
    environment_identity: str | None
    deployed_at: str | None
    notes: str | None = None


def not_deployed(*, revision: str | None = None, notes: str | None = None) -> DeploymentResult:
    return DeploymentResult(
        state=DeploymentState.NOT_DEPLOYED, revision=revision, environment_identity=None,
        deployed_at=None, notes=notes or "current revision was not deployed for this proof",
    )


def _deployment_is_current(deployment: DeploymentResult, *, revision: str) -> bool:
    """Phase 15.10.1 closure item 7: a deployment for a DIFFERENT
    revision must never count as current deployment readiness -- it
    remains visible HISTORY (the `DeploymentResult` itself is
    unmodified/unhidden), but this function is the single gate
    everything else (blockers, LAUNCH-gate wiring, release policy)
    consults before treating deployment as satisfied."""
    return (
        deployment.state is not DeploymentState.NOT_DEPLOYED
        and deployment.revision == revision
        and bool(deployment.environment_identity)
    )


@dataclass(frozen=True)
class RollbackResult:
    strategy_documented: bool
    procedure_tested: bool
    proven_for_current_deployment: bool
    method: str | None = None
    notes: str | None = None


def undocumented_rollback() -> RollbackResult:
    return RollbackResult(strategy_documented=False, procedure_tested=False, proven_for_current_deployment=False)


def _rollback_effectively_proven(rollback: RollbackResult, deployment: DeploymentResult, *, revision: str) -> bool:
    """Phase 15.10.1 closure item 7: `rollback.proven_for_current_
    deployment` is the CALLER's own declaration -- it is never trusted
    blindly. The system's own determination additionally requires a
    genuinely CURRENT deployment (`_deployment_is_current()`) and
    `procedure_tested=True`; a documented-but-untested plan, or a
    caller-asserted proof with no current deployment at all, can never
    count as effectively proven."""
    return (
        rollback.proven_for_current_deployment
        and rollback.procedure_tested
        and _deployment_is_current(deployment, revision=revision)
    )


# ── Release qualification policy (spec section 22, Phase 15.10.1 item 5) ──
# Removes the two naked promotion booleans entirely. A caller must
# supply an explicit, typed policy stating which proof categories are
# REQUIRED (vs NOT_APPLICABLE, with a real reason) for SUBMISSION_READY
# and RELEASE_CANDIDATE. Omitting a policy caps release_state at
# ENGINEERING_READY (or below) -- there is no way to reach a higher
# stage by flipping a boolean.

#: Category names this policy/derivation understands, mapped from the
#: real ProductionProof fields. "requirements"/"court"/"anti_gaming"
#: are always implicitly required for ENGINEERING_READY (never
#: policy-overridable -- these are the Phase 15.9 Court/anti-gaming
#: invariants this whole lineage exists to protect); every other name
#: below may be marked NOT_APPLICABLE by policy, with a real reason.
ENGINEERING_DEFAULT_REQUIRED = frozenset({
    "build", "unit_tests", "integration_tests", "e2e_tests", "regression", "security", "authority",
})


@dataclass(frozen=True)
class ReleaseQualificationPolicy:
    engineering_not_applicable: dict[str, str] = field(default_factory=dict)
    #: A stage is only ever evaluated for promotion when the caller has
    #: explicitly "addressed" it -- either by naming at least one
    #: required/not-applicable category, or by setting the matching
    #: `*_stage_addressed` flag to declare "I considered this stage and
    #: nothing further is required." An UN-addressed stage is never
    #: vacuously satisfied by an empty `required` set (spec item 5:
    #: promotion must derive from ACTUAL applicable evidence/policy,
    #: never from a policy that simply said nothing).
    submission_stage_addressed: bool = False
    submission_required: frozenset[str] = frozenset()
    submission_not_applicable: dict[str, str] = field(default_factory=dict)
    release_candidate_stage_addressed: bool = False
    release_candidate_required: frozenset[str] = frozenset()
    release_candidate_not_applicable: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for mapping in (self.engineering_not_applicable, self.submission_not_applicable, self.release_candidate_not_applicable):
            for category, reason in mapping.items():
                if not (reason or "").strip():
                    raise ProductionProofError(
                        f"ReleaseQualificationPolicy: category {category!r} marked NOT_APPLICABLE "
                        f"requires a non-empty reason (spec item 5)."
                    )


DEFAULT_RELEASE_POLICY = ReleaseQualificationPolicy()


@dataclass(frozen=True)
class ExternalPublicationConfirmation:
    """Replaces the naked `published_externally_confirmed: bool`.
    PUBLISHED is unreachable without a real instance of this, and its
    `revision` (when supplied) must match the proof's own revision."""
    source: str
    timestamp: str
    target: str
    evidence_reference: str
    revision: str | None = None
    artifact_identity: str | None = None

    def __post_init__(self) -> None:
        for name in ("source", "timestamp", "target", "evidence_reference"):
            _require_nonempty(getattr(self, name), field_name=f"ExternalPublicationConfirmation.{name}")


def _category_status(proof_categories: dict[str, VerificationOutcome], name: str) -> VerificationOutcome:
    return proof_categories.get(name, VerificationOutcome.UNVERIFIED)


def _stage_requirements_met(
    proof_categories: dict[str, VerificationOutcome], *, required: frozenset[str], not_applicable: dict[str, str],
) -> tuple[bool, tuple[str, ...]]:
    blockers: list[str] = []
    for category in sorted(required):
        if category in not_applicable:
            continue
        status = _category_status(proof_categories, category)
        if status is not VerificationOutcome.PASS:
            blockers.append(f"required category {category!r} is {status.value}, not PASS")
    return (not blockers), tuple(blockers)


def _evaluate_release_policy(
    *, requirements_unresolved: tuple[str, ...], requirements_failed: tuple[str, ...],
    court: CourtSnapshot, anti_gaming: AntiGamingSnapshot, proof_categories: dict[str, VerificationOutcome],
    policy: ReleaseQualificationPolicy, external_confirmation: ExternalPublicationConfirmation | None,
    revision: str,
) -> tuple[str, tuple[str, ...]]:
    """Returns `(release_state, policy_blockers)`. Machine (release_
    state) and human (blockers, folded into `proof.blockers`) views are
    derived from the SAME evaluation here -- they cannot disagree
    (spec item 12)."""
    policy_blockers: list[str] = []

    engineering_required = ENGINEERING_DEFAULT_REQUIRED - set(policy.engineering_not_applicable)
    engineering_ok, engineering_blockers = _stage_requirements_met(
        proof_categories, required=frozenset(engineering_required), not_applicable=policy.engineering_not_applicable,
    )
    policy_blockers.extend(engineering_blockers)

    requirements_ok = not requirements_unresolved and not requirements_failed
    court_ok = _court_effectively_accepted(court)
    anti_gaming_ok = anti_gaming.analysis_performed and not anti_gaming.blocking_finding_ids

    if not requirements_ok:
        if requirements_failed:
            policy_blockers.append(f"required requirement(s) failed: {list(requirements_failed)!r}")
        if requirements_unresolved:
            policy_blockers.append(f"required requirement(s) unresolved: {list(requirements_unresolved)!r}")
    if not court_ok:
        if court.verdict != CourtVerdict.ACCEPT.value:
            policy_blockers.append(f"Cognitive Court verdict is {court.verdict!r}, not ACCEPT")
        elif not court.context_bound:
            policy_blockers.append(
                f"Cognitive Court ACCEPT was made for mission={court.mission_id!r}/revision={court.revision!r}, "
                f"not the current proof context -- a stale or cross-mission ACCEPT cannot support readiness"
            )
    if not anti_gaming_ok:
        if not anti_gaming.analysis_performed:
            policy_blockers.append("anti-test-gaming analysis was not performed for this exact mission/revision")
        if anti_gaming.blocking_finding_ids:
            policy_blockers.append(f"blocking anti-gaming finding(s): {list(anti_gaming.blocking_finding_ids)!r}")

    engineering_ready = engineering_ok and requirements_ok and court_ok and anti_gaming_ok
    if not engineering_ready:
        return NOT_ENGINEERING_READY, tuple(policy_blockers)

    # A stage the policy never addressed (no required/not-applicable
    # categories AND the caller did not set its `*_stage_addressed`
    # flag) is never vacuously satisfied -- release_state stays capped
    # rather than promoting from an empty `required` set trivially
    # "passing" (spec item 5). An unaddressed SUBMISSION stage does not
    # block reaching RELEASE_CANDIDATE if that stage IS addressed
    # (a caller testing release-candidate readiness directly should not
    # be forced to also declare a no-op submission policy).
    addressed_submission = (
        policy.submission_stage_addressed or bool(policy.submission_required) or bool(policy.submission_not_applicable)
    )
    addressed_rc = (
        policy.release_candidate_stage_addressed
        or bool(policy.release_candidate_required) or bool(policy.release_candidate_not_applicable)
    )
    if not addressed_submission and not addressed_rc:
        return LaunchReadiness.ENGINEERING_READY.value, tuple(policy_blockers)

    if addressed_submission:
        submission_ok, submission_blockers = _stage_requirements_met(
            proof_categories, required=policy.submission_required, not_applicable=policy.submission_not_applicable,
        )
        if not submission_ok:
            return LaunchReadiness.ENGINEERING_READY.value, tuple(policy_blockers) + submission_blockers
        if not addressed_rc:
            return LaunchReadiness.SUBMISSION_READY.value, tuple(policy_blockers)

    rc_ok, rc_blockers = _stage_requirements_met(
        proof_categories, required=policy.release_candidate_required, not_applicable=policy.release_candidate_not_applicable,
    )
    if not rc_ok:
        return LaunchReadiness.SUBMISSION_READY.value, tuple(policy_blockers) + rc_blockers

    if external_confirmation is None:
        return LaunchReadiness.RELEASE_CANDIDATE.value, tuple(policy_blockers)
    if external_confirmation.revision is not None and external_confirmation.revision != revision:
        policy_blockers.append(
            f"ExternalPublicationConfirmation.revision {external_confirmation.revision!r} does not "
            f"match proof revision {revision!r} -- cannot certify PUBLISHED for this proof"
        )
        return LaunchReadiness.RELEASE_CANDIDATE.value, tuple(policy_blockers)

    return LaunchReadiness.PUBLISHED.value, tuple(policy_blockers)


NOT_ENGINEERING_READY = "NOT_ENGINEERING_READY"


# ── Stale-proof decision-context fingerprint (spec item 9) ──────────

def compute_decision_context_fingerprint(
    *, required_requirement_ids: tuple[str, ...],
    required_scopes_by_requirement: dict[str, RequiredVerificationScope],
    revision: str, requirement_semantics_fingerprints: dict[str, str] | None = None,
) -> str:
    """Canonical CONTENT fingerprint (SHA-256) of the decision context
    a proof was generated against -- never the identity of a mutable
    in-process registry. Covers: the exact set of required requirement
    ids, each one's exact scope keys, the revision, and (optionally)
    a caller-supplied per-requirement semantics fingerprint (e.g. a
    hash of the Requirement's own statement/acceptance_criteria) so a
    requirement whose ID stays the same but whose meaning changes is
    still detected as a context change. Sorted throughout, so
    reordered-but-equivalent inputs produce the IDENTICAL fingerprint."""
    payload = {
        "revision": revision,
        "required_requirement_ids": sorted(required_requirement_ids),
        "scopes": {
            rid: sorted(required_scopes_by_requirement[rid].keys)
            for rid in sorted(required_requirement_ids)
            if rid in required_scopes_by_requirement
        },
        "semantics": dict(sorted((requirement_semantics_fingerprints or {}).items())),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


# ── The typed ProductionProof (spec section 1) ───────────────────────

@dataclass(frozen=True)
class ProductionProof:
    # identity
    proof_id: str
    mission_id: str
    repository: str | None
    branch: str | None
    base_revision: str | None
    revision: str
    generated_at: str
    proof_schema_version: str
    generator_id: str
    generator_version: str
    decision_context_fingerprint: str

    # requirement truth
    required_requirement_ids: tuple[str, ...]
    requirement_results: tuple[RequirementResult, ...]
    requirements_satisfied: tuple[str, ...]
    requirements_unresolved: tuple[str, ...]
    requirements_failed: tuple[str, ...]

    # engineering evidence
    build: ProofCategory
    unit_tests: TestCategoryResult
    integration_tests: TestCategoryResult
    e2e_tests: TestCategoryResult
    regression: RegressionResult
    security: ProofCategory
    authority: ProofCategory
    anti_test_gaming: AntiGamingSnapshot
    cognitive_court: CourtSnapshot

    # release evidence
    supply_chain: ProofCategory
    licensing: ProofCategory
    accessibility: ProofCategory
    performance: ProofCategory
    release_build: ProofCategory
    deployment: DeploymentResult
    post_deploy_smoke: ProofCategory
    rollback: RollbackResult

    # honesty
    known_limitations: tuple[str, ...]
    unverified_assumptions: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    # identity/traceability
    evidence_refs: tuple[str, ...]
    artifact_hashes: tuple[tuple[str, str], ...]
    verifier_versions: tuple[tuple[str, str], ...]
    tool_versions: tuple[tuple[str, str], ...]

    release_state: str  # LaunchReadiness.value, or "NOT_ENGINEERING_READY"


# ── Generation (the ONE entry point that builds a ProductionProof) ──

def generate_production_proof(
    *,
    mission_id: str,
    revision: str,
    required_requirement_ids: tuple[str, ...],
    required_scopes_by_requirement: dict[str, RequiredVerificationScope],
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    repository: str | None = None,
    branch: str | None = None,
    base_revision: str | None = None,
    court_decision: CourtDecision | None = None,
    anti_gaming_evidence: AntiGamingAnalysisEvidence | None = None,
    build_records: tuple[VerificationRecord, ...] = (),
    unit_test_records: tuple[VerificationRecord, ...] = (),
    unit_test_stats: dict | None = None,
    integration_test_records: tuple[VerificationRecord, ...] = (),
    integration_test_stats: dict | None = None,
    e2e_test_records: tuple[VerificationRecord, ...] = (),
    e2e_test_stats: dict | None = None,
    regression: RegressionResult | None = None,
    security_records: tuple[VerificationRecord, ...] = (),
    authority_records: tuple[VerificationRecord, ...] = (),
    supply_chain: ProofCategory | None = None,
    licensing: ProofCategory | None = None,
    accessibility: ProofCategory | None = None,
    performance: ProofCategory | None = None,
    release_build: ProofCategory | None = None,
    deployment: DeploymentResult | None = None,
    post_deploy_smoke: ProofCategory | None = None,
    rollback: RollbackResult | None = None,
    known_limitations: tuple[str, ...] = (),
    unverified_assumptions: tuple[str, ...] = (),
    artifact_hashes: dict | None = None,
    verifier_versions: dict | None = None,
    tool_versions: dict | None = None,
    release_policy: ReleaseQualificationPolicy = DEFAULT_RELEASE_POLICY,
    external_publication_confirmation: ExternalPublicationConfirmation | None = None,
    requirement_semantics_fingerprints: dict[str, str] | None = None,
    proof_id: str | None = None,
    generated_at: str | None = None,
) -> ProductionProof:
    """The ONLY function that produces a ProductionProof. Reads ONLY
    typed evidence sources -- there is no parameter through which a
    caller can hand this function a bare `{"unit_tests": "PASS"}`-style
    claim, a naked promotion boolean, or an unscoped VerificationRecord
    reused across unrelated categories (Phase 15.10.1 closure)."""
    _require_nonempty(mission_id, field_name="mission_id")
    _require_nonempty(revision, field_name="revision")

    requirement_results = _requirement_results(
        required_requirement_ids=required_requirement_ids,
        required_scopes_by_requirement=required_scopes_by_requirement,
        records_by_requirement=records_by_requirement, mission_id=mission_id, revision=revision,
    )
    requirements_satisfied = tuple(r.requirement_id for r in requirement_results if r.outcome is VerificationOutcome.PASS)
    requirements_failed = tuple(r.requirement_id for r in requirement_results if r.outcome is VerificationOutcome.FAIL)
    requirements_unresolved = tuple(
        r.requirement_id for r in requirement_results
        if r.outcome not in (VerificationOutcome.PASS, VerificationOutcome.FAIL)
    )

    court_snapshot = (
        court_snapshot_from_decision(court_decision, mission_id=mission_id, revision=revision)
        if court_decision is not None
        else no_court_snapshot("no CourtDecision supplied for this proof")
    )
    anti_gaming = anti_gaming_snapshot(anti_gaming_evidence, mission_id=mission_id, revision=revision)

    build = evaluate_scoped_category(
        build_records, expected_category=CATEGORY_BUILD, mission_id=mission_id, revision=revision,
        not_run_summary="build not run for this proof",
    )
    unit_test_stats = unit_test_stats or {}
    integration_test_stats = integration_test_stats or {}
    e2e_test_stats = e2e_test_stats or {}
    unit_tests = evaluate_scoped_test_category(
        unit_test_records, expected_category=CATEGORY_UNIT_TEST, mission_id=mission_id, revision=revision,
        **unit_test_stats,
    )
    integration_tests = evaluate_scoped_test_category(
        integration_test_records, expected_category=CATEGORY_INTEGRATION_TEST, mission_id=mission_id,
        revision=revision, **integration_test_stats,
    )
    e2e_tests = evaluate_scoped_test_category(
        e2e_test_records, expected_category=CATEGORY_E2E_TEST, mission_id=mission_id, revision=revision,
        **e2e_test_stats,
    )
    regression = _bind_regression_to_revision(regression or not_run_regression(), revision=revision)
    security = evaluate_scoped_category(
        security_records, expected_category=CATEGORY_SECURITY, mission_id=mission_id, revision=revision,
        not_run_summary="security suite not run for this proof",
    )
    authority = evaluate_scoped_category(
        authority_records, expected_category=CATEGORY_AUTHORITY, mission_id=mission_id, revision=revision,
        not_run_summary="authority evidence not supplied for this proof",
    )

    supply_chain = supply_chain or unverified_category("supply-chain evidence not supplied for this proof")
    licensing = licensing or unverified_category("licensing evidence not supplied for this proof")
    accessibility = accessibility or unverified_category("accessibility not evaluated for this proof")
    performance = performance or unverified_category("performance not measured for this proof")
    release_build = release_build or unverified_category("no release-build artifact produced for this proof")
    deployment = deployment or not_deployed(revision=revision)
    post_deploy_smoke = post_deploy_smoke or unverified_category("no post-deploy smoke evidence for this proof")
    rollback = rollback or undocumented_rollback()

    deployment_current = _deployment_is_current(deployment, revision=revision)
    rollback_proven = _rollback_effectively_proven(rollback, deployment, revision=revision)

    proof_categories: dict[str, VerificationOutcome] = {
        "build": build.status, "unit_tests": unit_tests.status, "integration_tests": integration_tests.status,
        "e2e_tests": e2e_tests.status, "regression": regression.status, "security": security.status,
        "authority": authority.status, "supply_chain": supply_chain.status, "licensing": licensing.status,
        "accessibility": accessibility.status, "performance": performance.status,
        "release_build": release_build.status,
        "deployment": VerificationOutcome.PASS if deployment_current else VerificationOutcome.UNVERIFIED,
        "post_deploy_smoke": post_deploy_smoke.status,
        "rollback": VerificationOutcome.PASS if rollback_proven else VerificationOutcome.UNVERIFIED,
    }

    release_state, policy_blockers = _evaluate_release_policy(
        requirements_unresolved=requirements_unresolved, requirements_failed=requirements_failed,
        court=court_snapshot, anti_gaming=anti_gaming, proof_categories=proof_categories,
        policy=release_policy, external_confirmation=external_publication_confirmation, revision=revision,
    )

    blockers: list[str] = list(policy_blockers)

    warnings: list[str] = []
    if not anti_gaming.analysis_performed:
        warnings.append("anti-test-gaming analysis was not performed (or not context-bound) for this revision")
    warnings.append("Cognitive Court decision is a proof-time in-process snapshot, not independently durable")
    if regression.status is VerificationOutcome.UNVERIFIED:
        warnings.append("no regression baseline comparison bound to this revision was performed for this proof")
    if deployment.state is not DeploymentState.NOT_DEPLOYED and not deployment_current:
        warnings.append(
            f"a deployment record exists for revision {deployment.revision!r}, which does not match this "
            f"proof's revision {revision!r} -- it is historical, not current deployment readiness"
        )
    if rollback.proven_for_current_deployment and not rollback_proven:
        warnings.append(
            "rollback.proven_for_current_deployment was asserted by the caller, but the system's own "
            "determination (current deployment + procedure_tested) does not confirm it -- not counted"
        )

    fingerprint = compute_decision_context_fingerprint(
        required_requirement_ids=required_requirement_ids,
        required_scopes_by_requirement=required_scopes_by_requirement, revision=revision,
        requirement_semantics_fingerprints=requirement_semantics_fingerprints,
    )

    all_evidence_refs = tuple(dict.fromkeys(
        [rid for r in requirement_results for rid in r.contributing_record_ids]
        + list(build.evidence_refs) + list(unit_tests.evidence_refs) + list(integration_tests.evidence_refs)
        + list(e2e_tests.evidence_refs) + list(security.evidence_refs) + list(authority.evidence_refs)
        + ([court_snapshot.decision_id] if court_snapshot.decision_id else [])
    ))

    proof = ProductionProof(
        proof_id=proof_id or _pid(), mission_id=mission_id, repository=repository, branch=branch,
        base_revision=base_revision, revision=revision, generated_at=generated_at or _now_iso(),
        proof_schema_version=PROOF_SCHEMA_VERSION, generator_id=GENERATOR_ID, generator_version=GENERATOR_VERSION,
        decision_context_fingerprint=fingerprint,
        required_requirement_ids=tuple(required_requirement_ids), requirement_results=requirement_results,
        requirements_satisfied=requirements_satisfied, requirements_unresolved=requirements_unresolved,
        requirements_failed=requirements_failed,
        build=build, unit_tests=unit_tests, integration_tests=integration_tests, e2e_tests=e2e_tests,
        regression=regression, security=security, authority=authority,
        anti_test_gaming=anti_gaming, cognitive_court=court_snapshot,
        supply_chain=supply_chain, licensing=licensing, accessibility=accessibility, performance=performance,
        release_build=release_build, deployment=deployment, post_deploy_smoke=post_deploy_smoke, rollback=rollback,
        known_limitations=tuple(known_limitations), unverified_assumptions=tuple(unverified_assumptions),
        blockers=tuple(blockers), warnings=tuple(warnings),
        evidence_refs=all_evidence_refs, artifact_hashes=tuple(sorted((artifact_hashes or {}).items())),
        verifier_versions=tuple(sorted((verifier_versions or {}).items())),
        tool_versions=tuple(sorted((tool_versions or {}).items())),
        release_state=release_state,
    )
    # Phase 15.10.1 closure item 10: sanitize the FULLY-ASSEMBLED proof
    # before it is ever hashed, persisted, or rendered -- the object
    # that gets hashed is already the safe one.
    return _sanitize_value(proof)


# ── Canonical serialization + hashing (spec section 24) ──────────────

def _default_json(obj):
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"not JSON-serializable: {type(obj)!r}")


def to_dict(proof: ProductionProof) -> dict:
    raw = asdict(proof)
    return json.loads(json.dumps(raw, default=_default_json, sort_keys=True))


def canonical_json(proof: ProductionProof) -> str:
    return json.dumps(to_dict(proof), sort_keys=True, separators=(",", ":"))


def compute_proof_hash(proof: ProductionProof) -> str:
    return hashlib.sha256(canonical_json(proof).encode("utf-8")).hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Stale-proof detection (spec item 9) ──────────────────────────────

def is_proof_stale(
    proof: ProductionProof, *, current_revision: str,
    current_required_requirement_ids: tuple[str, ...] | None = None,
    current_required_scopes_by_requirement: dict[str, RequiredVerificationScope] | None = None,
    current_requirement_semantics_fingerprints: dict[str, str] | None = None,
) -> bool:
    """Revision mismatch alone is always stale. When the caller also
    supplies the CURRENT decision context (required requirement ids +
    scopes, optionally semantics fingerprints), the full canonical
    `decision_context_fingerprint` is recomputed and compared -- a
    newly-added or removed required requirement, a changed scope, or a
    requirement whose semantics changed under the same ID (via a
    supplied semantics fingerprint) are all detected; a merely
    reordered-but-equivalent input set is NOT (sorted internally)."""
    if proof.revision != current_revision:
        return True
    if current_required_requirement_ids is None or current_required_scopes_by_requirement is None:
        return False
    current_fp = compute_decision_context_fingerprint(
        required_requirement_ids=current_required_requirement_ids,
        required_scopes_by_requirement=current_required_scopes_by_requirement,
        revision=current_revision, requirement_semantics_fingerprints=current_requirement_semantics_fingerprints,
    )
    return current_fp != proof.decision_context_fingerprint


# ── Human-readable rendering (spec section 25) ───────────────────────

def render_human_readable(proof: ProductionProof, *, proof_hash: str | None = None) -> str:
    lines: list[str] = []
    lines.append(f"PRODUCTION PROOF {proof.proof_id}")
    lines.append(f"  mission:        {proof.mission_id}")
    if proof.repository:
        lines.append(f"  repository:     {proof.repository}")
    if proof.branch:
        lines.append(f"  branch:         {proof.branch}")
    lines.append(f"  revision:       {proof.revision}")
    if proof.base_revision:
        lines.append(f"  base_revision:  {proof.base_revision}")
    lines.append(f"  generated_at:   {proof.generated_at}")
    lines.append(f"  schema:         {proof.proof_schema_version}")
    lines.append(f"  generator:      {proof.generator_id}@{proof.generator_version}")
    lines.append(f"  context_fp:     {proof.decision_context_fingerprint}")
    lines.append("")
    lines.append(f"RELEASE STATE: {proof.release_state}")
    lines.append("")
    lines.append("REQUIREMENTS")
    lines.append(f"  satisfied ({len(proof.requirements_satisfied)}): {list(proof.requirements_satisfied)}")
    lines.append(f"  unresolved ({len(proof.requirements_unresolved)}): {list(proof.requirements_unresolved)}")
    lines.append(f"  failed ({len(proof.requirements_failed)}): {list(proof.requirements_failed)}")
    for r in proof.requirement_results:
        lines.append(f"    - {r.requirement_id}: {r.outcome.value} (scope={list(r.scope_keys)}, missing={list(r.missing_keys)})")
    lines.append("")
    lines.append("ENGINEERING EVIDENCE")
    lines.append(f"  build:            {proof.build.status.value} -- {proof.build.summary}")
    lines.append(
        f"  unit_tests:       {proof.unit_tests.status.value} "
        f"(collected={proof.unit_tests.collected} passed={proof.unit_tests.passed} "
        f"failed={proof.unit_tests.failed} skipped={proof.unit_tests.skipped})"
    )
    lines.append(
        f"  integration_tests:{proof.integration_tests.status.value} "
        f"(collected={proof.integration_tests.collected} passed={proof.integration_tests.passed})"
    )
    lines.append(f"  e2e_tests:        {proof.e2e_tests.status.value} (collected={proof.e2e_tests.collected})")
    lines.append(
        f"  regression:       {proof.regression.status.value} "
        f"(new_failures={list(proof.regression.new_failures)}, "
        f"pre_existing={list(proof.regression.known_pre_existing_failures)})"
    )
    lines.append(f"  security:         {proof.security.status.value} -- {proof.security.summary}")
    lines.append(f"  authority:        {proof.authority.status.value} -- {proof.authority.summary}")
    lines.append("")
    lines.append("COGNITIVE COURT")
    lines.append(f"  verdict:        {proof.cognitive_court.verdict}")
    lines.append(f"  decision_id:    {proof.cognitive_court.decision_id or '(none)'}")
    lines.append(f"  context_bound:  {proof.cognitive_court.context_bound}")
    lines.append(f"  evidence_source:{proof.cognitive_court.evidence_source} (durable={proof.cognitive_court.durable})")
    lines.append("")
    lines.append("ANTI-TEST-GAMING")
    lines.append(f"  analysis_performed: {proof.anti_test_gaming.analysis_performed}")
    lines.append(f"  analysis_id:        {proof.anti_test_gaming.analysis_id or '(none)'}")
    lines.append(f"  blocking_findings:  {list(proof.anti_test_gaming.blocking_finding_ids)}")
    lines.append(f"  critical_findings:  {list(proof.anti_test_gaming.critical_finding_ids)}")
    lines.append("")
    lines.append("RELEASE EVIDENCE")
    lines.append(f"  supply_chain:     {proof.supply_chain.status.value} -- {proof.supply_chain.summary}")
    lines.append(f"  licensing:        {proof.licensing.status.value} -- {proof.licensing.summary}")
    lines.append(f"  accessibility:    {proof.accessibility.status.value} -- {proof.accessibility.summary}")
    lines.append(f"  performance:      {proof.performance.status.value} -- {proof.performance.summary}")
    lines.append(f"  release_build:    {proof.release_build.status.value} -- {proof.release_build.summary}")
    lines.append(f"  deployment:       {proof.deployment.state.value} (revision={proof.deployment.revision})")
    lines.append(f"  post_deploy_smoke:{proof.post_deploy_smoke.status.value} -- {proof.post_deploy_smoke.summary}")
    lines.append(
        f"  rollback:         strategy_documented={proof.rollback.strategy_documented} "
        f"procedure_tested={proof.rollback.procedure_tested} "
        f"proven_for_current_deployment(claimed)={proof.rollback.proven_for_current_deployment} "
        f"proven(system)={_rollback_effectively_proven(proof.rollback, proof.deployment, revision=proof.revision)}"
    )
    lines.append("")
    lines.append(f"BLOCKERS ({len(proof.blockers)}):")
    for b in proof.blockers:
        lines.append(f"  - {b}")
    lines.append(f"WARNINGS ({len(proof.warnings)}):")
    for w in proof.warnings:
        lines.append(f"  - {w}")
    lines.append(f"KNOWN LIMITATIONS ({len(proof.known_limitations)}):")
    for k in proof.known_limitations:
        lines.append(f"  - {k}")
    lines.append(f"UNVERIFIED ASSUMPTIONS ({len(proof.unverified_assumptions)}):")
    for u in proof.unverified_assumptions:
        lines.append(f"  - {u}")
    lines.append("")
    lines.append(f"EVIDENCE REFS: {list(proof.evidence_refs)}")
    if proof_hash:
        lines.append(f"PROOF HASH (sha256): {proof_hash}")
    lines.append(
        "NOTE: this proof hash proves byte-identity/integrity of the proof payload -- "
        "it does not itself prove the claims inside the proof are true."
    )
    text = "\n".join(lines) + "\n"
    return redact_secrets(text) or text


# ── LAUNCH gate integration (reuses orca.mission.code_mode, spec section 23) ──

def launch_evidence_from_proof(proof: ProductionProof) -> dict[str, bool | None]:
    """Maps this proof's own already-derived, already-scoped category
    outcomes onto `orca.mission.code_mode.REQUIRED_LAUNCH_CATEGORIES`.
    Deployment/rollback readiness now go through the SAME current-
    deployment/effectively-proven gates used everywhere else in this
    module (Phase 15.10.1 closure item 7) -- a stale deployment or an
    unproven rollback claim can no longer leak into LAUNCH readiness."""
    def _tri(status: VerificationOutcome) -> bool | None:
        if status is VerificationOutcome.PASS:
            return True
        if status is VerificationOutcome.FAIL:
            return False
        return None

    requirements_ok = (
        bool(proof.required_requirement_ids)
        and not proof.requirements_failed and not proof.requirements_unresolved
    )
    court_ok = _court_effectively_accepted(proof.cognitive_court)
    anti_gaming_ok = proof.anti_test_gaming.analysis_performed and not proof.anti_test_gaming.blocking_finding_ids
    deployment_current = _deployment_is_current(proof.deployment, revision=proof.revision)
    rollback_proven = _rollback_effectively_proven(proof.rollback, proof.deployment, revision=proof.revision)

    return {
        "build_evidence": _tri(proof.build.status),
        "tests": _tri(proof.unit_tests.status),
        "regression": _tri(proof.regression.status),
        "security": _tri(proof.security.status),
        "authority": _tri(proof.authority.status),
        "supply_chain": _tri(proof.supply_chain.status),
        "release_configuration": _tri(proof.release_build.status),
        "deployment_readiness": True if deployment_current else None,
        "rollback_readiness": True if rollback_proven else None,
        "production_proof_hooks": requirements_ok and court_ok and anti_gaming_ok,
    }
