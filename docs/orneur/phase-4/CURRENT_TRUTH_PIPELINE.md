# Current Truth/RAG Pipeline — Pre-Phase-4 Audit

Read before any Phase 4 code was written. Maps the exact current flow and classifies every component.

## Current flow (as implemented, `orca/docs/pipeline.py::run_deep_rag`, called from `/api/stream` only — see Phase 2.1's own audit noting `/api/chat` doesn't call it)

```
request (message, doc_store, history)
  → doc_store.count() == 0 ? skip entirely : continue
  → Stage 1 Query Intelligence (orca/docs/query_engine.py::build_query_plan)
      rewrite, classify, decompose into sub-queries, expand, HyDE hypothetical-answer text
  → Stage 2 Multi-Signal Recall (doc_store.retrieve() per query variant + HyDE)
  → Stage 3 RRF Fusion (orca/docs/reranker.py::reciprocal_rank_fusion)
  → Stage 4 Lexical Prefilter (orca/docs/reranker.py::fast_lexical_prefilter)
  → Stage 5 Cross-Encoder Rerank (orca/docs/reranker.py::cross_encoder_rerank, LLM-as-reranker)
  → Stage 6 Sufficiency Check + one corrective round (orca/docs/sufficiency.py::check_sufficiency/detect_contradictions)
  → Stage 7 Citation DNA (orca/docs/sufficiency.py::make_citation_dna/format_context_with_citations)
  → context_block injected into system prompt → AgentLoop/ModelGateway generates
  → orca/docs/citation_check.py::check_citations — marker-presence-only compliance check
```

Separately, live web search: `orca/tools/web.py::search` (DuckDuckGo HTML scrape) → `orca/tools/search_grounding.py::search_and_ground` (numbered `[S#]` sources + injection-pattern sanitization on title+snippet) → `orca/tools/__init__.py`'s `web_search` tool, called by `AgentLoop`'s own tool-use planner. `orca/tools/web.py::fetch_page` (full-page fetch) exists but is **confirmed unreachable from any tool-calling surface** — dead code, by its own docstring's admission.

## Component classification

| Component | Classification | Notes |
|---|---|---|
| `orca/docs/pipeline.py::run_deep_rag` (7-stage orchestration) | **REAL** | Genuinely used in production (`/api/stream`, gated on `doc_store.count() > 0`), well-structured, independently testable per stage, graceful fallback. The right shape to wrap behind Truth Fabric contracts, not replace. |
| `orca/docs/query_engine.py` (query rewrite/decompose/expand/HyDE) | **REAL, but UNSAFE (Gateway bypass)** | Genuine, useful logic. `_ollama_generate`/`_ollama_embed` call `urllib.request` directly to Ollama's `/api/generate`/`/api/embeddings` — bypasses `ModelGateway` entirely (no circuit breaker, no priority scheduling, no observability, no cancellation). |
| `orca/docs/reranker.py` (RRF fusion, lexical prefilter, cross-encoder rerank) | **REAL, but UNSAFE (Gateway bypass)** | RRF fusion and lexical prefilter are pure/local (no bypass concern). `cross_encoder_rerank` uses the same raw `urllib.request` pattern as above for its LLM-as-reranker calls. |
| `orca/docs/sufficiency.py` (sufficiency check, corrective reform, contradiction scan, citation DNA) | **REAL, but UNSAFE (Gateway bypass)** | Same raw-`urllib.request` pattern (`_ollama_generate`). This is the single most Truth-Fabric-relevant existing module — sufficiency ≈ evidence-state judgment, contradiction detection already exists here in embryonic form. |
| `orca/docs/citation_check.py` (`check_citations`/`check_web_citations`) | **PARTIAL** | Real and currently the only citation enforcement, but explicitly, honestly scoped as **marker-presence-only** — a `[D#]`/`[S#]` marker appearing anywhere counts as "compliant" regardless of whether the marked source actually supports the claim next to it. This is exactly what Phase 4's acceptance gate requires no longer be *authoritative* (§27, §53) — kept as a cheap pre-check, superseded by claim-linked `CitationVerdict` for anything requiring real verification. |
| `orca/docs/hallucination_check.py::check_grounding` | **DEAD + UNSAFE** | Zero callers anywhere in the repository (confirmed by repo-wide grep) — this is the "dead hallucination judge" Phase 0 found and Phase 4 spec §25 asks to inspect. The judge prompt/logic is sound (grounded/confidence/issues/reason, fails open on judge error, doesn't flag legitimate inference) but it also uses raw `urllib.request`, bypassing the Gateway. **Verdict: not wired as-is** — its prompt design is reused inside the new Gateway-routed `ClaimVerifier` (see `CLAIM_VERIFICATION.md`); the original module is left in place, unchanged, explicitly marked superseded rather than deleted (zero callers means deleting it changes nothing behaviorally, but this audit is the right place to record the decision, not a silent removal). |
| `orca/tools/web.py::search` (DuckDuckGo HTML scrape) | **REAL** | Genuinely used (via `search_and_ground`), works, no API key needed. Becomes the first `SearchProvider` implementation behind the new abstraction (§13) — not rewritten. |
| `orca/tools/web.py::fetch_page` | **DEAD, with a documented known security gap** | Confirmed unreachable (matches its own docstring). Has an SSRF check on the initial URL but `follow_redirects=True` creates a TOCTOU bypass — a malicious server can pass the initial-URL check then redirect to an internal address. Its own comment says this "must be closed... before this is ever wired up as a callable tool." **Phase 4 is exactly the phase that wires up page fetching for Deep Search — this gap is closed as part of this phase, not carried forward** (see `SECURITY.md`). |
| `orca/tools/search_grounding.py` (`search_and_ground`, `sanitize_fetched_content`) | **REAL** | Genuinely useful, already-tested pattern (numbered sources, injection-pattern flagging, "block don't guess" posture). Reused as the model for Truth Fabric's own injection defense on FULL fetched-page content, which this module doesn't currently cover (it only sanitizes title+snippet, not full page text — full-page sanitization is new in Phase 4). |
| `orca/brain/knowledge_graph.py` (entity/relationship extraction) | **REAL, separate abstraction** | Semantic/entity relations, not provenance/support/contradiction — explicitly NOT the same thing as the new `EvidenceGraph` per phase spec §39. Left untouched; may cross-reference `EvidenceGraph` nodes by entity name later, not merged into it. |
| `orca/brain/memory.py` / `MemoryEngine` | **REAL, separate boundary** | Existing memory may supply retrieval candidates to Truth Fabric later, but per spec §38, memory-derived facts must stay distinguishable from external evidence — not touched this phase beyond that boundary being respected in `EvidenceSource.source_type`. |

## The one architecture-level finding that matters most

**The existing Deep RAG pipeline's own internal LLM-judge calls (query rewriting, HyDE, cross-encoder reranking, sufficiency checking, contradiction detection) all bypass `ModelGateway`.** This was not caught by Phase 2.1's own "direct-Ollama audit" (`docs/orneur/phase-2/PHASE_2_CLOSURE.md`) because that audit focused on the primary chat/generation serving path (`/api/chat`, `/api/stream`, `/api/ultra`) and classified `orca/docs/*` as `RAG_EMBEDDING` — real, but not re-inspected for Gateway compliance specifically, since Phase 2.1 was explicitly scoped to NOT touch RAG.

**Decision for Phase 4:** full migration of the existing Deep RAG pipeline's internal calls onto `ModelGateway` is a real, valuable, but large and separately-scoped undertaking — not required by this phase's own acceptance gates, and attempting it opportunistically here risks exactly the "rewrite working retrieval blindly" outcome the phase spec warns against (§3). Phase 4 instead ensures every **new** Truth Fabric module (claim verification, evidence compilation) is Gateway-routed from the start, and discloses the existing bypass explicitly as a known, tracked limitation for a future dedicated migration (see `PHASE_4_CLOSURE.md`).
