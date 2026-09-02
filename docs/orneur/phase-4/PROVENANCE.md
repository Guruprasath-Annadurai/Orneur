# Provenance & Source Independence (Phase 4)

## The problem

"Blog A, Blog B, and Blog C all confirm X" is not three independent
confirmations if all three derived their claim from the same original
source S1. Treating them as independent inflates confidence.
`orca/truth/provenance.py` addresses this directly (spec §19–20).

## `assess_independence()` — deterministic, no model call

Given two `(Evidence, EvidenceSource)` pairs, returns one of three
`IndependenceState` values:

- **`LIKELY_DERIVED`** when any of:
  - the two sources share the same registered domain (crude eTLD+1-ish
    approximation — last two labels of the hostname; documented as *not*
    a full public-suffix-list implementation, so a small class of
    multi-part TLDs will be approximated incorrectly rather than exactly);
  - the two evidence passages are near-identical (`SequenceMatcher` ratio
    ≥ `_HIGH_SIMILARITY_THRESHOLD = 0.85` over the first 2000 chars of
    each) — same wording, not just same topic;
  - one source explicitly attributes to the other by domain name in its
    text.
- **`UNKNOWN`** — everything else, **including** two sources that simply
  didn't trip any of the above heuristics. This is deliberate: the
  function never returns `INDEPENDENT`. A lexical heuristic can detect
  "these are clearly the same origin" with reasonable confidence; it
  cannot positively prove "these are genuinely independent origins" —
  that would require verifying the absence of a common upstream source,
  which this deterministic pass has no way to do. Claiming
  `INDEPENDENT` would be a false positive risk the spec explicitly rules
  out (§19: "do not claim perfect independence detection").

`annotate_independence(sources, evidence)` runs this pairwise over every
source in a retrieval result and mutates each `EvidenceSource.independence`
field in place — called once, right after retrieval, inside
`TruthFabric.assess_evidence()`.

## What this is not

- Not a citation-network crawl or backlink analysis — purely lexical,
  over the passages Truth Fabric already retrieved.
- Not persisted across sessions — independence is assessed fresh for
  each retrieval result, never cached as a standing judgment about a
  domain (consistent with `SourceQuality` never being a permanent
  per-domain score either — see [ARCHITECTURE.md](ARCHITECTURE.md)).
- `EvidenceSource.derived_from` (a list of source ids a source is
  *believed* derived from) is populated where `assess_independence`
  flags `LIKELY_DERIVED`, and feeds the `SAME_ORIGIN` edges in the
  [Evidence Graph](EVIDENCE_GRAPH.md) — but it is provenance lineage,
  not a verified citation graph.
