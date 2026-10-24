# P0 revocation freshness and deterministic-test reconciliation

This note records the follow-up to PR #90. It does not accept any requirement, does not authorize a merge, and does not change `docs/orneur/acceptance/acceptance_ledger.json`.

PR #90 head `476ee36137aae1600048187d9a46d4a35816b00d` is unchanged. This work is a descendant, not a rewrite.

## Status

**ENGINEERING PASS — INDEPENDENT SECURITY REQUALIFICATION PENDING**

The two defects below were reproduced on that exact tree, then corrected here. Antigravity still has to requalify both PR #90 and this follow-up. This document does not declare independent security acceptance.

## GitHub deterministic failure

Run `40013361785` on PR #90 failed only these two tests:

- `test_cloud_xl_cannot_register_output_under_a_reserved_native_model_name`
- `test_cloud_trainer_fails_before_any_ssh_or_network_call`

Both raise `FileNotFoundError` while importing `orca.train.cloud`, because `MODELS_DIR.mkdir` runs at import and `orca.config.ORCA_HOME` points at a deleted `/tmp/orca_test_*` directory.

Reproduced locally by running the five P0 tests that use `isolated_home` together with `monkeypatch.setattr("orca.config.ORCA_HOME", ...)` and then those two phase-16 tests. The five P0 tests passed. The two phase-16 tests failed with the same missing parent.

Cause: `isolated_home` deletes its temporary directory on teardown, after reloading `orca.config`. `monkeypatch` was activated earlier by the autouse fixture, so it tears down later and writes the deleted path back onto `orca.config.ORCA_HOME`. `test_p0_authorized_context.py` is collected before `test_phase16_*`. PR #86, PR #87, PR #88, and PR #89 CI were green because those tests did not exist yet. The same footgun in `test_serve_authorized_product_index.py` runs after the phase-16 import, so it did not fail GitHub CI; it is removed for the same reason.

The phase-16 tests do not import a missing directory when `ORCA_HOME` is left on a real path. The product `mkdir` was not changed.

### Other local failures, reconciled

Combined local run on 24 October 2026, 12:40 IST (`bash scripts/ci/run_deterministic_tests.sh`): sentinel 13 passed. Main process 9024 passed, 4 failed, 456 skipped, 43 deselected, 6 xfailed, 12 minutes 15 seconds.

The two phase-16 tests passed in that run, after the new multi-process tests. The four remaining failures are not this correction:

- `test_no_frozen_or_private_path_differs_from_the_branch_point` diffs three pretraining authorization files from `cd6af2a`. That diff is already present at PR #86 `5d9c6f7`. GitHub's PR #90 job did not report it. These files are not edited here.
- `test_isolated_install_can_import_ocl_and_run_cli` and `test_isolated_install_from_sdist_can_import_integrity_and_run_cli` fail because this machine has no `python3-venv`. GitHub did not report them.
- `test_golden_final_state_pins_cross_platform_determinism` fails in isolation on this machine and passed on the PR #90 GitHub job. Trainprep files are not edited here.

## Cross-worker revocation

Before this correction, `_load_binding` returned a cached `AuthorizedIndex` when the in-process token was still current. It did not re-read `revoked` on the binding file. Worker B's `revoke()` writes that flag and revokes only Worker B's memory. Worker A's next `retrieve_authorized` still returned the passage.

Reproduced with two interpreters sharing one `ORCA_HOME`: Worker A retrieved `archive key cobalt-77`, Worker B revoked, Worker A retrieved again and printed `SERVED archive key cobalt-77`.

A second reproduction held Worker A inside `run_authorized_retrieval` after the cache check, revoked from Worker B, then released the search. The passage was still returned. The file lock is not held during the search, so a revoke that lands in that window was invisible to the in-process token.

After this correction:

- every open reads the durable flag under the binding lock before trusting the cache
- a search re-reads the flag before its passages are returned
- a revoked record drops this process's cached session and raises `ProductRetrievalDenied` code `revoked`
- another conversation of the same user is not revoked

`tests/test_p0_multiprocess_revocation.py` runs those cases in separate interpreters. `drop_process_state_for_tests()` is not used as the worker boundary.

## Files

- `orca/serve/authorized_product_index.py`
- `tests/test_p0_authorized_context.py`
- `tests/test_serve_authorized_product_index.py`
- `tests/test_p0_multiprocess_revocation.py`

## Remaining limitations

- A retrieval that has already copied passage text into an upstream model request before the recheck cannot unsend bytes already written to that socket. The recheck runs before this process returns the passages to the chat handler.
- Same-OS-user write access to that user's binding file can still retarget their own conversation. The server does not do this.
- `production_neural` stays false. `tool_grant` stays false.
- GENESIS, NOVUS, and AETERNUM remain untrained.
