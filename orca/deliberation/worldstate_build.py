"""
Builds a request-scoped WorldState from real, already-produced sources
(Phase 7 spec §28): the current TruthResult's supported claims, and the
active hypothesis set. Deliberately does not invent a memory-recall path
of its own -- WorkingMemory/SemanticMemory integration remains exactly
Phase 5.1's existing Firewall-gated recall, unchanged (see
docs/orneur/phase-7/WORLD_STATE.md's honest scope note).
"""
from __future__ import annotations

from typing import Any

from orca.deliberation.contracts import HypothesisSet, WorldState
from orca.deliberation.worldstate_ops import WorldStateOp, WorldStateUpdate, apply_update


def build_world_state(objective: str, truth_result: Any = None, hypotheses: HypothesisSet | None = None) -> WorldState:
    state = WorldState()
    state.constraints.append(f"objective: {objective}")

    if truth_result is not None:
        claim_supports = {cs.claim_id: cs for cs in getattr(truth_result, "claim_supports", []) or []}
        for claim in getattr(truth_result, "claims", []) or []:
            support = claim_supports.get(claim.claim_id)
            if support is None:
                continue
            source_ref = (support.evidence_ids or ["truth_fabric"])[0]
            apply_update(
                state,
                WorldStateUpdate(op=WorldStateOp.ADD_FACT, value=claim.text, source_ref=f"evidence:{source_ref}"),
            )

    if hypotheses is not None:
        for hyp in hypotheses.hypotheses:
            apply_update(
                state,
                WorldStateUpdate(
                    op=WorldStateOp.UPDATE_ENTITY_STATE,
                    entity=hyp.hypothesis_id,
                    value=f"{hyp.statement} [status={hyp.status.value}]",
                    source_ref=f"hypothesis:{hyp.hypothesis_id}",
                ),
            )

    return state
