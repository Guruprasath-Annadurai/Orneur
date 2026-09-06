# Citation Engine (Phase 4)

`orca/truth/citation.py` is what makes citation enforcement **claim-linked**
rather than marker-presence-only — the limitation documented for the
pre-existing `orca/docs/citation_check.py` in
[CURRENT_TRUTH_PIPELINE.md](CURRENT_TRUTH_PIPELINE.md) (it only checked
that a `[D#]`-shaped marker existed somewhere in the text, never that the
marker's claim was actually supported).

## `build_citations(claim_supports) -> list[CitationVerdict]`

One `CitationCandidate`/`CitationVerdict` per `(claim, evidence)` pair
the `ClaimVerifier` actually linked — never attaches a citation to a
source just because that source appeared somewhere in the retrieval
context (spec §26). A claim the verifier couldn't link to any evidence
produces no candidate at all for that claim.

## The enum mapping — never a false positive

```python
_SUPPORT_TO_VERDICT = {
    SUPPORTED            -> SUPPORTED,
    PARTIALLY_SUPPORTED  -> PARTIAL,
    CONTRADICTED         -> CONTRADICTED,
    UNSUPPORTED          -> UNSUPPORTED,
    UNKNOWN              -> UNSUPPORTED,   # <- never SUPPORTED
}
```

`UNKNOWN` and `UNSUPPORTED` both map to an `UNSUPPORTED` verdict. This is
an explicit table, not an inferred default, specifically so an unresolved
claim-support state can never present as if it had a verified citation
(spec §27: "Do not emit unsupported citations as authoritative"). A
dedicated regression test in `tests/test_truth_citation_state.py` pins
this mapping down directly, independent of any specific verifier
behavior.

## `reject_unsupported(verdicts) -> list[CitationVerdict]`

Filters to only `SUPPORTED`/`PARTIAL` verdicts. This is the function
`TruthFabric.verify_answer()` actually calls before returning
`citation_verdicts` — a caller cannot forget to filter, because
unfiltered verdicts are never what reaches `TruthResult` in the first
place.

## `compute_citation_coverage(claims, claim_supports) -> dict`

The real metrics from spec §28, computed once per `verify_answer()` call:

```python
{
  "total_claims": int,
  "supported_claims": int,
  "partially_supported_claims": int,
  "unsupported_claims": int,       # includes UNKNOWN
  "contradicted_claims": int,
  "citation_coverage_ratio": (supported + partially_supported) / total,  # or None if total==0
}
```

`citation_coverage_ratio` feeds directly into
`orca/truth/state.py::compute_evidence_state()` (see
[ARCHITECTURE.md](ARCHITECTURE.md) for the full `EvidenceState`
computation) — it is the same number reported to a Kernel caller via
`CognitiveResult.citation_coverage`, not a separately-computed display
figure.
