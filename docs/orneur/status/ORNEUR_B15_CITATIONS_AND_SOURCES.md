# B15 — Citations & Sources: Implementation Report

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Source:** `APPROVED_SOURCE_ARCHIVES/ORNEUR_B15_FINAL_LOCK_AND_HANDOFF.zip` (SHA-256 `8c0403ab872766a1c6212756c7032575e62221e1391174da21c30897b87189fb`) — verified via the archive's own `verification/verify_handoff.py`: 30/30 + 41/41 files passing, before any code was written.

## Why B15, and why this one didn't need a backend-blocker disclosure

Unlike B10/B12, this backend already has a real, dedicated citation system — `orca/serve/citations.py` (`orneur.sources/1` schema) — computing genuine per-source records (never inferred from the answer text after the fact) and delivering them both on the SSE `done` event and persisted per-message in the transcript. The prior screen matrix noted this ("backend `source_summary`/`sources` fields exist, unused by the frontend"); this phase read the actual module and built the UI around its **real** shape, not the contract's own illustrative, richer schema.

## The contract's schema vs. the real one — read, not assumed

`docs/B15_IMPLEMENTATION_CONTRACT.md` proposes a `SourceCitationView` with `tenantId`, `access: 'allowed'|'denied'|'unknown'`, `integrity: 'matched'|'mismatched'|'unknown'`, `support: 'supported'|'conflicting'|'unsupported'|'unassessed'`, and `claimAnchorId` — explicitly labeled *"a proposed schema to adapt, not an assertion of existing API."* The real backend (`orca/serve/citations.py`) computes none of these: its per-source fields are `ref`, `kind`, `filename`/`doc_id`/`url`, `locator`, `excerpt`, `excerpt_sha256`, `retrieved_at`, `cited_in_answer`; the summary carries `grounding` (`none` / `retrieved_not_cited` / `cited` / `evidence_state_only`), `source_count`, `retrieval_performed`. This phase builds the UI from exactly that real shape and does not invent the richer contract fields — a structural test asserts none of `access`/`integrity`/`support`/`revoked`/`claimAnchor` ever appear in the rendering code.

## What was implemented

1. **Inline citation markers**: `mdToHtml(md, sources)` converts `[D1]`, `[D2]`, etc. into real, clickable, keyboard-focusable badges **only when a matching `source.ref` exists** in the real sources array for that message. A `[D#]`-looking bracket with no matching source is left as plain literal text — "no citations means no fabricated references" applies exactly as much to a false-positive marker as to inventing a source outright.
2. **A collapsed-by-default Sources panel** below the message (`renderSourcesPanel()`), matching the contract's "unobtrusive... closed by default." Its summary label is honest about grounding: `"Sources (N cited)"` when at least one source was actually cited, or `"Sources consulted (N, not directly cited)"` when retrieval happened but the model's answer cites none of them — the exact distinction `citations.py` itself draws (`retrieved_not_cited` vs `cited`), never collapsed into a single implied-verified label.
3. **Inline-to-panel linking**: clicking a `[D#]` marker opens the panel (if closed) and scrolls/flashes the matching source row — the contract's "Inline source preview," without a separate popover/dialog surface in this increment (see limitations).
4. **Reload persistence**: `openSession()` now binds each reloaded past message to **its own** persisted `meta.sources` (confirmed real by reading `orca/serve/conversations.py`'s `transcript()`, which includes a message's `meta` exactly when the backend originally set it) — not the live/latest conversation's citations, satisfying the contract's "bind to the correct answer revision" requirement at the level this backend actually supports (per-message, not per-answer-version within B11's edit/version lineage, which doesn't exist yet).
5. **Security**: every source `url` is passed through the existing, already-tested `_sanitizeLinkHref()` before ever becoming a real `<a href>` — the exact same function `mdToHtml()`'s own markdown-link handling already uses, not a new unvetted path. All text (`filename`, `excerpt`, `locator`) is escaped via the existing `esc()`.
6. **No fabricated grounding when there's nothing to show**: `grounding: "none"` or `"evidence_state_only"` (Truth Fabric answered with an evidence state but no per-passage records) correctly produce an empty `sources` array from the backend, which `renderSourcesPanel()` and `mdToHtml()`'s citation-marker logic both treat as "render nothing" — never a placeholder or loading state standing in for data that was never retrieved.

## A real bug caught by live verification — the exact same class found twice before this session

Simulated a two-source cited answer live: the Sources panel rendered **fully expanded by default**, not collapsed. Root cause: `.sources-list{display:flex}` as the base rule out-specified the browser's own `[hidden]` attribute styling — identical to the bug already found and fixed for B05's `.model-details` panel. Fixed the same way: `.sources-list{display:none}` as the real default, `.sources-list.open{display:flex}` as the authoritative toggle. Reproduced and confirmed fixed live, both themes. A structural regression test now guards this exact pattern directly (reading the CSS source, not just behavior), on top of the two now-fixed instances already covered this session.

## Verified live, in a real browser, both themes

Rendered a two-citation answer (`[D1]`/`[D2]` both backed by real-shaped source data matching the backend's exact schema): both markers became clickable badges, the panel stayed collapsed by default, clicking `D1` opened the panel and scrolled to/flashed the correct row, the `web_page` source's URL rendered as a real sanitized link. Confirmed identical correct behavior in Meridian light theme.

## Tests

```
node --test tests/frontend/test_b15_citations.mjs   # 9 tests, new
node --test tests/frontend/*.mjs                       # 111/111 passing (was 102)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

Structural guards: no fabricated access/integrity/revocation/support fields; the `[hidden]`/`display` specificity bug can't recur; URLs always routed through `_sanitizeLinkHref()`; `openSession()` binds to each message's own persisted sources. Behavioral tests exercise the real `renderSourcesPanel()` and `mdToHtml()` citation-marker logic against a minimal fake DOM, including an explicit `javascript:` URL rejection test.

## What was deliberately not built in this pass, and why

- **The optional Source Lens** (a separate desktop contextual inspector / mobile bottom sheet for "claim associations and state") — the contract marks this optional, and the real backend has no claim-association data to inspect beyond what the inline preview already shows (a source is linked to its `[D#]` ref, not to a finer-grained "claim" concept). Building a separate surface with nothing further to disclose would not add real information.
- **Revocation/update handling** ("Handle source updates/revocations") — the real backend has no revocation concept for a retrieved passage (an uploaded document can be deleted, but there is no observed endpoint that revokes a specific prior citation after the fact). Not fabricated; not built.
- **B11's "message version" binding** — citations correctly bind to a specific persisted message today, but B11 (Editing & Versions) itself remains `NOT STARTED`, so there is no second version of the same message to test drift against yet.
- A live, real end-to-end RAG-grounded answer (uploading a document, asking a question that genuinely retrieves it) was not driven through the actual backend in this pass — verification used realistically-shaped source data matching the exact real schema, consistent with this session's established practice when a full live round-trip is materially slower to set up than a scoped, schema-faithful simulation; the backend's own data-shape was independently confirmed correct by reading `orca/serve/citations.py` directly, not assumed.

## Honest verdict

**`ENGINEERING PASS — INDEPENDENT REQUALIFICATION PENDING`** for B15's default-reading and inline-preview scope specifically — this is the one B-series increment this phase did not need to report as `PARTIAL` against the available backend, since the real citation data already existed and the UI faithfully represents exactly what it provides, no more and no less. The optional Source Lens and revocation handling are disclosed as out of scope above, not fabricated or silently skipped.
