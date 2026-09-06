# Safe Fetch Cutover (Phase 4.1)

Phase 4 built `orca/truth/fetch.py::fetch_document()` (SSRF-hardened:
every redirect hop re-validated, bounded size, streamed read) but never
called it from anywhere reachable — [SECURITY.md](../phase-4/SECURITY.md)
disclosed this explicitly at Phase 4 closure. This phase makes it
reachable, in two places.

## 1. `TruthFabric._retrieve()` — the live Truth Fabric retrieval path

For `RAG_5_RESEARCH` (AUDIT_GRADE requests) specifically, the **top**
web search result now gets a real full-page fetch through the safe
boundary, bounded to exactly one fetch per retrieval pass:

```
search_provider.search(query) -> results
for i, result in enumerate(results):
    if i == 0 and mode == RAG_5_RESEARCH and result.url:
        fetch_document(result.url)        # SSRF-hardened
          -> extract_text(raw_html)       # strip scripts/styles/nav
          -> sanitize_extracted_text(text) # prompt-injection pattern scan
          -> evidence_from_fetched_passage(...)
        # on ANY failure/refusal/flagged content: fall back to the
        # snippet-only path for this result, never treat it as a hard
        # retrieval failure
    else:
        evidence_from_search_result(result)   # snippet-only, as before
```

Every other retrieval mode (`RAG_1`/`RAG_2`/`RAG_3`/`RAG_4`) and every
result after the first stay snippet-only — bounded deliberately: a
full-page fetch per result would multiply both cost and untrusted-content
surface far beyond what a snippet pass needs, and `RAG_5_RESEARCH` is
the one mode whose evidence requirement (AUDIT_GRADE) justifies the extra
depth and cost for at least the highest-ranked result.

`tests/test_truth_safe_fetch_cutover.py` proves: the fetched full page
text (not the snippet) ends up in evidence when the fetch succeeds; a
fetch failure falls back to the snippet rather than failing retrieval;
and prompt-injection-flagged fetched content is excluded from evidence
entirely (never regex-"cleaned" and used anyway) — falling back to the
snippet.

## 2. `orca/data/web_ingest.py` — training-corpus ingestion

Migrated off `fetch_page()` (the TOCTOU-vulnerable original) onto
`fetch_document()`/`extract_text()`. See
[LIVE_RETRIEVAL_AUDIT.md](LIVE_RETRIEVAL_AUDIT.md) for why this module
was in scope even though it's TRAINING_ONLY, not a Truth-Fabric-
authoritative path: it shared the exact same TOCTOU gap, and the
migration was small and contained. `fetch_page()` itself is now
confirmed to have zero callers anywhere in the codebase (see
`orca/tools/web.py`'s updated docstring) — it is kept only for any
external/notebook usage, and remains explicitly documented as unsafe to
wire up as a callable tool without the same fix.

## The `/api/stream` bypass this made visible

Auditing every live retrieval path (spec §2) surfaced a separate,
unrelated bug in `orca/serve/api.py`: the streaming chat endpoint
discarded a Truth-Fabric-verified Kernel answer in favor of the legacy
Deep RAG pipeline whenever a session had any document loaded — the exact
opposite of what "Truth Fabric is authoritative for evidence-backed
answers" should mean. Fixed in the same commit as this cutover; see
[LIVE_RETRIEVAL_AUDIT.md](LIVE_RETRIEVAL_AUDIT.md) and
[PHASE_4_FINAL_CLOSURE.md](PHASE_4_FINAL_CLOSURE.md) for the full
before/after.
