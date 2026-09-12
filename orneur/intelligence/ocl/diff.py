"""
Cognitive Diff (spec section 12; Phase 17 closure section 10) -- a
deterministic STRUCTURAL diff between two CognitiveArtifacts. Detects both
presence changes (added/removed by ID) AND same-ID content modification
(an atom whose ID is unchanged but whose canonical value differs) --
verified against commit ea9426f's `diff.py`, which only ever compared ID
sets and would report NO event at all for "atom a1 content='A'" becoming
"atom a1 content='COMPLETELY DIFFERENT'", a real, reproduced gap this
closure fixes. Never infers semantic/epistemic truth beyond what is
encoded in the artifacts themselves.
"""
from __future__ import annotations

from dataclasses import dataclass

from orneur.intelligence.ocl.artifact import CognitiveArtifact


@dataclass(frozen=True)
class CognitiveDiff:
    from_artifact_id: str
    to_artifact_id: str
    atoms_added: tuple[str, ...]
    atoms_removed: tuple[str, ...]
    atoms_modified: tuple[str, ...]
    relations_added: tuple[str, ...]
    relations_removed: tuple[str, ...]
    relations_modified: tuple[str, ...]
    evidence_added: tuple[str, ...]
    evidence_removed: tuple[str, ...]
    evidence_modified: tuple[str, ...]
    action_intents_added: tuple[str, ...]
    action_intents_removed: tuple[str, ...]
    action_intents_modified: tuple[str, ...]
    verification_contracts_modified: tuple[str, ...]
    escalation_requests_modified: tuple[str, ...]
    causal_hypotheses_modified: tuple[str, ...]
    counterfactual_branches_modified: tuple[str, ...]
    limitations_added: tuple[str, ...]
    limitations_removed: tuple[str, ...]
    provenance_changed: bool


def _added_removed(before: set, after: set) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return tuple(sorted(after - before)), tuple(sorted(before - after))


def _modified_ids(before_by_id: dict, after_by_id: dict) -> tuple[str, ...]:
    """IDs present in BOTH collections whose canonical value differs --
    dataclass equality (field-by-field) is exactly the structural
    comparison this needs, since every OCL type here is itself a frozen,
    canonicalizable dataclass."""
    common = set(before_by_id) & set(after_by_id)
    return tuple(sorted(i for i in common if before_by_id[i] != after_by_id[i]))


def diff(a: CognitiveArtifact, b: CognitiveArtifact) -> CognitiveDiff:
    a_atoms = {x.atom_id: x for x in a.atoms}
    b_atoms = {x.atom_id: x for x in b.atoms}
    atoms_added, atoms_removed = _added_removed(set(a_atoms), set(b_atoms))
    atoms_modified = _modified_ids(a_atoms, b_atoms)

    a_rel = {x.relation_id: x for x in a.relations}
    b_rel = {x.relation_id: x for x in b.relations}
    relations_added, relations_removed = _added_removed(set(a_rel), set(b_rel))
    relations_modified = _modified_ids(a_rel, b_rel)

    a_ev = {x.evidence_id: x for x in a.evidence}
    b_ev = {x.evidence_id: x for x in b.evidence}
    evidence_added, evidence_removed = _added_removed(set(a_ev), set(b_ev))
    evidence_modified = _modified_ids(a_ev, b_ev)

    a_intents = {x.intent_id: x for x in a.action_intents}
    b_intents = {x.intent_id: x for x in b.action_intents}
    intents_added, intents_removed = _added_removed(set(a_intents), set(b_intents))
    intents_modified = _modified_ids(a_intents, b_intents)

    a_contracts = {x.contract_id: x for x in a.verification_contracts}
    b_contracts = {x.contract_id: x for x in b.verification_contracts}
    contracts_modified = _modified_ids(a_contracts, b_contracts)

    a_esc = {x.escalation_id: x for x in a.escalation_requests}
    b_esc = {x.escalation_id: x for x in b.escalation_requests}
    esc_modified = _modified_ids(a_esc, b_esc)

    a_hyp = {x.hypothesis_id: x for x in a.causal_hypotheses}
    b_hyp = {x.hypothesis_id: x for x in b.causal_hypotheses}
    hyp_modified = _modified_ids(a_hyp, b_hyp)

    a_branch = {x.branch_id: x for x in a.counterfactual_branches}
    b_branch = {x.branch_id: x for x in b.counterfactual_branches}
    branch_modified = _modified_ids(a_branch, b_branch)

    limitations_added, limitations_removed = _added_removed(
        set(a.limitation_atom_refs), set(b.limitation_atom_refs)
    )

    return CognitiveDiff(
        from_artifact_id=a.artifact_id,
        to_artifact_id=b.artifact_id,
        atoms_added=atoms_added,
        atoms_removed=atoms_removed,
        atoms_modified=atoms_modified,
        relations_added=relations_added,
        relations_removed=relations_removed,
        relations_modified=relations_modified,
        evidence_added=evidence_added,
        evidence_removed=evidence_removed,
        evidence_modified=evidence_modified,
        action_intents_added=intents_added,
        action_intents_removed=intents_removed,
        action_intents_modified=intents_modified,
        verification_contracts_modified=contracts_modified,
        escalation_requests_modified=esc_modified,
        causal_hypotheses_modified=hyp_modified,
        counterfactual_branches_modified=branch_modified,
        limitations_added=limitations_added,
        limitations_removed=limitations_removed,
        provenance_changed=(a.provenance != b.provenance),
    )
