"""Honest RAG-38 and X1–X8 classification for this kernel.

`IMPLEMENTED_AND_QUALIFIED` means the in-memory contract below has an
executable test. It does not mean a production index or a published
model-quality method. Nothing here is `EXISTING_VERIFIED`: the older
Truth Fabric and federated retrieval modules were not re-run as this
matrix's evidence.
"""
from __future__ import annotations

from orca.rag_x.contracts import CapabilityClass

CAPABILITIES: dict[str, dict[str, str]] = {
    "RAG-01": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=naive", "limitation": "Term-count baseline over the in-memory corpus."},
    "RAG-02": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.rank.hash_embed", "limitation": "Default embedder is synthetic_hash_v1. mode=dense-neural is BACKEND_UNAVAILABLE without an injected function."},
    "RAG-03": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.docs.sparse.bm25_scores", "limitation": "Shared in-memory Okapi BM25. Not a durable posting index. The research kernel calls this same function."},
    "RAG-04": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=hybrid", "limitation": "Reciprocal rank fusion of BM25 and the active embedder. Fallback is not labeled hybrid."},
    "RAG-05": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=contextual", "limitation": "Uses a stored context prefix. It does not generate a new prefix with a model."},
    "RAG-06": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=rerank", "limitation": "Default reranker is lexical overlap. A callable reranker can replace it. No hosted rerank model is configured."},
    "RAG-07": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.rank.maxsim", "limitation": "synthetic-maxsim is not ColBERT. mode=colbert returns BACKEND_UNAVAILABLE."},
    "RAG-08": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=long-context", "limitation": "Packs spans under RetrievalBudget.max_tokens. Token cost is len(text)//4."},
    "RAG-09": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.kernel mode=self-rag", "limitation": "A runtime heuristic decides whether to retrieve. This is not the trained Self-RAG critic."},
    "RAG-10": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.kernel mode=corrective", "limitation": "One quoted reformulation when the first pass is empty, bounded by the retrieval budget."},
    "RAG-11": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.kernel mode=agentic", "limitation": "Bounded retrieve rounds. There is no separate planner model."},
    "RAG-12": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=multi-hop", "limitation": "The second hop must be an in-tenant entity edge to a visible document."},
    "RAG-13": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.kernel mode=adaptive", "limitation": "Rules choose decompose, contradiction, multi-hop, or sparse. They are not a learned router."},
    "RAG-14": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=decompose", "limitation": "Splits on the word 'and' and dedupes chunk ids."},
    "RAG-15": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=multi-query", "limitation": "Original query plus a token-normalized variant. Identical chunks are kept once."},
    "RAG-16": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.kernel mode=hyde", "limitation": "Hypothetical query text is marked synthetic and is never returned as evidence."},
    "RAG-17": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.kernel mode=reflection", "limitation": "Rejects a draft that is not contained in an authoritative span. It does not call a second model."},
    "RAG-18": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.contracts.RetrievalBudget", "limitation": "Stops before a call when the retrieval budget or deadline is already empty."},
    "RAG-19": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.kernel mode=graph", "limitation": "Entity edges expand neighbors. They are not evidence-support edges and this is not Microsoft GraphRAG."},
    "RAG-20": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.kernel mode=raptor", "limitation": "Summary chunks are non-authoritative and cannot solely support a claim."},
    "RAG-21": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=temporal", "limitation": "valid_from/valid_to filter the visible version. Historical answer records are not rewritten."},
    "RAG-22": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.kernel mode=multimodal", "limitation": "Text and table chunks can be retrieved. Image, audio, and video chunks are skipped."},
    "RAG-23": {"class": CapabilityClass.BACKEND_UNAVAILABLE.value, "path": "orca.rag_x.kernel mode=audio|video", "limitation": "No audio or video ingestion, timing, or encoder is present."},
    "RAG-24": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=sql", "limitation": "Structured equality filters only. Raw SQL is unauthorized. The tenant id is always applied."},
    "RAG-25": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=code", "limitation": "Symbol and reference lookup. Not a compiler or repository index."},
    "RAG-26": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=federated", "limitation": "Connector failures stay in partial_reasons. This does not replace orca.connectors.federated_retrieval."},
    "RAG-27": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=conversational", "limitation": "Follow-ups use only request.history. Session-scoped corpus rows from another session are not visible."},
    "RAG-28": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=memory", "limitation": "Memory rows are owner-scoped and deletion removes them from later retrieval."},
    "RAG-29": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=live", "limitation": "Disconnected or stale providers are skipped and named. No live connector is claimed."},
    "RAG-30": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=domain", "limitation": "domain_reliability=not_qualified. No scientific, legal, medical, or financial qualification is claimed."},
    "RAG-31": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.contracts.RetrievedEvidence", "limitation": "Digest, version, method, rank, and source URI are on each hit."},
    "RAG-32": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel.verify_claim", "limitation": "The claim string must occur in an authoritative span. A marker alone is not support."},
    "RAG-33": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel._contradictions", "limitation": "Detects KEY=value disagreements. Temporal non-overlap is labeled temporal and is not treated as a conflict."},
    "RAG-34": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.corpus._authorized", "limitation": "Tenant, workspace, principal, revocation, expiry, and session are checked before a row can be scored."},
    "RAG-35": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.corpus.Corpus.redact", "limitation": "Emails are redacted in the kernel log. This is not a full privacy-preserving index."},
    "RAG-36": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel.execute", "limitation": "Document text cannot change scope or authorize tools. No embedding-poisoning defense beyond the permission filter is claimed."},
    "RAG-37": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel mode=uncertainty", "limitation": "A single source abstains in this mode. lexical_score is not a calibrated probability."},
    "RAG-38": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.contracts.AnswerEvidenceManifest", "limitation": "Manifest binds config digest and document versions. Generation byte-identity is not promised."},
    "X1": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.kernel.verify_claim", "limitation": "Claim-to-span linkage on this kernel. Not a separate evidence graph beside orca.truth."},
    "X2": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.research.run_contradiction_first", "limitation": "Frozen synthetic comparison. See the recorded result rather than a superiority claim."},
    "X3": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.kernel.replay_evidence", "limitation": "Stored answer text is left unchanged when a source is revoked."},
    "X4": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.corpus.Corpus.visible", "limitation": "In-memory authorization. Not an enterprise IdP."},
    "X5": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.research.replay", "limitation": "Evidence and verification can be reconstructed. Model-generation replay reports that byte identity is unsupported."},
    "X6": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.corpus.Corpus.glossary", "limitation": "Cross-language match uses an explicit glossary or a shared identifier. It is not a translation model."},
    "X7": {"class": CapabilityClass.RESEARCH_PROTOTYPE.value, "path": "orca.rag_x.research.arbitrate", "limitation": "Roles can be labeled. Identical backend ids count once. Native models are not trained."},
    "X8": {"class": CapabilityClass.IMPLEMENTED_AND_QUALIFIED.value, "path": "orca.rag_x.research.authorize_action", "limitation": "Evidence never grants a tool. C02 is not modified."},
}
