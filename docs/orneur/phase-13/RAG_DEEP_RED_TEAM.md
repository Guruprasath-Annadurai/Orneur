# Phase 13.1 — RAG Deep Red-Team

10 new attacks executed against real code (`tests/test_redteam_rag_deep.py`).

| ID | Attack | Target | Status | Severity | Regression test |
|---|---|---|---|---|---|
| RAG-01a | Mirrored/syndicated/attributed copies of one origin | `orca.truth.provenance.assess_independence` | BLOCKED_AS_EXPECTED — all 3 variants correctly flagged `LIKELY_DERIVED` | — | `test_rag01_mirrored_and_paraphrased_copies_are_detected_as_derived` |
| RAG-01b | Heavily paraphrased dependent copy, different domain, no attribution | same | **Disclosed detection limitation** (lexical-only heuristic; documented in the module's own docstring) | LOW (disclosed, not fixed) | `test_rag01_well_paraphrased_dependent_copy_is_a_disclosed_detection_limitation` |
| RAG-02a | Authority spam: 2+ mutually-derived low-diversity sources reaching SUFFICIENT | `orca.truth.state.compute_evidence_state` | **REAL_VULNERABILITY — FOUND AND FIXED** | MEDIUM | `test_rag02_authority_spam_no_longer_reaches_sufficient_when_all_sources_are_mutually_derived` |
| RAG-02b | Regression: genuinely diverse sources still reach SUFFICIENT | same | BLOCKED_AS_EXPECTED (fix doesn't over-block) | — | `test_rag02_genuinely_diverse_sources_still_reach_sufficient` |
| RAG-02c | Regression: single source unaffected | same | BLOCKED_AS_EXPECTED | — | `test_rag02_single_source_is_unaffected_by_the_independence_check` |
| RAG-03 | Citation claim-swap (evidence for claim B attached to claim A) | `orca.truth.citation.build_citations` | BLOCKED_AS_EXPECTED (structural — no code path exists) | — | `test_rag03_citation_candidates_only_ever_reference_the_evidence_actually_linked_to_that_claim` |
| RAG-04 | Citation negation reversal, judge-unavailable fallback | `orca.truth.verification.verify_claim` | **Disclosed fallback limitation** — ceiling holds (never reaches SUPPORTED) | LOW (disclosed) | `test_rag04_negation_reversal_under_fallback_never_exceeds_partially_supported` |
| RAG-05 | Citation entity-swap confusion, judge-unavailable fallback | same | Disclosed fallback limitation — ceiling holds | LOW (disclosed) | `test_rag05_entity_swap_under_fallback_never_exceeds_partially_supported` |
| RAG-06 | Citation numeric mismatch, judge-unavailable fallback | same | Disclosed fallback limitation (reclassified from an initially-wrong hypothesis after actually running it — see test docstring) — ceiling holds | LOW (disclosed) | `test_rag06_numeric_mismatch_under_fallback_never_exceeds_partially_supported` |
| RAG-07 | Fake future-dated document | `orca.truth.state.compute_evidence_state` | BLOCKED_AS_EXPECTED — function never reads `published_at` | — | `test_rag07_future_dated_document_does_not_independently_grant_sufficiency` |

## The real finding (RAG-02a)

`annotate_independence()` (Phase 4) computed `IndependenceState`/
`derived_from` on every `EvidenceSource` — confirmed by grepping the
entire codebase that `.independence` was **write-only**: nothing
downstream ever read it. `compute_evidence_state()`'s SUFFICIENT
threshold was driven purely by `citation_coverage_ratio`, with zero
regard for whether the underlying sources were N genuinely independent
confirmations or N copies of one origin. Fixed: a would-be SUFFICIENT
result downgrades to PARTIAL when 2+ sources exist and every one is
`LIKELY_DERIVED`. Deliberately narrow — a set with even one `UNKNOWN` or
independent-looking source is unaffected, matching this module's
existing "never assert more than the evidence supports" discipline.

## Disclosed fallback-path limitations (RAG-04/05/06)

`verify_claim()`'s lexical-only fallback (used only when the live judge
call is unavailable) is negation-blind and entity-swap-blind by
construction — word-set overlap doesn't encode "not," and closely-named
entities share most tokens. This is the SAME limitation the module's own
docstring already discloses ("lexical proximity alone is not
entailment"). The real defense against these attacks is the live
entailment judge on the non-degraded path, which was not bypassed or
weakened. The security property verified here is the ceiling: even under
all three adversarial inputs, the fallback never claims full `SUPPORTED`.

## Not attacked this phase (disclosed)

Citation-numeric-mismatch and temporal-mismatch attacks against the
**live judge path** itself (as opposed to the deterministic fallback)
were not executed — that would require live Ollama calls with carefully
curated adversarial evidence, a larger undertaking than this
qualification pass's scope for one sub-campaign.
