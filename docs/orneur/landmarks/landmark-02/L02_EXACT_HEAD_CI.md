# LANDMARK-02 — exact-head CI (engineering evidence; not independent qualification)

Branch `claude/landmark-02-customer-trust-reliability`, draft PR #139, stacked on PR #136 (`9cb864c99ad323d11626063498a7d1cef0d7d4b5`, not modified). Mandatory jobs: all 10 jobs of `test.yml`.

## Final code-bearing SHA: `e27a4b2091b6d93eb83ce082bf73d02d1931a2fd` — run 40922563503 — **success, 10/10 jobs**
Deterministic Unit Tests **9330 passed, 0 failed, 399 skipped, 189 deselected, 6 xfailed**; Journeys (fixture provider) 39 + 15 + 23 + 3 passed (the L02 live deletion/recovery/operations/account and customer-journey fixture suites are included); frontend Node tests, Genesis security/sandbox, training math, container build + boot smoke, RSE jobs, dependency scans: success. Skips/xfails are the pre-existing conditional ones (PR #136 head: 398 skipped; the L02 test files skip nothing: 246 passed, 0 skipped locally). Commits after this SHA touch documentation/evidence only.

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
| **`e27a4b2`** | **40922563503** | **success, 10/10** | final code-bearing head |

Documentation-only head: recorded in the PR description after the docs commit (a docs commit cannot name its own SHA).

## Not run in CI
Real-Ollama journeys and D6 (workstation only, `L02_BLOCKER_REGISTER.md` L02-B1); the real PDF/DOCX parser suite (optional extra not installed in CI). Workstation results on the same code are in `L02_EVIDENCE_MANIFEST.json`.
