# Autonomous repair V2 — audit package

This package is for review. It does not authorize production, merge a protected branch, or change the acceptance ledger.

## Preserved status

- The document-deletion patch in PR #108 was written in a developer session. No qualified agent generated it.
- No enrolled reviewer approved it.
- Production authorization remains `DENIED`.
- No native model was loaded or trained.
- Agent patch generation in the unattended pipeline is `NOT DEMONSTRATED`.
- The acceptance ledger is unchanged: `[]\n`, sha256 `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`. Counted pretraining rows remain 95. Numerator remains 0.
- A journal hash chain is not a signature.
- Single-host `flock` is not a multi-host lease.
- Notification delivery is not exactly-once. A crash after `started` and before `delivered` leaves the outcome unknown and does not send again.

## What this continuation changes

### Combined-backend deletion

Branch `cursor/doc-delete-integration-a8b0` starts at the combined backend `c395dba09c54f10d626156ed57512dc635f1e9b8` (PR #99 and `test/combined-pr85-pr98-candidate`). That commit already contains Claude's frontend branch `claude/b04-b09-implementation-2026-10-23` at `92b6f155b49e74f88314df56e855c637e79119d2`.

`delete_uploaded_document()` remains. Authorized-index removal still happens first. A failed legacy delete does not call `admit_uploaded_document()`. The registry stays until every legacy store that was attempted is clean. The response sets `atomic` to false and names the collection and fallback states.

`DocStore.delete_doc` no longer returns success when a vector collection exists and the keyword fallback still holds the document. A collection error leaves the fallback file unchanged. The fallback rewrite uses a temporary file and `os.replace`. An error before replace leaves the original file. Concurrent deletes of different documents share one host file lock. That lock is not a multi-host guarantee, and the collection plus fallback are not one atomic commit.

An expired temporary chat receives `409 temporary_expired` from document deletion. A signed-in document session can still delete its own document without a model completion. Cross-tenant deletion remains covered by the existing conversation-document tests.

### Command boundary

`IncidentEngine.observe_command()` does not start a process. Authorized execution is `run_authorized_test()`, which accepts one relative pytest path and runs it with `unshare` user, mount, pid, and network namespaces, a tmpfs chroot, a cleared environment, `prlimit` CPU and address-space limits, and `timeout`. Host secrets in the parent environment are not passed in. A symlink in the tree is refused before execution.

If `unshare`, `chroot`, `prlimit`, or `timeout` is missing, or `unshare` cannot write the user-namespace map, the runner reports the gap and executes nothing. The GitHub-hosted runner for the previous head of this branch returned `unshare: write failed /proc/self/uid_map: Operation not permitted`. That result is a refusal. It is not a passed jail test. This host can create the namespace, and the jail assertions ran here. This is host isolation for a pytest process. It is not a production sandbox certification.

### Patch evidence

`seal_patch_evidence()` accepts a record only when the known-bad commit and the patched commit differ, the same test digest failed and then passed, the passing command is the reproducing command, and the applied bytes match the recorded patch digest. Editing the seal after the fact fails `verify_seal()`. The seal is a digest, not a signature. An accepted seal sets `repair_proof` to false. A caller-supplied digest is not repair proof.

`observe_execution()` runs the restricted pytest and records the git commit `git rev-parse` and `git cat-file` report for that checkout. The test and source digests are sha256 of the committed blobs. `compare_observed_executions()` accepts a failing-then-passing pair only when both runs were observed in this process, the test blob is unchanged, the source blob and the commit differ, and `git show` matches the digests. A self-supplied digest, a passing command for a different test, or a record marked `repair_proof` is rejected. The comparison still sets `repair_proof` to false and `patch_generation` to `NOT DEMONSTRATED`. It does not claim an agent wrote the source change.

### Durability

Journal append and incident deduplication take a single-host flock. Two processes that detect the same fingerprint keep one incident. Two processes that record different effect keys both remain after reload. A torn journal tail still refuses to open. `recover_torn_tail()` drops only the incomplete last line. A corrupted complete line is not repaired.

### Unattended intake

`UnattendedRepair.poll()` opens an incident from a detector result with no human command. `investigate()` records a source digest. It does not emit a patch. The report says `patch_generation: NOT DEMONSTRATED`, `autonomous_patch: false`, and `production_authorization: DENIED`. Restarting the worker returns the same incident as a duplicate.

### One hundred roles

`improvement_contracts()` returns one `improvement-contract-v1` row per declared role. Execution is `INACTIVE` for all 100 because none are independently qualified. `record_failure()` appends a genome line and does not promote the role.

### Three model families

`diagnose()` for GENESIS, NOVUS, and AETERNUM returns serving `NOT_RUN`, tokenizer regression `NOT_OBSERVED`, checkpoint provenance `UNVERIFIED`, and rollback `REFUSED`. `request_rollback()` raises. `model_loaded` and `trained` stay false.

## Local tests

On the combined-backend branch, `tests/test_doc_delete_consistency.py`, `tests/test_p0_authorized_context.py`, `tests/test_b2_conversation_documents.py`, `tests/test_doc_session_no_model_runtime.py`, `tests/test_b13_temporary_chat.py`, `tests/test_g006_tenant_isolation.py`, and `tests/test_session_ownership_isolation.py`: 88 passed, 2 xfailed.

On the previous head of this branch, `tests/test_repair_boundary.py`, `tests/test_incident_engine.py`, `tests/test_orchestration_integrity.py`, `tests/test_agent_role_registry.py`, `tests/test_agent_adversarial_trust.py`, `tests/test_synthetic_agent_eval.py`, `tests/test_cursor_model_family.py`, `tests/test_cursor_agent_orchestration.py`, and `tests/test_synthetic_provenance_steps.py`: 66 passed.

After the git-observed execution binding, `tests/test_repair_boundary.py` and `tests/test_incident_engine.py`: 16 passed on this host. The user namespace was available, so the jail path ran. The new refusal test monkeypatches the namespace as unavailable and checks that pytest is not started.

## Exact-head CI

- PR #108 `9e66770b172395b5f48b120d3dfdfb9878ea47c9`: 18/18 successful, including two deterministic unit-test runs.
- PR #109 `2009ccbd84edd61282e7bf55011419eb25851b5a`: 9/9 successful.
- PR #110 `bfdd4ebd7c81fa726b1999ce2a2555f5d762744d`: 9/9 successful.

- PR #112 `25f15c3adc7d20b3cc150c697c6a5bf15d674ec7`: the check rollup returned 10 successful results, including Deterministic Unit Tests and Conversation Shell Frontend. The last of those completed at 17:02 IST on 24 Oct 2026.
- PR #113 `ae54e44aed1fda5de2498a0a6c612e58a4cd7a05`: Deterministic Unit Tests failed. The failure is the user-namespace refusal above, in `tests/test_incident_engine.py` and `tests/test_repair_boundary.py`. The other returned checks on that run succeeded. This continuation asserts the refusal when the namespace is unavailable and still runs the jail on a host that permits it. That new head does not yet have its own CI result.

## Verdict

`ENGINEERING PARTIAL — SPECIFIC BLOCKERS`

Blockers that remain: no qualified patch generator, no enrolled reviewer, no production authorization, no multi-host coordination, no exactly-once external delivery, no loaded native model, and no user-namespace jail on the GitHub-hosted runner.
