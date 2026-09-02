"""
Real, bounded corrective retrieval (Phase 4.1 spec §8-11). Phase 4 only
planned `corrective_rounds` as metadata; this module is the actual retry
loop, reusing the reform-query pattern already proven in
orca/docs/sufficiency.py::check_sufficiency() (its `_REFORM_PROMPT`), now
Gateway-routed instead of raw urllib and operating on typed Evidence
rather than plain chunk dicts.

Canonical loop (orchestrated by TruthFabric.assess_evidence, not here):
  initial retrieval -> EvidenceState assessment
  while state in (INSUFFICIENT, LOW_AUTHORITY, STALE) and budget/rounds/
  the shared query cap allow:
    reform_query() -> retrieve again -> merge/dedupe -> reassess
  stop when: sufficient, budget exhausted, max rounds reached, the
  rewritten query repeats a prior one, no new evidence was found, the
  overall deadline is hit, or the request is cancelled.

Never loops "until an LLM says it's satisfied" -- termination is always
one of the structural conditions above, not a judge's own say-so.
"""
from __future__ import annotations

from orca.truth.llm import gateway_json_call

_REFORM_SYSTEM = """\
The CONTEXT below was retrieved for a QUERY but is insufficient. Explain
briefly what's missing and write ONE better search query that would find
it. Do not repeat the original query verbatim.

Return ONLY JSON:
{"reformed_query": "...", "reason": "one short sentence", "evidence_gap": "one short sentence naming what's missing"}"""


async def reform_query(objective: str, missing_info: str, tier: str = "nano") -> dict | None:
    """Gateway-routed version of orca/docs/sufficiency.py's _REFORM_PROMPT
    pattern. Returns None (never raises) if the Gateway call fails or the
    response is unparseable -- the caller's own loop treats that as a
    stop condition (no reformed query to retry with), not a crash."""
    prompt = f"QUERY: {objective}\n\nWHY IT'S INSUFFICIENT: {missing_info or 'no matching evidence found'}"
    result = await gateway_json_call(prompt, _REFORM_SYSTEM, tier=tier, max_tokens=120)
    if not isinstance(result, dict) or not result.get("reformed_query"):
        return None
    return {
        "reformed_query": str(result["reformed_query"]).strip(),
        "reason": str(result.get("reason", "")).strip(),
        "evidence_gap": str(result.get("evidence_gap", "")).strip(),
    }


def is_repeat_query(new_query: str, prior_queries: list[str]) -> bool:
    """Bounded, deterministic near-duplicate check -- a corrective round
    that just rephrases the same query (normalized casing/whitespace, or
    the identical string) is a real stop condition (spec §9: "same/
    equivalent query repeats"), not a fresh attempt."""
    normalized_new = " ".join(new_query.lower().split())
    return any(normalized_new == " ".join(q.lower().split()) for q in prior_queries)
