# Antigravity handoff — PR #80 security correction

Draft pull request: https://github.com/Guruprasath-Annadurai/Orneur/pull/80

Branch: `cursor/orneur-pretraining-foundation-p0-4e55`

Base: `claude/genesis-audit077-p0-remediation-2026-10-21` at `97582a94efcb93dda6c4e8a8c89e457f446a5af2`

The head SHA is the commit that adds this file. The pull request body records that SHA and the Actions run once it exists. This note is not an independent audit, and it does not accept any of the 95 pre-training requirements.

Checkpoint confinement, `isolated_worker.py`, authorization JSON, the acceptance ledger, and C02 mission code were not modified.

## What changed

### HMAC key confidentiality

`LoaderConfig.cache_integrity_key` used to be a plain `bytes` field. A frozen dataclass `repr` included the raw key.

The field is now stored as `CacheIntegrityKey` after validation. `repr`, `str`, `format`, `bytes()`, pickle reduction, and `json.dumps(..., default=str)` do not contain the raw key. `material()` is the supported way to pass the key to HMAC. A short key still raises `ValueError` with the length only. The caller-supplied key is copied, so later mutation of a `bytearray` does not change the stored key.

Keyed mode remains opt-in. No key was minted in the repository. Unkeyed caches still use truncated SHA-256 and still accept a coordinated rewrite of the store and the sidecar.

### Agent idempotency

`Orchestrator.submit()` used to return the previous task id as soon as the idempotency key matched, before checking the agent, the handler permission, or the payload.

A replay now returns that task id only when the agent id matches and the intent digest matches. The digest covers the handler, canonical JSON payload, `depends_on`, `parent_task_id`, `cost_units`, and `timeout_ticks`. It does not cover `task_id`, so a same-request retry may use a new task id and must not run the handler twice or spend the budget again.

A different agent raises `PermissionDenied`. A different handler, payload, dependency, parent, cost, or timeout raises `IdempotencyConflict`. A same-agent retry whose current permissions no longer include the handler permission raises `PermissionDenied`. Those errors do not include the original task id. The in-process `idempotency` dict still holds that id for the orchestrator owner.

### Task-id reuse

Reproduced on `7d66c721061c4d1a614c91ef38f95ea7aec91990` before the guard: `submit()` assigns `self.tasks[spec.task_id]` whenever the idempotency key is new. A second request with task id `T1` and key `K2` replaced `T1`'s handler, payload, and queued state, added a second idempotency binding, and charged the budget again. The first test run failed with `DID NOT RAISE TaskIdentityConflict`.

`submit()` now raises `TaskIdentityConflict("task id is already registered")` before writing the task, the idempotency map, the child list, the trace, or the budget. The message does not include the existing agent id, handler, payload, or idempotency key. The same rejection applies to a different agent, a changed payload, a changed handler, and a task that has already succeeded or been cancelled. A same-key, same-intent retry still returns the original id and does not run the handler again.

### Corpus pathname substitution

Reproduced before the fix, on this tree: planting `shard-0000-train.jsonl` as a symlink and calling `process_corpus` appended corpus JSON to the symlink target outside `output_dir`.

Shard reads, shard appends, shard truncation, shard digesting, the process lock, and the progress database open now go through a directory descriptor and `O_NOFOLLOW`. A symlink at the output directory leaf, at a shard name, or at the input leaf raises `CorpusBoundaryError` and does not follow the link. A stored path that is not this output directory's own `shard-NNNN-split.jsonl` is not opened. When `allowed_root` is set, each component under that root is opened with `O_NOFOLLOW`.

The progress database no longer uses `file:/proc/self/fd/<database-fd>` as its only open path. Before `sqlite3.connect`, the database file and the `-wal`, `-shm`, and `-journal` names are regular files or absent, checked with `O_NOFOLLOW` on the output directory descriptor. A symlink at any of those names raises `CorpusBoundaryError` and is not unlinked or followed. `iter_kept_records` uses the same opener.

On Linux the URI is `file:/proc/self/fd/<dirfd>/_progress.sqlite3?mode=rw`. The directory inode reported by `/proc/self/fd/<dirfd>` must match the descriptor. On Darwin the URI is built from `fcntl(F_GETPATH)` on that descriptor, and the path is accepted only when its inode is the opened directory. Any other `sys.platform` raises `CorpusBoundaryError` before `sqlite3.connect`. WAL mode and `synchronous=FULL` are required; a weaker journal mode is not accepted.

SQLite 3.45 on Linux still reports the real directory in `PRAGMA database_list` and creates `-wal` and `-shm` beside that file. The connection is rejected unless that file's inode is the no-follow descriptor. This environment executed the Linux path and the Darwin branch with a supplied descriptor path. It did not execute Darwin `F_GETPATH`.

`tests/test_genesis_data_pipeline.py` still asserts crash recovery and same-size shard tampering detection. The historical file `tests/test_audit_genesis_hardening_adversarial.py` was not edited. It remains ignored by deterministic CI as vulnerability-demonstration evidence.

## Local verification

Python 3.12. Commands:

```
python3 -m pytest tests/test_cursor_pipeline_admission.py tests/test_cursor_agent_orchestration.py tests/test_cursor_keyed_cache.py tests/test_genesis_data_pipeline.py tests/test_genesis_data_loader.py tests/test_audit_genesis_hardening_remediation.py::test_remediation_p0_03_same_size_tampering_is_detected_and_regenerated
```

On `7d66c72`, that command passed 106 tests. After the task-id guard, `tests/test_cursor_agent_orchestration.py` passed 11 tests, including `test_reused_task_id_with_a_new_key_does_not_overwrite`. The earlier failure on the unguarded code was `DID NOT RAISE TaskIdentityConflict`. No assertion was weakened. No xfail was added.

## Remaining risks for review

| Risk | State |
|---|---|
| Optional HMAC mode | Still the default to leave unkeyed cache ids unchanged. A founder-controlled key is required before keyed mode can be mandatory. Do not mint that key in the repo. |
| External rollback anchor | `FailClosedExternalAnchor` still raises `AnchorUnavailable`. `SyntheticAnchorDouble.kind` is `SYNTHETIC_TEST_DOUBLE`. No witness service exists. |
| Same-uid worker isolation | `isolated_worker.py` was not edited. Same-uid peer credentials are not a kernel sandbox. |
| Input ancestor symlinks | Followed when `allowed_root` is omitted. The leaf itself is not followed. |
| Progress database | Linux and the Darwin branch are descriptor-qualified. Other platforms refuse before connect. SQLite still resolves the real directory for WAL siblings. A same-uid swap after the no-follow check, and unexecuted Darwin `F_GETPATH`, remain outside the executed claim. |
| In-process idempotency map | A conflicting `submit()` does not return another agent's task id, and a reused task id is rejected without naming the current owner. Code that already holds the `Orchestrator` can still read `tasks` and `idempotency`. |
| Checkpoint confinement | Not reopened. No new defect was reproduced there. |
| Formal acceptance | Numerator remains 0 of 95. Training is not authorized. |
