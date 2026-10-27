# B16 reconciliation — PR #112 and PR #114 against the latest PR #111

Per the CTO's directive, step 2 (priority 2): *"Reconcile PR #112's document-deletion correction and the newer PR #114 backend changes with the latest PR #111. Since the branches have diverged, inspect ancestry and resolve changes deliberately."*

## Ancestry findings (inspected before merging anything)

- **PR #111** (`test/combined-candidate-fresh`): consolidated candidate, head `571f7d8` at the start of this reconciliation (my Phase E / B11-requalification work already merged in).
- **PR #112** (`cursor/doc-delete-integration-a8b0`): base `9250683` — an **older, different lineage** (`test/combined-pr85-pr98-candidate`), not PR #111's branch at all.
- **PR #114** (`cursor/cancellation-reconcile-a8b0`): base `6b2d37a` — a genuine ancestor of PR #111's current head (the original "consolidated draft PR #111" tip, before my Phase E/B11-requalification commits). PR #114's own branch history (`git log`) shows it was built through the *same* `9250683` starting point as PR #112, then forward through my own Phase C/D/E merges (`35b4fa4`), then four of Cursor's own commits.

**Decision: PR #114 supersedes PR #112 for document deletion. Only PR #114 was merged; PR #112 was deliberately NOT merged separately.**

Verified, not assumed: diffed `orca/docs/store.py` from both PRs against their respective bases. The `_fallback_txn()`, `_fallback_has_doc()`, `_purge_fallback()`, and `delete_doc()` implementations are functionally identical between the two PRs (same per-host `fcntl` lock, same temp-file-plus-`os.replace` rewrite, same `last_delete_state` reporting shape) — PR #114 is a rebase/re-implementation of PR #112's exact fix against the current lineage, not an unrelated change. The one piece of PR #112 not obviously visible in PR #114's diff — the `409 temporary_expired` refusal for deleting a document in an expired temporary chat — **is present in PR #114**, just implemented via the shared `_temporary_block()` helper (confirmed by reading its body: `decision = temporary_chat.enforce(session_id)` → `409` with `code: decision["code"]`, the same `temporary_expired` code) rather than inline, and PR #114's `delete_doc()` route calls it, matching PR #112's behavior exactly.

Merging both would have reintroduced the identical `delete_doc()`/`_purge_fallback()` logic through two different commit paths — a guaranteed conflict with no semantic benefit. Merging only PR #114 was the deliberate, ancestry-informed choice, not an accident of convenience.

## What PR #114 adds beyond document deletion (per its own description, cross-checked against the diff)

- **Cancellation vs. disconnect, properly separated**: `orca/serve/generations.py`'s `finish()`/new `end_worker()` now only write `cancelled` when an authenticated stop was already recorded *and* the upstream is proven `stopped`. A browser disconnect alone writes `interrupted_unknown`, never `cancelled`. A race where completion observes a stored stop before the upstream is proven stopped leaves the record `running` so a later explicit `finish(cancelled)` can still commit (the PR's own description notes an earlier head, `a6e2ed4`, failed this exact race on trial 3; `8f2b11a` — the actual merged head — is the fix for it).
- **`orca/docs/orphan_reconcile.py`** (new, 255 lines): inventories the live document directory, the authorized index, and temporary-chat records. Dry-run by default; the only deletion ever actually applied is a regular, non-symlink, document-only temp file older than 60 seconds. Everything else uncertain (registry/fallback/vector/binding/symlink/failed-temp-chat disagreements) is reported, never silently removed. Explicitly **not** atomic or exactly-once, by its own docstrings — that claim is preserved as written, not strengthened by this reconciliation.
- **`retry_failed_closure()`** (`orca/serve/temporary_chat.py`): lets an owner retry a failed temporary-chat closure, but only when the intended terminal state was actually stored and the transcript is genuinely gone — not a blind "try again" that could silently succeed on stale state.
- **Edit replay with the same idempotency key now reports `reconciled: true`** (`orca/serve/message_versions.py`) instead of silently returning the old `created: false` shape unchanged — makes the already-correct dedup behavior (which our own B11 requalification work depends on and just live-verified against the real backend) explicit in the response contract.
- **`done` event's `user_message_id`** is now gated on the user line actually being readable in the transcript, not merely persisted — tightens a prior B11 assumption in our favor (we already never infer the user message id client-side; this makes the one case where it *is* returned strictly more honest).

No frontend changes were required for any of this: `orphan_reconcile.py` exposes no HTTP route (an internal/ops module, not a capability to wire a UI to), and the cancellation/disconnect distinction is backward-compatible with the existing `interrupted_unknown` handling already in `conversation.html` (confirmed: that handling already treats `interrupted_unknown` as a derived, non-authoritative observation, never equates it with `cancelled` client-side — this PR makes the *server* enforce the same distinction more strictly, which only removes a prior server-side false-positive risk, it does not change the client contract).

## Merge mechanics (no force-push, ancestry verified first)

1. Confirmed `git merge-base --is-ancestor` for PR #114's base against the current PR #111 branch head — true.
2. Dry-run conflict check (`git merge-tree` plus a file-overlap diff) — **zero conflicts, zero overlapping files** between PR #114's changes (backend: `store.py`, `api.py`, `generations.py`, `message_versions.py`, `retention.py`, `temporary_chat.py`, plus new `orphan_reconcile.py`) and this branch's own recent work (frontend: `conversation.html`, `tests/frontend/*`, `docs/orneur/status/*`).
3. Real `git merge --no-edit` (not rebase/cherry-pick) of `origin/cursor/cancellation-reconcile-a8b0` into the consolidation worktree.
4. Also merged forward the B11 Cancel-after-uncertain-save fix (this session's Priority 1 work, `claude/b01-b16-backend-integration-2026-10-24` @ `91ed8ce`) into the same worktree, same way — zero conflicts, zero file overlap.
5. Pushed via a plain fast-forward (`git push origin HEAD:test/combined-candidate-fresh`) — no force, no history rewrite.

## Tests

```
node --check <extracted inline script>   # syntax OK
node --test tests/frontend/*.mjs          # 225/225 passing
pytest tests/test_cancellation_lifecycle.py tests/test_generation_atomicity.py \
       tests/test_b10_generation_state.py tests/test_p0_authorized_context.py \
       tests/test_b2_conversation_documents.py tests/test_b13_temporary_chat.py \
       tests/test_g006_tenant_isolation.py tests/test_session_ownership_isolation.py \
       tests/test_b11_message_versions.py tests/test_conversation_shell.py \
       tests/test_background_task_tracking.py tests/test_audit_cancellation_and_attachments_addendum.py \
       -q   # 147 passed, 2 xfailed
```

`tests/test_audit_cancellation_and_attachments_addendum.py` includes `test_b16_delete_doc_response_contracts_and_dom_consistency`, which exercises the same `delete_doc()` response contract PR #112's own standalone `tests/test_doc_delete_consistency.py` covered — that standalone file was intentionally not ported (it belongs to PR #112's superseded implementation path and tests response shapes PR #114 already restates equivalently); this addendum test is the retained coverage for that contract and is green.

A full-repo collection pass (`pytest --collect-only`) confirms 9,566 tests collect cleanly after the merge, with exactly 4 pre-existing collection errors, all missing optional third-party packages (`torch`, `mcp`) unrelated to this change — not introduced by this reconciliation. See the companion qualification report for the full-suite execution result.

## Preserved protections (explicitly checked, not assumed)

- **Authorization**: `delete_uploaded_document()` and `ProductRetrievalDenied` → `403 retrieval_unauthorized` handling is unchanged.
- **Deletion honesty**: `atomic: false` is still reported on every response; a partial deletion still returns a 500 `document_store_disagreement` (when the index was removed but the legacy store wasn't) or 409 `delete_incomplete`, never a silent 200.
- **Orphan recovery**: dry-run default preserved; only a narrowly-scoped, non-symlink, aged document temp file is ever actually deleted.
- **Temporary-chat protections**: `_temporary_block()` (shared across all 5 routes, now including document deletion) still refuses document deletion with `409 temporary_expired` on an expired temporary chat.
