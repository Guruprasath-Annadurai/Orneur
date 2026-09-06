# Truth Fabric Evaluation V2 (Phase 4.1)

Extends [EVALUATION.md](EVALUATION.md) (Phase 4's original 6-case
harness) with 2 new AUDIT_GRADE cases (`orca/truth/eval_harness.py::
CASES_V2`) and the corrective-retrieval/evidence-contradiction/counter-
evidence work delivered this phase. **The original six cases are kept
verbatim, never replaced or re-labeled** (spec §32/§33) — every number
below for them is directly comparable to Phase 4's own reported numbers.

## Before / After — the original six cases (same corpus, same evaluator)

| Metric | Before (Phase 4) | After (Phase 4.1) |
|---|---|---|
| Mean Recall@K | 1.000 | 1.000 |
| MRR | 0.833 | 0.833 |
| Mean nDCG | 1.000 | 1.000 |
| Mean citation coverage ratio | 0.875 | 0.875 |
| Mean unsupported-claim rate | 0.083 | 0.083 |
| Claim-support precision | 0.667 (4/6) | 0.667 (4/6) — **unchanged, honestly** (spec §20: not declaring success from a metric bump that didn't happen) |
| `contradiction_pair` case: any contradiction detected | false | **true** — real fix (see below) |
| `contradiction_pair` case: DIRECT_CONTRADICTION detected | n/a (not measured) | **true** — the evidence-vs-evidence conflict between the two corpus documents is now caught during `assess_evidence`, before generation, independent of what the answer says |
| `multi_doc_synthesis` false-positive DIRECT_CONTRADICTION | true (every observed run) | **still occurs on some runs** — see finding below; not eliminated |
| Mean retrieval latency | 74.3 ms | 2,667.9 ms |
| Mean verification latency | 14,985.4 ms | 14,968.0 ms (~unchanged) |

Retrieval latency rose sharply because `assess_evidence()` now runs
`detect_evidence_contradictions()` (a real Gateway judge call per
candidate evidence pair) as part of retrieval, not because retrieval
itself got slower. This is a real, disclosed cost of the new capability,
not overhead that should be hidden from the number.

Recall@K/nDCG/coverage/unsupported-rate are unchanged because nothing in
this phase touched dense retrieval scoring or the citation-coverage
computation itself — only contradiction detection and corrective
retrieval changed, and neither of the original six cases needed a
corrective round (their initial retrieval was always sufficient or
cleanly insufficient).

## Finding: the claim-verifier false positive is reduced, not eliminated (spec §19)

Reproduced exactly (see [PHASE_4_FINAL_CLOSURE.md](PHASE_4_FINAL_CLOSURE.md)
for the reproduction transcript): the answer "Model A performs better,
achieving 92% accuracy versus Model B's 88%" gets split into 2-3 atomic
claims, and `detect_contradictions()`'s nano-tier judge sometimes flags a
comparative claim ("Model A performs better...") against a specific-value
claim ("Model B achieves 88%...") as `DIRECT_CONTRADICTION`, which is
wrong — the comparison is entailed by, not contradicted by, the
underlying values.

**Diagnosis**: prompt/schema, not claim segmentation or evidence
segmentation — the claims themselves are correctly and reasonably split;
the judge's *reasoning* about comparative claims is what's unreliable.

**Fix attempted**: added an explicit rule + worked example to
`_JUDGE_SYSTEM` ("A comparative claim... and a claim giving one of the
specific values... are CONSISTENT, not contradictory..."). Verified via
direct reproduction: with the fix, 3 out of the first several real runs
against the exact same input correctly avoided `DIRECT_CONTRADICTION`
(returning `TEMPORALLY_RECONCILABLE` instead — not a perfectly correct
label either, since there's no time dimension here, but critically it no
longer forces `EvidenceState.CONFLICTED`). **However, on other real
runs against the identical input, the nano-tier judge still produces
`DIRECT_CONTRADICTION`** — this is genuine run-to-run model
non-determinism, not a prompt-coverage gap the current fix missed.

**Disposition (spec §19's explicit options)**: **partially generic-fixed,
partially retained as a documented model limitation.** The prompt
improvement is real and kept (it measurably reduces the failure rate on
repeated manual reproduction, and does not regress the existing direct-
conflict-detection test `test_detect_contradictions_finds_direct_conflict`
or the unrelated-claims test). A regression test
(`tests/test_truth_claims_verification_contradiction.py::
test_detect_contradictions_does_not_flag_comparative_claim_as_direct_conflict`)
pins down that this exact reproduction case does not *reliably* produce
the worst-case classification, without claiming the underlying nano-tier
judge fallibility on comparative claims has been eliminated — that
remains a real, retained model limitation. No evaluation data was
altered to manufacture this result; the fix and the finding were derived
independently by testing the isolated judge call.

## AUDIT_GRADE cases (`CASES_V2`, reported separately, never blended into the six above)

| Case | Outcome | Notes |
|---|---|---|
| `audit_grade_strong_evidence` | citation coverage `None` (no claims extracted / evidence-level contradiction flagged) | A genuinely new, honest finding, not a hidden failure: the SQL-syntax answer text (backtick-wrapped `ALTER TABLE` statements) yielded zero extracted atomic claims on this run, AND the evidence-vs-evidence judge flagged the migration document and its own documented rollback procedure (same column, opposite operation) as `DIRECT_CONTRADICTION` — a `SCOPE_DIFFERENCE` (forward migration vs. its own rollback) would have been the correct relationship. Neither issue was chased further with additional prompt tuning (diminishing-returns risk per spec §20's "do not tune evaluation data to make the score look better"); both are recorded as real, disclosed nano-tier limitations distinct from the comparative-claim finding above. |
| `audit_grade_insufficient_evidence` | Correctly shows no citation coverage | The corpus has nothing relevant to the query; the honest "insufficient evidence" outcome is exactly what's expected. |

**The AUDIT_GRADE-can-succeed acceptance gate is satisfied independently**,
by the live Kernel-level integration test
(`tests/test_cognitive_kernel_truth_fabric_integration.py::
test_audit_grade_request_with_strong_evidence_can_succeed`), which uses
simpler single-sentence evidence and passes reliably (verified 3
consecutive live runs) — reaching `CognitiveState.COMPLETED` with
`evidence_state == "SUFFICIENT"` and a `RAN` counter-evidence attempt.
The eval-harness `audit_grade_strong_evidence` case's more complex,
SQL-syntax-bearing evidence surfaced a *different*, real limitation
rather than disproving that AUDIT_GRADE success is achievable — both
facts are reported here rather than only the favorable one.

## What section §32's case list still doesn't have a harness case for

Stale evidence, low-authority web evidence, derived-duplicate web
source, and prompt-injected-page cases all depend on live web search
results (`SearchProvider`) or a full-page fetch — this sandbox has no
outbound web access (`orca.tools.web.search` returns `[]` here), so a
harness case built on live DuckDuckGo results would measure network
availability, not Truth Fabric behavior. These are instead covered by
**deterministic pytest tests with fake providers**, which is a more
reliable evaluation method for exactly this reason:

- Low-authority / derived-duplicate source signals: `tests/test_truth_evidence_provenance_graph.py`
- Prompt-injected fetched page (excluded, not sanitized-in-place): `tests/test_truth_safe_fetch_cutover.py::test_prompt_injected_fetched_page_is_excluded_not_sanitized_in_place`
- Stale evidence → `EvidenceState.STALE`: covered by `orca/truth/state.py`'s existing unit tests in `tests/test_truth_citation_state.py` (deterministic, freshness-mismatch input)
