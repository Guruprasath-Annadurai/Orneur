"""
ProceduralMemory (Phase 5 spec §20) -- first production version. "HOW TO
PERFORM A TASK", not an autonomous self-modifying procedure (spec §59):
this module is a retrieval/reference system a caller consults and
updates explicitly, never a system that rewrites its own steps.
"""
from __future__ import annotations

from orca.memory.contracts import MemoryScope, MemoryType, ProceduralMemoryRecord, _now_iso
from orca.memory import store as memory_store


def record_procedure(
    scope: MemoryScope, scope_id: str, name: str, steps: list[str],
    preconditions: list[str] | None = None, postconditions: list[str] | None = None,
) -> ProceduralMemoryRecord:
    record = ProceduralMemoryRecord(
        name=name, steps=steps, preconditions=preconditions or [], postconditions=postconditions or [],
        scope=scope, scope_id=scope_id,
    )
    memory_store.save(record)
    return record


def record_execution(memory_id: str, scope: MemoryScope, scope_id: str, succeeded: bool) -> ProceduralMemoryRecord | None:
    """One execution outcome is never treated as universally valid (spec
    §20) -- it only increments a counter; nothing here escalates
    epistemic_state to KNOWN purely from execution count. A caller
    wanting a stronger state must do so explicitly, informed by its own
    policy (e.g. N consecutive successes)."""
    record = memory_store.load(MemoryType.PROCEDURAL, scope, scope_id, memory_id)
    if record is None:
        return None
    if succeeded:
        record.successful_executions += 1
    else:
        record.failed_executions += 1
    record.last_verified_at = _now_iso()
    memory_store.save(record)
    return record


def find_by_name(scope: MemoryScope, scope_id: str, name: str) -> ProceduralMemoryRecord | None:
    key = name.strip().lower()
    for record in memory_store.list_records(MemoryType.PROCEDURAL, scope, scope_id):
        if record.name.strip().lower() == key:
            return record
    return None


def new_version(old: ProceduralMemoryRecord, steps: list[str]) -> ProceduralMemoryRecord:
    """A changed procedure becomes a NEW version, not a silent overwrite
    of the old one's steps -- preserves what was actually executed
    historically (the old record's successful_executions/
    failed_executions stay attached to the steps that earned them)."""
    new = ProceduralMemoryRecord(
        name=old.name, steps=steps, preconditions=list(old.preconditions), postconditions=list(old.postconditions),
        version=old.version + 1, scope=old.scope, scope_id=old.scope_id, source_refs=[old.memory_id],
    )
    memory_store.save(new)
    return new
