# B-01 — Exact-head CI report

Evidence state: **VERIFIED_ENGINEERING** (CI is engineering-owned; not independent qualification).

## SHAs
| Role | SHA |
|---|---|
| Original Claude (LANDMARK-01, PR #134) | `8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788` |
| Cursor base (PR #135) | `15befec7191a1992286d7fa027236002f7d385db` |
| Last product-code commit | `01444cb084e530cd2aca1f5ed24a5e767c8b143d` |
| CI-wiring fix (only `.github/workflows/test.yml`) | `d4621521b9f497667933794c5dc99caff787accb` |
| Documentation-only commits | the commits after `d462152` on the branch (docs under `b01-final-integration/`) |

Integration PR: https://github.com/Guruprasath-Annadurai/Orneur/pull/136 (draft, base `cursor/b01-kernel-incremental-streaming-1cdf`).

## Runs
| Run | Head | Conclusion | Note |
|---|---|---|---|
| 40834538816 | `01444cb` | **failure** | `Deterministic Unit Tests` and `Genesis V2 Security`: governance guard `tests/test_genesis_v2_authorization.py` flagged a comment containing the word "Ollama" that I had added inside the auto-triggered journeys job's `run:` block. Not a product defect. 9083 passed, 2 failed. |
| 40834711869 | `fb1eea5` | **failure** | same cause (docs-only commit on top) |
| 40837020404 | `d462152` | **success** | all 10 jobs green |

Runs on documentation-only commits after `d462152` are listed in the final response / PR; they carry no code change.

## Run 40837020404 — per job
| Job | Result | Counts |
|---|---|---|
| Deterministic Unit Tests | success | 9085 passed, 398 skipped, 149 deselected, 6 xfailed, 0 failed (19m54s) |
| Journeys (real servers + real Redis + real Chromium, fixture provider) | success | 39 passed (incl. the B-01 fixture suites) |
| Genesis V2 Security | success | governance guard tests pass |
| Genesis V2 Sandbox | success | — |
| SSE Diagnostics (+ frontend Node tests) | success | Node: 89 tests, 89 pass, 0 fail (incl. `test_b01_stop_upstream.mjs`) |
| Training Math Unit Tests (Torch) | success | 25 passed |
| Production Container Build + Boot Smoke | success | — |
| RSE Docker Synthetic Integration Lab | success | — |
| RSE dependency lock and vulnerability scan | success | — |
| Dependency Vulnerability Scan (informational) | success | — |

Skips: 398 pre-existing conditional skips in the deterministic job (capability/OS/optional-dependency gated), 6 xfail; the `test_serve_streaming.py` ASGI-transport disconnect skip is documented (the real-socket variant runs). The `xfail(strict)` that documented B-01 was converted to a passing test.

CI does **not** run real-Ollama journeys (workstation only, blocker B-04).
