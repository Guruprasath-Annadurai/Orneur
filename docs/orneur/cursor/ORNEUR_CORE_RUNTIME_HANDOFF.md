# Core runtime handover

Parent: `cursor/cancellation-reconcile-a8b0` at `f3d2509770226f7dd2ee1848737aa578afa5775a`.

Defects in the first correction were reproduced on `408a912d34ab9043641984a51d3eb9bbaeca5c48`. Antigravity then rejected `d1b2fe00cf0b53a78b7351df793c44ecdb0983dc`. Qualify only the commit that follows that rejection. Cursor does not self-certify it.

This branch does not edit the acceptance ledger, the register graph, trust roots, or training authorization. Formal accepted pretraining count remains 0/95. `training_start_permitted` is false. No native model is trained.

## Reproduced on 408a912 and corrected

- Editing `report.json` after `completed_verified` still replayed as verified success. The journal state now stays `completed_verified`, and the replay reports `current_integrity=artifact_digest_mismatch` with `independently_verified` false. The stored verification record is not rewritten.
- `Journal.transition(..., "completed_verified")` entered that state with no artifact binding. The generic transition raises `verification_required`. `seal_verified` is the only writer of that state.
- A copied verification object, a missing artifact, a symlink artifact, and a changed input replay as `artifact_digest_mismatch`, `missing_artifact`, `artifact_unreadable`, or `input_revision_mismatch`. Historical state is kept.
- Cancel or revoke after `begin_effect` leaves the effect `not_committed` with `external_outcome=unconfirmed`. The mission is not sealed. A local file written before the refusal can remain on disk; the receipt does not call that an external acknowledgement.
- Restart after `after:draft`, `after:running`, `before:write_report`, `after_bytes:write_report`, and `after:verifying` resumes once. A second completion does not write the artifact again.
- Replacing `missions` with a symlink to another directory raised no error and wrote there. `O_NOFOLLOW` on each path component now raises `symlink_refused` and leaves the target untouched. A planted predictable temp name is not the file that is replaced.
- `units: true` counted as 1 because `bool` is an `int`. `recompute` now requires `type is int`. `NaN`, infinities, booleans, and negative budgets return `invalid_budget` and do not select the calculator.
- A two-row list ledger was reported as `ledger_accepted_count` 0 with no separate raw count. The worksheet now reports `ledger_raw_entry_count` and passes the list to `scripts/acceptance/acceptance_engine.py`. Forged rows are `rejected`. The empty published ledger is `empty` and accepted count 0. The worksheet does not write the ledger or the graph. Engineering evidence, founder authorization, and training permission stay false.
- `fetch_readonly` classified a name, then `urllib` resolved it again and honored proxy environment variables. The fetch now resolves twice, refuses `dns_rebinding` before `create_connection` when the set changes, connects only to the pinned address, checks `getpeername`, ignores proxy variables, and refuses redirects. IPv4-mapped IPv6 answers are blocked. `perform_action("browse_read")` returns `performed: false` and `authorized_not_performed`.
- Scorer identity compared case-sensitively, so `Learner` could score `learner`. Comparison is now stripped and casefolded. `scorer_authenticated` and `age_verified` are false. A caller-asserted adult band cannot make a record shareable.
- Naive dates and mixed offsets could raise `TypeError` or accept an inverted window. Invalid, naive, and inverted windows are ineligible. A naive clock raises `naive_clock`.

## Reproduced on d1b2fe0 and corrected

- `Journal.seal_verified(input_bytes=b"forged", total_cents=1)` from `verifying`, with an artifact and zero effects, returned `completed_verified`. Caller totals and input bytes now raise `verifier_rejected` and leave the state unchanged. The verifier id `orneur-deterministic-recompute/1` is written only after the journal recomputes the input file stored by `bind_input` before execution.
- A planted `committed` effect file, even when its payload hash matches a well-formed artifact, does not admit the effect. `seal_verified` raises `effect_not_authorized`. `commit_effect` requires `bytes_written`. An unconfirmed outcome stays unsealed. Cancel and revoke still fail closed. A later artifact or input change keeps the historical `completed_verified` record and reports a separate integrity code.
- `open(.lock)` followed a symlink and created the mission. The lock is opened from the root directory descriptor with `O_NOFOLLOW`, `O_CLOEXEC`, and mode `0600`. Creation uses `O_EXCL` because Darwin `openat(dirfd, name, O_CREAT)` without `O_EXCL` returns `ENOENT` to the loser of a create race. A symlink raises `symlink_refused`. A hard link, fifo, or cross-device replacement raises `lock_refused`. This remains single-host `flock`. This Linux host did not reproduce that `ENOENT`. macOS was not executed here.
- The freeze-amendment proposal is `docs/orneur/cursor/FREEZE_AMENDMENT_PROPOSAL.md`. It is `PROPOSED` and inactive. The three `genesis_native_pretraining` files and the governance failure stay as they are.
- `docs/orneur/cursor/EVIDENCE_TRUST_BOUNDARY.md` records that matching hashes do not identify a writer who can replace every journal file, and that `principal.authenticate` is a refusal.
- The frozen-path governance test skipped when `cd6af2a` was absent. It now fails instead of skipping. The deterministic CI checkout uses `fetch-depth: 0`. With history present, the check executes and fails on three added `NOT_AUTHORIZED` files under `docs/orneur/authorization/genesis_native_pretraining/`. Those files are not edited here. The difference and the two founder options are in `docs/orneur/cursor/GOVERNANCE_DIFF_PROPOSAL.md`.
- The dry-run golden state diverged on CPython 3.12 because `sum` of floats uses compensated addition. The gradient norm now uses an explicit left-to-right fold. The pinned hash `5bb79b0f13b944b0e7ea966f867cbbcba85585ebcf4cc035a6dc3b1f85e424c9` is unchanged. This machine did not run macOS.
- An allowlist containing `169.254.169.254`, its IPv4-mapped form, `fd00:ec2::254`, or `metadata.google.internal` permitted a metadata target. Those names and the `169.254.0.0/16` block are `metadata_refused` before connect. Any non-loopback allowlist entry is `permit_not_loopback`. `127.0.0.1` and `::1` remain the loopback permits. This is not a production cloud browser.
- `read_memory` contained a branch that required the actor, the mission owner, and the memory owner to be the same user, so it never granted another user. That branch is gone. `share_with` is a same-owner label. `orca/core_runtime/principal.py` refuses authentication with `principal_not_authenticated`. The journal is not for untrusted multi-user access.

## What runs

`orca/core_runtime/journal.py` stores one owner's mission, effects, and memory on one machine. Writes use `O_NOFOLLOW`, `O_EXCL`, a random temp name, and `rename` on a directory descriptor. The lock file is opened from that directory descriptor. `flock` serializes that machine. It is not multi-host durability. Caller identity is `actor_authenticated: false`. A memory share names only a mission owned by the same caller. Another caller gets `not_found`. `principal.authenticate` does not return a principal.

`orca/core_runtime/report.py` binds the canonical input before calculation. It selects `deterministic.calculator` when the budget is finite. `seal_verified` takes no caller total. It recomputes the stored input, checks the artifact schema, and requires an admitted `write_report` effect whose outcome is `local_receipt_only`. A later mismatch does not erase the historical verification. Natural language is not interpreted. GENESIS, NOVUS, and AETERNUM are refused and are not substituted. `production_runtime` is false.

`orca/core_runtime/browser.py` is a direct HTTP GET with a pinned address. It is not a production cloud browser. Chromium is not launched. Chrome, Safari, Firefox, and Edge stay unsupported. An allowlist may name only loopback, and only `127.0.0.1` or `::1` are used by the local tests. Metadata addresses and metadata hostnames are refused even when the allowlist names them. DNS is checked again before connect. Proxy environment variables are ignored. Redirects are refused.

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

`tests/test_core_runtime.py`, `tests/test_core_runtime_integrity.py`, and `tests/test_pretraining_evidence.py` passed after this correction, including the `d1b2fe0` exploit regressions.

`bash scripts/ci/run_deterministic_tests.sh` on this Linux x86_64 worktree, CPython 3.12.3: sentinel 13 passed. Main process: 1 failed, 9177 passed, 456 skipped, 43 deselected, 6 xfailed, in 791.97s. The one failure is `test_no_frozen_or_private_path_differs_from_the_branch_point`. History for `cd6af2a` was present, so the check executed. It reports the three added `genesis_native_pretraining` files. That is a qualification failure until a founder decides. It is not a skip.

Packaging tests `test_wheel_contains_both_orca_and_orneur_packages`, `test_isolated_install_can_import_ocl_and_run_cli`, `test_sdist_contains_all_three_intelligence_packages`, and `test_isolated_install_from_sdist_can_import_integrity_and_run_cli` passed. The golden pin `5bb79b0f13b944b0e7ea966f867cbbcba85585ebcf4cc035a6dc3b1f85e424c9` passed on this interpreter. macOS was not executed.

The acceptance ledger sha256 remains `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`. GitHub CI for `d1b2fe0` is not evidence for the commit that follows it.

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
