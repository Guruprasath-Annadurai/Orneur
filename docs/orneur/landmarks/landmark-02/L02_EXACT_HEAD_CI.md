# LANDMARK-02 — exact-head CI (engineering evidence; not independent qualification)

Branch `claude/landmark-02-customer-trust-reliability`, draft PR #139, stacked on PR #136 (`9cb864c99ad323d11626063498a7d1cef0d7d4b5`, not modified). Mandatory jobs: all 10 jobs of `test.yml`.

## Final code-bearing SHA: `faee97576bebee41b0cf307ccb1fa2089d4d2dbe` — run 40993535386 — **success, 10/10 jobs (Journeys job passed on a re-run of the failed job, see below)**
Deterministic Unit Tests **9331 passed, 0 failed, 399 skipped, 189 deselected, 6 xfailed**; Journeys (fixture provider) 39 + 15 + 23 + 3 passed (the L02 live deletion/recovery/operations/account and customer-journey fixture suites are included); frontend Node tests, Genesis security/sandbox, training math, container build + boot smoke, RSE jobs, dependency scans: success. Skips/xfails are the pre-existing conditional ones (PR #136 head: 398 skipped; the L02 test files skip nothing: 246 passed, 0 skipped locally). Commits after this SHA change only documentation/evidence and a test-harness diagnostic (`tests/journey/harness.py` prints the server-log tail when a live server exits early).

## Every run on this work, including failures
| Head | Run | Result | Cause / repair |
|---|---|---|---|
| `503ce0b`, `35cb248`, `9100361` | 40858954520, 40859334558, 40859996724 | success | L02-01 slices |
| `11801a8` (+docs `67e04f8`) | 40862564360, 40862662385 | success | L02-02 (9129 passed) |
| `ff33e4c` | – | **failure** | temporary-chat `409` contract broken by the tombstone → `_deleted_for_access` exempts temporary chats |
| `d050171` | 40905264930 | **failure** | every Postgres integration test: a `;` inside my SQL comment (schema string is split on `;`) → comment reworded |
| `c7f1c45`, `3710236`, `7c7bb06`, `1717b4a` | 40910526682, 40910034642, 40908981238, 40911147431 | failure | same Postgres defect (not yet fixed on those heads) |
| `7059629` | 40911662690 | **failure** | Postgres fixed (13 passed); 3 test-side failures: serving-facts system message is now first in the context; one-account login attempts hit the new per-account lockout before the per-IP limiter; wiring test needed a reachable Ollama |
| `a4f2d86` | 40914596573 | success, 10/10 | 9329 passed |
| `bf614fb` | 40918762387 | **failure** | my new CLI test asserted `--keep` in colour-rendered help; the product fix (`orca backup` no longer shadowed) was correct |
| `e27a4b2` | 40922563503 | success, 10/10 | 9330 passed |
| `e9c7df1` (docs) | 40992019637 | **failure** | unrelated `test_browser_sovereign_mission.py::test_live_browser_mission_isolates_users`: `ValueError: filedescriptor out of range in select()` — a real latent defect: `orca/browser_engine/cdp.py` used `select()`, which fails for descriptors ≥ 1024 in a busy process (`proxy.py` already used `poll()`). Fixed with `poll()` + a test that is red without the fix |
| **`faee975`** | **40993535386** | **attempt 1 failure; re-run of the failed job: success, 10/10** | attempt 1: the Journeys job's `test_l02_deletion_live.py` D1–D5 errored with `server exited early (code 1)` at startup; the server log was not retained, so the **cause is unknown** (it passed on three earlier heads and locally; the diff between those heads and this one does not touch server startup). The failed job was re-run once and passed. Not claimed as explained; the harness now prints the log tail so a recurrence is diagnosable |

Documentation-only head: recorded in the PR description after the docs commit (a docs commit cannot name its own SHA).

## Not run in CI
Real-Ollama journeys and D6 (workstation only, `L02_BLOCKER_REGISTER.md` L02-B1); the real PDF/DOCX parser suite (optional extra not installed in CI). Workstation results on the same code are in `L02_EVIDENCE_MANIFEST.json`.
