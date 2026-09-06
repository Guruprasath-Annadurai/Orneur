"""
FailureMemory (Phase 5 spec §21-22). A future similar task should be
able to retrieve relevant prior failure knowledge -- but a permanent
failure memory is never manufactured from an unverified guess (spec
§22): verification_state stays UNVERIFIED unless the caller can supply
an actual root cause, a confirmed regression test, or explicit human
diagnosis.
"""
from __future__ import annotations

from orca.memory.contracts import FailureMemoryRecord, FailureVerificationState, MemoryScope, MemoryType
from orca.memory import store as memory_store


def record_failure(
    scope: MemoryScope, scope_id: str, task_context: str, attempted_strategy: str, failure_mode: str,
    root_cause: str = "", correction: str = "", regression_test_ref: str | None = None,
    verification_state: FailureVerificationState = FailureVerificationState.UNVERIFIED,
) -> FailureMemoryRecord:
    if verification_state == FailureVerificationState.VERIFIED_ROOT_CAUSE and not (root_cause and regression_test_ref):
        # Honest downgrade, never a silent no-op: a caller claiming
        # VERIFIED_ROOT_CAUSE without a root_cause string AND a
        # regression test reference hasn't actually met the bar spec §22
        # requires -- record it as PROBABLE instead of trusting the
        # caller's own label.
        verification_state = FailureVerificationState.PROBABLE if root_cause else FailureVerificationState.UNVERIFIED

    record = FailureMemoryRecord(
        task_context=task_context, attempted_strategy=attempted_strategy, failure_mode=failure_mode,
        root_cause=root_cause, correction=correction, regression_test_ref=regression_test_ref,
        verification_state=verification_state, scope=scope, scope_id=scope_id,
    )
    memory_store.save(record)
    return record


def find_relevant(scope: MemoryScope, scope_id: str, task_context_query: str, limit: int = 5) -> list[FailureMemoryRecord]:
    """Bounded, lexical relevance -- consistent with the rest of this
    phase's "no unbounded scan, no embedding dependency required for a
    correct floor" posture. A future phase can add semantic-similarity
    ranking without changing this function's contract."""
    query_words = {w.lower() for w in task_context_query.split() if len(w) > 2}
    scored = []
    for record in memory_store.list_records(MemoryType.FAILURE, scope, scope_id):
        record_words = {w.lower() for w in record.task_context.split() if len(w) > 2}
        overlap = len(query_words & record_words)
        if overlap > 0:
            scored.append((overlap, record))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [r for _, r in scored[:limit]]
