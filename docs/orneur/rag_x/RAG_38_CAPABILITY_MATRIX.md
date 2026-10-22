# RAG-38 capability matrix

Scope: `orca/rag_x` on synthetic in-memory fixtures. Local test: `python3 -m pytest tests/test_rag_x_foundation.py` (16 passed in this session). This is not a production retrieval service and not an independent audit.

`EXISTING_VERIFIED` is unused. Older Truth Fabric, memory, document, and federated-retrieval code is inventoried in the reality baseline and was not re-executed for this matrix.

| ID | Class | Code | Limitation |
|---|---|---|---|
| RAG-01 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=naive` | Term-count baseline over the in-memory corpus. |
| RAG-02 | RESEARCH_PROTOTYPE | `orca.rag_x.rank.hash_embed` | Default embedder is synthetic_hash_v1. mode=dense-neural is BACKEND_UNAVAILABLE without an injected function. |
| RAG-03 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.rank.bm25_scores` | In-memory Okapi BM25, not a durable posting index. |
| RAG-04 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=hybrid` | Reciprocal rank fusion of BM25 and the active embedder. Fallback is not labeled hybrid. |
| RAG-05 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=contextual` | Uses a stored context prefix. It does not generate a new prefix with a model. |
| RAG-06 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=rerank` | Default reranker is lexical overlap. A callable reranker can replace it. No hosted rerank model is configured. |
| RAG-07 | RESEARCH_PROTOTYPE | `orca.rag_x.rank.maxsim` | synthetic-maxsim is not ColBERT. mode=colbert returns BACKEND_UNAVAILABLE. |
| RAG-08 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=long-context` | Packs spans under RetrievalBudget.max_tokens. Token cost is len(text)//4. |
| RAG-09 | RESEARCH_PROTOTYPE | `orca.rag_x.kernel mode=self-rag` | A runtime heuristic decides whether to retrieve. This is not the trained Self-RAG critic. |
| RAG-10 | RESEARCH_PROTOTYPE | `orca.rag_x.kernel mode=corrective` | One quoted reformulation when the first pass is empty, bounded by the retrieval budget. |
| RAG-11 | RESEARCH_PROTOTYPE | `orca.rag_x.kernel mode=agentic` | Bounded retrieve rounds. There is no separate planner model. |
| RAG-12 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=multi-hop` | The second hop must be an in-tenant entity edge to a visible document. |
| RAG-13 | RESEARCH_PROTOTYPE | `orca.rag_x.kernel mode=adaptive` | Rules choose decompose, contradiction, multi-hop, or sparse. They are not a learned router. |
| RAG-14 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=decompose` | Splits on the word 'and' and dedupes chunk ids. |
| RAG-15 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=multi-query` | Original query plus a token-normalized variant. Identical chunks are kept once. |
| RAG-16 | RESEARCH_PROTOTYPE | `orca.rag_x.kernel mode=hyde` | Hypothetical query text is marked synthetic and is never returned as evidence. |
| RAG-17 | RESEARCH_PROTOTYPE | `orca.rag_x.kernel mode=reflection` | Rejects a draft that is not contained in an authoritative span. It does not call a second model. |
| RAG-18 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.contracts.RetrievalBudget` | Stops before a call when the retrieval budget or deadline is already empty. |
| RAG-19 | RESEARCH_PROTOTYPE | `orca.rag_x.kernel mode=graph` | Entity edges expand neighbors. They are not evidence-support edges and this is not Microsoft GraphRAG. |
| RAG-20 | RESEARCH_PROTOTYPE | `orca.rag_x.kernel mode=raptor` | Summary chunks are non-authoritative and cannot solely support a claim. |
| RAG-21 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=temporal` | valid_from/valid_to filter the visible version. Historical answer records are not rewritten. |
| RAG-22 | RESEARCH_PROTOTYPE | `orca.rag_x.kernel mode=multimodal` | Text and table chunks can be retrieved. Image, audio, and video chunks are skipped. |
| RAG-23 | BACKEND_UNAVAILABLE | `orca.rag_x.kernel mode=audio|video` | No audio or video ingestion, timing, or encoder is present. |
| RAG-24 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=sql` | Structured equality filters only. Raw SQL is unauthorized. The tenant id is always applied. |
| RAG-25 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=code` | Symbol and reference lookup. Not a compiler or repository index. |
| RAG-26 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=federated` | Connector failures stay in partial_reasons. This does not replace orca.connectors.federated_retrieval. |
| RAG-27 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=conversational` | Follow-ups use only request.history. Session-scoped corpus rows from another session are not visible. |
| RAG-28 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=memory` | Memory rows are owner-scoped and deletion removes them from later retrieval. |
| RAG-29 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=live` | Disconnected or stale providers are skipped and named. No live connector is claimed. |
| RAG-30 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=domain` | domain_reliability=not_qualified. No scientific, legal, medical, or financial qualification is claimed. |
| RAG-31 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.contracts.RetrievedEvidence` | Digest, version, method, rank, and source URI are on each hit. |
| RAG-32 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel.verify_claim` | The claim string must occur in an authoritative span. A marker alone is not support. |
| RAG-33 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel._contradictions` | Detects KEY=value disagreements. Temporal non-overlap is labeled temporal and is not treated as a conflict. |
| RAG-34 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.corpus._authorized` | Tenant, workspace, principal, revocation, expiry, and session are checked before a row can be scored. |
| RAG-35 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.corpus.Corpus.redact` | Emails are redacted in the kernel log. This is not a full privacy-preserving index. |
| RAG-36 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel.execute` | Document text cannot change scope or authorize tools. No embedding-poisoning defense beyond the permission filter is claimed. |
| RAG-37 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel mode=uncertainty` | A single source abstains in this mode. lexical_score is not a calibrated probability. |
| RAG-38 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.contracts.AnswerEvidenceManifest` | Manifest binds config digest and document versions. Generation byte-identity is not promised. |
| X1 | RESEARCH_PROTOTYPE | `orca.rag_x.kernel.verify_claim` | Claim-to-span linkage on this kernel. Not a separate evidence graph beside orca.truth. |
| X2 | RESEARCH_PROTOTYPE | `orca.rag_x.research.run_contradiction_first` | Frozen synthetic comparison. See the recorded result rather than a superiority claim. |
| X3 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.kernel.replay_evidence` | Stored answer text is left unchanged when a source is revoked. |
| X4 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.corpus.Corpus.visible` | In-memory authorization. Not an enterprise IdP. |
| X5 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.research.replay` | Evidence and verification can be reconstructed. Model-generation replay reports that byte identity is unsupported. |
| X6 | RESEARCH_PROTOTYPE | `orca.rag_x.corpus.Corpus.glossary` | Cross-language match uses an explicit glossary or a shared identifier. It is not a translation model. |
| X7 | RESEARCH_PROTOTYPE | `orca.rag_x.research.arbitrate` | Roles can be labeled. Identical backend ids count once. Native models are not trained. |
| X8 | IMPLEMENTED_AND_QUALIFIED | `orca.rag_x.research.authorize_action` | Evidence never grants a tool. C02 is not modified. |

Denominator note: 38 RAG rows and 8 research rows are accounted for. A row is not a production implementation unless its class is `IMPLEMENTED_AND_QUALIFIED`, and that class here means the in-memory contract test passed. `RESEARCH_PROTOTYPE` and `BACKEND_UNAVAILABLE` are not production implementations.
