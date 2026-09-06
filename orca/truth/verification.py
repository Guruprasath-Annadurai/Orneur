"""
ClaimVerifier (Phase 4 spec §24-25). Combines lexical overlap (deterministic,
always available) with a Gateway-routed entailment/contradiction judge
(the role orca/docs/hallucination_check.py's dead check_grounding() played,
reimplemented here so it actually goes through ModelGateway -- see
CURRENT_TRUTH_PIPELINE.md's audit and CLAIM_VERIFICATION.md). Architecture
allows a stronger verifier (a real NLI model) to replace or augment the
judge call later without ClaimSupport's shape changing.

Never uses citation-marker presence as verification (spec §24) -- this
module never even looks at [D#]/[S#] markers; it compares claim text
against evidence PASSAGE text directly.
"""
from __future__ import annotations

from orca.truth.contracts import ClaimSupport, ClaimSupportState, Evidence
from orca.truth.llm import gateway_json_call

_JUDGE_SYSTEM = """\
You are checking whether a CLAIM is supported by the EVIDENCE passages below.

Legitimate inference and reasonable synthesis of the evidence are NOT
contradictions -- do not flag those. Flag CONTRADICTED only if the
evidence directly states something incompatible with the claim.

Return ONLY JSON:
{"verdict": "SUPPORTED"|"PARTIALLY_SUPPORTED"|"UNSUPPORTED"|"CONTRADICTED", "reason": "one sentence"}"""

_LEXICAL_STRONG_THRESHOLD = 0.35
_LEXICAL_WEAK_THRESHOLD = 0.12


def _lexical_overlap(claim_text: str, evidence_text: str) -> float:
    claim_words = {w.lower() for w in claim_text.split() if len(w) > 3}
    evidence_words = {w.lower() for w in evidence_text.split() if len(w) > 3}
    if not claim_words:
        return 0.0
    return len(claim_words & evidence_words) / len(claim_words)


async def verify_claim(claim_id: str, claim_text: str, evidence: list[Evidence], tier: str = "nano") -> ClaimSupport:
    if not evidence:
        return ClaimSupport(
            claim_id=claim_id, evidence_ids=[], support_state=ClaimSupportState.UNKNOWN,
            reasons=["no evidence available to check this claim against"],
        )

    overlaps = [(ev, _lexical_overlap(claim_text, ev.passage.text)) for ev in evidence]
    overlaps.sort(key=lambda pair: pair[1], reverse=True)
    best_evidence, best_overlap = overlaps[0]

    combined_evidence_text = "\n\n".join(ev.passage.text[:1000] for ev, _ in overlaps[:3])
    judge_result = await gateway_json_call(
        f"CLAIM: {claim_text}\n\nEVIDENCE:\n{combined_evidence_text}", _JUDGE_SYSTEM, tier=tier, max_tokens=150,
    )

    evidence_ids = [ev.evidence_id for ev, overlap in overlaps if overlap >= _LEXICAL_WEAK_THRESHOLD] or [best_evidence.evidence_id]

    if isinstance(judge_result, dict) and judge_result.get("verdict") in (s.value for s in ClaimSupportState):
        state = ClaimSupportState(judge_result["verdict"])
        reasons = [judge_result.get("reason", "judged by Gateway-routed entailment check")]
        strength = f"lexical_overlap={best_overlap:.2f}, judge_verdict={state.value}"
        return ClaimSupport(claim_id=claim_id, evidence_ids=evidence_ids, support_state=state, support_strength=strength, reasons=reasons)

    # Judge unavailable or unparseable -- fall back to lexical-only signal,
    # deliberately weaker (never claims full SUPPORTED without the judge's
    # entailment check; lexical proximity alone is not entailment).
    if best_overlap >= _LEXICAL_STRONG_THRESHOLD:
        state = ClaimSupportState.PARTIALLY_SUPPORTED
        reason = "judge unavailable -- strong lexical overlap only, entailment not confirmed"
    elif best_overlap >= _LEXICAL_WEAK_THRESHOLD:
        state = ClaimSupportState.UNKNOWN
        reason = "judge unavailable -- weak lexical overlap, cannot determine support"
    else:
        state = ClaimSupportState.UNSUPPORTED
        reason = "judge unavailable -- no meaningful lexical overlap with any evidence"

    return ClaimSupport(
        claim_id=claim_id, evidence_ids=evidence_ids, support_state=state,
        support_strength=f"lexical_overlap={best_overlap:.2f}", reasons=[reason],
    )
