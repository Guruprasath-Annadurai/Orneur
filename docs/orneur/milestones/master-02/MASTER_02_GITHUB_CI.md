# MASTER-02 — GitHub CI tracking (terminal)

| Field | Value |
|---|---|
| Draft PR | https://github.com/Guruprasath-Annadurai/Orneur/pull/145 |
| Branch | `cursor/master-02-integration-candidate-316a` |
| Merge tip (content) | `7fb78a3d9c522edff26335a551ceadc5d500f941` / tree `7a980d4ae918bc4dbec374772a2ec20e36d3107f` |
| Pre-repair tip | `5d56e7ef2d5ccb8427c3d79c10be44d55f2ac8de` |
| **Post-repair tip** | `6d977703ef0af77e7099fa9979bfb4a8cdf21864` |

## Post-repair tip `6d97770` — all applicable checks PASS

| Workflow run | Event | Conclusion |
|---|---|---|
| https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41057213544 | `pull_request` Test Suite | **success** |
| https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41057203275 | `push` Test Suite | **success** |
| https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41057213519 | `pull_request` Eval Static Checks | **success** |

| Job | push `41057203275` | pull_request `41057213544` |
|---|---|---|
| Deterministic Unit Tests | PASS (23m27s) | PASS (23m0s) |
| Training Math (Torch) | PASS | PASS |
| Production Container Build + Boot Smoke | PASS | PASS |
| SSE Diagnostics | PASS | PASS |
| Journeys (fixture Redis Chromium) | PASS | PASS |
| Genesis V2 Security | PASS | PASS |
| Genesis V2 Sandbox | PASS | PASS |
| RSE Docker Lab | PASS | PASS |
| RSE dependency audit | PASS | PASS |
| Dependency Vulnerability Scan | PASS | PASS |
| Training Data Static Check | — | PASS (`41057213519`) |

## Pre-repair tip `5d56e7e` (not suppressed)

| Job | Conclusion |
|---|---|
| Deterministic Unit Tests | **FAIL** — runs `41054030409` / `41054022691` (4 failed then repaired; see `evidence/DETERMINISTIC_CI_REPAIR.md`) |
| All other applicable jobs | PASS |

Intermittent B3 TOTP failure observed once on pre-repair PR run; absent on sibling pre-repair push run and on both post-repair runs; product auth untouched.
