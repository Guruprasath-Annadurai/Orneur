"""
Proposal-only objects (spec sections 8.5-8.7): ActionIntent,
VerificationContract, EscalationRequest. Every one of these represents a
REQUEST, never a grant, decision, or verified fact. None of these types
carries -- and the compiler (compiler.py) actively rejects -- any field
that could be mistaken for authority (see enums.py's forbidden-construct
check and errors.ForbiddenAuthorityConstruct).

Execution, verification, and escalation routing all remain governed by the
existing deterministic Phase 15/16 systems (orca.godmode, orca.mission,
orca.society) -- OCL objects are inputs those systems may choose to
consult, never a bypass around them.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActionIntent:
    """Represents proposed work only. Deliberately has NO authority-bearing
    field of any kind -- not even a boolean that defaults to False. An
    ActionIntent cannot execute; it can only be read by the existing
    Mission/Policy/Authority path (orca.agent.policy, orca.mission), which
    decides independently whether to act on it."""
    intent_id: str
    proposed_capability: str
    target_reference: str | None = None
    arguments_summary: dict = field(default_factory=dict)
    rationale_atom_refs: tuple[str, ...] = field(default_factory=tuple)
    expected_effect: str = ""
    preconditions: tuple[str, ...] = field(default_factory=tuple)
    verification_requirement_refs: tuple[str, ...] = field(default_factory=tuple)
    risk_hints: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VerificationContract:
    """What would establish or falsify a claim/proposal -- a REQUEST/
    CONTRACT, never a `orca.mission.verification.VerificationRecord`
    itself. Only a real VerificationRecord (produced by the existing
    deterministic verification path) counts as verification truth."""
    contract_id: str
    target_atom_ref: str
    required_evidence_kinds: tuple[str, ...] = field(default_factory=tuple)
    proposed_test: str = ""
    pass_conditions: tuple[str, ...] = field(default_factory=tuple)
    fail_conditions: tuple[str, ...] = field(default_factory=tuple)
    verification_scope_ref: str | None = None
    status: str = "UNRESOLVED"  # UNRESOLVED is the only status OCL itself may set


@dataclass(frozen=True)
class EscalationRequest:
    """A cognitive request for deeper intelligence. Phase 17 does not
    decide routing -- the Phase 20 router may later consume this. The
    model cannot choose its own authority, cost budget, or destination."""
    escalation_id: str
    triggering_atom_refs: tuple[str, ...] = field(default_factory=tuple)
    reason_categories: tuple[str, ...] = field(default_factory=tuple)
    unresolved_conflict_refs: tuple[str, ...] = field(default_factory=tuple)
    requested_capability_type: str = ""
    evidence_deficit: str = ""
    requested_cognitive_role: str | None = None  # advisory only, e.g. "REASONER" -- not a router command
