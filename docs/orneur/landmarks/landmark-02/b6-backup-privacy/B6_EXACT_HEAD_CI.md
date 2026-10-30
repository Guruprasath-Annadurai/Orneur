# L02-B6 — exact-head CI (engineering evidence; not independent qualification)

Draft PR #143, branch `claude/l02-b6-backup-privacy`, base = PR #139 branch (`38e0d31`).

| Head | Run | Result | Notes |
|---|---|---|---|
| **`ba36e74`** | **41043199842** | **success 10/10, first attempt** | Deterministic: **9378 passed, 0 failed, 399 skipped, 190 deselected, 6 xfailed**; the skipped-test set is identical to the PR #139 head run (40998377463), so no existing test became a skip. All 46 tests of `tests/test_l02_b6_backup.py` passed in CI. Journeys (fixture provider) 39 + 15 + 24 + 3 passed; the 24 includes the new real-server + CLI test `test_l02_b6_backup_live.py` (23 on the base) |

No failed run exists for this branch. Commits after `ba36e74` change documentation/evidence only. Not run in CI: nothing specific to B6 is workstation-only; the live test uses the fixture provider and a test-only key.
