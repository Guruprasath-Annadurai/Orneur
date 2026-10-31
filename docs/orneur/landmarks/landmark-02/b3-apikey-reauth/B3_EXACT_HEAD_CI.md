# L02-B3 — exact-head CI (engineering evidence; not independent qualification)

Draft PR #141, branch `claude/l02-b3-apikey-reauth`, base = PR #139 branch (`38e0d31`).

| Head | Run | Result | Notes |
|---|---|---|---|
| `1a17fb0` | 41012363816 | success 10/10 | 9353 passed, **400 skipped** (baseline 399). Diffing the skipped-test names found `test_g006_tenant_isolation.py::test_07d` newly SKIPPED: its old "skip if creation is not 200" had turned a tenant-isolation security test into a skip. Not accepted as green evidence |
| **`283e3a4`** | **41014535017** | **success 10/10** | **9354 passed, 0 failed, 399 skipped, 190 deselected, 6 xfailed**; skipped-test set identical to the PR #139 head run (40998377463). Journeys 39 + 15 + 24 + 3 passed (the new two-worker live test is included in the 24) |

No earlier failed run exists for this branch. Commits after `283e3a4` change documentation/evidence only. Not run in CI: browser journeys for the two new inputs in the API Keys panel.
