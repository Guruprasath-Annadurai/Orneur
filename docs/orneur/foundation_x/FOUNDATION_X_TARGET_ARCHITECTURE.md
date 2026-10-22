# Foundation-X target architecture

The programme diagram is a target. This file describes the path this branch actually runs.

## Canonical retrieval

`orca.truth` remains the Truth Fabric. `orca.rag_x.execute` is not on that path.

| Concern | Canonical module | What stayed separate |
|---|---|---|
| Retrieval plan | `orca.truth.planner.build_retrieval_plan` | Research modes in `orca.rag_x.kernel` |
| Session | `orca.truth.access.SessionAuthority` | `AuthorizedRetrievalScope` inside the research kernel |
| Local index | `orca.docs.authorized_index.AuthorizedIndex` | `orca.docs.store.DocStore` Chroma/Ollama path, unchanged |
| Chunking | `orca.docs.chunker.chunk_text` | Research corpus chunks |
| Sparse rank | `orca.docs.sparse.bm25_scores` | `DocStore._bm25_score` remains the older TF-only fallback |
| Hybrid fusion | `orca.docs.reranker.reciprocal_rank_fusion` | Research `rrf_fuse` over in-memory indexes |
| Evidence record | `orca.truth.evidence.evidence_from_document_chunk` | Research `RetrievedEvidence` |
| Claim check | `orca.truth.verification` thresholds | Research span containment. The authorized path does not call the entailment judge, so it never returns full `SUPPORTED` |
| Federated tenant boundary | `orca.connectors.document_store.search_documents` | Research connector list |
| Training grant | `NativePretrainingGrant.verify_integrity` | Caller strings on `LifecycleChain.authorization_kind` |

`TruthFabric.assess_evidence` gains an optional `access` argument. A store with `requires_trusted_session` must `permits(access)` before `count` or `retrieve`. Existing `DocStore` callers do not set that flag.

`run_authorized_retrieval` compiles hits into Truth evidence, abstains when two retrieved passages disagree on the same `KEY = value` fact, and sets `tool_grant` false. Retrieved text cannot change the session tenant.

Dense retrieval runs only when the supplied encoder has `kind="neural"`, is not marked research-only, and is not `orneur.rag_x.synthetic_hash_v1`. `production_neural` is true only for identity `nomic-embed-text` after `probe_ollama` succeeds. A test double can exercise fusion and is reported as that double, not as nomic.

## Research-only kernel

`orca/rag_x` still executes the fixture strategies covered by `tests/test_rag_x_foundation.py`. Its BM25 scores call `orca.docs.sparse`. Hash embeddings and token maxsim stay in `orca.rag_x.rank` and are not a neural or ColBERT backend. The kernel does not authorize tools and does not start training.

## Lifecycle

`assess_lifecycle` still checks the caller-supplied chain for missing links. Authorization is separate: a `FOUNDER_GRANT` string is ignored as a claim. A real `NativePretrainingGrant` must pass `verify_integrity()` and match the chain's dataset, transformation, tokenizer, config, and run identities. This function does not call `authorize_native_pretraining` or `GenesisTrainingRun.authorize`. A completed chain would still be `chain_complete_training_not_authorized`. No such grant can be constructed in tests, because the seal is private to the authorization gate.

## What remains unfinished

These are not implemented as usable systems on this branch:

- Production neural retrieval. No nomic weights were used as the hybrid arm. `probe_ollama` records availability and does not install an encoder.
- True late interaction. `maxsim` is a hash sketch. ColBERT weights are absent.
- Graph evidence. Truth Fabric's evidence graph and the research entity edges are not a GraphRAG index.
- Temporal correctness beyond version, digest, and the research kernel's `valid_from` / `valid_to` filter.
- Multilingual retrieval quality. The research glossary is not a translation model.
- Multimodal ingestion. Text chunks only. Audio and video stay `backend_unavailable` in the research kernel.
- Reproducible training lifecycle evidence. The grant check is fail-closed. It is not a witnessed training run.
- Scaling and GPU measurements. Parameter and AdamW byte formulas remain estimates.
- Training-math coverage on this commit. The earlier torch job was for `b5230a0`, not this head.
- Darwin `F_GETPATH` for the progress database. Linux CI for `fc1eb1d` is green. This environment cannot execute the Darwin branch.
- Application integration through PR #79 and PR #81. Those branches were not edited.
- Independent audit. This file is an author note.

Acceptance remains `pretraining=95 numerator=0 application=3 execution=2 post=1`. Training is not authorized.
