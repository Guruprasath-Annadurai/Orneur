# LANDMARK-01 — Engineering Report

**Milestone:** Secure Real Chatbot Integration · **Branch:** `claude/landmark-01-secure-chatbot-integration` · **Operating mode:** evidence first, no protected merge, no deployment, no training, no paid services, frozen UI untouched.

**Integration readiness verdict:** *a working, integrated, engineering-verified candidate that is **not** independently qualified and has **one P1 product gap** (default-path answers are a labelled replay, not token streaming — B-01). It is ready for Antigravity's consolidated qualification. It is not a production-readiness or release claim.*

## 1. Starting and final SHAs

| | SHA |
|---|---|
| Starting references | #125 `9298b157` · #126 `7ea44aed` · #127 `22225086` · #128 `a6def68d` · #129 `485ca951` · #130 `497073d2` · #131 `040d6947` · Claude frontend `f7c004f1` (all re-verified against GitHub at start; heads unchanged) |
| Integration base | `485ca951e7b7bc2242cf71f323bf90af0656908f` (#129 tip) + merge of #130 `497073d2dfb45f82554fb260db3fe4d87b0b5019` |
| **Last code-bearing commit (tests below were run at this SHA)** | `9755567a1c0423c6040ed267ea62209ebe66facb` |
| Branch head at handoff | the head of the draft PR — `git diff 9755567a1c0423c6040ed267ea62209ebe66facb..HEAD` is documentation only (`docs/orneur/landmarks/landmark-01/**`) |

## 2. Architecture decisions

1. **Product lineage #125 → #126 → #129**, as directed. #129 was branched from #126 before #126's last commit (`7ea44ae`); that commit's content (owner id into inference history assembly) is already in #129 (`d1e98fd`).
2. **Persistence: #130, not #131.** One transcript engine only. #130 fences with a durable SQLite epoch checked inside the commit transaction; #131's commit-time check is a Redis read. Details and the full comparison table: `…_INTEGRATION_PROVENANCE.md` §3.
3. **One serving boundary.** `/api/chat` and `/api/stream` (what the browser calls) now use the same admission, authority, DLP and commit components as the inference routes: atomic quota reservation (`_QuotaTicket`), `_TurnAuthority` (Redis lease + SQLite fencing epoch, taken before the Kernel reads history, heartbeat-renewed, re-proved inside the commit transaction), output DLP before anything is remembered, and **durable commit before any derived state** (live window, long-term memory, graph, Redis-shared history).
4. **Redis is advisory, SQLite is the fence.** A Redis outage degrades cross-worker coordination to the SQLite fence (and says so via `context_freshness`); an unreachable *SQLite* store refuses the turn up front (503 `history_unavailable`) rather than generating an answer that cannot be saved.
5. **Honest delivery.** `done.persisted` is `saved | failed | not_applicable`; the page says when a reply was not saved. `stream.delivery` is `upstream` or a labelled `replayed`.
6. **No relabelling.** The served model is the real `llama3.2:1b` tag under safe internal deployment ids (`stable_deployment_id(backend, model, family)`); nothing is presented as GENESIS/NOVUS/AETERNUM-native.

## 3. What was implemented (by wave)

| Wave | Delivered | State |
|---|---|---|
| 1 Auth | invalid / expired / revoked bearer ⇒ 401 (never anonymous); wrong-type tokens refused; logout & logout-all across workers; token-keyed logout guard and `storage` handler in the page | VERIFIED_ENGINEERING |
| 2 Boundary | atomic quota on chat/stream (+ultra/vision/cognitive); `_TurnAuthority`; DLP-before-memory; commit-first ordering; stream idempotency; tri-state Redis lease; `renew_quota`; `persisted` status; authority heartbeat on `/api/inference/*` | VERIFIED_ENGINEERING |
| 3 Multi-turn | SQLite-sourced, ownership-bound, edit-overlaid, bounded context; canary challenge asserted on recorded Ollama requests; literal `llama3.2:1b` tag journeys | VERIFIED_ENGINEERING |
| 4 Frontend | notice when a reply is not saved; reload restores the active conversation (per tab / per account / never temporary); derived sidebar titles; stale 401 comments corrected; node suites in CI | VERIFIED_ENGINEERING |
| 5 Temp chat | resumable `closing` state, inode-verified lock, `commit_guard`, strict deletion verification, SQLite `secure_delete` + WAL truncate | VERIFIED_ENGINEERING |
| 6 Reliability | provider down / 500 / malformed / timeout / truncated stream; SQLite down / commit failure; duplicates; Redis restart / outage; SIGSTOP hung worker; SIGKILL restart | VERIFIED_ENGINEERING |
| 7 Journeys | A–J (see `…_REAL_USER_JOURNEY_REPORT.md`) | VERIFIED_ENGINEERING |
| 8 Closure | CI job for the fixture journeys; guard against FLUSHDB of foreign Redis data; provenance, matrices, blocker register | this document set |

## 4. Defects fixed (selection — full list in the provenance document §5)

Anonymous fallback for revoked tokens · racy quota (49/50) · authority acquired after generation (stale writer) · **unscanned model text on the stream route's default path reaching the browser *and* the transcript** · raw secrets in long-term memory / live window · **every transcript read stranding turn authority for 30 s** (found by the live journey) · authority row seeded at revision 0 · temp-chat crash-mid-closure and racing-commit residue (bytes of deleted text still in `turns.db`) · **one model tag behind several tiers collapsing to one deployment** (found by the live browser journey) · stale-reservation refund under a live generation · lock race in temp-chat closure.

## 5. Known limitations (blocker register: `…_BLOCKER_REGISTER.md`)

P1 **B-01** default-path answers are one labelled replay (not token streaming) · P1 **B-02** no independent qualification · P2 B-04 real-Ollama journeys not in CI · P2 B-05 physical reclamation of vector-store data best-effort · P2 B-06 duplicated model calls for document sessions · P3 B-07…B-11. **No P0 is known to remain.**

## 6. Test execution (all at `9755567a1c0423c6040ed267ea62209ebe66facb`)

| Suite | Result | Evidence class |
|---|---|---|
| Full deterministic suite (`scripts/ci/run_deterministic_tests.sh`), run at `7b0fd19` (no product code differs from `9755567`; later commits touch only `tests/journey/**`) | **9059 passed, 0 failed**, 340 skipped, 97 deselected, 7 xfailed (live Ollama present, so Ollama-dependent tests ran) | DETERMINISTIC + local live |
| Frontend Node suites (5 files) | 7 + 39 + 13 + 5 + 20 = **84 passed, 0 failed** | NODE |
| Full journey suite `pytest tests/journey -m journey_live` (alias model) | **57 passed, 0 failed** | LIVE_API / BROWSER / FIXTURE |
| API + browser journeys with the **literal tag `llama3.2:1b`** | **38 passed, 0 failed** | LIVE_API / BROWSER (real Ollama) |

Note: the shared workstation was under load from another agent's test run (load average ≈ 11); one journey start-up exceeded a 90 s timeout once, the timeout was raised to 180 s and a server-leak in that test fixed. Observed CI flake outside this milestone: `tests/test_browser_engine.py::test_live_local_workflow_and_isolation` (`browser_exited`) failed once on `b7fa0b0` and passed on neighbouring runs.

## 7. CI

Exact-head results are recorded in the draft PR (checks on the head SHA). Earlier heads: `91c9c83`, `a835c53`, `06a6788`, `db3e698` green; `06d98b9` failed on a temp-chat race found and fixed (`db3e698`); `75a4665`/`b7fa0b0` failed on a journey-test counting flaw (fixed in `69fb1b9`) and once on the unrelated browser-engine flake.

## 8. Real-system evidence — what truly exercised what

| System | Exercised by | Not exercised by |
|---|---|---|
| **Real Ollama** (`llama3.2:1b`, via a recording tap) | `test_journey_api_live.py` (19), `test_journey_browser.py` (browser), run with both the alias `orneur-journey` and the **literal tag `llama3.2:1b`**; local live-Ollama unit suites (`test_gateway_ollama_runtime.py`, `test_api_production_cutover.py`, …) | the fixture journeys and all `tests/test_*` that use `FakeOllama` (provider timing/chunking/failure is controlled there) |
| **Real Redis** (docker, DBs 12–15) | concurrency journeys (lease, takeover, restart, outage), `test_redis_*`, `test_multiworker_*`, `test_p0_transcript_*` | browser journeys (single server) |
| **Real SQLite** | everything above; byte-level scans in the temp-chat multi-process tests and journey `I2` | — |
| **Real Chromium** | `test_journey_browser.py` (17 steps), `test_journey_browser_fixture.py` (S0–S6) | node suites (vm sandbox over the real page bytes) |
| **Real multi-process** | `H1–H6`, `I1`, `G3`, `test_temporary_chat_multiprocess.py`, `test_redis_independent_processes.py` | — |

## 9. Scorecard

| Category | Acceptance | State |
|---|---|---|
| Authentication | Secure session lifecycle, invalid-token refusal | `VERIFIED_ENGINEERING` |
| Frontend | Functional approved ORNEUR interface | `VERIFIED_ENGINEERING` |
| Streaming — upstream/incremental path | genuine chunks, Stop, refresh, severed connection | `VERIFIED_ENGINEERING` |
| Streaming — default plain-chat path | token streaming | `BLOCKED` (B-01: labelled replay) |
| Multi-turn history | Correct authorized context | `VERIFIED_ENGINEERING` |
| Editing | Correct effective history after edits | `VERIFIED_ENGINEERING` |
| Persistence | Durable, authoritative, crash-safe turns | `VERIFIED_ENGINEERING` |
| Quotas | Atomic, replay-safe | `VERIFIED_ENGINEERING` |
| Privacy | No cross-user or temporary-chat leaks | `VERIFIED_ENGINEERING` |
| Concurrency | Safe multi-worker turn handling | `VERIFIED_ENGINEERING` |
| Real Ollama | Verified request and output provenance | `VERIFIED_ENGINEERING` |
| Browser journeys | Mandatory A–J pass | `VERIFIED_ENGINEERING` |
| CI | All mandatory exact-head checks pass | see PR checks |
| Independent qualification | Pending Antigravity audit | `IMPLEMENTED_UNVERIFIED` — not requested/performed |

## 10. Smallest remaining correction list

1. **B-01** — Kernel `on_chunk` streaming hook + API forwarding (design in the register). Everything else listed is P2/P3.
2. Antigravity consolidated qualification of the frozen SHA (B-02).
3. A CI job or runner for the real-Ollama journeys (B-04).

## 11. Hand-off statement

No protected branch was merged; nothing was deployed; no training; no paid service; the frozen UI/UX, logo and themes were not changed (the only `conversation.html` edits are behaviour: not-saved notice, active-conversation restore, token-keyed logout guard, corrected comments). Antigravity's earlier findings and results were not modified. **Request:** independent qualification of the exact SHA recorded in the draft PR, including the earlier vulnerabilities (stale-writer after takeover, JSONL phantom turns, prompt contamination, chunk-split DLP, reservation theft, replay) and the integration regressions listed in `…_INTEGRATION_PROVENANCE.md` §5.
