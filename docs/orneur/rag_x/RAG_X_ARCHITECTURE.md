# RAG-X architecture

`orca/rag_x` is one kernel, not 38 services.

`RetrievalRequest.mode` selects a strategy. `Corpus.visible` applies tenant, workspace, principal, session, memory owner, revocation, deletion, and validity before scoring. `execute` then dedupes by chunk id, packs to `max_tokens`, records contradictions, and checks the drafted span.

Ranking lives in `orca/rag_x/rank.py`: term counts, Okapi BM25, reciprocal rank fusion, `synthetic_hash_v1`, and token maxsim. Maxsim is not ColBERT. The hash embedder is not a neural embedding model. `mode=dense-neural` without an injected embedder returns `backend_unavailable`.

The kernel does not import `orca.connectors.federated_retrieval` or `orca.truth`. Those modules remain the existing implementations. The new federated mode is an in-memory connector list with explicit partial failures.
