# PR #111 — CTO corrective review response (2026-10-28)

Both issues reproduced, fixed, and regression-tested. PR #111's own SHA/history untouched.

## Issue 1 — `session_messages()` missing `_temporary_block()`

Confirmed exactly as raised: `GET /api/session/{id}/messages` (the main transcript route) and the adjacent `GET /api/explain/{id}/{message_id}` checked ownership only, never the temporary-chat terminal state — the same class of gap as the version/edit/regenerate routes fixed in the prior closeout, just missed on those two.

- Added a **failing-before** test for each route (`test_the_main_transcript_read_route_is_refused_after_genuine_expiry_and_actually_triggers_the_real_deletion`, `test_explain_answer_is_refused_after_genuine_expiry`), confirmed both fail against the unpatched code (409 expected, got 200/404).
- Fixed both routes with the same `_temporary_block(session_id)` guard every other owned-session route already has. Confirmed both tests now pass.
- Audited every other session-scoped route for the same exposure: `/api/sessions/search` already excludes temporary sessions entirely (`temporary_chat.is_hidden`); `/api/session/{id}/export` already refuses all temporary chats unconditionally; `/api/session/load` only touches long-term memory, which temporary chats never commit to. None of these needed a change.
- **One pre-existing test broke as a direct, correct consequence**: `test_close_deletes_the_transcript_before_reporting_closed` asserted that reading a *closed* temp chat's transcript returns `200` with an empty list. That assertion encoded the bug's own symptom — every other guarded route already refuses a closed/expired temp chat with 409. Updated the assertion to the now-consistent behavior (409 `temporary_closed`); the dedicated `/temporary` status route remains the correct way to confirm a chat was closed.

## Issue 2 — Redis consistency after a committed edit

Confirmed the mechanism: `session_store.save_session_state()` and `delete_session()` silently swallow every exception, by design (a normal chat turn must never crash over Redis being down). But `_replace_visible_copy()` (this branch's own prior B11 closeout fix) called `persist_to_redis()` for its side effect only, never checking whether the write actually happened — so a silently-failed write left the **old, pre-edit value sitting in Redis under its own still-live TTL**, fully readable by another application instance as if it were current.

- Reproduced directly against a **real, locally-running Redis** (isolated on db 15, same convention as the existing `test_multiworker_session_and_fault_injection.py`, skips rather than fakes a result if unreachable): a forced write failure leaves the old value in place; `load_session_state()` returns it unchanged, proving the exact "another instance recovers stale history" scenario.
- Fixed: `save_session_state()` and `delete_session()` now return `True`/`False` (never raise) instead of swallowing silently with no signal; `_replace_visible_copy()` treats a reported write failure as a genuine sync failure (same eviction + audit-log path the prior closeout already built), and the eviction's own `delete_session()` result (`redis_entry_cleared: true/false`) is now part of that audit record, so a residual risk (Redis still unreachable at cleanup time) is visible, not assumed resolved.
- The edit response itself is unaffected by any of this: `created: true` and the real `active_content` are always returned; only the `live_sync` field reflects the Redis outcome. An already-committed edit is never reported as failed.
- 5 new tests in `tests/test_redis_post_commit_consistency.py`, all against real Redis: the raw reproduction, the full HTTP-route failure path (confirms no stale entry survives and `live_sync: false`), and a healthy-write regression guard (confirms Redis genuinely mirrors the live agent history when nothing is wrong).

### A second, more severe bug, caught by this session's own regression suite before it shipped

The first version of the issue-2 fix made `save_session_state()` return `False` whenever Redis was simply **not configured** (`REDIS_URL` unset — the default for this entire test suite, and for any single-instance deployment) — indistinguishable from a genuine failure. That meant **every single message edit**, in the overwhelmingly common no-Redis case, would incorrectly trip the live-sync-failure path: evicting the session and reporting `live_sync: false` for a condition that was never actually a problem (no shared cache means no other instance could ever read anything stale). Caught by running the broader regression suite (`test_audit_cursor_backend_adversarial.py::test_b11_security_and_failure_semantics` failed, asserting a session should still be cached after an edit). Fixed: "Redis not configured" now correctly returns `True` (nothing to worry about); only a **configured-but-failed** write returns `False`. Two dedicated regression tests added directly guarding this exact distinction (`test_save_session_state_treats_redis_disabled_as_a_no_op_not_a_failure`, `test_a_plain_edit_with_redis_disabled_is_not_treated_as_a_live_sync_failure`), placed in the always-run `test_b11_post_commit_live_sync.py` rather than the Redis-gated file, since they must run even when no local Redis is available (as CI's own environment will be).

## Full-suite reconciliation (single invocation, exact test identities)

```
pytest tests/ (default verbosity, same 12 --ignore flags as before)
collected 9526 items / 31 skipped
...
27 failed, 9180 passed, 344 skipped, 6 xfailed, in 1452.28s (24m12s)
```

**Arithmetic now fully reconciled** (the prior report's flagged-as-unresolved 31-test gap): total discovered = 9,526 + 31 = **9,557**. Execution outcome sum = 27 + 9,180 + 344 + 6 = **9,557** — exact match. The "31 skipped" in the collection header are pytest's own collection-time skips (module-level `pytest.mark.skipif`, mostly `test_*_live_neon.py` files needing a real Postgres/Neon connection not present here), already folded into the final 344; the remaining 313 are ordinary runtime skips.

**Failure identities, diffed exactly** against the known 28 pre-existing failures:
- **26 of 27 are an exact, by-name match** to the known baseline.
- **1 new**: `test_truth_fabric_integration.py::test_verify_answer_supports_a_grounded_claim` — a `TruthTimeoutError` from claim extraction (nothing in its code path touches `orca/serve/api.py`, `session_store.py`, or anything else in this diff). Re-run in isolation twice: failed once more under continued load (94s, both of its own internal retries exhausted), then **passed cleanly** (48.57s) once the machine wasn't running a 20+ minute full suite concurrently — consistent with the same resource-contention-under-full-suite-scale pattern already documented for two other tests in the prior report, not a regression.
- The 3 baseline entries absent from this run are the same ones explained before: 2 deliberately excluded (real-Ollama files), 1 (`test_container_adversarial`) genuinely passed again, consistent with its own timing-sensitive nature.

**Net: zero regressions from either issue-1 or issue-2 fix**, confirmed by exact test identity, not count alone.

## Preserved

- B11/B16 fixes from the prior closeout: untouched, still green (`test_b11_message_versions.py`, `test_b11_post_commit_live_sync.py`'s original 7 tests, `test_b13_version_endpoints_expiry_closeout.py`'s original 7 tests all still pass unmodified).
- Approved frontend: no frontend file touched this round; `node --test tests/frontend/*.mjs` — 225/225.
- PR #111's own SHA and history: untouched. All work on `claude/pr111-closeout-2026-10-27`.

## Handoff

- **New head**: `claude/pr111-closeout-2026-10-27` (SHA below, pushed).
- **Diff this round**: `orca/serve/api.py` (2 routes guarded), `orca/serve/session_store.py` (bool returns, disabled-vs-failed distinction), `tests/test_redis_post_commit_consistency.py` (new, 5 tests), `tests/test_b11_post_commit_live_sync.py` (+2 tests), `tests/test_b13_version_endpoints_expiry_closeout.py` (+2 tests), `tests/test_b13_temporary_chat.py` (1 assertion corrected to match the now-consistent behavior).
- No protected merge, deployment, paid services, or model training occurred.
