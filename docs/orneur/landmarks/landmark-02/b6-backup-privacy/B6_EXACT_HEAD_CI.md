# L02-B6 — exact-head CI (engineering evidence; not independent qualification)

> History preserved. The first row (`ba36e74`, green) is the candidate that the CTO finding showed to be incomplete (legacy plaintext bypass). Green CI did not establish that the privacy boundary was closed; the corrective rows follow.

Draft PR #143, branch `claude/l02-b6-backup-privacy`, base = PR #139 branch (`38e0d31`).

| Head | Run | Result | Notes |
|---|---|---|---|
| **`ba36e74`** | **41043199842** | **success 10/10, first attempt** | Deterministic: **9378 passed, 0 failed, 399 skipped, 190 deselected, 6 xfailed**; the skipped-test set is identical to the PR #139 head run (40998377463), so no existing test became a skip. All 46 tests of `tests/test_l02_b6_backup.py` passed in CI. Journeys (fixture provider) 39 + 15 + 24 + 3 passed; the 24 includes the new real-server + CLI test `test_l02_b6_backup_live.py` (23 on the base) |

| `b1c56b9` (docs on `ba36e74`) | – | – | documentation/evidence only; this is the head the CTO audited |
| `e5266c7` | 41052123184 | **FAILURE** | *Production Container Build + Boot Smoke*: `ModuleNotFoundError: No module named 'cryptography'`. The corrective commit made the server lifespan import the backup module (optional `cryptography`, absent from the production image). All other jobs of that run passed. This also exposed that the deletion ledger (imported on every deletion path) and the `/readyz` handler of the first delivery had the same hidden dependency. Reproduced locally by blocking the import (`evidence/b6c_no_crypto_red_e5266c7.txt`), then fixed |
| **`14e1160`** | **41055502902** | **success 10/10, first attempt of this head** | **9398 passed, 0 failed, 399 skipped, 190 deselected, 6 xfailed**; the skipped-test set is identical to the PR #139 head run (40998377463). Journeys 39 + 15 + 24 + 3 passed (24 includes the extended real-server + CLI test). *Production Container Build + Boot Smoke* passed. New tests passed in CI: corrective 23/23, no-cryptography 3/3, B6 suite 46/46, legacy `test_ops_backup` 4/4 |

Final code-bearing SHA of the corrective pass: **`14e1160dc50024d726f2f379fba510fbd2a88f66`**. Commits after it change documentation/evidence only. Not run in CI: nothing specific to B6 is workstation-only; the live test uses the fixture provider and a test-only key. Not covered by CI: an actual `docker build` with `.[backup]` (the image is unchanged; decision B6-B5).
