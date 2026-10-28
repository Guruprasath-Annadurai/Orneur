# LANDMARK-01 — Security and Privacy Matrix

Evidence states: `IMPLEMENTED_UNVERIFIED` · `VERIFIED_ENGINEERING` · `INDEPENDENTLY_QUALIFIED` · `FAILED` · `BLOCKED`.
Nothing below is `INDEPENDENTLY_QUALIFIED`: that state belongs to Antigravity and has not been requested yet. "Verified" here means *a test in this
repository, run against the candidate, fails when the control is removed and passes with it* (failing-before evidence is noted where it was captured).

Candidate: branch `claude/landmark-01-secure-chatbot-integration`. The exact SHA is stamped in `LANDMARK_01_ENGINEERING_REPORT.md` §1 and in the draft PR.

## 1. Authentication and session lifecycle — `VERIFIED_ENGINEERING`

| Control | Enforcement point | Evidence |
|---|---|---|
| No credential ⇒ anonymous only where the route permits it | `orca/auth/middleware.py::get_current_user_optional` | `tests/test_auth_invalid_bearer_refused.py::test_absent_credentials_remain_anonymous_where_permitted` |
| **Presented-but-invalid credential ⇒ 401, never anonymous** (garbage, expired, revoked, wrong token type, unknown/revoked API key, issued before an invalidation) | same function (previously swallowed every `HTTPException` into `None`) | `tests/test_auth_invalid_bearer_refused.py` — 12 tests; **10 fail on the pre-fix code**; every probe asserts **zero model dispatches** at the provider |
| Reset / email-verification / 2FA-pending tokens are not session credentials | `get_current_user` type check (G-006) | `…::test_non_session_tokens_never_become_session_credentials[reset\|email_verification\|2fa_pending\|bogus]` |
| Logout revokes the server token; logout-all revokes every device on every worker | `orca/auth/routes.py::logout / logout_all` + shared auth DB | `tests/test_b_logout_revocation.py`; live `test_G1…`, `test_G2…`, `test_G3_logout_all_on_one_worker_revokes_every_device_token_on_every_worker` (two real servers) |
| Browser clears sensitive UI immediately; other tabs follow; server-confirmed vs unconfirmed revocation is stated truthfully | `conversation.html::doLogout`, `storage` listener | `tests/frontend/test_logout_revocation.mjs` (13), browser `G1`, `S5`, `S6`, `G2` |
| A late event about an *older* token cannot sign out a *newer* session; a pending logout cannot block a newer sign-in | `_logoutInFlightToken` keyed by token; `storage` handler compares `oldValue` | `test_logout_revocation.mjs` (3 new tests) — addresses CodeAnt finding on PR #129 |
| Token revoked while a page is open ⇒ page falls back to sign-in and **nothing reaches the model** | 401 ⇒ `_handleSessionExpired` | browser `S5` + `test_revoked_page_never_reached_the_provider` |

Residual: sign-up has no email verification and is rate limited per IP (a control left ON); out of scope for this milestone.

## 2. Tenant isolation — `VERIFIED_ENGINEERING`

| Control | Evidence |
|---|---|
| Another account's session id ⇒ 404 *before* any history is read or model is called | `tests/test_canonical_turn_authority.py`, `tests/test_context_window_bounds.py::test_another_users_session_never_contributes_context`, live `test_D1…`, browser `D1` |
| Model context is assembled only after an ownership check | `conversation_context.assemble_messages(user_id=…)` (PR #129) — recording tap asserts Alice's canary never appears in any outbound Ollama body |
| Titles, search, export never cross accounts | `tests/test_canonical_turn_authority.py::test_a_titles_never_leak_to_another_account` |
| API keys / tokens are per-user | `tests/test_g006_tenant_isolation.py` |

## 3. Quota — `VERIFIED_ENGINEERING`

Defect closed: `/api/chat` and `/api/stream` did `check_quota` → model call → `increment_usage`. At 49/50, N concurrent requests all passed the check.

| Property | Mechanism | Evidence |
|---|---|---|
| Atomic admission | `reserve_quota` (single conditional UPDATE) via `_admit_message_quota` → `_QuotaTicket` | `tests/test_canonical_quota_admission.py::test_49_of_50_concurrent_{chat,stream}…` (**fail on the old code**); live `test_I1…` — **10 concurrent streams across two real workers admit exactly one, exactly one provider dispatch** |
| Exhausted user / replay | refused with **zero dispatch** on both routes | `…::test_exhausted_user_is_refused_without_any_dispatch_on_both_routes`, live `test_I1` replay |
| Request-ID theft / cross-user fingerprint | `reserve_quota` binds request id to user + fingerprint (from #127) | `tests/test_p0_reservation_ownership.py`, `…::test_a_foreign_request_id_cannot_be_reused` |
| Duplicate provider dispatch | stream `Idempotency-Key` replays the stored answer: no second model call, charge or turn | `tests/test_reliability_failures.py::test_duplicate_stream_delivery_replays_…`; live `test_H3` across two workers |
| Long-running generation | `renew_quota` heartbeat; a stale-but-live reservation is no longer refunded under the user | `…::test_heartbeat_keeps_a_long_reservation_from_being_refunded_as_stale` (fails before), `…::test_a_stale_unrenewed_reservation_is_still_refunded` |
| No free inference by disconnecting | unit is spent at first model output (kernel answer / first chunk) | `_consume_message_quota` call sites; browser `S2` |
| Failure refunds | every non-consuming exit releases | `…::test_backend_failure_refunds_the_reservation`, `tests/test_reliability_failures.py` |
| Accounting outage fails **closed** | `QuotaError` ⇒ 503, no dispatch | `…::test_quota_backend_unavailable_fails_closed` |
| Secondary routes (`/api/ultra`, `/api/vision`, `/api/cognitive/execute`) | same reservation | `…::test_ultra_concurrent_race_…`, `…::test_cognitive_execute_concurrent_race_…` |

Residual: anonymous callers have no per-user quota (IP rate limit only) — by design.

## 4. DLP — `VERIFIED_ENGINEERING`

Defects closed (reproduced first): `/api/stream` kernel-direct path sent the model's text **unscanned** to the browser **and** wrote it, secret included, to the authoritative transcript; `/api/chat` redacted the response but committed the **raw** text to long-term memory and the live agent window; `/api/ultra` stored raw output in memory/LTM; the upstream stream left the raw text in the live agent window.

`tests/test_canonical_route_dlp.py` asserts, per route and path, that a leaked OpenAI key / AWS key / GitHub token never appears on the **wire, transcript, export, long-term memory or live agent window**, including a secret **split across provider chunks at five offsets**. Live `test_I2…` additionally greps every byte under the shared `ORNEUR_HOME` and every Redis value. What the client saw equals what was stored (`test_what_the_client_saw_is_what_was_stored`). Chunk-boundary scanning is the PR #127/#130 `StreamRedactor`; DLP remains a pattern floor, not a ceiling.

## 5. Concurrency and turn authority — `VERIFIED_ENGINEERING`

`_TurnAuthority` (Redis lease **plus** SQLite fencing epoch) is taken **before** the Kernel reads history and held through the durable commit; a heartbeat renews it; `commit_turn` re-proves fence/epoch/expiry/owner **inside the SQLite transaction**.

| Scenario | Result | Evidence |
|---|---|---|
| Overlapping turns on one session (any route, any worker) | second gets `session_busy` (409); transcript is serial, never interleaved | `test_overlapping_turns_…`, live `test_H1` |
| Stale `/api/chat` vs valid `/api/stream` (and reverse) | stale worker told `persisted: failed`, nothing published anywhere | `test_a_chat_worker_cannot_overwrite_a_valid_stream_turn_and_vice_versa` |
| **Hung worker** (`SIGSTOP`) superseded by another process, then resumed | resumed worker cannot write; next prompt contains the successor's turn and **not** the stale one | live `test_H2` |
| Redis restart mid-conversation | nothing committed is lost; prompt keeps history | live `test_H4` (real `docker restart`) |
| Redis unreachable | degrades to SQLite authority; honest `context_freshness` | live `test_H5`; `test_inference_proceeds_on_sqlite_authority_when_redis_is_unreachable` |
| SIGKILL + restart | committed conversations intact, listed, usable | live `test_H6` |
| Authoritative store (SQLite) unreachable | refused up front (503 `history_unavailable`), model **not** called, no charge | `test_sqlite_down_refuses_up_front_…` |
| Commit refused | answer is shown but flagged `persisted:"failed"`; UI says so; no memory/LTM/graph/Redis publication; next prompt excludes it | `test_sqlite_commit_failure_is_reported_as_not_saved_…` |
| Durable commit precedes derived state | memory/LTM/graph/Redis written only after an accepted commit | api.py `_persist_turn` ordering |
| Reads must not take authority | `reconcile_legacy_session` probes first (found by the live journey: every transcript read stranded authority for 30 s) | `test_reading_the_transcript_never_blocks_or_strands_the_next_turn` |

## 6. Transcript authority — `VERIFIED_ENGINEERING` (selection: PR #130)

SQLite (`conversation_turns`, `session_authority`, `session_export_state`) is the single source of truth for: model context, `/messages`, search, export, titles. JSONL is a derived export rebuilt after COMMIT (short writes now loop to completion). Uncommitted JSONL, stale revisions, unverified legacy history never reach a prompt (`tests/test_conversation_context.py` seeds through the authoritative path; `…::test_assemble_includes_prior_turns…` also asserts a JSONL-only line is not sent). Legacy JSONL requires explicit one-shot reconciliation (`test_legacy_jsonl_history_is_imported_once_explicitly…`). Revision continuity when an authority row is recreated over existing turns: `test_authority_row_created_over_existing_turns_continues_the_revision_sequence`.

## 7. Temporary chat — `VERIFIED_ENGINEERING`

Real multi-process tests (`tests/test_temporary_chat_multiprocess.py`, byte-level assertions on disk) with failure injection:

* crash (`os._exit`) in the middle of a closure ⇒ explicit resumable `closing` state; **another process finishes the deletion** and refuses the turn;
* a commit racing the closure is refused by `commit_guard` (same flock as the closure) — nothing survives; a worker arriving after the closure leaves no authority/export rows (**found by CI**, fixed, deterministic regression added);
* four processes closing the same chat concurrently; a closed chat cannot be reopened or adopted;
* deleted content is overwritten: SQLite `secure_delete=ON` + WAL truncate (the bytes `secret question` were still present in `turns.db` before this change);
* lock lifecycle: the lock file is unlinked at the end of a closure, so `_lock` verifies the inode it holds is still the one at the path (fixes the CodeAnt-reported two-owners race); deletion verification is *strict* (an unreadable SQLite is never treated as "gone").

Exclusions verified: long-term memory, knowledge graph, retrieval index (`_omit_long_term`, `is_hidden`), sidebar list, search, export, share (`tests/test_temporary_chat_privacy.py`, live `F1`, browser `F1/F2`). A content-free terminal tombstone remains by design.

## 8. Reliability matrix — `VERIFIED_ENGINEERING`

`tests/test_reliability_failures.py` (provider down / HTTP 500 / malformed 200 / read-timeout / truncated stream / SQLite down / commit failure / duplicate delivery / retry after failure) and the browser journey (Stop, refresh mid-stream, severed connection, revoked token). Each ends in recovery with authoritative state intact or a truthful refusal; none fabricates a completion, a saved message or a provider response.

## 9. What this matrix does **not** claim

No independent qualification; no production readiness; no native-model claim (`llama3.2:1b` is a third-party model served locally under safe internal deployment ids); DLP is a pattern floor; quota for anonymous callers is IP-rate-limit only; physical reclamation of deleted vector-store data remains best-effort (see `docs/orneur/status/P1_DELETION_ASSURANCE_DESIGN.md`).
