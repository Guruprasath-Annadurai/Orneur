# MASTER-04 — merge conflict resolutions

Genuine `git merge --no-ff` of `claude/landmark-03-vector-containment` (`bfeaae2`) onto MASTER-03 tip `b96cc32`.

| Path | Resolution |
|---|---|
| `orca/serve/api.py` | **Manual** — keep B6 `serving_lock` lifespan + L03 `vectorstore.enable_service_mode(True)` |
| `scripts/ci/run_deterministic_tests.sh` | **Manual** — keep MASTER-03 adversarial ignores **and** L03 vector-suite ignores; later also ignore MASTER-04 suite (runs in Journeys) |
| `docs/.../l02_04_login_timing.json` | **Manual** — retain MASTER-03 dual-provenance index; do not substitute L03 single-workstation sample |
| `.github/workflows/test.yml` | Auto-merge retained B3+B6 journeys + L03 vector jobs; MASTER-04 suite added to Journeys |

Source PRs #146 / #147 not rewritten, not rebased, not merged to main.
