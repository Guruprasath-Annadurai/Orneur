"""
Phase 15.10 -- Production Proof: ORNEUR Code's first-class, typed,
machine-readable + human-readable evidence artifact (spec sections
17-20).

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

This module does NOT invent a new verification truth rule. Requirement
results are derived exclusively via `orca.mission.verification_
aggregation.evaluate_requirement_completion_for_mission()` (Phase
15.9.4's single authoritative mission-critical aggregation function),
and every other category that is VerificationRecord-backed (build,
security, authority) is aggregated via the SAME `aggregate_outcomes()`
rule the Verification Engine and the Cognitive Court already use --
not a duplicate.

Phase 15.7's in-process `AcceptanceCriterion` registry is deliberately
never consulted here (mirroring Phase 15.9.4's own closure): every
required requirement's `RequiredVerificationScope` must be supplied
explicitly to `generate_production_proof()`, or generation raises
`ProductionProofError` -- unknown expected scope fails closed, exactly
as it does one layer down in `arbiter_decide()`/`can_complete_
verified()`.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
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

PROOF_SCHEMA_VERSION = "15.10.0"
GENERATOR_ID = "orca.mission.production_proof"
GENERATOR_VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductionProofError(Exception):
    pass


def _pid() -> str:
    return f"proof_{uuid.uuid4().hex[:16]}"


# ── Section 4: small defense-in-depth input-integrity hardening ─────
# Narrow, additive checks on top of what RequiredVerificationScope,
# arbiter_decide(), and evaluate_requirement_completion_for_mission()
# already enforce -- NOT a redesign of the scope architecture.

def _require_nonempty(value: str, *, field_name: str) -> None:
    if not (value or "").strip():
        raise ProductionProofError(
            f"Production Proof: {field_name!r} must be a non-empty string on the "
            f"mission-critical evaluation path (Phase 15.10 closure item 4)."
        )


def _validate_scope_keys(scope: RequiredVerificationScope, *, requirement_id: str) -> None:
    """Malformed-scope-input hardening (spec item 4): an empty string
    inside `criterion_ids`/`requirement_level_categories` would collapse
    into a bare `""` or `"category:"` aggregation key -- indistinguishable
    from a genuinely different key and therefore a silent scope-collapse
    hazard. `RequiredVerificationScope.__post_init__` already forbids a
    wholly EMPTY scope (Phase 15.9.4); this adds the narrower check that
    no individual key within a non-empty scope is itself blank."""
    for cid in scope.criterion_ids:
        if not (cid or "").strip():
            raise ProductionProofError(
                f"Production Proof: requirement {requirement_id!r} has a blank criterion_id "
                f"inside its RequiredVerificationScope -- this would silently collapse into "
                f"a bare aggregation key (Phase 15.10 closure item 4)."
            )
    for cat in scope.requirement_level_categories:
        if not (cat or "").strip():
            raise ProductionProofError(
                f"Production Proof: requirement {requirement_id!r} has a blank "
                f"requirement_level_category inside its RequiredVerificationScope -- this "
                f"would silently collapse into a bare 'category:' aggregation key "
                f"(Phase 15.10 closure item 4)."
            )
    combined = scope.criterion_ids | scope.requirement_level_categories
    if len(combined) != len(scope.criterion_ids) + len(scope.requirement_level_categories):
        raise ProductionProofError(
            f"Production Proof: requirement {requirement_id!r} has a criterion_id and a "
            f"requirement_level_category sharing the same literal name -- this would "
            f"silently collapse two distinct required checks into one aggregation key "
            f"(Phase 15.10 closure item 4)."
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
    """Best-effort scrubber applied to every human-facing string this
    module derives from raw verifier/command output before it can
    reach a persisted or rendered Production Proof (spec section 26).
    Not a substitute for the verifiers' own bounded-output discipline
    (they already truncate stdout/stderr) -- an additional layer, since
    a persisted proof must NEVER contain a raw secret."""
    if text is None:
        return None
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


# ── Category outcome helpers (spec section 2) ────────────────────────
# PASS / FAIL / UNVERIFIED / NOT_APPLICABLE / ERROR / CANCELLED /
# TIMED_OUT are reused directly from Phase 15.8's VerificationOutcome
# -- no narrower proof-category enum is invented (spec section 2).

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
                "it may never be the default for a merely-unchecked category (spec section 16)."
            )


def category_from_records(
    records: tuple[VerificationRecord, ...], *, not_run_summary: str,
) -> ProofCategory:
    """The shared rule for any VerificationRecord-backed category
    (build, security, authority): reuses `aggregate_outcomes()` --
    the SAME non-vacuous aggregation rule used everywhere else in this
    package -- rather than inventing a parallel one. Zero records is
    UNVERIFIED, never PASS (spec sections 9, 12, 13)."""
    if not records:
        return ProofCategory(status=VerificationOutcome.UNVERIFIED, summary=redact_secrets(not_run_summary) or "")
    status = aggregate_outcomes(tuple(r.outcome for r in records))
    summary = redact_secrets(f"{len(records)} verification record(s): " + ", ".join(r.id for r in records)) or ""
    return ProofCategory(status=status, summary=summary, evidence_refs=tuple(r.id for r in records))


def not_applicable_category(reason: str) -> ProofCategory:
    return ProofCategory(status=VerificationOutcome.NOT_APPLICABLE, summary=reason, not_applicable_reason=reason)


def unverified_category(reason: str) -> ProofCategory:
    return ProofCategory(status=VerificationOutcome.UNVERIFIED, summary=redact_secrets(reason) or "")


# ── Test evidence (spec section 10) ──────────────────────────────────

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


def test_category_from_records(
    records: tuple[VerificationRecord, ...], *, revision: str | None = None,
    collected: int | None = None, passed: int | None = None, failed: int | None = None,
    skipped: int | None = None, errors: int | None = None, duration_seconds: float | None = None,
) -> TestCategoryResult:
    """0 tests collected must never silently become PASS (spec section
    10) -- enforced HERE too, as defense in depth, even though
    `UnitTestVerifier` already implements this rule at the verifier
    layer (spec section 4's narrow hardening: don't trust a single
    layer to be the only place this invariant is checked)."""
    if not records:
        return TestCategoryResult(
            status=VerificationOutcome.UNVERIFIED, collected=collected, passed=passed, failed=failed,
            skipped=skipped, errors=errors, duration_seconds=duration_seconds, revision=revision,
            summary="not run -- zero verification records supplied for this test category",
        )
    status = aggregate_outcomes(tuple(r.outcome for r in records))
    if collected == 0 and status is VerificationOutcome.PASS:
        status = VerificationOutcome.UNVERIFIED
    summary = f"collected={collected} passed={passed} failed={failed} skipped={skipped} errors={errors}"
    return TestCategoryResult(
        status=status, collected=collected, passed=passed, failed=failed, skipped=skipped,
        errors=errors, duration_seconds=duration_seconds, revision=revision,
        evidence_refs=tuple(r.id for r in records), summary=redact_secrets(summary) or "",
    )


# ── Regression evidence (spec section 11) ────────────────────────────

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


# ── Cognitive Court snapshot (spec section 7) ────────────────────────

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


def court_snapshot_from_decision(decision: CourtDecision, *, durable: bool = False) -> CourtSnapshot:
    """`durable=False` by default: Phase 15.9 CourtDecisions are
    in-process only (no `court_decisions` table exists yet) -- this
    snapshot is a proof-time copy of the supplied decision, honestly
    disclosed as non-durable unless the caller genuinely backs it with
    a durable Court store (spec section 7: never claim tamper-evident
    Court history that does not exist)."""
    return CourtSnapshot(
        decision_id=decision.decision_id, mission_id=decision.mission_id, revision=decision.revision,
        risk_level=decision.risk_level.value, roles_invoked=tuple(r.value for r in decision.roles_invoked),
        verdict=decision.verdict.value, findings_considered=decision.findings_considered,
        verification_refs=decision.verification_refs,
        reasoning_summary=redact_secrets(decision.reasoning_summary) or "", durable=durable,
    )


def no_court_snapshot(reason: str) -> CourtSnapshot:
    return CourtSnapshot(
        decision_id="", mission_id="", revision="", risk_level="", roles_invoked=(),
        verdict="NOT_EVALUATED", findings_considered=(), verification_refs=(),
        reasoning_summary=reason, durable=False,
    )


# ── Anti-test-gaming snapshot (spec section 8) ───────────────────────

@dataclass(frozen=True)
class AntiGamingSnapshot:
    analysis_performed: bool
    baseline_revision: str | None
    candidate_revision: str | None
    blocking_finding_ids: tuple[str, ...]
    critical_finding_ids: tuple[str, ...]
    total_findings: int
    detector_ids: tuple[str, ...]


def anti_gaming_snapshot(
    findings: tuple[AntiGamingFinding, ...], *, analysis_performed: bool,
    baseline_revision: str | None = None, candidate_revision: str | None = None,
) -> AntiGamingSnapshot:
    """Distinguishes "no findings after analysis" from "analysis not
    performed" (spec section 8) -- `analysis_performed` must be
    supplied explicitly by the caller; zero findings never implies
    analysis happened on its own."""
    blocking = tuple(f.finding_id for f in findings if f.blocking)
    critical = tuple(f.finding_id for f in findings if f.severity is Severity.CRITICAL)
    detectors = tuple(sorted({f.detector_id for f in findings}))
    return AntiGamingSnapshot(
        analysis_performed=analysis_performed, baseline_revision=baseline_revision,
        candidate_revision=candidate_revision, blocking_finding_ids=blocking,
        critical_finding_ids=critical, total_findings=len(findings), detector_ids=detectors,
    )


# ── Deployment / rollback evidence (spec sections 19-21) ─────────────

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


@dataclass(frozen=True)
class RollbackResult:
    strategy_documented: bool
    procedure_tested: bool
    proven_for_current_deployment: bool
    method: str | None = None
    notes: str | None = None


def undocumented_rollback() -> RollbackResult:
    return RollbackResult(strategy_documented=False, procedure_tested=False, proven_for_current_deployment=False)


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


# ── Release-state policy (spec section 22) ───────────────────────────

NOT_ENGINEERING_READY = "NOT_ENGINEERING_READY"


def _derive_release_state(
    *, requirements_unresolved: tuple[str, ...], requirements_failed: tuple[str, ...],
    court: CourtSnapshot, anti_gaming: AntiGamingSnapshot, build: ProofCategory,
    unit_tests: TestCategoryResult, security: ProofCategory,
    submission_ready_satisfied: bool, release_candidate_satisfied: bool,
    published_externally_confirmed: bool,
) -> str:
    engineering_ready = (
        not requirements_unresolved and not requirements_failed
        and court.verdict == CourtVerdict.ACCEPT.value
        and anti_gaming.analysis_performed and not anti_gaming.blocking_finding_ids
        and build.status is VerificationOutcome.PASS
        and unit_tests.status is VerificationOutcome.PASS
        and security.status is VerificationOutcome.PASS
    )
    if not engineering_ready:
        return NOT_ENGINEERING_READY
    if not submission_ready_satisfied:
        return LaunchReadiness.ENGINEERING_READY.value
    if not release_candidate_satisfied:
        return LaunchReadiness.SUBMISSION_READY.value
    if not published_externally_confirmed:
        return LaunchReadiness.RELEASE_CANDIDATE.value
    return LaunchReadiness.PUBLISHED.value


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
    court_decision_durable: bool = False,
    anti_gaming_findings: tuple[AntiGamingFinding, ...] = (),
    anti_gaming_analysis_performed: bool = False,
    anti_gaming_baseline_revision: str | None = None,
    anti_gaming_candidate_revision: str | None = None,
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
    submission_ready_satisfied: bool = False,
    release_candidate_satisfied: bool = False,
    published_externally_confirmed: bool = False,
    proof_id: str | None = None,
    generated_at: str | None = None,
) -> ProductionProof:
    """The ONLY function that produces a ProductionProof. Reads ONLY
    typed evidence sources (VerificationRecord tuples, a real
    CourtDecision, real AntiGamingFinding tuples) -- there is no
    parameter through which a caller can hand this function a bare
    `{"unit_tests": "PASS"}`-style claim (spec section 6): every PASS
    this function can produce traces back to a real VerificationRecord
    (or, for regression/deployment/rollback, an explicitly-typed
    result object the caller must construct field by field, never a
    bare boolean)."""
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
        court_snapshot_from_decision(court_decision, durable=court_decision_durable)
        if court_decision is not None
        else no_court_snapshot("no CourtDecision supplied for this proof")
    )
    anti_gaming = anti_gaming_snapshot(
        anti_gaming_findings, analysis_performed=anti_gaming_analysis_performed,
        baseline_revision=anti_gaming_baseline_revision, candidate_revision=anti_gaming_candidate_revision,
    )

    build = category_from_records(build_records, not_run_summary="build not run for this proof")
    unit_test_stats = unit_test_stats or {}
    integration_test_stats = integration_test_stats or {}
    e2e_test_stats = e2e_test_stats or {}
    unit_tests = test_category_from_records(unit_test_records, revision=revision, **unit_test_stats)
    integration_tests = test_category_from_records(integration_test_records, revision=revision, **integration_test_stats)
    e2e_tests = test_category_from_records(e2e_test_records, revision=revision, **e2e_test_stats)
    regression = regression or not_run_regression()
    security = category_from_records(security_records, not_run_summary="security suite not run for this proof")
    authority = category_from_records(authority_records, not_run_summary="authority evidence not supplied for this proof")

    supply_chain = supply_chain or unverified_category("supply-chain evidence not supplied for this proof")
    licensing = licensing or unverified_category("licensing evidence not supplied for this proof")
    accessibility = accessibility or unverified_category("accessibility not evaluated for this proof")
    performance = performance or unverified_category("performance not measured for this proof")
    release_build = release_build or unverified_category("no release-build artifact produced for this proof")
    deployment = deployment or not_deployed(revision=revision)
    post_deploy_smoke = post_deploy_smoke or unverified_category("no post-deploy smoke evidence for this proof")
    rollback = rollback or undocumented_rollback()

    blockers: list[str] = []
    if requirements_failed:
        blockers.append(f"required requirement(s) failed: {list(requirements_failed)!r}")
    if requirements_unresolved:
        blockers.append(f"required requirement(s) unresolved: {list(requirements_unresolved)!r}")
    if court_snapshot.verdict != CourtVerdict.ACCEPT.value:
        blockers.append(f"Cognitive Court verdict is {court_snapshot.verdict!r}, not ACCEPT")
    if anti_gaming.blocking_finding_ids:
        blockers.append(f"blocking anti-gaming finding(s): {list(anti_gaming.blocking_finding_ids)!r}")
    if build.status is not VerificationOutcome.PASS:
        blockers.append(f"build category is {build.status.value}, not PASS")
    if unit_tests.status is not VerificationOutcome.PASS:
        blockers.append(f"unit_tests category is {unit_tests.status.value}, not PASS")
    if security.status is not VerificationOutcome.PASS:
        blockers.append(f"security category is {security.status.value}, not PASS")

    warnings: list[str] = []
    if not anti_gaming.analysis_performed:
        warnings.append("anti-test-gaming analysis was not performed for this revision")
    if not court_snapshot.durable:
        warnings.append("Cognitive Court decision is a proof-time in-process snapshot, not independently durable")
    if regression.status is VerificationOutcome.UNVERIFIED:
        warnings.append("no regression baseline comparison was performed for this proof")

    release_state = _derive_release_state(
        requirements_unresolved=requirements_unresolved, requirements_failed=requirements_failed,
        court=court_snapshot, anti_gaming=anti_gaming, build=build, unit_tests=unit_tests, security=security,
        submission_ready_satisfied=submission_ready_satisfied,
        release_candidate_satisfied=release_candidate_satisfied,
        published_externally_confirmed=published_externally_confirmed,
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
    return proof


# ── Canonical serialization + hashing (spec section 24) ──────────────

def _default_json(obj):
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"not JSON-serializable: {type(obj)!r}")


def to_dict(proof: ProductionProof) -> dict:
    """Canonical dict form -- used for both hashing and durable
    storage. Enum values are serialized as their `.value` string."""
    raw = asdict(proof)
    return json.loads(json.dumps(raw, default=_default_json, sort_keys=True))


def canonical_json(proof: ProductionProof) -> str:
    """The canonical serialization hashing is computed over. Does NOT
    include a hash field itself -- `ProductionProof` carries no
    self-referential `proof_hash` field, so there is no risk of
    recursively hashing the hash (spec section 24)."""
    return json.dumps(to_dict(proof), sort_keys=True, separators=(",", ":"))


def compute_proof_hash(proof: ProductionProof) -> str:
    """SHA-256 of the canonical serialization. Proves byte-identity of
    the proof payload -- it does NOT prove the claims inside the proof
    are true (spec section 24)."""
    return hashlib.sha256(canonical_json(proof).encode("utf-8")).hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Human-readable rendering (spec section 25) ───────────────────────

def render_human_readable(proof: ProductionProof, *, proof_hash: str | None = None) -> str:
    """Deterministic renderer DERIVED from the typed object -- it
    never independently invents a conclusion; every line traces to a
    field already on `proof`."""
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
    lines.append(f"  durable:        {proof.cognitive_court.durable}")
    lines.append("")
    lines.append("ANTI-TEST-GAMING")
    lines.append(f"  analysis_performed: {proof.anti_test_gaming.analysis_performed}")
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
        f"proven_for_current_deployment={proof.rollback.proven_for_current_deployment}"
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
# Wires a real ProductionProof into the EXISTING interface-only LAUNCH
# evidence-category gate from Phase 15.9's code_mode.py rather than
# building a second, competing readiness gate.

def launch_evidence_from_proof(proof: ProductionProof) -> dict[str, bool | None]:
    """Maps this proof's own already-derived category outcomes onto
    `orca.mission.code_mode.REQUIRED_LAUNCH_CATEGORIES` -- True only
    for a genuine PASS, False for a genuine FAIL, `None` (UNVERIFIED)
    for everything else, including categories this proof never
    populated. `code_mode.evaluate_launch_gate()` then applies its own
    unchanged, missing-evidence-never-PASS policy over this dict."""
    def _tri(status: VerificationOutcome) -> bool | None:
        if status is VerificationOutcome.PASS:
            return True
        if status is VerificationOutcome.FAIL:
            return False
        return None

    # "production_proof_hooks" folds requirement truth, Court verdict,
    # and anti-gaming analysis into the ONE category REQUIRED_LAUNCH_
    # CATEGORIES actually names for this purpose -- rather than
    # inventing new category keys `evaluate_launch_gate()` would
    # silently ignore (it only reads the 10 names it already knows).
    requirements_ok = (
        bool(proof.required_requirement_ids)
        and not proof.requirements_failed and not proof.requirements_unresolved
    )
    court_ok = proof.cognitive_court.verdict == CourtVerdict.ACCEPT.value
    anti_gaming_ok = proof.anti_test_gaming.analysis_performed and not proof.anti_test_gaming.blocking_finding_ids

    return {
        "build_evidence": _tri(proof.build.status),
        "tests": _tri(proof.unit_tests.status),
        "regression": _tri(proof.regression.status),
        "security": _tri(proof.security.status),
        "authority": _tri(proof.authority.status),
        "supply_chain": _tri(proof.supply_chain.status),
        "release_configuration": _tri(proof.release_build.status),
        "deployment_readiness": True if proof.deployment.state is not DeploymentState.NOT_DEPLOYED else None,
        "rollback_readiness": True if proof.rollback.proven_for_current_deployment else None,
        "production_proof_hooks": requirements_ok and court_ok and anti_gaming_ok,
    }
