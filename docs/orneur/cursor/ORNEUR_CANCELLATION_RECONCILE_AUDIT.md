# Cancellation, deletion, and recovery

PR #114 branch `cursor/cancellation-reconcile-a8b0`. PR #113 is not changed.
The product parent is `test/combined-candidate-fresh` at `571f7d8c750ba99953222cd39eecfee5ec8038ef`, merged without a rebase.

## Cancellation

A browser disconnect does not write `cancelled`. An authenticated stop stores `cancel_requested` immediately. That flag is not proof the upstream stopped.

The stream loop leaves the upstream `aclosing` block before it writes the terminal generation record. `cancelled` is written only when that close returned and an authenticated stop is already stored. The generation SSE is read back from that record, so the event and a later GET name the same state.

`aiter_blocking` reports `closed` only after `close()` returns. If `next()` is still in flight, the report is `close_deferred_until_inflight_read_returns` and the later callback does not rewrite the terminal record. A raised `close()` is `close_failed`. Both stay `interrupted_unknown` even when the stop flag is set.

`ModelGateway._stop_upstream` treats `runtime.cancel()` as a cooperative flag. Proof is `aclose()` returning. For Ollama that means the local HTTP response context exited. It does not mean the remote server aborted an in-flight token. A local HTTP server observed that connection drop in `tests/test_upstream_closure_contract.py`.

If the worker sees the stop before the gateway iterator is entered, the closure reason is `upstream_not_started`. No request was opened. An authenticated stop can then be `cancelled`. A disconnect in that window stays `interrupted_unknown`.

`completed`, `failed`, `cancelled`, and `interrupted_unknown` stay distinct. A terminal record is not overwritten. A dead or stale lease becomes `interrupted_unknown`, not `cancelled`. The lock is single-host `flock`.

## Orphan uploads

`reconcile_orphan_uploads()` inventories the document directory, the authorized index, and temporary-chat records. It does not delete them. `apply=True` still returns `removed: []`, `deletion_performed: false`, and `automatic_deletion: "refused"`. Age is not orphan proof. A temp file is `uncertain`: `active_upload` or `interrupted_upload` is only an age hint. Referenced sessions and matching bindings are `referenced`. A fallback line the registry does not list, and a failed temporary closure, are `partially_deleted`. Nothing is classified `orphan_safe`.

The missing piece is an owner-scoped journal committed before the bytes, with `upload_id`, owner, session, and a state. Deletion would be allowed only when that journal says abandoned, the owner matches, no live lock is held, and the file is opened with `O_NOFOLLOW` inside the journal directory. This layout does not have that journal. `atomic` and `exactly_once` stay false.

## Temporary-chat recovery

`POST /api/session/{session_id}/temporary/closure/retry` retries the stored `intended_state` for the owning account. The contract is `docs/orneur/cursor/ORNEUR_CLOSURE_RECOVERY_CONTRACT.md`. `closed` and `expired` are returned only when the re-read stores are empty. A remaining transcript, message version, document registry row, keyword fallback, episodic file, generation record, live session, title, or authorized binding stays `failed` and is listed in `remaining`. Revocation does not prove authorized-index bytes are gone, so a binding blocks success. The route does not guess a final state and does not grant another account access.

## Edit cache

If `message_versions.edit` commits and `_replace_visible_copy` then raises, the edit route returns HTTP 500 `edit_saved_cache_uncertain` with `authoritative_content`. The same idempotency key returns HTTP 200 `reconciled: true` and does not append a second version. When the parent text is still in the live history, that replay replaces it. The conversation UI was not changed. Claude's existing client treats HTTP 500 from this route as ambiguous and retries the same key.

## Repair boundary

PR #113 stays `fd04b135d376632b2acefdbbdd96fd3dbf71f8e1`. This assignment does not extend autonomous execution. `patch_generation` stays `NOT DEMONSTRATED`. `repair_proof` stays false where a real observed repair is absent. Production authorization stays `DENIED`. No model was run. No patch is executed when user-namespace isolation is unavailable.

## Local tests

`tests/test_upstream_closure_contract.py` covers the known-bad publish-inside-close order, the product order, a failed close, a disconnect that stays unknown until a later post, a deferred in-flight read, a local HTTP close through `OllamaRuntime` and `ModelGateway`, and a gateway close that raises.

`tests/test_recovery_contracts.py` covers an edit rejected before commit, a write failure before replace, a cache failure after commit with a same-key heal, owner-scoped closure retry, remaining transcript evidence, and an authorized binding that blocks `closed`. The stand-in session is removed when the test ends. Leaving it in the process-wide map makes `_get_session`'s idle sweep raise `AttributeError` on `last_active` for a later request. Deterministic Unit Tests on `441bab64ab8230fddcf8445120dcef243d05045d` failed that way in `tests/test_session_ownership_isolation.py`.

`tests/test_cancellation_lifecycle.py` no longer expects an old temp file to be deleted.

Production authorization remains DENIED. No model was loaded. The acceptance ledger was not modified.
