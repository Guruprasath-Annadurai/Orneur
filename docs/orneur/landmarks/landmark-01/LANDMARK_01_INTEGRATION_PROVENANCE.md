# LANDMARK-01 — Integration Provenance

## 1. Starting SHAs (refreshed from GitHub before any change, 2026-10-28)

| PR | Head at start | Matches directive reference | CI at start | Base |
|---|---|---|---|---|
| #125 | `9298b157fe22c95c897d7afbcc9f2e21a99d256e` | yes | 9/9 success | `cursor/inference-session-isolation-ae9d` (#124) |
| #126 | `7ea44aed3e9dabb6d75e4d99fb0dba82a87c8edc` | yes | 9/9 success | #125 branch |
| #127 | `22225086873cba5274d3ad44aab9e7ef5a913230` | yes | 9/9 success | #125 branch |
| #128 | `a6def68d4154b83c8ffa3bdc605729be3b68ac05` | yes | 9/9 success | #125 branch |
| #129 | `485ca951e7b7bc2242cf71f323bf90af0656908f` | yes | 8 success, 1 not concluded; GitHub reported it CONFLICTING | #126 branch |
| #130 | `497073d2dfb45f82554fb260db3fe4d87b0b5019` | yes | 8 success, 1 not concluded | #127 branch |
| #131 | `040d694702d9d70bb0dbeb70d643bc19877dfcf4` | yes | 9/9 success (run 40711479614) | #127 branch |
| Claude frontend ref | `f7c004f1c297c93906099180a9dab00fc843fc01` | yes | 10/10 success | (own branch) |

`main` = `20a8546f`; every candidate is 31–39 commits ahead and 0 behind. No candidate has been merged.

## 2. Dependency map (verified with `git merge-base --is-ancestor`)

```
main 20a8546
 └─ … #117 sovereign mission → #118/#119 browser → #120/#121 mission → #122 backend programme → #123 G1 docker → #124 session isolation
     └─ #125  9298b15  inference qualification P0                          (frozen baseline)
         ├─ #126  7ea44ae  multi-turn context + Ollama deployment ids
         │    └─ #129  485ca95  privacy / ownership / frontend  (branched at #126 a686e5f; does NOT contain #126's last commit 7ea44ae)
         ├─ #127  2222508  DLP + reservation theft + transcript fencing       (Antigravity: FAILED_QUALIFICATION on P0-3 only)
         │    ├─ #130  497073d  SQLite fencing epochs + authoritative transcript   ◄── SELECTED
         │    └─ #131  040d694  alternative SQLite-authoritative transcript         ✗ not combined
         └─ #128  a6def68  alternative security implementation                       ✗ not used
```

## 3. Decision: #130 over #131 (they are never combined)

Both are corrections of the same Antigravity finding (P0-3) stacked on #127. Compared on the criteria in the directive:

| Criterion | #130 | #131 | Basis |
|---|---|---|---|
| Durable authority enforcement | **SQLite `session_authority` row**; commit validates fence + epoch + expiry + owner + revision CAS in one transaction | commit calls `authority_check` = **Redis `lease_held` read** inside the SQLite txn | #131's own CodeAnt note: "not atomic with SQLite commit; the lease can expire and a successor acquire it before this worker inserts" |
| Fencing epochs | yes (epoch bump on takeover) | no durable epoch (revision = `MAX+1`) | `conversations.py` |
| Redis role | advisory only; losing Redis cannot disable fencing | load-bearing for fencing; Redis flush/outage removes the fence | design docs |
| Crash safety | rollback + `reconcile_pending_exports` | rollback + `reconcile_export` | both |
| Revision monotonicity | `committed_revision` CAS | `MAX(revision)+1` | |
| Legacy migration | explicit `reconcile_legacy_session` | explicit `migrate_legacy_jsonl` | both |
| Cross-process tests | two-OS-process fencing test | multi-process lease takeover test | both |
| Test hygiene | tests `FLUSHDB` a hard-coded dedicated DB (15/14) | tests and the repro script `FLUSHDB` a hard-coded dedicated DB (15/14) | verified by `git grep flushdb` on both tips — **both** do; neither is preferable on this axis. This branch replaces every `FLUSHDB` in the suites with `tests/_redis_guard.py::safe_flush`, which refuses unless the database holds only ORNEUR keys |
| `/api/chat`+`/api/stream` integration | wired (`_persist_turn` → authority → commit) | partial | handoffs |

Neither has independent qualification; the integration is therefore labelled **provisional / unqualified**. #130's own defects found during this integration are listed in §5 and were fixed here, not hidden.

## 4. Commit-by-commit register of the integration branch (`claude/landmark-01-secure-chatbot-integration`)

Base: `485ca95` (#129 tip). Origin legend: **Cursor** = authored by Cursor agents; **Claude** = authored in this milestone; **Merge** = integration.

| Commit | Origin | What |
|---|---|---|
| `2222508`, `908c5f4`, `2e79766`, `7b730a1`, `497073d` | Cursor (#127 → #130) | DLP/reservation/fencing closure; SQLite fencing + authoritative transcript; CI follow-up. **Included unmodified by merge.** |
| `7a55c30` | Merge | Merge of #130 into the #129 lineage. Conflicts in `api.py`, `inference.py`, `conversations.py`. Resolution: #130's `acquire_authority → commit_turn` kept; #129's server message ids (`user_message_id`/`message_id`), `message_versions.seed`, ownership-bound `assemble_messages(user_id=…)` and the stream's temporary-chat lease kept; `StreamRedactor` re-indented inside the lease `try`; `_messages_from_turns` extended so the user row carries its server `message_id` (needed for edit overlay over SQLite rows). |
| `5bbd869` | Claude | Wave 1: invalid bearer ⇒ 401 (`get_current_user_optional`); `tests/test_auth_invalid_bearer_refused.py`; PR #111 Redis multi-worker suites brought into this lineage (all 30 pass). |
| `147e58b` | Claude | Wave 2: atomic quota admission (`_QuotaTicket`), `_TurnAuthority`, DLP-before-memory, durable-commit-first ordering, tri-state Redis lease, `renew_quota`, `persisted` status. |
| `91c9c83` | Claude | Reads no longer strand turn authority (`reconcile_legacy_session`); live-window redaction; truthful B1 journey; contexts tests re-seeded through the authoritative path; CI node suites. |
| `a835c53` | Claude | Temp-chat `closing` state, inode-verified lock, `commit_guard`, strict deletion verification, SQLite `secure_delete`; stream idempotency; `history_unavailable`; reliability matrix; multi-process temp-chat tests. |
| `06d98b9` | Claude | `stable_deployment_id(..., family)` (single Ollama tag behind several tiers); live concurrency + controlled-provider browser journeys. |
| `8713515` | Claude | Canary, context-window bounds, a11y smoke. |
| `06a6788` | Claude | Authority seeding over existing turns; full-write loops; inference Redis-advisory + refund-safe prompt assembly; token-keyed logout guard. |
| `1df4ec0` | Claude | Derived sidebar titles; `context_freshness` on stream `done`; atomic quota on ultra / vision / cognitive routes. |
| `db3e698` | Claude | Refused racing commit leaves no rows (**found by CI on `06d98b9`**). |
| `75a4665` | Claude | CI job for the fixture-provider journeys. |
| (next) | Claude | `tests/_redis_guard.py::safe_flush` replaces every `FLUSHDB` in the suites. |
| (docs) | Claude | `docs/orneur/landmarks/landmark-01/**` only. |

Rejected / not used: **#128** (alternative security implementation — would duplicate #127's controls), **#131** (competing transcript engine), the `7ea44ae` commit of #126 (its content — passing the owner id into inference history assembly — is already in #129 via `d1e98fd`; verified by `tests/test_conversation_context.py` and the inference tests).

Test infrastructure imported from the PR #111 closeout (`e8e6ab1`): `tests/test_multiworker_edit_consistency.py`, `test_multiworker_session_and_fault_injection.py`, `test_redis_post_commit_consistency.py`, `test_redis_stale_payload_resurrection.py`, `test_redis_independent_processes.py`, `tests/_redis_worker.py` — they were **not** in the #125/#129 lineage even though `session_store.py` there already carries the revision-fencing design. They pass against this tree unmodified.

## 5. Defects found *by integrating* (all fixed on this branch, each with a failing-before test unless stated)

1. `reconcile_legacy_session` took (and on its early return never released) turn authority for **every transcript read** ⇒ the next real turn was refused as busy for 30 s. *(Found by the live journey; PR #130.)*
2. `acquire_authority` created an authority row at `committed_revision = 0` over a session that already had turns ⇒ later commits collide with revision 1 forever. *(CodeAnt finding on #130; reproduced.)*
3. `ConversationStore.delete()` swallowed SQLite failures and returned success; `last_activity` swallowed read errors ⇒ a temporary chat could be reported "closed" while rows remained. SQLite free pages and the WAL still held the deleted text. *(Found by the byte-level multi-process test.)*
4. `/api/stream` kernel-direct path delivered **unscanned** model text to the browser and the transcript. `/api/chat` and `/api/ultra` put raw text in long-term memory. *(Reproduced.)*
5. `/api/chat` and `/api/stream` quota was check-then-increment (race at 49/50); reservations were refunded as "stale" under a live long generation.
6. Authority was acquired **after** generation on the canonical routes — a stalled worker could still commit a turn built from stale context. *(Hung-worker journey.)*
7. One Ollama tag behind several tiers produced one deployment id; the second tier's registration replaced the first's (`ModelNotRoutableError` on its next request). *(Found by the live browser journey.)*
8. `get_current_user_optional` treated revoked/expired/garbage tokens as anonymous. *(Directive Wave 1.)*
9. Temporary-chat lock was unlinked while held (two owners possible); a crash mid-closure left a still-`active`, usable chat. *(CodeAnt + failure injection.)*
10. Inference routes: prompt assembly could fail after the quota reservation without a refund; a Redis outage refused every request although Redis is advisory; JSONL export trusted a short `os.write`. *(CodeAnt findings.)*

## 6. Contract changes to existing tests (each replaced by an equal or stronger assertion)

| Test | Old contract | New contract | Why |
|---|---|---|---|
| `test_a_serving_authorization.py::test_every_route_that_spends_inference_applies_the_standard_gates` | `/api/chat`,`/api/stream` contain `check_quota` | contain `_admit_message_quota` **and must not contain** `check_quota`/`increment_usage` | the racy pair is now forbidden, not merely absent |
| `test_g006_tenant_isolation.py::test_07d…` | revoked API key ⇒ 404 (as anonymous) | ⇒ **401** | explicit directive requirement |
| `test_b_logout_revocation.py::test_a_revoked_token_cannot_be_used_as_an_optional_identity_either` | 404 | 401, *and* a truly anonymous caller still 404 | same |
| `test_conversation_context.py` (4 tests) | seeded via JSONL `conversations.append` | seeded via `commit_turn`; plus a new assertion that a JSONL-only line is **not** sent | #130 makes JSONL derived data |
| `test_ollama_deployment_id.py`, `test_gateway_wiring.py`, `test_public_serving_authority.py` | `stable_deployment_id(backend, model)` lookups | pass the served family | deployment identity now includes the family; regression test added |
| `test_api_production_cutover.py::test_rag_forces_deferral…` | fixed 8-char session-id prefix | unique prefix | prefix is a storage key; collided with earlier runs |
| `tests/frontend/test_logout_revocation.mjs`, `test_view_ownership_epoch.mjs` | boolean in-flight guard | token-keyed guard | CodeAnt finding on #129 |

Nothing was weakened, skipped, or mocked at a security boundary to obtain a pass.

## 7. Environment changes made on the workstation (disclosed)

* Local Ollama aliases (copies of `llama3.2:1b`, no download): `orneur-journey`, `orca-nano`, `orca-core`, `orca-ultra`, `orca-nano-v7`. The repository's existing live-Ollama tests assume those names and otherwise fail locally (they skip in CI, which has no Ollama). Remove with `ollama rm <name>`.
* Git worktrees under `/home/pc/projects/Orneur-l01-*` (read-only baselines and gate runs) — safe to delete.
* No system software was reinstalled; Redis used the existing `orneur-redis-test` container (dedicated DBs 12–15; only ORNEUR keys were ever deleted, never `FLUSHDB`).
