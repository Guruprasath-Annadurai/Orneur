# Core runtime handover

Parent: `cursor/cancellation-reconcile-a8b0` at `f3d2509770226f7dd2ee1848737aa578afa5775a`.

Defects in this note were reproduced on `408a912d34ab9043641984a51d3eb9bbaeca5c48`. That SHA is not the qualification subject. Qualify the correction commit that follows it.

This branch does not edit the acceptance ledger, the register graph, trust roots, or training authorization. Formal accepted pretraining count remains 0/95. `training_start_permitted` is false. No native model is trained.

## Reproduced on 408a912 and corrected

- Editing `report.json` after `completed_verified` still replayed as verified success. The journal state now stays `completed_verified`, and the replay reports `current_integrity=artifact_digest_mismatch` with `independently_verified` false. The stored verification record is not rewritten.
- `Journal.transition(..., "completed_verified")` entered that state with no artifact binding. The generic transition now raises `verification_required`. Only `seal_verified` can enter it, and only from `verifying`, after it reads the on-disk artifact with `O_NOFOLLOW` and checks mission id, integer total, and `verified: false`.
- A copied verification object, a missing artifact, a symlink artifact, and a changed input replay as `artifact_digest_mismatch`, `missing_artifact`, `artifact_unreadable`, or `input_revision_mismatch`. Historical state is kept.
- Cancel or revoke after `begin_effect` leaves the effect `not_committed` with `external_outcome=unconfirmed`. The mission is not sealed. A local file written before the refusal can remain on disk; the receipt does not call that an external acknowledgement.
- Restart after `after:draft`, `after:running`, `before:write_report`, `after_bytes:write_report`, and `after:verifying` resumes once. A second completion does not write the artifact again.
- Replacing `missions` with a symlink to another directory raised no error and wrote there. `O_NOFOLLOW` on each path component now raises `symlink_refused` and leaves the target untouched. A planted predictable temp name is not the file that is replaced.
- `units: true` counted as 1 because `bool` is an `int`. `recompute` now requires `type is int`. `NaN`, infinities, booleans, and negative budgets return `invalid_budget` and do not select the calculator.
- A two-row list ledger was reported as `ledger_accepted_count` 0 with no separate raw count. The worksheet now reports `ledger_raw_entry_count` and passes the list to `scripts/acceptance/acceptance_engine.py`. Forged rows are `rejected`. The empty published ledger is `empty` and accepted count 0. The worksheet does not write the ledger or the graph. Engineering evidence, founder authorization, and training permission stay false.
- `fetch_readonly` classified a name, then `urllib` resolved it again and honored proxy environment variables. The fetch now resolves twice, refuses `dns_rebinding` before `create_connection` when the set changes, connects only to the pinned address, checks `getpeername`, ignores proxy variables, and refuses redirects. IPv4-mapped IPv6 answers are blocked. `perform_action("browse_read")` returns `performed: false` and `authorized_not_performed`.
- Scorer identity compared case-sensitively, so `Learner` could score `learner`. Comparison is now stripped and casefolded. `scorer_authenticated` and `age_verified` are false. A caller-asserted adult band cannot make a record shareable.
- Naive dates and mixed offsets could raise `TypeError` or accept an inverted window. Invalid, naive, and inverted windows are ineligible. A naive clock raises `naive_clock`.

## What runs

`orca/core_runtime/journal.py` stores one owner's mission, effects, and memory on one machine. Writes use `O_NOFOLLOW`, `O_EXCL`, a random temp name, and `rename` on a directory descriptor. `flock` serializes that machine. It is not multi-host durability. Caller identity is `actor_authenticated: false`. A memory share names only a mission owned by the same caller. Another caller gets `not_found`.

`orca/core_runtime/report.py` accepts a structured objective and non-boolean integer cents. It selects `deterministic.calculator` when the budget is finite. Completion binds the canonical input digest, the artifact digest, and the recomputed total. A later mismatch does not erase the historical verification. Natural language is not interpreted. GENESIS, NOVUS, and AETERNUM are refused and are not substituted. `production_runtime` is false.

`orca/core_runtime/browser.py` is a direct HTTP GET with a pinned address. It is not a production cloud browser. Chromium is not launched. Chrome, Safari, Firefox, and Edge stay unsupported. An explicit `allow_hosts` entry is required for loopback. Metadata hostnames are refused even with a permit.

`orca/core_runtime/proof.py` scores synthetic items. Nothing here accredits a learner or verifies age.

`orca/core_runtime/opportunity.py` matches caller-supplied fixtures. `live_provider_connected` and `external_integration` are false. Nothing is submitted.

`orca/core_runtime/voice.py` stores intake text. Wake word, mobile OS integration, and driving mode are unsupported. No audio is rendered.

`orca/core_runtime/router.py` reads `default_registry()`. All three native families stay unqualified. `production_router` is false.

`orca/train/pretraining_evidence.py` recomputes the 95 counted rows. It refuses spend above the zero cap, refuses holdout open for `TRAINING`, and reads locks that stay false. The workstation probe sets `validated` to false.

## What this does not do

- Native model training, weight download, or a capability score.
- Acceptance of any of the 95 requirements. R65 stays `NOT_VERIFIABLE`. C27 stays unmet. DEC-K stays unauthorized. G1 stays unverifiable.
- A replacement for Postgres `orca.mission.mission_store` or the in-process product contract.
- Multi-host durability, an authenticated caller, or an external effect acknowledgement.
- A cloud browser, a proxy-aware enterprise fetch, or a browser that executes page scripts.
- Founder hardware acceptance. This process did not observe the Ryzen 7 9700X workstation.
- Claude frontend changes.
- Independent qualification. Cursor does not self-certify this branch.

## Local tests

`tests/test_core_runtime.py`, `tests/test_core_runtime_integrity.py`, and `tests/test_pretraining_evidence.py`: 40 passed.

`bash scripts/ci/run_deterministic_tests.sh` on this worktree: sentinel 13 passed; main process 4 failed, 9165 passed, 456 skipped, 43 deselected, 6 xfailed. The four failures are not caused by this correction:

- `test_no_frozen_or_private_path_differs_from_the_branch_point` sees three `genesis_native_pretraining` authorization files that already differ from `cd6af2a` on committed HEAD `408a912`. Those files were not edited here.
- `test_isolated_install_can_import_ocl_and_run_cli` and `test_isolated_install_from_sdist_can_import_integrity_and_run_cli` fail because this machine has no `python3-venv` (`ensurepip` is missing).
- `test_golden_final_state_pins_cross_platform_determinism` hashes the dry-run toy in `orca.train.dryrun`. This correction does not import that package. The local digest differed from the pinned golden value.

GitHub CI for `408a912` is not evidence for the correction commit.

Truth labels:

| Area | Label |
| --- | --- |
| Verified-completion binding and restart | IMPLEMENTED — INDEPENDENT QUALIFICATION PENDING |
| Single-host journal and owner scope | IMPLEMENTED — INDEPENDENT QUALIFICATION PENDING |
| Native model routing | IMPLEMENTED AND VERIFIED as a refusal |
| Pinned read-only GET | IMPLEMENTED — INDEPENDENT QUALIFICATION PENDING |
| Production cloud browser | BLOCKED |
| Proof scoring | IMPLEMENTED — SYNTHETIC ONLY |
| Opportunity matching | IMPLEMENTED — SYNTHETIC ONLY |
| Voice | DESIGNED / CONTRACT ONLY |
| Pretraining acceptance | BLOCKED at 0/95 |
| Training start | BLOCKED |
| Workstation | BLOCKED until the named machine is observed |
