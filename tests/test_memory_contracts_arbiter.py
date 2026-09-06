"""
Phase 5: memory contracts, episodic ledger, MemoryArbiter (duplicate
detection, contradiction coexistence, temporal supersession), entity/
procedural/failure memory. Deterministic -- no Ollama dependency.
"""
from __future__ import annotations

import uuid

import pytest

from orca.memory import entity, episodic, failure, procedural, store
from orca.memory.arbiter import MemoryArbiter
from orca.memory.candidates import extract_candidates
from orca.memory.contracts import (
    ContradictionResolution,
    DuplicateClassification,
    EpistemicState,
    FailureVerificationState,
    MemoryCandidate,
    MemoryEpisode,
    MemoryEvidence,
    MemoryScope,
    PromotionDecision,
    SemanticMemoryRecord,
)
from orca.memory.significance import assess_significance


@pytest.fixture
def sid():
    scope_id = f"test-{uuid.uuid4().hex[:8]}"
    yield scope_id
    episodic.delete_ledger(MemoryScope.SESSION, scope_id)
    store.delete_scope(MemoryScope.SESSION, scope_id)


# ── Significance filter ───────────────────────────────────────────────

def test_casual_chatter_is_not_significant():
    is_sig, signals = assess_significance("hey, how's it going today?")
    assert not is_sig
    assert signals == []


def test_explicit_remember_request_is_significant():
    is_sig, signals = assess_significance("Please remember that our staging DB is on port 5433.")
    assert is_sig
    assert "explicit_remember_request" in signals


def test_failure_language_is_significant():
    is_sig, signals = assess_significance("That deployment failed with a root cause of a missing config flag.")
    assert is_sig
    assert "failure_signal" in signals


# ── Episodic ledger ──────────────────────────────────────────────────

def test_episodic_ledger_is_append_only_and_idempotent(sid):
    ep = MemoryEpisode(scope=MemoryScope.SESSION, scope_id=sid, event="user asked to remember X", outcome="stored")
    r1 = episodic.append_episode(ep)
    r2 = episodic.append_episode(ep)
    assert r1.memory_id == r2.memory_id
    assert len(episodic.list_episodes(MemoryScope.SESSION, sid)) == 1

    ep2 = MemoryEpisode(scope=MemoryScope.SESSION, scope_id=sid, event="user corrected X", outcome="stored correction")
    episodic.append_episode(ep2)
    all_eps = episodic.list_episodes(MemoryScope.SESSION, sid)
    assert len(all_eps) == 2  # the correction is a NEW linked record, not a rewrite of the original


def test_candidate_extraction_from_episode(sid):
    ep = MemoryEpisode(scope=MemoryScope.SESSION, scope_id=sid, event="Project Atlas uses PostgreSQL for storage", outcome="")
    candidates = extract_candidates(ep)
    assert candidates
    assert candidates[0].source_episode_id == ep.memory_id
    assert "PostgreSQL" in candidates[0].entities or "Atlas" in candidates[0].entities


# ── MemoryArbiter: duplicate detection ──────────────────────────────

def test_identical_candidate_is_rejected(sid):
    arbiter = MemoryArbiter()
    c1 = MemoryCandidate(extracted_claim="The API rate limit is 100 requests per minute.", scope=MemoryScope.SESSION, scope_id=sid)
    rec1 = arbiter.promote(c1)
    existing = store.list_records(rec1.memory_type, MemoryScope.SESSION, sid)

    c2 = MemoryCandidate(extracted_claim="The API rate limit is 100 requests per minute.", scope=MemoryScope.SESSION, scope_id=sid)
    decision, reasons = arbiter.decide_promotion(c2, existing)
    assert decision == PromotionDecision.REJECTED


def test_conflicting_numeric_claim_is_not_misclassified_as_identical(sid):
    """Regression: 'rate limit is 100' vs 'rate limit is 500' score a
    very high SequenceMatcher ratio (one digit differs) -- must be
    POTENTIAL_CONFLICT, never IDENTICAL/NEAR_DUPLICATE (which would
    silently drop a real contradiction)."""
    arbiter = MemoryArbiter()
    c1 = MemoryCandidate(extracted_claim="The API rate limit is 100 requests per minute.", entities=["API"], scope=MemoryScope.SESSION, scope_id=sid)
    rec1 = arbiter.promote(c1)
    existing = store.list_records(rec1.memory_type, MemoryScope.SESSION, sid)

    c2 = MemoryCandidate(extracted_claim="The API rate limit is 500 requests per minute.", entities=["API"], scope=MemoryScope.SESSION, scope_id=sid)
    dup, classification = arbiter.find_duplicate(c2, existing)
    assert classification == DuplicateClassification.POTENTIAL_CONFLICT
    assert dup.memory_id == rec1.memory_id


def test_contradictory_memories_coexist_not_overwritten(sid):
    """Spec §17: never simply choose the newest string -- both records
    must remain retrievable after a conflict is detected."""
    arbiter = MemoryArbiter()
    c1 = MemoryCandidate(extracted_claim="The API rate limit is 100 requests per minute.", entities=["API"], scope=MemoryScope.SESSION, scope_id=sid)
    rec1 = arbiter.promote(c1)
    existing = store.list_records(rec1.memory_type, MemoryScope.SESSION, sid)

    c2 = MemoryCandidate(extracted_claim="The API rate limit is 500 requests per minute.", entities=["API"], scope=MemoryScope.SESSION, scope_id=sid)
    dup, _ = arbiter.find_duplicate(c2, existing)
    decision, reasons = arbiter.decide_promotion(c2, existing)
    assert decision == PromotionDecision.PROMOTED
    rec2 = arbiter.promote(c2, conflicting=dup)

    all_records = store.list_records(rec1.memory_type, MemoryScope.SESSION, sid)
    assert len(all_records) == 2  # both survive
    assert rec2.memory_id in dup.contradicts or dup.memory_id in rec2.contradicts


def test_truth_fabric_relationship_is_preserved_not_rederived(sid):
    """Spec §12: when the candidate's own evidence already carries a
    Truth Fabric contradiction relationship, MemoryArbiter uses it
    directly rather than re-deriving its own verdict."""
    arbiter = MemoryArbiter()
    existing_record = SemanticMemoryRecord(claim="The limit was 100 as of March.", scope=MemoryScope.SESSION, scope_id=sid)
    candidate = MemoryCandidate(
        extracted_claim="The limit is 500 as of September.", scope=MemoryScope.SESSION, scope_id=sid,
        evidence_refs=[MemoryEvidence(note="truth_relationship:TEMPORALLY_RECONCILABLE")],
    )
    resolution = arbiter.resolve_contradiction(candidate, existing_record)
    assert resolution == ContradictionResolution.TEMPORAL_CHANGE


# ── Temporal supersession ───────────────────────────────────────────

def test_supersede_never_deletes_the_old_record(sid):
    old = SemanticMemoryRecord(claim="System uses Model A.", scope=MemoryScope.SESSION, scope_id=sid, valid_from="2026-01-01T00:00:00Z")
    new = SemanticMemoryRecord(claim="System uses Model B.", scope=MemoryScope.SESSION, scope_id=sid, valid_from="2026-08-01T00:00:00Z")
    store.save(old)
    arbiter = MemoryArbiter()
    arbiter.supersede(old, new)

    reloaded_old = store.load(old.memory_type, MemoryScope.SESSION, sid, old.memory_id)
    reloaded_new = store.load(new.memory_type, MemoryScope.SESSION, sid, new.memory_id)
    assert reloaded_old is not None  # old record still exists, not deleted
    assert reloaded_old.superseded_by == new.memory_id
    assert reloaded_old.valid_to == "2026-08-01T00:00:00Z"
    assert reloaded_new.supersedes == old.memory_id

    # "What did we use before August?" is answerable
    all_records = store.list_records(old.memory_type, MemoryScope.SESSION, sid)
    before_august = [r for r in all_records if r.valid_from and r.valid_from < "2026-08-01T00:00:00Z"]
    assert len(before_august) == 1
    assert before_august[0].claim == "System uses Model A."


# ── Entity / procedural / failure memory ────────────────────────────

def test_entity_memory_links_by_reference_not_blob(sid):
    e1 = entity.link_semantic(MemoryScope.SESSION, sid, "PostgreSQL", "mem-sem-1", entity_kind="technology")
    e2 = entity.link_episode(MemoryScope.SESSION, sid, "PostgreSQL", "mem-ep-1")
    assert e1.memory_id == e2.memory_id  # same entity, not a duplicate
    assert "mem-sem-1" in e2.semantic_memory_ids
    assert "mem-ep-1" in e2.episode_ids


def test_procedural_memory_execution_never_treated_as_universal(sid):
    p = procedural.record_procedure(MemoryScope.SESSION, sid, "deploy model", ["validate", "scan", "canary", "promote"])
    p = procedural.record_execution(p.memory_id, MemoryScope.SESSION, sid, succeeded=True)
    assert p.successful_executions == 1
    assert p.epistemic_state == EpistemicState.UNVERIFIED  # one success alone never escalates epistemic state


def test_failure_memory_downgrades_unsubstantiated_claim(sid):
    f = failure.record_failure(
        MemoryScope.SESSION, sid, task_context="deploy X", attempted_strategy="guess",
        failure_mode="unknown", verification_state=FailureVerificationState.VERIFIED_ROOT_CAUSE,
    )
    # Claimed VERIFIED_ROOT_CAUSE without root_cause+regression_test_ref -- downgraded, not trusted at face value
    assert f.verification_state != FailureVerificationState.VERIFIED_ROOT_CAUSE


def test_failure_memory_relevant_recall(sid):
    failure.record_failure(MemoryScope.SESSION, sid, "deploy Novus to production", "direct promote", "canary skipped")
    failure.record_failure(MemoryScope.SESSION, sid, "unrelated database migration", "manual script", "typo in SQL")
    hits = failure.find_relevant(MemoryScope.SESSION, sid, "deploying Novus production canary")
    assert hits
    assert "novus" in hits[0].task_context.lower()
