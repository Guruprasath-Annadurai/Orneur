# LANDMARK-01 — Real User Journey Report

Every row says what **actually ran**, against which real systems, and what was asserted. Nothing here is a skipped test counted as a pass: a missing capability makes a journey test *fail* (`capability missing: …`).

## 0. Evidence classes

| Class | Meaning | Real systems involved |
|---|---|---|
| `LIVE_API` | real `orca serve` subprocess(es) driven over HTTP | ORNEUR server, SQLite, (Redis where stated), **real Ollama** behind a pass-through recording tap |
| `BROWSER` | real Chromium (Playwright 1.49.1) driving the approved `/conversation` page | all of the above |
| `FIXTURE` | the model provider is a controllable stand-in (`tests/fake_ollama.py`) so timing/chunking/failure is deterministic; **everything ORNEUR-side is the real code in real processes** | ORNEUR servers, SQLite, real Redis, real Chromium |
| `NODE` | page logic in isolation (vm sandbox over the real `conversation.html` bytes) | none |
| `DETERMINISTIC` | FastAPI app in-process with a fixture provider | none |

Environment: Windows 11 Pro workstation, WSL2 Ubuntu 24.04, Python 3.11.18, Node 22.11, Redis 7 (docker, localhost:6379, DBs 12–15), Ollama with `llama3.2:1b` (real tag) on `localhost:11434`, Chromium via Playwright.
**Recording tap** = `OllamaTap`: forwards every request unchanged to the real Ollama and records each `/api/chat` body, so context assertions are made on *what the model was sent*, never on what a 1B model happened to say; `answer_contexts()` isolates the answering call from side-calls (knowledge-graph extraction) that quote earlier turns.

## 1. Result summary (all at code SHA `9755567a1c0423c6040ed267ea62209ebe66facb`)

| Suite | Result | Evidence class |
|---|---|---|
| Full deterministic suite (`scripts/ci/run_deterministic_tests.sh`), run at `7b0fd19` (no product code differs from `9755567`; later commits touch only `tests/journey/**`) | **9059 passed, 0 failed**, 340 skipped, 97 deselected, 7 xfailed (live Ollama present, so Ollama-dependent tests ran) | DETERMINISTIC + local live |
| Frontend Node suites (5 files) | 7 + 39 + 13 + 5 + 20 = **84 passed, 0 failed** | NODE |
| Full journey suite `pytest tests/journey -m journey_live` (alias model) | **57 passed, 0 failed** | LIVE_API / BROWSER / FIXTURE |
| API + browser journeys with the **literal tag `llama3.2:1b`** | **38 passed, 0 failed** | LIVE_API / BROWSER (real Ollama) |

## 2. Journeys A – J

### A — Authentication — PASS
| Evidence | Test | Asserts |
|---|---|---|
| LIVE_API | `test_A1_login_issues_a_working_session_token`, `test_A2_wrong_password_and_missing_token_are_refused` | wrong password refused; missing token ⇒ 401; **garbage bearer ⇒ 401 on `/api/sessions`** (was 200 anonymous) |
| DETERMINISTIC | `tests/test_auth_invalid_bearer_refused.py` (12) | garbage / expired / revoked / reset-type / 2FA-pending / unknown API key / pre-invalidation tokens ⇒ 401 on `/api/chat`, `/api/stream`, `/api/sessions`, `/api/session/…/messages`, `/api/inference/complete`; **zero provider dispatches** |
| BROWSER | `A1` wrong password message, `A2` login + usable shell | |

### B — Generation — PASS, with blocker B-01
| Evidence | Test | Asserts |
|---|---|---|
| LIVE_API (real Ollama) | `test_B1_new_conversation_streams_a_real_ollama_answer` | the request reached Ollama (tap); `session` → `generation` → `model` → `stream` → … → `done`; the stream is **either** multi-chunk `upstream` **or** exactly one chunk labelled `replayed`, `cancellable:false`. Observed on the default path: **labelled replay** |
| LIVE_API + FIXTURE | `test_B1b_controlled_multichunk_provider_is_delivered_incrementally` | 6 provider chunks 0.4 s apart ⇒ ≥ 4 forwarded individually, ≥ 1.2 s wire spread, exact text |
| BROWSER (real Ollama) | `B1` | the SSE the *browser* received (tee'd in-page) has the same shape; final answer rendered |
| BROWSER + FIXTURE | `S1` | wire spread ≥ 1.2 s **and** ≥ 4 distinct DOM states, measured by an in-page `MutationObserver` |
| BROWSER + FIXTURE | `S2` | Stop mid-stream ⇒ interrupted badge; provider **saw the hang-up**; 4 s later the transcript has no phantom turn; next turn works (authority released) |
| LIVE_API (real Ollama) | `test_B3_second_turn_is_sent_the_first_turn` ×3, `test_B4_chat_endpoint_also_carries_conversation_context` | turn 2's outbound request contains turn 1 (all three phrasings; `/api/chat` too) |

### C — Persistence — PASS
`test_C1_transcript_is_persisted_and_listed`; `test_C2_conversation_survives_a_full_server_restart`; live `H6` (SIGKILL + restart: transcript, listing, and the next prompt contains the old turn); browser `C0` (sidebar lists the conversation without a reload), `C1` (**reload restores the active conversation with no click**, highlighted in the sidebar, no duplicated messages), `C2` (each new conversation appears without a reload).

### D — Isolation — PASS
`test_D1_another_user_cannot_read_stream_into_or_edit_a_conversation` (Alice's canary never appears in any outbound Ollama body for Bob); browser `D1` (second account sees none of the first's conversations); `tests/test_context_window_bounds.py::test_another_users_session_never_contributes_context`.

### E — Editing — PASS
| Evidence | Test | Asserts |
|---|---|---|
| LIVE_API (real Ollama) | `E1`, `E2` | after editing turn 1, the follow-up's outbound request contains the edit and not the original |
| LIVE_API (real Ollama) | **`test_E5_pineapple_peach_mango_canary`** | turn 1 `pineapple-<tag>`, turn 2 `peach-<tag>`, edit turn 1 → `mango-<tag>`, turn 3 asks: the recorded request for turn 3 **contains mango, excludes pineapple, excludes peach (the invalidated tail)**, current message appears exactly once, roles alternate; the read path shows the edit |
| LIVE_API (2 servers + Redis) | `E3` | edit committed on server B is used by server A (`context_freshness == "confirmed"`) |
| BROWSER | `E0` same-turn edit available right after streaming (server `user_message_id` bound to the exact DOM element), `E1` inline edit saves, `E2` follow-up from the UI, `E3` the follow-up the UI sent reached the model with the edit, `E4` two tabs edit their own messages by authoritative id | |

### F — Temporary chat — PASS
`test_F1_temporary_chat_is_hidden_unshareable_and_deleted_on_close`; browser `F1`, `F2` (closing in the UI deletes the transcript); **real multi-process failure injection** `tests/test_temporary_chat_multiprocess.py` (5 tests: crash mid-closure resumed by another process, racing commit refused, four concurrent closers, no reopen, late committer leaves no rows) with byte-level scans of `ORNEUR_HOME`.

### G — Session security — PASS
`test_G1_logout_revokes_the_token_everywhere`, `test_G2_logout_all_revokes_every_device`; **`test_G3_logout_all_on_one_worker_revokes_every_device_token_on_every_worker`** (4 device tokens, 2 real workers, `/api/auth/me`, `/api/sessions`, `/api/chat`, `/api/stream` all 401, zero dispatches); browser `G1` (UI cleared, token revoked, old token 401 from outside **and** from inside the page), `G2` (server unreachable at sign-out ⇒ the page says the server did **not** confirm), `S5` (token revoked from another device while a page is open ⇒ sign-in shown, **message never reaches the provider**), `S6` (sign-out in one tab signs out the other).

### H — Concurrency — PASS (2 real workers + real Redis)
| Test | Scenario | Result |
|---|---|---|
| `H1` | overlapping turns, A (slow) then B on the same session | B gets `session_busy`; transcript serial; B works after A finishes and its prompt contains A's turn |
| `H2` | **`SIGSTOP` worker A mid-generation**, authority/lease lapse, worker B takes over and commits, `SIGCONT` A | A's reply is **not saved** (`turn_superseded` / `persisted:"failed"`); transcript = B only; A's next prompt contains B's turn and **not** A's stale one |
| `H3` | duplicate delivery of the same `Idempotency-Key` on the other worker | replay, **no second model call**, no second turn |
| `H4` | **`docker restart` of Redis** mid-conversation | nothing lost; ordering and prompt intact |
| `H5` | Redis unreachable | served on the SQLite fence; `context_freshness` honest |
| `H6` | SIGKILL then restart on the same home | conversation intact |

### I — Quota and DLP — PASS
`I1`: user at 49/50, **10 concurrent streams across two real workers ⇒ exactly one `done`, nine `quota_exceeded`, exactly one provider dispatch**, replay after exhaustion refused. `I2`: a credential split across three provider chunks never reaches the wire, any file under `ORNEUR_HOME`, or any Redis value. Plus `tests/test_canonical_quota_admission.py` (12) and `tests/test_canonical_route_dlp.py` (8, five split offsets, wire/transcript/export/LTM/live-window).

### J — Real browser quality — PASS
Steps `T1` dark theme renders the logged-in shell, `T2` accessibility smoke (every visible control has an accessible name, inputs labelled, `html[lang]`, `main` landmark), `S3` **refresh mid-stream** shows only committed turns and the conversation is usable, `S4` **severed connection mid-stream** (a real TCP cut through a forwarding proxy) is reported, leaves no partial assistant message and is recoverable; **no uncaught page errors and no console errors** across the real-Ollama browser run and the fixture browser run.

## 3. What was *not* demonstrated
* Plain-chat answers are delivered as one labelled replay (blocker **B-01**), not token-by-token; incremental delivery is proven on the upstream path with the fixture provider.
* The real-Ollama journeys ran on the workstation only (blocker **B-04**); the fixture-provider journeys also run in GitHub Actions.
* No independent qualification (blocker **B-02**).
* `llama3.2:1b` answer *quality* is not assessed or claimed anywhere.
