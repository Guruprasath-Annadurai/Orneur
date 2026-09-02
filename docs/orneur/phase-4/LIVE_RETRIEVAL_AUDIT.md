# Live Retrieval Path Audit (Phase 4.1)

Every production path that can retrieve external/web content or make a
factual-retrieval LLM call, classified before any Phase 4.1 code changed.
Corrects two claims from Phase 4's own audit ([CURRENT_TRUTH_PIPELINE.md](CURRENT_TRUTH_PIPELINE.md))
that turned out to be imprecise once traced further — see the notes below.

| Path | Classification | Notes |
|---|---|---|
| `orca/truth/truth_fabric.py::TruthFabric._retrieve` (DENSE/SPARSE via DocStore) | TRUTH_FABRIC_SAFE_FETCH | Local vector search, no network egress. |
| `orca/truth/search_provider.py::DuckDuckGoProvider` → `orca/tools/web.py::search` | TRUTH_FABRIC_SAFE_FETCH | Wraps a fixed, trusted host (`html.duckduckgo.com`); `follow_redirects=True` here is low-risk since the target host isn't attacker-controlled (unlike `fetch_page`, whose target URL comes from an arbitrary search result). |
| `orca/truth/fetch.py::fetch_document` | TRUTH_FABRIC_SAFE_FETCH | SSRF-hardened (every redirect hop re-validated, bounded size, streamed read). **As of this phase, wired into `TruthFabric._retrieve` for RAG_5_RESEARCH's top web result** (see [SAFE_FETCH_CUTOVER.md](SAFE_FETCH_CUTOVER.md)) — Phase 4 built this but never called it. |
| `orca/tools/search_grounding.py::search_and_ground` (the live agent's `web_search` tool, `orca/tools/__init__.py::build_registry`) | LEGACY_SAFE | Snippet-only via `orca/tools/web.py::search` — same trusted-host profile as the DuckDuckGo provider above, never calls `fetch_page`. |
| `orca/tools/web.py::fetch_page` | DEAD_CODE (corrected from Phase 4's "confirmed dead code, zero callers") | **Phase 4's audit was imprecise**: `orca/data/web_ingest.py::ingest_urls` DID call it. That caller, however, has zero callers of its own anywhere in the codebase — no CLI command, no API route, no scheduled job invokes `ingest_urls`. Net effect (reachable from live traffic: no) was correct, but "zero callers" (reachable from any code path at all: false) was not. **Phase 4.1 migrated `web_ingest.py` off `fetch_page` entirely** (see below) — `fetch_page` now genuinely has zero callers. |
| `orca/data/web_ingest.py::ingest_urls` | TRAINING_ONLY | A standalone training-corpus-building utility, not wired into any CLI/API entry point. Not a factual-retrieval path Truth Fabric claims authority over. Migrated to `orca/truth/fetch.py::fetch_document`/`extract_text` in this phase regardless, since it shared `fetch_page`'s TOCTOU gap and the safe replacement was a small, contained change. |
| `orca/docs/pipeline.py::run_deep_rag` and its stages (`query_engine.py`, `reranker.py`, `sufficiency.py`, `semantic_chunker.py`, `store.py`) | LEGACY_UNSAFE (ModelGateway bypass, not an SSRF/web-fetch issue) | Every raw-`urllib.request` call in these modules targets the configured **Ollama host** (`ollama_host` parameter, defaulting to `localhost:11434`) for embeddings/generation — not an arbitrary attacker-supplied URL. This is a real `ModelGateway`-bypass (observability/routing gap), not an SSRF vector: the host is trusted local infrastructure, not content-controlled. Disclosed, not fixed, in Phase 4; still disclosed, not fixed, in this phase — see §4 discussion below. |
| `orca/docs/sufficiency.py::check_sufficiency`/`detect_contradictions` | LEGACY_UNSAFE (same ModelGateway-bypass class as above) | **Genuinely valuable prior art**: this module already implemented a real corrective-retry-on-insufficiency loop and a real contradiction-detection judge call, years before Phase 4.1's spec asked for the same capability in Truth Fabric. Phase 4.1's `orca/truth/corrective.py` and the evidence-vs-evidence path in `orca/truth/contradiction.py` reuse this module's exact prompt-design pattern, Gateway-routed and operating on typed `Evidence` instead of raw chunk dicts. |
| `orca/serve/api.py::run_deep_rag` call site (`/api/chat` streaming branch) | **UNEXPECTED_TRUTH_BYPASS — found and fixed this phase** | See §26 finding below: this call site unconditionally preferred the legacy Deep RAG pipeline over a Truth-Fabric-produced Kernel answer whenever a session had any document loaded, discarding a verified, citation-checked Truth Fabric answer in favor of the Gateway-bypassing legacy pipeline. Fixed — see [SAFE_FETCH_CUTOVER.md](SAFE_FETCH_CUTOVER.md) and `PHASE_4_FINAL_CLOSURE.md`. |
| `orca/serve/api.py` non-streaming `/api/chat` Kernel-output branch | TRUTH_FABRIC_AUTHORITATIVE (already correct) | Unconditionally uses `cognitive_result.output` when non-None, regardless of `doc_store.count()` — already gives Truth Fabric priority over legacy RAG. This asymmetry with the streaming branch (fixed above) is itself notable: the two endpoints diverged in RAG-vs-Kernel precedence before this phase. |
| `orca/tools/code.py::run_shell`, `read_file`/`write_file` sandboxing | INTERNAL | Unrelated to factual/web retrieval; not audited further here (already covered by `docs/SECURITY_AUDIT.md`). |

## `UNEXPECTED_UNSAFE_FETCH_BYPASS` (spec §4)

**= 0** for user-facing factual/research paths Truth Fabric claims
authority over, after this phase's fix to the `/api/stream` Kernel-vs-RAG
precedence bug. The one remaining raw-network path in a Truth-Fabric-
adjacent module (`ingest_urls`) has been migrated to the safe fetch
boundary regardless, even though it was TRAINING_ONLY and not strictly
required by this count.

## `UNEXPECTED_TRUTH_BYPASS` (spec §27)

**= 0** after the `/api/stream` fix above, for supported STRICT/
AUDIT_GRADE factual flows (i.e., a plan whose only operations are
RETRIEVE/SEARCH/VERIFY). The pre-existing Deep RAG pipeline remains the
path for any request needing USE_TOOL/DELEGATE_AGENT alongside retrieval
(unchanged Phase 3 CUTOVER.md discipline — not a bypass, a deliberately
un-migrated request class) and for sessions where the Kernel's own plan
didn't route through Truth Fabric at all (e.g. ANSWER_DIRECTLY-only
plans with no evidence requirement).

## Raw-urllib legacy bypass disposition (spec §4)

The Deep RAG pipeline's `ModelGateway` bypass is **not migrated in this
phase**, for the same reason Phase 4 disclosed rather than fixed it:
these calls target trusted local Ollama infrastructure, not arbitrary
external content, so the risk class is observability/routing debt, not a
security vulnerability an attacker can exploit via crafted web content.
Migrating six modules' raw-`urllib` Ollama calls to `ModelGateway` is a
real, valuable follow-up — but it is a mechanical, wide-blast-radius
rewrite of the working legacy retrieval path that Phase 4.1's own scope
(§39: no Memory Continuum, no large-scope rewrites) argues against
bundling into the corrective-retrieval/contradiction/counter-evidence
work this phase actually delivered. Recorded here as the one disclosed,
deliberately-still-open item from Phase 4's own findings.
