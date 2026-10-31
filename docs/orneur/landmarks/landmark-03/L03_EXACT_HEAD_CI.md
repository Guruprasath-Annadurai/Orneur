# L03 — exact-head CI (engineering evidence; not independent qualification)

Draft PR against the PR #139 branch. Mandatory jobs: all 10 jobs of `test.yml`. Every run on this branch is listed, including the failed and cancelled ones.

## Final code-bearing head: `c8b0f54bafe364c18e507425570d34be1e7b8dd7` — run 41189270383 — **success, 10/10 jobs, first attempt of this head**
* **Deterministic Unit Tests:** 9332 passed, **0 failed**, 399 skipped, 195 deselected, 6 xfailed (14 min 35 s). The skipped-test set is **identical** to the PR #139 head run (40998377463): no existing test became a skip. The L03 real-process tests are not in this job (see row `f105274`).
* **Journeys (real servers + real Redis + real Chromium, fixture provider):** all suites passed — 39, 15, 23 (the LANDMARK-02 live suites), 3, **48** (`test_l03_vector_service.py` 14 + `test_l03_lifecycle.py` 26 + `test_l03_failure_lab.py` 8) and **6** (`test_l03_vector_live.py`, two real `orca serve` workers + the real owner + real chromadb). 54 L03 tests passed in CI.
* Production Container Build + Boot Smoke, SSE diagnostics, Genesis security/sandbox, training math, RSE jobs, dependency scans: success.

## All runs
| Head | Run | Result | Cause / repair |
|---|---|---|---|
| `f02ea88` | 41183581577 | **failure** | `test_one_conversation_cannot_monopolise_the_service` — `VectorTimeout`. Everything else in the run passed (9376 passed). Cause: the test's 50-document seed used a flat 2 s deadline; embedding 50 documents (first use of the ONNX model) exceeded it on the slower runner. A test-environment symptom of a real product weakness: **a flat deadline refuses legitimate bulk indexing** |
| `52b2eb3`, `e249188` | 41183680753, 41184037398 | cancelled | superseded by the next push to the branch (documentation commits) |
| `2ffada1` | 41185402546 | **failure** | the same test. My first fix (refuse a flood on one conversation in the client) was correct for the isolation property but did not address the seed, so it failed again: root cause only identified from the traceback, which showed the failure in `_seed`, not in the flood |
| `f105274` | 41187453633 | **cancelled at the job limit** | the root-cause fix (indexing deadline scales with the batch; owner warms the default embedder) was in, but the Deterministic job (limit 25 min) was cancelled after 25 min 17 s: the earlier failed run had taken 24 min 36 s and the added real-process L03 tests (≈ 1 min local, ≈ 3–4 min in CI) pushed it over. All other jobs passed, including Journeys |
| **`c8b0f54`** | **41189270383** | **success 10/10** | the real-process L03 tests moved to the Journeys job (45-minute limit; `scripts/ci/run_deterministic_tests.sh` ignores them with a comment saying why); nothing else changed |

Commits after `c8b0f54` change documentation and evidence only; the documentation head's own run is recorded in the PR description (a commit cannot name its own run).

## Notes
* Moving tests between mandatory jobs is a CI-layout change made to respect a time limit, not to avoid scrutiny: the tests are unchanged and run in a mandatory job. The deterministic job's `tests/test_l03_*` ignore list is in the script.
* Not run in CI: real-Ollama and real-parser suites (workstation-only), the B6 comparison (local worktree), and `orca vector stop` against a real container.
* Local figures (510 passed in the broad adjacent run, benchmarks, comparison) are in the other documents and are workstation measurements, not CI results.
