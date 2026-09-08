"""
Phase 15.7 -- the assumption/unknown/fact model (spec section 3).

Reuses the exact four states the Phase 15.2 `assumptions` table's own
CHECK constraint already defines (`orca/mission/schema.py`:
`CHECK (state IN ('VERIFIED', 'UNVERIFIED', 'UNKNOWN', 'CONTESTED'))`)
-- this module does not invent a new state vocabulary, it enforces
the hard invariants around the one that already exists in the durable
schema, ahead of Phase 16's fuller Epistemic State Machine (explicitly
NOT claimed to be built here).

Hard invariants enforced structurally, not just documented:
  - VERIFIED requires a non-empty evidence_ref (mirrors
    orca.mission.requirements.transition()'s own VERIFIED gate).
  - A caller cannot construct a Fact directly in the VERIFIED state --
    every Fact starts UNVERIFIED, UNKNOWN, or CONTESTED, and only
    `verify()` (which demands evidence) can move it to VERIFIED. This
    is the concrete mechanism behind "a model cannot mark its own
    assumption VERIFIED merely by proposing an answer" (spec section
    3/11): a `provenance=INFERRED_ASSUMPTION` Fact can be
    *constructed* at UNVERIFIED, but nothing in this module lets an
    inferred fact self-promote to VERIFIED without a real evidence_ref
    supplied by the caller (which Phase 15.7's own idea compiler never
    does on a model's behalf).
  - CONTESTED preserves competing statements rather than picking one
    -- `contest()` appends to `competing_statements`, it never
    silently overwrites `statement`.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum

from orca.mission.provenance import SourceProvenance


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FactState(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"
    CONTESTED = "CONTESTED"


class FactError(Exception):
    pass


@dataclass(frozen=True)
class Fact:
    """A typed assumption/unknown/fact record (spec section 3),
    linked to a ProductContract or Mission. Matches the shape of the
    existing `assumptions` table's columns (id/mission_id/statement/
    state/created_at/updated_at) plus the fields Phase 15.7 adds:
    contract linkage, provenance, evidence_ref, and (for CONTESTED)
    competing_statements."""
    id: str
    contract_id: str | None
    mission_id: str | None
    statement: str
    state: FactState
    provenance: SourceProvenance
    created_at: str
    updated_at: str
    evidence_ref: str | None = None
    competing_statements: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise FactError(f"{self.id}: statement must not be empty.")
        if self.state is FactState.VERIFIED and not (self.evidence_ref or "").strip():
            raise FactError(
                f"{self.id}: VERIFIED requires a non-empty evidence_ref -- "
                f"a model/provider cannot mark its own assumption VERIFIED by proposing an answer."
            )
        if self.state is FactState.CONTESTED and not self.competing_statements:
            raise FactError(
                f"{self.id}: CONTESTED requires at least one competing_statement -- "
                f"a contested fact must preserve the disagreement, not silently pick one side."
            )


_REGISTRY: dict[str, Fact] = {}


def reset_registry_for_tests() -> None:
    _REGISTRY.clear()


def record_fact(
    *,
    id: str,
    statement: str,
    state: FactState,
    provenance: SourceProvenance,
    contract_id: str | None = None,
    mission_id: str | None = None,
    evidence_ref: str | None = None,
    competing_statements: tuple[str, ...] = (),
) -> Fact:
    if state is FactState.VERIFIED:
        raise FactError(
            f"{id}: a Fact cannot be CONSTRUCTED directly as VERIFIED -- "
            f"record it UNVERIFIED/UNKNOWN/CONTESTED first, then call verify() with real evidence."
        )
    now = _now_iso()
    fact = Fact(
        id=id, contract_id=contract_id, mission_id=mission_id, statement=statement,
        state=state, provenance=provenance, created_at=now, updated_at=now,
        evidence_ref=evidence_ref, competing_statements=competing_statements,
    )
    if id in _REGISTRY:
        raise FactError(f"{id} is already registered.")
    _REGISTRY[id] = fact
    return fact


def get_fact(fact_id: str) -> Fact:
    try:
        return _REGISTRY[fact_id]
    except KeyError:
        raise FactError(f"No such fact: {fact_id}") from None


def facts_for_contract(contract_id: str) -> tuple[Fact, ...]:
    return tuple(f for f in _REGISTRY.values() if f.contract_id == contract_id)


def verify(fact_id: str, *, evidence_ref: str) -> Fact:
    """The ONLY path to FactState.VERIFIED. Requires a real,
    non-empty evidence_ref supplied by the CALLER (never inferred by
    this module) -- structurally prevents "a model proposes an
    answer" from ever becoming a verified fact."""
    if not (evidence_ref or "").strip():
        raise FactError(f"{fact_id}: verify() requires a non-empty evidence_ref.")
    current = get_fact(fact_id)
    updated = replace(current, state=FactState.VERIFIED, evidence_ref=evidence_ref, updated_at=_now_iso())
    _REGISTRY[fact_id] = updated
    return updated


def contest(fact_id: str, *, competing_statement: str) -> Fact:
    """Preserves the disagreement -- appends to competing_statements,
    never overwrites the original statement or silently resolves in
    either direction."""
    if not competing_statement.strip():
        raise FactError(f"{fact_id}: contest() requires a non-empty competing_statement.")
    current = get_fact(fact_id)
    updated = replace(
        current,
        state=FactState.CONTESTED,
        competing_statements=current.competing_statements + (competing_statement,),
        updated_at=_now_iso(),
    )
    _REGISTRY[fact_id] = updated
    return updated
