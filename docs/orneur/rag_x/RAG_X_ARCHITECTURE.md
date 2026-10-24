# RAG-X architecture

`orca/rag_x` is one kernel, not 38 services.

`RetrievalRequest.mode` selects a strategy. `Corpus.visible` applies tenant, workspace, principal, session, memory owner, revocation, deletion, and validity before scoring. `execute` then dedupes by chunk id, packs to `max_tokens`, records contradictions, and checks the drafted span.

Ranking helpers live in `orca/rag_x/rank.py`: term counts, reciprocal rank fusion over integer indexes, `synthetic_hash_v1`, and token maxsim. Okapi BM25 is `orca.docs.sparse.bm25_scores`; the research kernel calls that function. Maxsim is not ColBERT. The hash embedder is not a neural embedding model. `mode=dense-neural` without an injected embedder returns `backend_unavailable`.

Canonical local retrieval is `AuthorizedIndex` and `run_authorized_retrieval`. This kernel does not import `orca.connectors.federated_retrieval` or `orca.truth`. Those modules remain the existing implementations. The research federated mode is an in-memory connector list with explicit partial failures.
