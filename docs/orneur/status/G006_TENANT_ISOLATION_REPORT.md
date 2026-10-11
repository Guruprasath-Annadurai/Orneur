# G-006 — Multi-user / multi-tenant isolation: findings, fixes, evidence

Status: **IMPLEMENTED_TESTED — NOT_INDEPENDENTLY_AUDITED. Tenant isolation is NOT claimed complete** (see §5 and §6).
Scope: the real FastAPI app driven through `TestClient` with synthetic users in isolated temporary storage; no real account, key, model, GPU or
network. RSE-ARCH-1.2, Manifest V3, the eval/corpus/training gates and every frozen contract are untouched.
Tests: `tests/test_g006_tenant_isolation.py`. Evidence: `docs/orneur/status/g006/` (original-code and fixed-code runs of the identical tests).

## 1. Category results (sprint order)

| # | Category | Result | Evidence |
|---|---|---|---|
| 1 | User A requesting User B's conversations | **FIXED** (G006-F1) | `GET /api/sessions` returned every session id + title on the server to anyone, including anonymous callers |
| 2 | Modify / delete another user's records | **FIXED** (G006-F2) / existing control held for docs | title `PATCH` and `session/save` were unauthenticated and unscoped; doc delete across sessions already returned 404 |
| 3 | Cross-user file / attachment access | **FIXED** (G006-F3) | document store shared through a colliding 8-char session prefix (`total_chunks` of A's store visible from B's session) |
| 4 | Cross-user memory and search leakage | **FIXED** (G006-F3, F4) | `/api/memory/recall` returned A's long-term hits and `prior_context` to B via prefix collision; `/api/remember` merged all users' notes into one global blob |
| 5 | Guessed / attacker-chosen identifiers | **FIXED** (G006-F5) | `../../../x`, separators, NUL, 4 KB ids accepted; `…/../g006_escape.json` was **written outside the storage tree** |
| 6 | Tenant switching and role escalation | **FIXED** (G006-F6); signup role/tier injection and admin-route RBAC **held** | an `admin` could promote themselves to `owner` and demote the real owner |
| 7 | Session fixation, invalidation, replay | **FIXED** (G006-F7, F8, F9) | see below. API-key scoping/revocation and tampered-token rejection **held** |
| 8 | Streaming data delivered to the wrong user | **ownership gate VERIFIED; live streaming NOT TESTED** | stream/chat/ultra/recall refuse a stranger without touching the session; no model exists in this harness, so cross-stream isolation under a real model is untested |
| 9 | Background jobs under the wrong identity | **NOT_IMPLEMENTED** | `LensJobQueue` jobs carry no user identity; nothing in serving uses it. Tripwire test fails if a route starts using it |
| 10 | Shared cache keys crossing tenants | **VERIFIED for the 2 existing sites** | only `semantic memory` and the unused lens queue use diskcache; closed-set tripwire; prefix claims protect semantic keys. No response cache exists |
| 11 | Tool invocations using another user's authority | **KNOWN, UNFIXED (G-020)** — needs a product decision | agent `shell` (`cat`/`find`/`grep`/`git`) reads any path the server OS user can read; agent file tools share ONE server-wide workspace; tools carry no user identity. Two strict-xfail tests reproduce it |
| 12 | Race between authorization check and access | **FIXED** (G006-F4) | two workers both saw "unowned" and both recorded themselves owner |

## 2. Confirmed defects and fixes

| ID | Severity | Defect (reproduced against the original code) | Fix |
|---|---|---|---|
| F1 | High | `GET /api/sessions` unauthenticated, global: leaked all session ids/titles (and gave an attacker the 8-char prefix needed for F3) | requires identity semantics: signed-in → only own sessions; anonymous → empty unless the instance has no accounts and is not a public edge |
| F2 | High | `PATCH /api/session/{id}/title` and `POST /api/session/save` had no identity/ownership check; title route also created entries for non-existent ids | same access rule as every session route; unknown ids → 404 |
| F3 | **Critical** | long-term memory, semantic facts and the doc store are keyed by `session_id[:8]` (docs: `[:12]` minus dashes) while ownership is checked on the full id. A session named `<victim-prefix>-x` read the victim's memory, summary and documents | every storage name is now claimed in `session_storage_keys`; a colliding id is refused (404). Legacy owned sessions are protected by an owner-prefix check |
| F4 | High | ownership check and ownership record were two steps; concurrent workers could both own a session | atomic `claim_session()`: conflict resolved by the database, winner read back; unique index on `user_sessions.session_id` (migration collapses existing duplicates to the earliest claim) |
| F5 | **Critical** | caller-supplied session ids became file names/keys unvalidated → path traversal wrote `*.json` outside storage; hostile ids were also interpolated into the web client's HTML | ids must match `[A-Za-z0-9_-]{1,64}` (server-generated UUIDs pass); anything else → 422 |
| F6 | High | `manage_users` let an admin set any role on anyone | `can_assign_role`: only strictly-lower ranks, except an owner |
| F7 | **Critical** | with `AUTH_SECRET` set (every real deployment) a **2FA-pending, password-reset or email-verification token was accepted as a full session** — a password-only attacker skipped TOTP; anyone who saw an emailed link got a session | session tokens are typed `"session"`; the middleware rejects any other type (legacy typeless session tokens still work) |
| F8 | High | no way to invalidate sessions: a stolen 30-day token survived password change/reset, and a reset link could be replayed for 1 h | tokens carry `iat`; `update_password` stamps `users.tokens_valid_after`; older tokens and older reset links are rejected |
| F9 | High | `AUTH_SECRET` defaults to a constant published in the source; nothing stopped a public deployment using it (forged owner token) | `assert_secret_usable`: with `ORNEUR_PUBLIC_EDGE` set, signing/verifying with a default secret is refused |
| F4b | Medium | `/api/remember` appended every user's note to the global `all_sessions_summary` (survived account deletion) | that write is removed; the note stays in the session's own long-term memory |

## 3. Behaviour changes operators must know

* Invalid session ids → HTTP 422; a colliding or foreign session → 404 (as before for foreign).
* Anonymous callers of `GET /api/sessions` get `[]` on any public edge or once any account exists. The web client now sends its auth header.
* Existing sessions whose ids contain characters outside `[A-Za-z0-9_-]` (none are generated by ORNEUR) become unreachable by API.
* **Password change/reset signs out every existing token of that user.** Tokens issued before this release stay valid until then.
* **Migration** (runs automatically in `init_db`): adds `users.tokens_valid_after`, table `session_storage_keys`, and a unique index on `user_sessions.session_id` after deleting duplicate owner rows (keeps the earliest claim). Back up the auth database first; rollback = restore the backup (the new column/table are ignored by older code).
* Public deployments **must** set `ORNEUR_AUTH_SECRET`; otherwise logins fail closed.

## 4. Verification

* New file `tests/test_g006_tenant_isolation.py`: **41 tests**. Identical file, two source trees (`scripts/security/g006_repro.py`):
  * original source — `docs/orneur/status/g006/BEFORE_original_source.txt`: **23 EXPLOITABLE**, 16 secure (existing controls that already held, now regression-pinned), 2 known-unfixed (G-020, strict xfail);
  * fixed source — `docs/orneur/status/g006/AFTER_fixed_source.txt`: **0 exploitable, 39 secure**, 2 known-unfixed.
* Full deterministic suite (`pytest -m "not live_ollama_smoke"`, Python 3.11, local, uid 0): **7325 passed, 5 failed, 413 skipped, 2 xfailed**. The 5 failures
  (`test_eval_sandbox` ×2, `test_genesis_v2_tier0s_phase_gate::test_Q6…`, `test_training_provenance::…chmod_readonly…`, `test_truth_fetch_security::…ordinary_public_url`)
  are root-user / no-DNS artefacts of this sandbox: they fail identically on the unmodified source (re-run and compared). CI runs as a normal user.
* Exact-SHA CI results are recorded on the PR.

## 5. Residual risks (not fixed here)

1. **G-020 — agent tools run with server authority, not user authority** (category 11). Needs a founder/product decision: remove `shell`/file tools from web sessions, or per-session workspaces plus argument path confinement, or a real sandbox (G-004).
2. **Fresh-install owner bootstrap**: the first account created becomes `owner`; the count-then-insert is racy (two simultaneous first signups can both become owner) and, on a new public deployment, the first visitor gets owner. Needs a provisioning flow.
3. **Storage keys are still 8-char prefixes.** The claim table makes a collision fail closed (404, never a leak), but two legitimate random UUIDs share a prefix with probability ≈ N²/2³³, so at scale a fresh session can be refused (the server retries 5 new ids). The proper fix is keying by the full id with a data migration.
4. **Legacy anonymous sessions** stay reachable by anyone holding their id (the id is the credential, by design), and a legacy session is not protected from a prefix squatter until it is first used after this release — mitigated by the loss of the enumeration route (F1).
5. Tokens are still stateless 30-day bearers: no logout endpoint or per-token revocation; only epoch invalidation on password change.
6. PostgreSQL migration SQL (`DELETE … USING`, `DOUBLE PRECISION`, `ON CONFLICT DO NOTHING`) was written for, but not executed against, a live PostgreSQL in this environment.
7. Race tests exercise threads on SQLite; multi-process / multi-instance PostgreSQL behaviour is covered by the database constraints, not by a multi-process test.
8. Live streaming isolation, quota accounting per tenant, and Redis-backed session restore under concurrent users are untested without a model/Redis.
9. Title file (`session_titles.json`) is a single unlocked, non-atomically rewritten file.

## 6. What this does not establish

This is the first adversarial pass over the session/auth boundary, written by the same engineer who made the fixes, and not independently reviewed.
Passing tests demonstrate that these specific exploits no longer work; they do not demonstrate that tenant isolation is complete. Background jobs
(category 9) and per-user tool authority (category 11) are recorded as `NOT_IMPLEMENTED` / `KNOWN_UNFIXED`, not as secure.
