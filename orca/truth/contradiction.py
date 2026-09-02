"""
Contradiction detection foundation (Phase 4 spec §29). Bounded pairwise
comparison: a lexical pre-filter keeps this from becoming an O(n^2)
Gateway-call explosion over many claims, and the judge prompt explicitly
distinguishes a real contradiction from a temporally-reconcilable pair
("was true, no longer is") or two unrelated true claims -- reusing the
same non-forcing discipline orca/docs/sufficiency.py's existing
detect_contradictions() already established, now Gateway-routed.
"""
from __future__ import annotations

from orca.truth.contracts import AtomicClaim, Contradiction, ContradictionRelationship, Evidence
from orca.truth.llm import gateway_json_call

MAX_PAIRS_CHECKED = 10
_TOPIC_OVERLAP_THRESHOLD = 0.25
MAX_EVIDENCE_PAIRS_CHECKED = 10

_JUDGE_SYSTEM = """\
Compare CLAIM A and CLAIM B ONLY for a direct factual contradiction --
where they assert opposite things about the SAME specific fact.

Do NOT flag as a contradiction:
- Two true claims about different topics
- A claim that was true at one time and a claim that is true now (that is
  TEMPORALLY_RECONCILABLE, not a contradiction -- note it as such)
- Complementary or additional information

Return ONLY JSON:
{"relationship": "DIRECT_CONTRADICTION"|"TEMPORALLY_RECONCILABLE"|"UNRELATED", "temporal_context": "", "reason": "one sentence"}"""


def _topic_overlap(a: str, b: str) -> float:
    words_a = {w.lower() for w in a.split() if len(w) > 3}
    words_b = {w.lower() for w in b.split() if len(w) > 3}
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / min(len(words_a), len(words_b))


def _candidate_pairs(claims: list[AtomicClaim]) -> list[tuple[AtomicClaim, AtomicClaim]]:
    candidates = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            if _topic_overlap(claims[i].text, claims[j].text) >= _TOPIC_OVERLAP_THRESHOLD:
                candidates.append((claims[i], claims[j]))
    # Highest-overlap pairs first, bounded -- never an unbounded scan.
    candidates.sort(key=lambda pair: _topic_overlap(pair[0].text, pair[1].text), reverse=True)
    return candidates[:MAX_PAIRS_CHECKED]


async def detect_contradictions(claims: list[AtomicClaim], tier: str = "nano") -> list[Contradiction]:
    if len(claims) < 2:
        return []

    contradictions: list[Contradiction] = []
    for claim_a, claim_b in _candidate_pairs(claims):
        result = await gateway_json_call(
            f"CLAIM A: {claim_a.text}\n\nCLAIM B: {claim_b.text}", _JUDGE_SYSTEM, tier=tier, max_tokens=150,
        )
        if not isinstance(result, dict):
            continue
        relationship_raw = result.get("relationship")
        if relationship_raw not in (r.value for r in ContradictionRelationship):
            continue
        relationship = ContradictionRelationship(relationship_raw)
        if relationship == ContradictionRelationship.UNRELATED:
            continue
        contradictions.append(Contradiction(
            claim_a_id=claim_a.claim_id, claim_b_id=claim_b.claim_id, relationship=relationship,
            temporal_context=str(result.get("temporal_context", "")),
        ))
    return contradictions


_EVIDENCE_JUDGE_SYSTEM = """\
Compare EVIDENCE A and EVIDENCE B ONLY for a direct factual contradiction
about the same specific claim/entity (e.g. one says a numeric limit is X,
the other says it's Y for the same thing).

Do NOT flag as a contradiction:
- Different facts about different topics/entities
- A difference explainable by different scope (different product tier,
  jurisdiction, plan, or version) -- that is SCOPE_DIFFERENCE
- A difference explainable by time passing (an old value vs a newer one)
  -- that is TEMPORALLY_RECONCILABLE
- Complementary or additional information

If you suspect a conflict but cannot confirm both passages are about the
exact same subject with confidence, use LIKELY_CONFLICT rather than
DIRECT_CONTRADICTION.

Return ONLY JSON:
{"relationship": "DIRECT_CONTRADICTION"|"TEMPORALLY_RECONCILABLE"|"SCOPE_DIFFERENCE"|"LIKELY_CONFLICT"|"UNRELATED",
 "subject": "short name of the specific fact/entity being compared", "reason": "one sentence"}"""


def _evidence_candidate_pairs(evidence: list[Evidence]) -> list[tuple[Evidence, Evidence]]:
    candidates = []
    for i in range(len(evidence)):
        for j in range(i + 1, len(evidence)):
            if _topic_overlap(evidence[i].passage.text, evidence[j].passage.text) >= _TOPIC_OVERLAP_THRESHOLD:
                candidates.append((evidence[i], evidence[j]))
    candidates.sort(key=lambda pair: _topic_overlap(pair[0].passage.text, pair[1].passage.text), reverse=True)
    return candidates[:MAX_EVIDENCE_PAIRS_CHECKED]


def _likely_temporal(ev_a: Evidence, ev_b: Evidence) -> bool:
    """Deterministic pre-check (spec §14): if both pieces of evidence
    carry a determinable publication time and they differ, a judge-flagged
    conflict is reclassified as TEMPORALLY_RECONCILABLE without needing
    the judge to reason about dates itself (small/nano models are
    unreliable at date arithmetic) -- e.g. a 2025 source and a 2026
    source disagreeing on a numeric limit is far more likely a real
    update than a genuine standing contradiction."""
    a_time = ev_a.published_at or ev_a.updated_at
    b_time = ev_b.published_at or ev_b.updated_at
    return bool(a_time and b_time and a_time != b_time)


async def detect_evidence_contradictions(evidence: list[Evidence], tier: str = "nano") -> list[Contradiction]:
    """Evidence-vs-evidence contradiction detection (spec §12-15) --
    distinct from detect_contradictions() above, which only ever compares
    claims WITHIN a generated answer. This compares retrieved EVIDENCE
    passages directly, so two conflicting sources are flagged even if the
    generated answer only repeated one of them. Bounded the same way:
    lexical pre-filter, MAX_EVIDENCE_PAIRS_CHECKED cap, never O(n^2) over
    an unbounded evidence set."""
    if len(evidence) < 2:
        return []

    contradictions: list[Contradiction] = []
    for ev_a, ev_b in _evidence_candidate_pairs(evidence):
        result = await gateway_json_call(
            f"EVIDENCE A: {ev_a.passage.text[:800]}\n\nEVIDENCE B: {ev_b.passage.text[:800]}",
            _EVIDENCE_JUDGE_SYSTEM, tier=tier, max_tokens=150,
        )
        if not isinstance(result, dict):
            continue
        relationship_raw = result.get("relationship")
        if relationship_raw not in (r.value for r in ContradictionRelationship):
            continue
        relationship = ContradictionRelationship(relationship_raw)
        if relationship == ContradictionRelationship.UNRELATED:
            continue
        # Temporal reconciliation overrides the judge's own verdict (spec
        # §14/§15): never let a source's higher nominal authority silently
        # decide "the older evidence must be wrong" -- both pieces of
        # evidence stay visible in the contradiction record either way,
        # only the RELATIONSHIP label changes.
        if relationship == ContradictionRelationship.DIRECT_CONTRADICTION and _likely_temporal(ev_a, ev_b):
            relationship = ContradictionRelationship.TEMPORALLY_RECONCILABLE
        contradictions.append(Contradiction(
            claim_a_id=ev_a.evidence_id, claim_b_id=ev_b.evidence_id, relationship=relationship,
            subject=str(result.get("subject", "")), source_a_id=ev_a.source_id, source_b_id=ev_b.source_id,
            temporal_context=f"{ev_a.published_at or ev_a.updated_at or ''} vs {ev_b.published_at or ev_b.updated_at or ''}".strip(),
        ))
    return contradictions
