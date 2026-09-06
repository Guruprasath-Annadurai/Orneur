# Truth Fabric Evaluation (Phase 4)

## Harness

`orca/truth/eval_harness.py` — run directly with
`.venv/bin/python -m orca.truth.eval_harness` (requires a local Ollama
instance; prints an error and exits non-zero if unreachable, rather than
fabricating numbers).

**Corpus**: 6 hand-labeled cases, each with its own tiny document set (2–3
short documents) and known-correct relevance judgments. This is
deliberately small. A statistically meaningful benchmark needs a real
labeled dataset (hundreds+ of query/relevance pairs) and a GPU budget for
running many nano-tier Gateway calls per case — building that dataset is
its own project, out of scope for "first production version of Truth
Fabric." This harness's job is to prove the metrics are computed
correctly from real, live runs against a real (if small) ground truth —
not to produce a publishable leaderboard number. Every number below came
from one real `python -m orca.truth.eval_harness` run against local
Ollama (nano tier) on 2026-08-25 — nothing here is estimated or
hand-picked.

## Results (n=6)

| Metric | Value |
|---|---|
| Mean Recall@K | 1.000 |
| MRR | 0.833 |
| Mean nDCG | 1.000 |
| Mean citation coverage ratio | 0.875 |
| Mean unsupported-claim rate | 0.083 |
| Claim-support precision (verdict matches hand-label) | 0.667 (4/6) |
| Contradiction case detected (the one case designed to have it) | **False** — see finding #1 below |
| Mean retrieval latency | 74.3 ms |
| Mean verification latency (claim extraction + verify + contradiction check, nano tier) | 14,985.4 ms |

Recall@K/nDCG are 1.0 across the board because the corpus per case is
tiny (2–3 documents, 1–2 relevant) — dense retrieval over 2–3 short
chunks is not a hard problem. MRR is 0.833 rather than 1.0 because of the
`no_evidence` case, where nothing in the (deliberately irrelevant) corpus
is relevant and the harness scores that correctly as reciprocal rank 0
rather than papering over "no relevant result exists" as a perfect score.

## Findings from real runs (not hypothetical)

**1. Contradiction detection operates on the generated answer's claims,
not on conflicting evidence documents directly.** The `contradiction_pair`
case supplied two evidence documents that directly conflict (rate limit
"100/min" vs. a later "raised to 500/min"), expecting the system to flag
this. It didn't, and the harness's real output shows why: `detect_
contradictions()` (`orca/truth/contradiction.py`) runs over `AtomicClaim`s
extracted from the *answer text*, not over the evidence set itself. The
single-sentence answer used in this case ("The rate limit is 100 requests
per minute.") extracts to one claim — there is nothing for a second claim
to contradict. This is a real, previously undocumented scope gap between
what the spec's phrasing ("contradiction detection") might suggest and
what Phase 4 actually built: evidence-vs-evidence contradiction detection
(flagging that two *sources* disagree, independent of what the model
ends up saying) is not implemented — only answer-claim-vs-answer-claim
detection is. Recorded here rather than fixed silently, since fixing it
changes `TruthFabric.assess_evidence()`'s scope (it would need to run
contradiction detection over evidence text pre-generation, not just
post-generation over the answer).

**2. One likely false-positive contradiction, from the nano-tier judge.**
The `multi_doc_synthesis` case's answer ("Model A performs better,
achieving 92% accuracy versus Model B's 88%") is internally consistent —
it correctly reports two different models' two different scores — but
`detect_contradictions()` flagged it as containing a direct contradiction
in this real run. This is plausible nano-tier judge behavior: a small
model comparing two claims that both mention "accuracy" and different
percentages can conflate "different values for the same subject"
(genuine contradiction) with "different values for different, named
subjects" (not a contradiction) if it doesn't attend closely enough to
the subject noun phrase. `_candidate_pairs()`'s lexical pre-filter
(`orca/truth/contradiction.py`) correctly identified these two claims as
topically related enough to check — the false positive is downstream, in
the judge call itself, not in the bounding/pre-filter logic. Not
"fixed" by prompt-tuning here, since a single real run isn't a reliable
basis for tuning a prompt without risking regressing the cases that
already pass; recorded as a known nano-tier judge limitation instead.

**3. Verification latency is real, sequential Gateway-call cost, not
retrieval cost.** Retrieval is fast (74ms mean) because it's local
vector search against a tiny in-process corpus. Verification is slow
(up to 47.8s for the `multi_doc_synthesis` case) because
`TruthFabric.verify_answer()` makes one Gateway call for claim
extraction, then one additional Gateway call *per extracted claim* for
verification, then one more for contradiction checking — all against the
nano tier on a shared machine, matching the same class of Ollama
cold-load/model-swap latency root-caused in
`docs/orneur/phase-3/OLLAMA_TEST_RELIABILITY.md` (see also
`VERIFICATION_TIMEOUT_S=45.0`'s own justifying comment in
`orca/truth/truth_fabric.py`). This is why `VERIFICATION_TIMEOUT_S` is
45s rather than a smaller number, and why any production latency budget
for STRICT/AUDIT_GRADE requests needs to account for claim count, not
just retrieval time.

## Baseline comparison (spec §48)

The pre-existing Deep RAG pipeline (`orca/docs/pipeline.py::run_deep_rag`)
does not produce claim-level citation verdicts, a citation-coverage
ratio, or contradiction detection at all — see
[CURRENT_TRUTH_PIPELINE.md](CURRENT_TRUTH_PIPELINE.md)'s classification
of `citation_check.py` as marker-presence-only (PARTIAL) and
`hallucination_check.py::check_grounding` as DEAD. There is therefore no
existing apples-to-apples number for citation precision/recall,
claim-support precision, or unsupported-claim rate to compare against —
the honest baseline is "0/undefined for all Truth-Fabric-specific
metrics, because the capability did not exist." The one metric that is
comparable is retrieval latency: the existing pipeline's dense retrieval
step and Truth Fabric's `RAG_1_SEMANTIC`/`RAG_2_HYBRID` dense step use
the same underlying `DocStore.retrieve()` call, so retrieval latency is
expected to be equivalent by construction, not separately re-measured
here.
