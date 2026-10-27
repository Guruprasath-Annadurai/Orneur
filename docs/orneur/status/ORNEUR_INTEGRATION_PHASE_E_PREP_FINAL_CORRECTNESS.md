# Phase E Prep, Continued — Final Correctness Obligations

Per the CTO's "Phase E–I Execution Continuation" directive's two named follow-ups, addressed before Phase E proper.

## 1. B11 ambiguous save — second pass: idempotency key, not text comparison

The prior pass's `GET .../versions` + `active_content` text-comparison reconciliation was correctly flagged: a text match is not definitive proof of commit (a later, unrelated edit could coincidentally produce matching text, or move the active version again before reconciliation runs).

**Read `orca/serve/message_versions.py`'s `edit()` directly** rather than assume. It already *is* the authoritative mechanism the directive asks to coordinate with Cursor for — no new backend capability was needed:

```python
existing = _find_key(record, key)          # looks up by the EXACT idempotency_key, under a real per-message lock
if existing is not None:
    if existing.get("request_hash") != request_hash or existing.get("kind") != "edit":
        raise MessageVersionMismatch(...)   # different content under the same key -- a real conflict, not ambiguous
    view = _public(record); view["created"] = False
    return view                             # the SAME version, authoritatively -- no duplicate
# ...otherwise: a genuinely new version is created, created: True
```

**Replaced the text-comparison reconciliation with a same-key retry.** `_pendingEditKey`/`_pendingEditContent` persist a save attempt's key across retries, cleared only on a **definitive** outcome (a real success, or a real non-network rejection like empty content or a genuine `idempotency_mismatch`) — never on an ambiguous network failure. One automatic retry (same key) happens immediately on a thrown fetch error, since most transient blips resolve there silently; if that also fails, the UI shows a genuinely uncertain state and explicitly explains that a further manual retry is safe (same request identity, never a duplicate) — it does not recommend a fresh-key retry, and does not guess an outcome either way. Changing the draft content after an uncertain outcome *does* mint a fresh key, correctly, since that is a genuinely different edit, not a retry of the ambiguous one.

**Live-verified against the real backend**, not just unit tests: sent the identical `Idempotency-Key` + content twice via raw `curl`. First response: `created: true`, a new `version_id`. Second response: `created: false`, the *exact same* `version_id` and `active_content`. Independently confirmed via `GET .../versions` that `version_count` stayed at 2 (not 3) — no duplicate was created. This is the real mechanism the fix relies on, confirmed end-to-end, not assumed from reading source alone.

**Tests**: 5 new/rewritten in `test_b11_inline_edit.mjs` — single-failure-then-successful-retry (same key proven via assertion), two-failures-uncertain-state (key retained, draft preserved, no "not saved" claim), manual-retry-reuses-key, and content-change-mints-a-new-key. 28/28 passing in that file.

## 2. B13 failed-close handling — kept truthful, documented for Cursor

**No behavior change needed beyond what the prior pass already did** (confirmed by re-reading `temporary_chat.finish()`): a terminal `state: "failed"` response already shows the real server error, never implies the transcript was deleted, and permanently disables the Close button (via `closeBtn.dataset.permanentlyFailed`) rather than implying a retry could succeed — because `"failed"` is itself in `_TERMINAL`, so the backend's own short-circuit means a retry of `POST .../temporary/close` returns the *same stale record* without ever attempting deletion again.

**Documented as a real, open backend dependency, not silently left for later**: this state has **no recovery path through the existing API at all**. There is no "force delete," no "retry deletion," no admin override reachable from this interface. The CTO directive's instruction to "provide accurate, restrained recovery guidance using the existing approved interface" is honored precisely by *not* inventing a recovery affordance the backend cannot back up — the honest guidance is the disabled button and the accurate error text already shown, stating plainly that clicking Close again cannot help.

**Backend recovery mechanism needed from Cursor** (stated explicitly, to close this loop): `temporary_chat.finish()` should allow a genuinely new attempt to retry deletion from a `"failed"` state — e.g., excluding `"failed"` from the short-circuit check (only `{"expired", "closed"}` should skip straight to returning the cached view; a `"failed"` record should re-attempt `_delete_contents()` on the next `finish()` call) — or, if `"failed"` must remain terminal by design, a distinct recovery route (e.g., a scheduled sweep, or an explicit `POST .../temporary/retry-close`) is needed so a transcript that failed to delete isn't permanently stuck with zero path to ever completing deletion through normal use. This is the same category of durable-reconciliation gap already on record for B16's orphaned-attachment cleanup — restated here for B13's equivalent case.

## Honest verdict

**IMPLEMENTED AND INTEGRATION-TESTED** (not independently qualified, not production authorized). B11's save-outcome correctness is now built on the backend's own authoritative idempotency mechanism rather than an inference, confirmed live. B13's failed-close handling remains truthful with no new behavior needed, and its genuine recovery gap is documented precisely for Cursor rather than papered over with a fake "try again" affordance.
