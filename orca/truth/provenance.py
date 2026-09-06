"""
Source independence / provenance lineage (Phase 4 spec §19-20) --
"Blog A, Blog B, Blog C all derived from Original Source S1 must not count
as 3 independent confirmations." Deterministic, lexical-similarity-based
heuristic -- explicitly NOT a claim of perfect independence detection.
No model call: fast enough to run over every evidence pair in a plan's
result set.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from orca.truth.contracts import Evidence, EvidenceSource, IndependenceState

# A near-identical passage (same wording, not just same topic) is the
# strongest deterministic signal a real independence check can use without
# an LLM. High threshold deliberately -- false positives here would
# wrongly discount a genuinely independent confirmation.
_HIGH_SIMILARITY_THRESHOLD = 0.85


def _passage_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a[:2000], b[:2000]).ratio()


def _registered_domain(domain: str) -> str:
    """Crude eTLD+1-ish approximation (last two labels) -- good enough to
    catch "same site, different path/subdomain," not a full public-suffix-
    list implementation. Documented limitation, not silently assumed exact."""
    parts = domain.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain.lower()


def assess_independence(evidence_a: Evidence, source_a: EvidenceSource, evidence_b: Evidence, source_b: EvidenceSource) -> IndependenceState:
    """
    Deterministic signals, checked in order of strength:
      1. Same registered domain -> LIKELY_DERIVED (same publication origin).
      2. Near-identical passage text across DIFFERENT domains -> LIKELY_DERIVED
         (classic "syndicated/copied content" signal).
      3. Explicit attribution: one passage's text mentions the other's domain
         by name -> LIKELY_DERIVED.
      4. None of the above -> INDEPENDENT is too strong a claim from lexical
         signals alone; returns UNKNOWN rather than falsely asserting
         independence (spec §20: "Do not claim perfect independence
         detection").
    """
    if source_a.domain and source_b.domain and _registered_domain(source_a.domain) == _registered_domain(source_b.domain):
        return IndependenceState.LIKELY_DERIVED

    similarity = _passage_similarity(evidence_a.passage.text, evidence_b.passage.text)
    if similarity >= _HIGH_SIMILARITY_THRESHOLD:
        return IndependenceState.LIKELY_DERIVED

    if source_b.domain and source_b.domain.lower() in evidence_a.passage.text.lower():
        return IndependenceState.LIKELY_DERIVED
    if source_a.domain and source_a.domain.lower() in evidence_b.passage.text.lower():
        return IndependenceState.LIKELY_DERIVED

    return IndependenceState.UNKNOWN


def annotate_independence(sources: list[EvidenceSource], evidence: list[Evidence]) -> None:
    """
    Mutates each EvidenceSource's `.independence`/`.derived_from` in place
    -- pairwise comparison across the (typically small, per-plan-bounded)
    evidence set. A source's `.independence` reflects the STRONGEST
    LIKELY_DERIVED signal found against any other source in the set; a
    source found independent of everything else it was compared against
    stays UNKNOWN (never upgraded to INDEPENDENT from absence of evidence
    to the contrary -- see assess_independence's own docstring).
    """
    evidence_by_source: dict[str, Evidence] = {}
    for ev in evidence:
        if ev.source_id not in evidence_by_source:
            evidence_by_source[ev.source_id] = ev

    sources_by_id = {s.source_id: s for s in sources}
    ids = list(evidence_by_source.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            sid_a, sid_b = ids[i], ids[j]
            if sid_a not in sources_by_id or sid_b not in sources_by_id:
                continue
            state = assess_independence(evidence_by_source[sid_a], sources_by_id[sid_a], evidence_by_source[sid_b], sources_by_id[sid_b])
            if state == IndependenceState.LIKELY_DERIVED:
                sources_by_id[sid_a].independence = IndependenceState.LIKELY_DERIVED
                sources_by_id[sid_b].independence = IndependenceState.LIKELY_DERIVED
                if sid_b not in sources_by_id[sid_a].derived_from:
                    sources_by_id[sid_a].derived_from.append(sid_b)
