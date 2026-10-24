# Cancellation, deletion, and orphan reconciliation

This branch starts at PR #111 `6b2d37ad5bee2e381e56246a679d59fffeaad930` (`test/combined-candidate-fresh`). PRs #108–#113 are unchanged.

## Cancellation

A browser disconnect does not write `cancelled`. An in-stream authenticated stop closes the attempt and the terminal generation event is written after that stop is stored, so the event state is `cancelled`. A disconnect inside the loop is stored as `interrupted_unknown` with upstream `unconfirmed`. A later POST can confirm `cancelled` only when the stored upstream is already `stopped`. An unconfirmed upstream stays `interrupted_unknown` with `cancel_requested` true and `cancel_accepted` false.

`completed`, `cancelled`, `failed`, and `interrupted_unknown` stay distinct. `finish` does not replace an existing terminal state, so a late completion cannot overwrite a cancellation. A completion that sees a stored stop before the upstream is proven stopped leaves the record `running`, so the explicit cancel publication can still commit. It does not invent `interrupted_unknown` for that race. A live lock that has been dropped is reconciled to `interrupted_unknown`, not to `cancelled`. The lock is single-host `flock`.

## Deletion

`delete_uploaded_document()` remains. The keyword fallback is purged only after the collection delete succeeds. Partial state is reported with `atomic: false`. The registry stays when a store still holds the document, and the authorized copy is not re-admitted. HTTP 200 `deleted: false` is preserved when the index was not removed, matching the client chip contract. An index removal plus a failed legacy delete stays HTTP 500 `document_store_disagreement`.

## Orphan uploads

`retention.reconcile_orphan_uploads()` inventories the live document directory, the authorized-index directory, and temporary-chat records. Dry-run is the default. The only applied deletion is a regular, non-symlink document temp file older than 60 seconds, and a second apply removes nothing further. Keyword fallback files, vector files, the session registry, authorized bindings, index temp files, symlinks, and failed temporary-chat records are report-only. A registry session that still lists documents is marked `preserve`. A fallback line whose document is absent from the registry is a `storage_disagreement` and is kept. A binding whose `user_id` does not match its directory is `owner_uncertain` and is kept. The scan sets `atomic` and `exactly_once` to false.

## Other contracts

`user_message_id` is added to the stream `done` event only after the user line is readable in the transcript. An edit replay with the same idempotency key returns `reconciled: true` and does not create another version. `retry_failed_closure()` retries a `failed` temporary chat for the same owner and only writes `closed` or `expired` when the transcript is gone and that intended state was stored.

## Local tests

`tests/test_cancellation_lifecycle.py`: 16 passed. The cases cover disconnect without a stop, unconfirmed stop after POST, proven stop, duplicate cancel, dropped POST, reread of an unknown termination, stale heartbeat, a live lock held by another process, worker failure, failed temporary closure, missing intended state, edit replay, transcript-confirmed `user_message_id`, temp-file deletion, and an uncertain-store scan that deletes nothing.

`tests/test_generation_atomicity.py`, `tests/test_b10_generation_state.py`, `tests/test_b11_message_versions.py`, `tests/test_b13_temporary_chat.py`, and `tests/test_audit_cancellation_and_attachments_addendum.py`: 43 passed.

`tests/test_p0_authorized_context.py`, `tests/test_b2_conversation_documents.py`, `tests/test_doc_session_no_model_runtime.py`, `tests/test_b11_message_versions.py`, and `tests/test_g006_tenant_isolation.py` were run on the earlier head of this branch: 85 passed, 2 xfailed. They were not re-run after the inventory change.

Production authorization remains DENIED. No model was loaded. The acceptance ledger was not modified.

Verdict: `ENGINEERING PARTIAL — SPECIFIC BLOCKERS`.
