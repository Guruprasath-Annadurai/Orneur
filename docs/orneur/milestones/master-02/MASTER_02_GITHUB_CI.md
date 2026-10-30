# MASTER-02 — GitHub CI tracking

| Field | Value |
|---|---|
| Draft PR | https://github.com/Guruprasath-Annadurai/Orneur/pull/145 |
| Branch | `cursor/master-02-integration-candidate-316a` |
| Merge tip (content) | `7fb78a3d9c522edff26335a551ceadc5d500f941` / tree `7a980d4ae918bc4dbec374772a2ec20e36d3107f` |
| Pre-repair PR tip | `5d56e7ef2d5ccb8427c3d79c10be44d55f2ac8de` |

## Pre-repair tip `5d56e7e` (exact)

| Job | Conclusion | Evidence |
|---|---|---|
| Deterministic Unit Tests | **FAIL** (4 failed / 9657 passed / 427 skipped / 6 xfailed) | runs `41054030409`, `41054022691` |
| Training Math (Torch) | PASS | same |
| Production Container Build + Boot Smoke | PASS | same |
| SSE Diagnostics | PASS | same |
| Journeys (fixture Redis Chromium) | PASS | same |
| Genesis V2 Security | PASS | same |
| Genesis V2 Sandbox | PASS | same |
| RSE Docker Lab | PASS | same |
| RSE dependency audit | PASS | same |
| Dependency Vulnerability Scan | PASS | same |
| Eval Static / Training Data Static | PASS | `41054030418` |

See `evidence/DETERMINISTIC_CI_REPAIR.md` for failure inventory + repair.

## Post-repair tip

_Filled after push + terminal CI._
