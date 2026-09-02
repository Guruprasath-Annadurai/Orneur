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

from orca.truth.contracts import AtomicClaim, Contradiction, ContradictionRelationship
from orca.truth.llm import gateway_json_call

MAX_PAIRS_CHECKED = 10
_TOPIC_OVERLAP_THRESHOLD = 0.25

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
