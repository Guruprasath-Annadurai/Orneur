# Fault injection

`orca/pretrain_foundation/faults.py` `publish_bytes` writes a temp file in the destination directory and renames it.

Injected modes, each of which raises `InjectedFault` and leaves the destination bytes unchanged:

- `disk_full` before any payload is written
- `partial_write` after a short write to the temp file
- `after_write_before_rename` after fsync and before `os.replace`

A symlink destination is refused. The test checks the symlink target is not overwritten.

Tests: `tests/test_cursor_fault_injection.py`.

The GENESIS checkpoint and pipeline code on the base already covers crash windows for those formats. This helper is the small publisher used by new tests. It is not a second checkpoint format.

Agent-level faults (timeout, handler exception, cancellation, duplicate idempotency key) are in `tests/test_cursor_agent_orchestration.py`.
