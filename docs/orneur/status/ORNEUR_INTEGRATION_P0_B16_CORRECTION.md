# Immediate P0 — B16 Correctness Correction

Per the CTO's Phase C-I Continuation Directive, before proceeding into Phase C.

## What was fixed

Both `removeAttachment()` and `_deleteOrphanedUpload()` previously treated `r.ok` (bare HTTP 200) as proof of deletion, and treated any `r.status === 404` as a non-failure. Both are now wrong on this backend, confirmed by reading `delete_doc()` directly:

1. **HTTP 200 does not prove deletion.** `doc_store.delete_doc()` can return `False` without raising; the route still answers `200 {"deleted": false, ...}`. Fixed: only a literal `data.deleted === true` is treated as confirmed. A `200` with `deleted: false` now shows an honest "The server did not confirm this document was deleted" state and **preserves the chip**.
2. **403 `retrieval_unauthorized` handled explicitly.** Both upload and delete can refuse this way (authorized-index admission/removal denied). Shown with the server's own `error` text, chip preserved, explicitly **not** routed through `_handleSessionExpired()` — this is not session expiry.
3. **404 is ambiguous, now distinguished.** `delete_doc()`'s two 404 shapes differ in their body: "No such document in this conversation" echoes `doc_id` and `code: "not_found"` — genuinely confirms absence, chip removed. The session-ownership 404 ("session not found" via `_get_session`) has no `doc_id` field, an `error_id` instead — tells us nothing about whether the document exists, now treated as **unconfirmed**, chip preserved.
4. **Visible attachments are now preserved on any unconfirmed/failed outcome** — the above three fixes plus the pre-existing 500/network-error handling all converge on "never remove the chip without positive confirmation."
5. **`_deleteOrphanedUpload()` (the fire-and-forget orphan-cleanup helper) gets the identical fix**, not just `removeAttachment()` — it had the same two bugs (bare `r.ok`, blanket 404-as-success).

## Regression tests added

`removeAttachment()`: 200 deleted:true (removes), 200 deleted:false (preserves, shown as unconfirmed), 403 retrieval_unauthorized (preserves, not session-expiry), 404 confirmed-absent (removes), 404 ambiguous (preserves), 500 document_store_disagreement (preserves). `_deleteOrphanedUpload()`: the same 200/404 distinctions, plus 401/403/500/network-failure logging (already covered by the prior security addendum, re-verified unchanged). 175/175 JS tests passing total (was 167), 13/13 Python.

**Live-verified**: the happy path (real upload → real remove → real `deleted:true` → chip correctly removed) end-to-end against the actual merged backend. The new edge-case branches (200 `deleted:false`, 403 `retrieval_unauthorized`, ambiguous 404) are verified via unit tests built from the exact response shapes read directly from `delete_doc()`'s source, not independently reproduced live — forcing those exact server-side conditions (an authorized-index revocation, a doc-store/registry desync) through the public API within this pass's scope was not attempted; stated honestly rather than claimed as live-reproduced.

## Backend-owned durable orphan reconciliation — unresolved dependency, restated

Already documented in full in `ORNEUR_B16_SECURITY_ADDENDUM.md`'s "Backend reconciliation contract" section (recommendation: extend the existing idle-session eviction sweep to reap unreferenced documents — no new API surface needed). Restated here per the directive's explicit instruction: this P0 correction makes the frontend **honest** about confirmation state; it does not and cannot make frontend-only cleanup **reliable**. That gap remains open, owned by the backend, not worked around by inventing a client-side deletion sweep (explicitly the directive's own instruction: do not invent one that could erase intentionally retained document-only conversations).

## Honest verdict

**Fixed and regression-tested.** All 6 numbered points in the directive's P0 section are addressed: deleted-value check, explicit 403 handling, ambiguous-404-as-unconfirmed, chip preservation on any unconfirmed outcome, the named regression test matrix, and the backend-reconciliation dependency restated rather than silently worked around.
