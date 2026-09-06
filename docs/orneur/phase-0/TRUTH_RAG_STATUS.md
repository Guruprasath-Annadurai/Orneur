# Orneur Phase 0 — Truth Fabric / RAG Status

Verified by direct code audit. Being deliberately skeptical per the audit brief: ordinary vector retrieval is not called an "advanced Truth Fabric" here unless the code actually does more than that.

## Retrieval — REAL, degrades gracefully, not true hybrid

ChromaDB is genuinely wired (`orca/docs/store.py:102-116`, `PersistentClient` + per-session collection), embedding via Ollama's `nomic-embed-text`. If that embedding call fails, ChromaDB falls back to its own default embedder; if `chromadb` itself isn't importable, the system falls back further to an **on-disk JSONL + hand-rolled BM25-style TF-IDF scorer** (`store.py:70-83`). So: real vector search when dependencies are present, real (if simple) keyword search otherwise — **one or the other per query, never both fused in the same query.** The pipeline's "multi-signal recall" stage fires multiple query variants against this single resolved backend, not independent dense+sparse retrievers run in parallel — calling this "hybrid retrieval" would overclaim.

## Reranking — REAL, LLM-as-reranker (not a dedicated reranking model)

`cross_encoder_rerank()` (`orca/docs/reranker.py:57-94`) fires concurrent Ollama calls per (query, passage) pair asking for a 0–10 relevance score, parsed via regex. This is a legitimate, working technique — but it is bounded by the underlying chat model's instruction-following at a short `num_predict=5`, not a dedicated trained cross-encoder (e.g. bge-reranker/Cohere Rerank). RRF fusion (`reciprocal_rank_fusion`) is a correct, standard implementation.

## Citation enforcement — REAL, but the weaker "marker-only" form

`citation_check.py` verifies only that at least one `[D#]`/`[S#]` marker appears in the response when context was available. It does **not** verify that the cited claim actually traces to that source's content — the module's own docstring is explicit that this is "mechanically checkable" marker-presence, not claim-to-source verification. Calling this "verified citations" to a customer would overclaim what's actually enforced.

## Hallucination/grounding check — REAL implementation, but UNWIRED (dead code)

`hallucination_check.py`'s `check_grounding()` is a genuine LLM-as-judge implementation (asks whether response claims contradict or are unsupported by context, fails open to `grounded=True` on judge error). A repo-wide grep found **zero call sites** outside its own module — it is never invoked from the live request path. The only hallucination-adjacent mechanism actually wired into production is the weaker marker-presence check above. **This is a real, fixable gap**: wiring an already-built module into the pipeline, not new-feature work.

## Live web search — real for what exists; the one specific documented gap is real too

`orca/tools/web.py` scrapes DuckDuckGo's HTML interface (no API key); `orca/tools/search_grounding.py` wraps it with `[S#]` citation numbering and a regex-based prompt-injection sanitizer that excludes flagged content from context entirely. This **is** wired into the live agent tool registry and citation enforcement, contrary to what `docs/DEVELOPMENT_PHASES.md` implies — that roadmap doc is **stale**: it frames citation-discipline and injection-sanitization as future Phase 2 work, but both are already shipped. The one part of that doc's Phase 2 that remains genuinely true: no paid real-time search API (Brave/Bing/Serper-class) exists — DuckDuckGo scraping is the only search backend today.

## What's real vs. absent in the "Self-RAG/CRAG" mechanisms

Real and present: query rewriting (anaphora resolution via LLM), multi-hop query decomposition into sub-questions, HyDE, multi-query expansion, one bounded round of corrective retrieval triggered by a sufficiency judge (capped at `max_corrective_rounds=1`), and contradiction detection between retrieved chunks via LLM judge. All of these are genuine LLM-heuristic mechanisms with documented fail-open behavior on judge/model error — not formally verified, but not fake either.

Absent entirely: knowledge-graph-based retrieval fusion (a `KnowledgeGraph` class exists and extracts entities from chat turns, but is **not** used as a RAG retrieval signal), temporal reasoning, and corrective retrieval beyond the single bounded round.

## Classification for the Orneur "Truth Fabric" concept

| Component | Classification |
|---|---|
| Vector retrieval + BM25 fallback | REAL (not true hybrid — one backend per query) |
| LLM-as-reranker + RRF | REAL |
| Citation enforcement | REAL but PARTIAL (marker-presence only, not claim verification) |
| Hallucination/grounding judge | REAL implementation, but UNWIRED — dead code |
| Live web search | REAL (DDG scrape), citation + injection-sanitization already shipped; paid search API absent |
| Query rewriting / multi-hop / HyDE / corrective retrieval / contradiction detection | REAL, LLM-heuristic-based |
| Knowledge-graph-fused retrieval | ABSENT (KG exists but unused for retrieval) |
| Temporal reasoning | ABSENT |

**Bottom line for Orneur's "Truth Fabric" ambition**: there is a genuinely more sophisticated RAG pipeline here than "ordinary vector retrieval" — the Self-RAG-style mechanisms are real. But the two pieces that would make a "Truth Fabric" claim honest — actual claim-to-source citation verification and a wired hallucination/grounding check — are exactly the two pieces that are currently either weak (marker-only) or inert (built but unwired). Wiring `hallucination_check.py` in is the highest-leverage, lowest-risk next step and does not require new development.
