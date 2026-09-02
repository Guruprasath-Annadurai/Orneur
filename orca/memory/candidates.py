"""
MemoryCandidate pipeline (Phase 5 spec §10). New information is NEVER
promoted straight to a trusted SemanticMemoryRecord -- it becomes a
MemoryCandidate first, and MemoryArbiter (arbiter.py) makes the explicit
promotion decision.

Pipeline: experience -> candidate extraction -> entity identification ->
duplicate detection -> contradiction detection -> temporal analysis ->
scope/privacy classification -> promotion decision (delegated to
MemoryArbiter, not decided here).
"""
from __future__ import annotations

from orca.cognitive.contracts import PrivacyClass
from orca.memory.contracts import MemoryCandidate, MemoryEpisode, MemoryEvidence, MemoryScope

# Bounded -- an episode's event/outcome/actions text is naturally short
# (these come from significance-filtered turns, not raw transcripts), so
# a hard cap here is a safety net, not the normal case.
MAX_CANDIDATES_PER_EPISODE = 4


def _naive_entities(text: str) -> list[str]:
    """Deterministic, no Gateway call -- capitalized multi-word spans are
    a cheap, honest heuristic for likely entity mentions (proper nouns),
    not a claim of real NER quality. Reuses the same "floor, not ground
    truth" posture already used for orca/brain/knowledge_graph.py's own
    LLM-based extraction, just cheaper and deterministic for this fast
    per-turn path."""
    import re
    candidates = re.findall(r"\b[A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*)*\b", text)
    seen: list[str] = []
    for c in candidates:
        if c not in seen and len(c) > 1:
            seen.append(c)
    return seen[:10]


def extract_candidates(episode: MemoryEpisode, evidence_refs: list[MemoryEvidence] | None = None) -> list[MemoryCandidate]:
    """Lightweight, deterministic extraction from an already
    significance-filtered episode -- one candidate per distinct
    sentence-like unit in event+outcome, bounded. Higher-fidelity
    Gateway-routed extraction (reusing orca.truth.claims.extract_atomic_claims)
    is available via extract_candidates_via_gateway() below for callers
    that can afford the extra latency (e.g. explicit "remember this"
    requests), matching the project's existing tiered-cost pattern rather
    than always paying for the expensive path."""
    text = f"{episode.event} {episode.outcome}".strip()
    if not text:
        return []
    sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    candidates = []
    for sentence in sentences[:MAX_CANDIDATES_PER_EPISODE]:
        candidates.append(MemoryCandidate(
            source_episode_id=episode.memory_id,
            extracted_claim=sentence,
            entities=_naive_entities(sentence),
            evidence_refs=list(evidence_refs or []),
            scope=episode.scope,
            scope_id=episode.scope_id,
            privacy=episode.privacy,
        ))
    return candidates


async def extract_candidates_via_gateway(episode: MemoryEpisode, evidence_refs: list[MemoryEvidence] | None = None, tier: str | None = None) -> list[MemoryCandidate]:
    """Gateway-routed variant, reusing orca.truth.claims.extract_atomic_claims
    (already tested, already Gateway-routed) rather than a second,
    parallel claim-extraction implementation. Used for episodes worth the
    extra latency -- explicit remember requests, decisions, failures --
    not the default per-turn path.

    Not currently called by any production code path (verified -- no
    caller exists in orca/ or tests/ as of Phase 7.1); documented honestly
    as unwired in docs/orneur/phase-7/ROLE_MIGRATION.md rather than left
    silently on a hardcoded tier. `tier=None` (the default) resolves
    through Model Society's MEMORY_SELECTOR role for whenever this
    function is eventually wired in; an explicit `tier` bypasses Society
    (LEGACY_COMPATIBILITY)."""
    from orca.society.contracts import CognitiveRole
    from orca.society.router import resolve_tier_for_role
    from orca.truth.claims import extract_atomic_claims

    resolved_tier, _decision = resolve_tier_for_role(CognitiveRole.MEMORY_SELECTOR, override_tier=tier)

    text = f"{episode.event} {episode.outcome}".strip()
    if not text:
        return []
    atomic_claims = await extract_atomic_claims(text, tier=resolved_tier)
    candidates = []
    for claim in atomic_claims[:MAX_CANDIDATES_PER_EPISODE]:
        candidates.append(MemoryCandidate(
            source_episode_id=episode.memory_id,
            extracted_claim=claim.text,
            entities=_naive_entities(claim.text),
            evidence_refs=list(evidence_refs or []),
            scope=episode.scope,
            scope_id=episode.scope_id,
            privacy=episode.privacy,
        ))
    return candidates
