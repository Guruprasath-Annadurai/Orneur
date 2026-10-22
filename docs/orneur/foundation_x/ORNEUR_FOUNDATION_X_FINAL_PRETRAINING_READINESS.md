# Pre-training readiness

## A. What was completed

The canonical local path is now `AuthorizedIndex` plus `run_authorized_retrieval`, with Truth Fabric evidence compilation and a sealed `SessionAuthority`. Sparse retrieval uses shared Okapi BM25 over admitted chunks. Hybrid fusion runs only when a neural encoder function actually runs, and a test double is not labeled nomic. Hash embeddings stay research-only.

The research kernel, claim checks, synthetic data admission, a parameter estimate, and a proposal gate that cannot accept itself remain. The progress-database portability correction is on PR #80.

Research prototypes that execute but are not the published methods: hash embeddings, hash maxsim, self-rag heuristic, one-step corrective reformulation, raptor summary flag, entity-graph expansion, HyDE query text, and the contradiction-first comparison.

Not implemented as usable systems: production neural dense retrieval, ColBERT weights, audio, video, and application integration. A caller-supplied founder-grant string is rejected.

Live backends: no native model, no hosted embedder, no live connector. The template backend quotes a span.

## B. Research

Prior-art titles were fetched for Self-RAG, Corrective RAG, RAPTOR, GraphRAG, and ColBERTv2. X2 on six frozen items: baseline 2 confident conflicted answers, treatment 0, correct-answer loss 0. Q1 on twelve frozen local documents: sparse hits 7/7, basic confident conflicts 4, contradiction-first confident conflicts 0, citation `SUPPORTED` 0, `model_backed` false. That is not a general result and not a neural evaluation. No external benchmark was run.

## C. Security

The in-memory tests listed in `RAG_X_ADVERSARIAL_TEST_REPORT.md` passed. `tests/test_truth_authorized_index.py` additionally denies forged sessions, cross-tenant indexes, connector tenant mismatch, symlink reads, digest substitution, stale cache reuse, revocation, and instruction text as a tool grant. Residual: no production identity provider, no SSRF suite, no real generator injection suite, and Darwin filesystem execution was not performed. There is no independent security report for this SHA.

## D. Evidence

PR #80: https://github.com/Guruprasath-Annadurai/Orneur/pull/80 at `fc1eb1dd098377e8506485dbcd82d6ed148b52b3`. Exact-head CI: https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39840961482 (9/9 success). Darwin `F_GETPATH` was not executed.

PR #82 previous head `81e4e310c6ca6e08428aa22cd178e8d0f1c4b57a`: https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39843423059 (9/9 success). That run does not cover the integration commit.

Local Linux runs for this integration: `tests/test_truth_authorized_index.py`, `tests/test_rag_x_foundation.py`, and the non-smoke Truth, connector, and tenant suites named in the test run (163 passed, 12 deselected, 2 xfailed). Q1 resource observation: about 9.7 ms and 92324 peak bytes for twelve items. p50/p95 for the earlier 100 in-memory sparse queries: 0.199 ms / 0.262 ms.

## E. Models

| | GENESIS | NOVUS | AETERNUM |
|---|---|---|---|
| Architecture prepared | Formula and existing training code only | Same | Same |
| Training infrastructure qualified | No | No | No |
| Dataset authorized | No | No | No |
| Evaluation protocol qualified | No | No | No |
| Hardware available for frontier pretraining | Not shown | Not shown | Not shown |
| Formal acceptance | Numerator 0 | Numerator 0 | Numerator 0 |
| Training authorization | No | No | No |
| Trained model | No | No | No |

## F. Open work

Engineering-owned and still open: CI on the integration commit, application integration, and training-math execution for this head. External: GPUs, a real nomic encoder used as retrieval, Darwin execution, a private corpus. Review: independent audit. Founder: training authorization, acceptance changes, merges, spend. Future research: learned retrieval, real late interaction, retrieval-conditioned training.

Darwin qualification blocker: native `F_GETPATH` for the progress database has not run. The Linux design and the monkeypatched path test are not that execution.

## G. Verdict

**FOUNDATION PARTIAL**

Authorized local sparse retrieval, session checks, and grant-string rejection are implemented and tested. Substantial qualification remains: production neural retrieval, independent audit, CI on the integration commit, Darwin execution, application integration, and the unchanged acceptance register.

`pretraining=95 numerator=0 application=3 execution=2 post=1`.

Training is not authorized.
