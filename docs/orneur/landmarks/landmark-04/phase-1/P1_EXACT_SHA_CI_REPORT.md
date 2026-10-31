# P1 — Exact-SHA CI Report

Repository `Guruprasath-Annadurai/Orneur`, draft PR #151, base `main` `0a4c5180555a3102a4e0d61f56e0f8539975f4ee` (tree `106487db…`; its own exact-main runs: Test Suite `41207007702`, training-data check `41207007703`).

## Final code-bearing commit
| | |
|---|---|
| Code SHA | `02572dd6ef72bfc07dd4847b7cff3977766ee96e` |
| Tree | `40bdf43ce56c07e99cd8f8a7d0115d796814f4ee` |
| CI run (push) | [41217652876](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41217652876) — **success, all 10 jobs** |
| CI run (pull_request) | 41217658644 — see the final handover message for its conclusion (it was still running when this file was written) |

| Job | Conclusion |
|---|---|
| Deterministic Unit Tests | success — **9749 passed, 425 skipped, 6 xfailed, 0 failed** (23 m 08 s; limit 25 m) |
| Journeys (real servers + real Redis + real Chromium, fixture provider) | success — groups: 39 · 15 · 25 · 3 · **9 (new P1 set)** · 48 · 6 · 9 passed, 0 failed |
| Training Math Unit Tests (Torch) | success |
| SSE Diagnostics | success |
| Genesis V2 Security / Genesis V2 Sandbox | success / success |
| Production Container Build + Boot Smoke | success |
| RSE Docker Synthetic Integration Lab | success |
| RSE dependency lock and vulnerability scan | success |
| Dependency Vulnerability Scan (informational, base install only) | success |

Comparison with exact-main run 41207007702: **skipped 425 → 425, xfailed 6 → 6** (no skip was added or hidden); passed 9730 → 9749 = **+19, exactly the 19 new deterministic tests**; wall time +16 s. Operational note: the Deterministic job runs at ~23 of its 25 minutes (main: ~23); any large addition to it will need the heavy tests moved to the Journeys job, as LANDMARK-03 did.

## Failure and flake history (preserved)
| Run | Head | Result | Cause | Action |
|---|---|---|---|---|
| 41216772491 (pull_request) | `c2a6081` | Journeys **failed**; every other job passed (Deterministic 9749 passed) | `test_Q2…` asserted the provider request count was unchanged after a quota refusal, but the background extraction call of the last *served* turn completed after the snapshot (99 → 100). No product defect: the refused request sent nothing | test now waits for provider quiet and asserts on the streamed count plus a settled total; 3/3 local reruns stable; fix is in `02572dd` |
| 41216759729 (push) | `c2a6081` | all jobs passed | the same racy assertion happened to pass | confirms flakiness, not a product failure |

No exact-head green is claimed for any SHA other than the one listed.

## Documentation head
This file lives in a documentation-only commit that follows the code commit. The CI result for that exact documentation head is reported in the final handover and as a PR comment (a file cannot cite its own commit's SHA).

## What CI does not cover
Real Ollama suites and the real-parser suites are workstation-only (no Ollama in CI). The real-model evidence in this package was produced locally (see `P1_REAL_INFERENCE_EVIDENCE.md`). The account journeys use a local mail sink.
