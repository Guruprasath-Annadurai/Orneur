# Truth Fabric Security (Phase 4)

## TOCTOU SSRF fix in `orca/truth/fetch.py`

**The gap.** `orca/tools/web.py::fetch_page()` (pre-existing, dead code —
zero callers before this phase) checked the *initial* URL for SSRF risk
(private/loopback/link-local/reserved/multicast address) but then fetched
with `follow_redirects=True`. A malicious server can return a URL that
passes the initial check, then respond with a redirect to an internal
address (e.g. a cloud metadata endpoint) — the check-then-use gap is a
classic time-of-check-to-time-of-use bypass. That module's own comment
flagged this as needing to be closed before ever being wired up as a
callable tool. Phase 4 is the first phase to make page-fetching reachable
in principle (Deep Search), so this is where it gets fixed.

**The fix.** `fetch_document()` in `orca/truth/fetch.py`:

- Uses `httpx.Client(follow_redirects=False)` and manually walks each
  redirect hop itself.
- Re-runs `_is_ssrf_risk()` — DNS-resolves the hostname and checks the
  resolved address, not just the string — **before every single hop**,
  including the first, and again after following each `Location` header.
- Bounds the redirect chain to `MAX_REDIRECTS=5`; exceeding it raises
  `FetchRefusedError` rather than looping.
- Streams the response body and aborts once `MAX_DOCUMENT_BYTES=5MB` is
  exceeded, rather than trusting a `Content-Length` header (protects
  against a decompression-bomb-shaped response with a lying or absent
  header).

Verified by `tests/test_truth_fetch_security.py` against a **real local
HTTP server** performing an actual redirect to a private address — not a
mocked assertion that the function "would" check redirects. The test
suite's own history includes a self-caught false start: the first version
bound the "initial" URL to `127.0.0.1`, which the *first-hop* check alone
would already catch, so it never actually exercised the redirect
re-validation logic. It was rewritten
(`test_fetch_document_checks_every_redirect_hop_not_just_the_first`) to
simulate a safe-looking initial URL and prove — via a call-count
assertion — that the *redirect target* was independently re-checked, not
just the first hop.

## Honest scope: this fix is not yet reachable in production

`TruthFabric._retrieve()` never calls `fetch_document()` — see
[SEARCH_PROVIDERS.md](SEARCH_PROVIDERS.md). The WEB retrieval path uses
only `SearchProvider` snippets (`evidence_from_search_result`), which
never fetch a page or follow a redirect at all. So today, in the live
system, neither the old vulnerable `fetch_page()` nor the new fixed
`fetch_document()` is invoked by any retrieval mode. The fix exists,
is correct, and is proven by a real integration test — it is prepared
for the phase that wires full-page fetching into `RAG_5_RESEARCH`, not
yet exercised by production traffic. This is disclosed here rather than
implied as "shipped and protecting live traffic," which would overstate
what changed.

## Content sanitization — retrieved content is untrusted

`sanitize_extracted_text()` (`orca/truth/fetch.py`) reuses and extends the
injection-pattern list already proven in
`orca/tools/search_grounding.py::sanitize_fetched_content` — that module
only covers title+snippet; this one covers full extracted page text (once
wired in, per the scope note above). Patterns matched are prompt-injection
shaped: "ignore previous instructions," "you are now DAN," fake
`[system]`/`<|system|>` blocks, "disregard all previous/safety," etc.

**Block, don't guess.** Flagged content is never regex-edited or
"cleaned" in place and then used anyway — `sanitize_extracted_text()`
returns a `flagged: bool`, and the intended caller contract is to exclude
flagged content from the evidence pipeline entirely, never to silently
strip the matched substring and proceed as if the rest of the document
were still trustworthy.

## What is NOT re-audited or changed in this phase

Per [CURRENT_TRUTH_PIPELINE.md](CURRENT_TRUTH_PIPELINE.md)'s audit, the
pre-existing Deep RAG pipeline (`orca/docs/query_engine.py`,
`reranker.py`, `sufficiency.py`) makes raw `urllib.request` calls that
bypass `ModelGateway` entirely — a real architectural gap Phase 2.1's own
direct-Ollama audit missed (it was scoped to the primary chat path, not
RAG internals). This is disclosed, not fixed, in Phase 4: every *new*
Truth Fabric LLM call is Gateway-routed (`orca/truth/llm.py`), but
rewriting the existing, working retrieval pipeline's internals blindly
was judged out of scope for a phase whose job is to build Truth Fabric
alongside it, not rewrite it.
