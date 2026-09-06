"""
Atomic claim extraction (Phase 4 spec §22) -- decomposes generated output
into independently-verifiable factual claims before citation verification.
Gateway-routed (via orca.truth.llm), unlike the pre-existing dead
hallucination judge this replaces the role of (see
CURRENT_TRUTH_PIPELINE.md and CLAIM_VERIFICATION.md).
"""
from __future__ import annotations

import re

from orca.truth.contracts import AtomicClaim, _new_id
from orca.truth.llm import gateway_json_call

_EXTRACTION_SYSTEM = """\
Decompose the RESPONSE below into independent, atomic factual claims --
each claim should be a single, self-contained, checkable statement.

Do NOT extract:
- opinions, hedges, or subjective statements
- pure conversational filler ("I hope this helps")
- questions

Return ONLY a JSON array of strings, each one atomic claim, e.g.:
["Model X is faster than Model Y.", "The improvement is approximately 30%.", "Model X supports FP8."]

If the response contains no checkable factual claims, return []."""

# Deterministic fallback (no model call) -- splits on sentence boundaries.
# Coarser than the LLM extractor (a sentence may bundle multiple claims),
# but never silently returns nothing just because the model was
# unavailable -- honest about being a fallback, not real claim atomicity.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _fallback_sentence_claims(text: str) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return [s for s in sentences if len(s.split()) >= 3]  # skip trivial fragments


async def extract_atomic_claims(response_text: str, tier: str = "nano") -> list[AtomicClaim]:
    if not response_text.strip():
        return []

    result = await gateway_json_call(response_text, _EXTRACTION_SYSTEM, tier=tier, max_tokens=500)
    claim_texts: list[str]
    if isinstance(result, list) and all(isinstance(c, str) for c in result):
        claim_texts = result
    else:
        claim_texts = _fallback_sentence_claims(response_text)

    return [AtomicClaim(claim_id=_new_id("claim"), text=text, source_span=text) for text in claim_texts]
