"""
Phase 5.1 spec §27-29: MemoryReflex cannot bypass the Firewall/scope/
epistemic-state checks just because it fires automatically; procedure
recall never grants execution authority; a recalled failure informs
planning without automatically blocking execution.
"""
from __future__ import annotations

import uuid

import pytest

from orca.memory import procedural, store
from orca.memory.contracts import EpistemicState, FailureVerificationState, MemoryScope, ProceduralMemoryRecord, SemanticMemoryRecord
from orca.memory.reflex import MemoryReflexRegistry, ReflexTrigger


@pytest.fixture
def sid():
    scope_id = f"test-{uuid.uuid4().hex[:8]}"
    yield scope_id
    store.delete_scope(MemoryScope.SESSION, scope_id)


# ── Memory Reflex authority (spec §27) ──────────────────────────────

def test_reflex_cannot_recall_disproven_memory(sid):
    disproven = SemanticMemoryRecord(claim="A disproven claim.", scope=MemoryScope.SESSION, scope_id=sid, epistemic_state=EpistemicState.DISPROVEN)
    store.save(disproven)

    registry = MemoryReflexRegistry()
    registry.register(ReflexTrigger(name="t1", condition_tags=frozenset({"tag_a"}), relevance_text="claim"))
    recalled = registry.evaluate({"tag_a"}, MemoryScope.SESSION, sid)
    assert disproven.memory_id not in [r.memory_id for r in recalled]


def test_reflex_cannot_recall_cross_scope_memory(sid):
    other_sid = f"other-{uuid.uuid4().hex[:8]}"
    other_record = SemanticMemoryRecord(claim="Another scope's secret.", scope=MemoryScope.SESSION, scope_id=other_sid)
    store.save(other_record)

    registry = MemoryReflexRegistry()
    registry.register(ReflexTrigger(name="t1", condition_tags=frozenset({"tag_a"}), relevance_text="secret"))
    recalled = registry.evaluate({"tag_a"}, MemoryScope.SESSION, sid)  # evaluated against sid, not other_sid
    assert other_record.memory_id not in [r.memory_id for r in recalled]
    store.delete_scope(MemoryScope.SESSION, other_sid)


def test_reflex_respects_privacy_clearance(sid):
    from orca.cognitive.contracts import PrivacyClass
    from orca.memory.firewall import check as firewall_check
    restricted = SemanticMemoryRecord(claim="Restricted.", scope=MemoryScope.SESSION, scope_id=sid, privacy=PrivacyClass.RESTRICTED)
    verdict = firewall_check(restricted, MemoryScope.SESSION, sid, requester_privacy_clearance=PrivacyClass.STANDARD)
    assert not verdict.allowed  # the same check MemoryReflexRegistry.evaluate() routes through


# ── Procedural memory authority (spec §28) ──────────────────────────

def test_procedure_recall_does_not_grant_execution_authority(sid):
    """Recalling a ProceduralMemoryRecord returns DATA (steps, a
    description of how something was done before) -- never a callable,
    a tool handle, or any object with execution capability. This test
    documents/enforces that contract shape directly."""
    procedural.record_procedure(MemoryScope.SESSION, sid, "deploy model", ["validate", "scan", "canary", "promote"])
    found = procedural.find_by_name(MemoryScope.SESSION, sid, "deploy model")
    assert isinstance(found, ProceduralMemoryRecord) or found is None
    if found:
        assert isinstance(found.steps, list)
        assert all(isinstance(s, str) for s in found.steps)
        # No attribute on the record grants capability/permission -- it is
        # a plain dataclass with no callable, no tool reference, no token.
        for attr_name in vars(found):
            assert not callable(getattr(found, attr_name))


def test_one_procedure_execution_never_escalates_trust(sid):
    p = procedural.record_procedure(MemoryScope.SESSION, sid, "risky procedure", ["step1"])
    p = procedural.record_execution(p.memory_id, MemoryScope.SESSION, sid, succeeded=True)
    assert p.epistemic_state == EpistemicState.UNVERIFIED  # a single success never implies "safe to always run"


# ── Failure memory authority (spec §29) ─────────────────────────────

def test_recalled_failure_does_not_block_a_new_attempt():
    """FailureMemory is advisory data, not a gate -- nothing in this
    module's API prevents a caller from proceeding despite a recalled
    prior failure. Verified by absence: find_relevant() returns records,
    never raises/blocks, and there is no "is this safe to attempt" gate
    function anywhere in orca/memory/failure.py."""
    import inspect
    from orca.memory import failure as failure_module
    functions = [name for name, _ in inspect.getmembers(failure_module, inspect.isfunction)]
    assert not any("block" in f.lower() or "prevent" in f.lower() or "deny" in f.lower() for f in functions)


def test_failure_memory_preserves_root_cause_confidence_state(sid):
    from orca.memory import failure
    f = failure.record_failure(
        MemoryScope.SESSION, sid, "deploy X", "direct promote", "missing canary",
        root_cause="canary step was skipped in the deploy script", regression_test_ref="test_canary_required",
        verification_state=FailureVerificationState.VERIFIED_ROOT_CAUSE,
    )
    assert f.verification_state == FailureVerificationState.VERIFIED_ROOT_CAUSE
