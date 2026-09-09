"""
Phase 15.9 -- Cognitive Court: typed critic roles, risk classification,
and a deterministic Arbiter (spec sections 15-26).

The "Arbiter" here is a SOFTWARE ROLE/INTERFACE only -- it is not, and
must never be presented as, Orneur Genesis/Novus/Aeternum/ORNEUR Auto.
No native model intelligence is created by this module.

Hard invariant: a `ModelProvider` (Phase 15.6, reused unmodified) may
contribute narrative reasoning to any critic, but that narrative is
kept in a SEPARATE field (`CriticOutput.provider_narrative`) and never
substitutes for the critic's own deterministic `conclusion`. The
Arbiter's policy function (`arbiter_decide`) reads ONLY deterministic
inputs (anti-gaming findings, verification outcomes, critic
conclusions) -- there is no code path where provider text can flip a
verdict.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from orca.mission.anti_gaming import AntiGamingFinding, critical_findings, has_blocking_finding
from orca.mission.providers import ModelProvider, ProviderError, ProviderRequest
from orca.mission.test_collection_diff import CollectionDelta
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import (
    RequiredVerificationScope,
    evaluate_requirement_completion_for_mission,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _did() -> str:
    return f"court_{uuid.uuid4().hex[:16]}"


class CourtRole(str, Enum):
    CONSTRUCTOR = "CONSTRUCTOR"
    FALSIFIER = "FALSIFIER"
    SECURITY_CRITIC = "SECURITY_CRITIC"
    REGRESSION_CRITIC = "REGRESSION_CRITIC"
    TEST_CRITIC = "TEST_CRITIC"
    PERFORMANCE_CRITIC = "PERFORMANCE_CRITIC"
    ARBITER = "ARBITER"


class CriticConclusion(str, Enum):
    SUPPORTS_ACCEPT = "SUPPORTS_ACCEPT"
    SUPPORTS_REJECT = "SUPPORTS_REJECT"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    NOT_REQUIRED = "NOT_REQUIRED"


class RiskLevel(str, Enum):
    TRIVIAL = "TRIVIAL"
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CourtVerdict(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    NEED_MORE_EVIDENCE = "NEED_MORE_EVIDENCE"
    ESCALATE = "ESCALATE"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class CourtError(Exception):
    pass


class CourtConfigurationError(CourtError):
    """Raised when `arbiter_decide()` is invoked in a configuration
    that could otherwise allow a vacuous or unscoped ACCEPT -- an
    empty `required_requirement_ids`, or a missing/empty `mission_id`
    or `revision` (Phase 15.9.2 closure items 1-2). This is a caller
    misconfiguration, not a normal Court verdict: it is raised before
    any `CourtDecision` is constructed, so there is no verdict value
    that could be misread as ACCEPT."""
    pass


@dataclass(frozen=True)
class CriticOutput:
    role: CourtRole
    conclusion: CriticConclusion
    reasoning_summary: str
    findings_considered: tuple[str, ...] = field(default_factory=tuple)
    provider_narrative: str | None = None  # kept separate -- never authoritative

    def __post_init__(self) -> None:
        if not self.reasoning_summary.strip():
            raise CourtError(f"{self.role.value}: reasoning_summary must not be empty.")


@dataclass(frozen=True)
class CourtDecision:
    decision_id: str
    mission_id: str | None
    revision: str
    risk_level: RiskLevel
    roles_invoked: tuple[CourtRole, ...]
    findings_considered: tuple[str, ...]
    verification_refs: tuple[str, ...]
    reasoning_summary: str
    verdict: CourtVerdict
    created_at: str = field(default_factory=_now_iso)
    limitations: str | None = None


# ── Risk classification (spec section 24) ───────────────────────────

def classify_risk(
    *, changed_files: tuple[str, ...], security_relevant_files_touched: bool,
    findings: tuple[AntiGamingFinding, ...],
) -> RiskLevel:
    if critical_findings(findings):
        return RiskLevel.CRITICAL
    if security_relevant_files_touched:
        return RiskLevel.HIGH
    non_doc_files = [f for f in changed_files if not f.endswith((".md", ".txt"))]
    if not non_doc_files:
        return RiskLevel.TRIVIAL
    if len(non_doc_files) <= 2 and not any(f.startswith("tests/") for f in non_doc_files):
        return RiskLevel.STANDARD
    return RiskLevel.ELEVATED


def roles_for_risk(risk: RiskLevel) -> tuple[CourtRole, ...]:
    """Which roles are actually invoked, and why (spec section 24:
    "Record which roles were invoked and why")."""
    if risk is RiskLevel.TRIVIAL:
        return (CourtRole.CONSTRUCTOR, CourtRole.REGRESSION_CRITIC)
    if risk is RiskLevel.STANDARD:
        return (CourtRole.CONSTRUCTOR, CourtRole.TEST_CRITIC, CourtRole.ARBITER)
    if risk is RiskLevel.ELEVATED:
        return (CourtRole.CONSTRUCTOR, CourtRole.TEST_CRITIC, CourtRole.REGRESSION_CRITIC, CourtRole.ARBITER)
    # HIGH and CRITICAL: full court -- every role is INVOKED (asked for
    # an opinion), but Performance Critic is free to answer
    # CriticConclusion.NOT_REQUIRED when the candidate genuinely has no
    # meaningful performance risk (spec section 22) -- "invoked" here
    # means "consulted", not "must produce a real measurement out of
    # nothing." Phase 15.9.1 closure: this role was previously omitted
    # from the set this branch actually returned, contradicting its
    # own "full court" comment.
    return (
        CourtRole.CONSTRUCTOR, CourtRole.FALSIFIER, CourtRole.SECURITY_CRITIC,
        CourtRole.REGRESSION_CRITIC, CourtRole.TEST_CRITIC, CourtRole.PERFORMANCE_CRITIC, CourtRole.ARBITER,
    )


# ── Roles (spec sections 17-23) ──────────────────────────────────────

def constructor_summarize(
    *, revision: str, requirement_ids: tuple[str, ...], implementation_files: tuple[str, ...],
    evidence_refs: tuple[str, ...], limitations: tuple[str, ...],
    provider: ModelProvider | None = None,
) -> CriticOutput:
    """Constructor does NOT approve its own work -- its conclusion is
    always NOT_REQUIRED (it has no accept/reject opinion), it only
    summarizes."""
    summary = (
        f"Candidate {revision}: requirements={requirement_ids!r}, "
        f"implementation_files={implementation_files!r}, evidence_refs={evidence_refs!r}, "
        f"known_limitations={limitations!r}."
    )
    narrative = _try_provider_narrative(provider, summary, purpose="constructor_summary")
    return CriticOutput(
        role=CourtRole.CONSTRUCTOR, conclusion=CriticConclusion.NOT_REQUIRED,
        reasoning_summary=summary, provider_narrative=narrative,
    )


def falsifier_review(
    *, verification_outcomes: dict[str, VerificationOutcome], stale_requirement_ids: tuple[str, ...],
    missing_negative_case_requirement_ids: tuple[str, ...], provider: ModelProvider | None = None,
) -> CriticOutput:
    gaps = []
    if stale_requirement_ids:
        gaps.append(f"stale evidence for {stale_requirement_ids!r}")
    if missing_negative_case_requirement_ids:
        gaps.append(f"no negative-case coverage for {missing_negative_case_requirement_ids!r}")
    unverified = [rid for rid, outcome in verification_outcomes.items() if outcome is not VerificationOutcome.PASS]
    if unverified:
        gaps.append(f"not-PASS requirements: {unverified!r}")

    summary = f"Falsifier found gaps: {gaps!r}" if gaps else "Falsifier found no contradictory evidence."
    conclusion = CriticConclusion.SUPPORTS_REJECT if gaps else CriticConclusion.SUPPORTS_ACCEPT
    narrative = _try_provider_narrative(provider, summary, purpose="falsifier_review")
    return CriticOutput(role=CourtRole.FALSIFIER, conclusion=conclusion, reasoning_summary=summary,
                         provider_narrative=narrative)


def security_critic_review(
    findings: tuple[AntiGamingFinding, ...], *, provider: ModelProvider | None = None,
) -> CriticOutput:
    crit = critical_findings(findings)
    if crit:
        summary = f"{len(crit)} CRITICAL security-relevant finding(s): {[f.finding_id for f in crit]!r}."
        conclusion = CriticConclusion.SUPPORTS_REJECT
    else:
        security_findings = [f for f in findings if f.security_relevance]
        summary = (f"{len(security_findings)} security-relevant finding(s), none CRITICAL."
                   if security_findings else "No security-relevant findings.")
        conclusion = CriticConclusion.SUPPORTS_ACCEPT
    narrative = _try_provider_narrative(provider, summary, purpose="security_critic_review")
    return CriticOutput(role=CourtRole.SECURITY_CRITIC, conclusion=conclusion, reasoning_summary=summary,
                         findings_considered=tuple(f.finding_id for f in findings if f.security_relevance),
                         provider_narrative=narrative)


def regression_critic_review(
    delta: CollectionDelta | None, *, justified_removals: frozenset[str] = frozenset(),
    provider: ModelProvider | None = None,
) -> CriticOutput:
    if delta is None:
        return CriticOutput(
            role=CourtRole.REGRESSION_CRITIC, conclusion=CriticConclusion.NEEDS_MORE_EVIDENCE,
            reasoning_summary="No test-collection comparison was performed for this candidate.",
        )
    unjustified_removed = delta.removed - justified_removals
    if unjustified_removed:
        summary = (f"Collection shrank: {len(delta.removed)} test(s) removed, "
                   f"{len(unjustified_removed)} without justification: {sorted(unjustified_removed)!r}.")
        conclusion = CriticConclusion.SUPPORTS_REJECT
    elif delta.removed:
        summary = f"{len(delta.removed)} test(s) removed, all justified: {sorted(delta.removed)!r}."
        conclusion = CriticConclusion.SUPPORTS_ACCEPT
    else:
        summary = f"No test removed; {len(delta.added)} new test(s) added."
        conclusion = CriticConclusion.SUPPORTS_ACCEPT
    narrative = _try_provider_narrative(provider, summary, purpose="regression_critic_review")
    return CriticOutput(role=CourtRole.REGRESSION_CRITIC, conclusion=conclusion, reasoning_summary=summary,
                         provider_narrative=narrative)


def review_test_quality(
    findings: tuple[AntiGamingFinding, ...], *, provider: ModelProvider | None = None,
) -> CriticOutput:
    """Uses the anti-gaming findings DIRECTLY -- does not regenerate
    contradictory facts from prose (spec section 21's explicit
    instruction)."""
    test_related = [
        f for f in findings if f.category.value in (
            "TEST_DELETED", "TEST_DISABLED", "TEST_SKIPPED", "ASSERTION_REMOVED",
            "ASSERTION_WEAKENED", "MOCK_REPLACES_REQUIRED_BEHAVIOR",
        )
    ]
    blocking = has_blocking_finding(tuple(test_related))
    summary = (f"{len(test_related)} test-quality finding(s) from the anti-gaming engine, "
              f"blocking={blocking}: {[f.finding_id for f in test_related]!r}.")
    conclusion = CriticConclusion.SUPPORTS_REJECT if blocking else (
        CriticConclusion.NEEDS_MORE_EVIDENCE if test_related else CriticConclusion.SUPPORTS_ACCEPT
    )
    narrative = _try_provider_narrative(provider, summary, purpose="review_test_quality")
    return CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=conclusion, reasoning_summary=summary,
                         findings_considered=tuple(f.finding_id for f in test_related), provider_narrative=narrative)


def performance_critic_review(
    *, required: bool, measured: bool = False, passed: bool | None = None,
    provider: ModelProvider | None = None,
) -> CriticOutput:
    if not required:
        return CriticOutput(role=CourtRole.PERFORMANCE_CRITIC, conclusion=CriticConclusion.NOT_REQUIRED,
                             reasoning_summary="No meaningful performance risk for this candidate; role not required.")
    if not measured:
        return CriticOutput(role=CourtRole.PERFORMANCE_CRITIC, conclusion=CriticConclusion.NEEDS_MORE_EVIDENCE,
                             reasoning_summary="Performance is relevant but no real measurement exists -- never fabricated PASS.")
    summary = f"Real performance measurement exists; passed={passed}."
    conclusion = CriticConclusion.SUPPORTS_ACCEPT if passed else CriticConclusion.SUPPORTS_REJECT
    narrative = _try_provider_narrative(provider, summary, purpose="performance_critic_review")
    return CriticOutput(role=CourtRole.PERFORMANCE_CRITIC, conclusion=conclusion, reasoning_summary=summary,
                         provider_narrative=narrative)


def _try_provider_narrative(provider: ModelProvider | None, fact_summary: str, *, purpose: str) -> str | None:
    """Provider output is ADVISORY narrative only. A provider failure
    or absence never blocks or flips the deterministic conclusion --
    Court degrades truthfully (spec section 25: "Provider unavailable:
    Court must degrade truthfully. Do not turn provider failure into
    automatic ACCEPT"), which is trivially satisfied here since this
    function's return value is never consulted by arbiter_decide()."""
    if provider is None:
        return None
    try:
        response = provider.invoke(ProviderRequest(
            provider=getattr(provider, "provider_name", "unknown"), model=getattr(provider, "model_name", "unknown"),
            purpose=purpose, prompt=fact_summary,
        ))
        return response.text
    except ProviderError:
        return None


# ── Arbiter (spec section 23) ────────────────────────────────────────

def arbiter_decide(
    *, mission_id: str, revision: str, risk_level: RiskLevel,
    critic_outputs: tuple[CriticOutput, ...], findings: tuple[AntiGamingFinding, ...],
    required_verification_records: dict[str, tuple[VerificationRecord, ...]],
    required_requirement_ids: tuple[str, ...],
    required_scopes_by_requirement: dict[str, RequiredVerificationScope],
    owner_approval_required: bool = False,
) -> CourtDecision:
    """The ONLY function that produces a final CourtVerdict. Reads
    ONLY deterministic inputs -- no provider narrative is consulted
    here, so no model prompt can override these restrictions (spec
    section 23's explicit invariant).

    Phase 15.9.1 closure (item 5): ACCEPT is evidence-backed. The
    caller no longer supplies a bare `dict[str, VerificationOutcome]`
    that could be fabricated with no underlying record -- it supplies
    real `VerificationRecord` objects (from
    `orca.mission.verification_store`, the actual Phase 15.8 durable
    store, or an equivalent in-memory set in tests), and this function
    reuses `orca.mission.verification_aggregation.filter_current_context()`
    + `aggregate_requirement()` (the SAME functions the mission gate
    uses -- not a duplicate) to independently verify: the record's
    `mission_id` matches THIS decision's `mission_id`, the record's
    `revision` matches THIS decision's `revision`, and the aggregated
    outcome is genuinely PASS. Only the real record ids that actually
    supported an ACCEPT are written into `CourtDecision
    .verification_refs` -- a decision that could not ACCEPT always
    carries `verification_refs=()`.

    Phase 15.9.2 closure (items 1-2): an independent audit found this
    function could still be called with `required_requirement_ids=()`
    (the previous default) or `mission_id=None`/`""`. With an empty
    required set, `outcomes` and `not_pass` both stay `{}`, so a
    critic-only SUPPORTS_ACCEPT could fall through to a vacuous ACCEPT
    with `verification_refs=()` -- zero verification requirements must
    NEVER vacuously PASS (the exact invariant `aggregate_outcomes(())`
    already enforces one level down, but the empty-required-SET case
    bypassed that check entirely by never calling it). And a missing
    `mission_id` would silently disable `filter_current_context()`'s
    mission scoping (it treats `mission_id=None` as "no scoping
    requested" -- correct for generic Phase 15.8 callers, but never
    correct for the mission Court path). Both are now hard
    preconditions, checked before any `CourtDecision` is constructed,
    and the previous `required_requirement_ids=()` default is removed
    so a caller must always supply the real set explicitly.

    Phase 15.9.3 closure (items 1-2): tracing this hardened path
    end-to-end found two further scope-integrity gaps. First,
    `required_verification_records[req_id]` was trusted as proof for
    `req_id` purely because of its dict placement -- a record whose
    OWN `requirement_id` field disagreed with the key it was filed
    under still silently counted. Second, aggregation could only ever
    aggregate whichever criterion/category keys happened to be PRESENT
    in the supplied records -- if a requirement genuinely required two
    acceptance criteria and only one had evidence, the aggregate was
    computed over just that one, never detecting the other was
    silently missing.

    Phase 15.9.4 closure: the Phase 15.9.3 fix could still fall back
    to the Phase 15.7 in-process `AcceptanceCriterion` registry, or (if
    that registry had nothing registered either) to whatever records
    happened to exist -- a fail-OPEN condition, since a separately-
    started process that never repopulates that in-memory registry
    would silently accept a weaker verification scope than originally
    intended. This function now REQUIRES an explicit, already-resolved
    `RequiredVerificationScope` per required requirement
    (`required_scopes_by_requirement`) and delegates to
    `orca.mission.verification_aggregation.evaluate_requirement_
    completion_for_mission()` (also used by `orca.mission
    .mission_verification_gate`, Phase 15.9.4 closure item 9's single
    central truth rule) -- there is no code path left here that
    consults the in-process registry or infers scope from whatever
    records happen to be present. A required requirement with no entry
    in `required_scopes_by_requirement` raises
    `CourtConfigurationError` immediately, before any `CourtDecision`
    is constructed -- unknown expected scope fails closed."""
    if not mission_id:
        raise CourtConfigurationError(
            "arbiter_decide() requires a non-empty mission_id for the mission Court "
            "path -- a missing/empty mission_id would disable cross-mission filtering "
            "inside filter_current_context() (Phase 15.9.2 closure item 2)."
        )
    if not revision:
        raise CourtConfigurationError(
            "arbiter_decide() requires a non-empty revision -- a missing/empty "
            "revision would disable stale-evidence filtering inside "
            "filter_current_context() (Phase 15.9.2 closure item 3)."
        )
    if not required_requirement_ids:
        raise CourtConfigurationError(
            "arbiter_decide() requires a non-empty required_requirement_ids -- an "
            "empty required set would let a critic-only ACCEPT proceed with zero "
            "verification basis (Phase 15.9.2 closure item 1)."
        )
    missing_scopes = [rid for rid in required_requirement_ids if rid not in required_scopes_by_requirement]
    if missing_scopes:
        raise CourtConfigurationError(
            f"arbiter_decide() has no explicit RequiredVerificationScope for: "
            f"{missing_scopes!r} -- an unknown expected verification scope must never "
            f"be silently inferred from the AcceptanceCriterion registry or from "
            f"whatever records happen to exist (Phase 15.9.4 closure)."
        )

    roles_invoked = tuple(c.role for c in critic_outputs)
    findings_considered = tuple(f.finding_id for f in findings)

    if owner_approval_required:
        return CourtDecision(
            decision_id=_did(), mission_id=mission_id, revision=revision, risk_level=risk_level,
            roles_invoked=roles_invoked, findings_considered=findings_considered, verification_refs=(),
            reasoning_summary="Owner approval is genuinely required for this candidate's scope.",
            verdict=CourtVerdict.HUMAN_APPROVAL_REQUIRED,
        )

    if has_blocking_finding(findings):
        blocking_ids = [f.finding_id for f in findings if f.blocking]
        return CourtDecision(
            decision_id=_did(), mission_id=mission_id, revision=revision, risk_level=risk_level,
            roles_invoked=roles_invoked, findings_considered=findings_considered, verification_refs=(),
            reasoning_summary=f"Blocking anti-gaming finding(s) present: {blocking_ids!r} -- cannot ACCEPT "
                              f"regardless of critic conclusions.",
            verdict=CourtVerdict.REJECT,
        )

    outcomes: dict[str, VerificationOutcome] = {}
    verification_refs: list[str] = []
    for req_id in required_requirement_ids:
        records = required_verification_records.get(req_id, ())
        scope = required_scopes_by_requirement[req_id]
        outcome, contributing = evaluate_requirement_completion_for_mission(
            records, requirement_id=req_id, current_revision=revision, mission_id=mission_id,
            required_scope=scope,
        )
        outcomes[req_id] = outcome
        if outcome is VerificationOutcome.PASS:
            verification_refs.extend(r.id for r in contributing)

    not_pass = {rid: o for rid, o in outcomes.items() if o is not VerificationOutcome.PASS}
    if not_pass:
        not_pass_summary = {rid: o.value for rid, o in not_pass.items()}
        return CourtDecision(
            decision_id=_did(), mission_id=mission_id, revision=revision, risk_level=risk_level,
            roles_invoked=roles_invoked, findings_considered=findings_considered, verification_refs=(),
            reasoning_summary=f"Required verification not PASS for: {not_pass_summary!r} (revision "
                              f"{revision!r}, mission {mission_id!r}) -- cannot ACCEPT as COMPLETED_VERIFIED.",
            verdict=CourtVerdict.NEED_MORE_EVIDENCE,
        )

    opinions = [c for c in critic_outputs if c.conclusion is not CriticConclusion.NOT_REQUIRED]
    supports_reject = [c for c in opinions if c.conclusion is CriticConclusion.SUPPORTS_REJECT]
    needs_evidence = [c for c in opinions if c.conclusion is CriticConclusion.NEEDS_MORE_EVIDENCE]
    supports_accept = [c for c in opinions if c.conclusion is CriticConclusion.SUPPORTS_ACCEPT]

    if supports_reject and supports_accept and risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        return CourtDecision(
            decision_id=_did(), mission_id=mission_id, revision=revision, risk_level=risk_level,
            roles_invoked=roles_invoked, findings_considered=findings_considered, verification_refs=(),
            reasoning_summary=f"Critics disagree at {risk_level.value} risk: "
                              f"{[c.role.value for c in supports_reject]!r} REJECT vs "
                              f"{[c.role.value for c in supports_accept]!r} ACCEPT -- escalating rather than averaging.",
            verdict=CourtVerdict.ESCALATE,
        )

    if supports_reject:
        return CourtDecision(
            decision_id=_did(), mission_id=mission_id, revision=revision, risk_level=risk_level,
            roles_invoked=roles_invoked, findings_considered=findings_considered, verification_refs=(),
            reasoning_summary=f"Critic(s) {[c.role.value for c in supports_reject]!r} support REJECT.",
            verdict=CourtVerdict.REJECT,
        )

    if needs_evidence:
        return CourtDecision(
            decision_id=_did(), mission_id=mission_id, revision=revision, risk_level=risk_level,
            roles_invoked=roles_invoked, findings_considered=findings_considered, verification_refs=(),
            reasoning_summary=f"Critic(s) {[c.role.value for c in needs_evidence]!r} need more evidence.",
            verdict=CourtVerdict.NEED_MORE_EVIDENCE,
        )

    if not opinions:
        return CourtDecision(
            decision_id=_did(), mission_id=mission_id, revision=revision, risk_level=risk_level,
            roles_invoked=roles_invoked, findings_considered=findings_considered, verification_refs=(),
            reasoning_summary="No critic opinions were supplied -- insufficient factual basis for ACCEPT.",
            verdict=CourtVerdict.NEED_MORE_EVIDENCE,
        )

    return CourtDecision(
        decision_id=_did(), mission_id=mission_id, revision=revision, risk_level=risk_level,
        roles_invoked=roles_invoked, findings_considered=findings_considered,
        verification_refs=tuple(verification_refs),
        reasoning_summary=f"All {len(opinions)} critic(s) support ACCEPT, no blocking finding, "
                          f"all required verification PASS (mission={mission_id!r}, revision={revision!r}, "
                          f"verification_refs={verification_refs!r}).",
        verdict=CourtVerdict.ACCEPT,
    )
