"""
Memory deletion cascade + derived-memory re-evaluation (Phase 5 spec
§38-39). Two distinct operations:

  delete_scope() -- full right-to-delete cascade for a scope (extends
  orca/serve/account_delete.py's existing real cross-store deletion,
  never replaces it -- see docs/orneur/phase-5/FORGETTING.md).

  delete_episode_and_reevaluate() -- deletes ONE episode (a
  privacy-safe tombstone, not a silent removal) and re-checks every
  semantic memory that cited it: if no other episode or evidence still
  supports the claim, the memory is archived (never silently kept as if
  nothing happened); if other support remains, the memory survives with
  the dangling source_ref removed.
"""
from __future__ import annotations

from orca.memory import episodic
from orca.memory import store as memory_store
from orca.memory.arbiter import record_decision
from orca.memory.contracts import EpistemicState, MemoryDecision, MemoryLifecycleState, MemoryScope, MemoryType


def delete_scope(scope: MemoryScope, scope_id: str) -> dict:
    """Full Memory Continuum deletion for one scope. Returns a report,
    not just success=True (same discipline as orca/serve/account_delete.py's
    own delete_account())."""
    episodic_deleted = episodic.delete_ledger(scope, scope_id)
    typed_counts = memory_store.delete_scope(scope, scope_id)
    return {"scope": scope.value, "scope_id": scope_id, "episodic_ledger_deleted": episodic_deleted, "typed_records_deleted": typed_counts}


def delete_episode_and_reevaluate(scope: MemoryScope, scope_id: str, episode_memory_id: str) -> list[MemoryDecision]:
    """Spec §39's exact scenario: deleting one supporting episode does
    NOT blindly delete every semantic memory derived from it -- each
    affected record is re-checked against its REMAINING support."""
    if not episodic.delete_episode(scope, scope_id, episode_memory_id):
        return []

    decisions: list[MemoryDecision] = []
    for record in memory_store.list_records(MemoryType.SEMANTIC, scope, scope_id):
        if episode_memory_id not in record.source_refs:
            continue
        remaining_refs = [r for r in record.source_refs if r != episode_memory_id]
        still_supported = bool(remaining_refs) or bool(record.evidence_refs)
        record.source_refs = remaining_refs

        if not still_supported:
            record.lifecycle_state = MemoryLifecycleState.ARCHIVED
            record.epistemic_state = EpistemicState.UNVERIFIED
            decisions.append(record_decision(
                "ARCHIVE", record.memory_id,
                f"sole supporting episode {episode_memory_id} deleted; no remaining source episode or evidence",
            ))
        else:
            decisions.append(record_decision(
                "DOWNGRADE_SOURCE_REFS", record.memory_id,
                f"episode {episode_memory_id} deleted; {len(remaining_refs)} source episode(s) and "
                f"{len(record.evidence_refs)} evidence ref(s) still support this memory",
            ))
        memory_store.save(record)
    return decisions
