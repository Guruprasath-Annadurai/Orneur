# FAILURE_RECOVERY_AND_DATA_INTEGRITY_REPORT

**Tip:** `7c8f7b0e3a2724e77f3be971f7b36cc17ebe530f`

## Protocol reminders

1. SQLite COMMIT is authoritative for turns.
2. JSONL export is derived and may lag; reconcile repairs.
3. Redis lease loss does not roll back a committed SQLite turn; it blocks stale workers from new inserts.

## Injected / tested boundaries

| Boundary | Expected | Evidence |
|---|---|---|
| Before commit | No turn | Generation without `commit_turn` leaves SQLite empty |
| Authority expired before commit | `authority_expired` / stale | `tests/test_p0_transcript_integrity.py` |
| Wrong epoch / fence | `stale_authority` | Same |
| After SQLite commit, export skipped | Turn present; export pending | commit helpers `_test_skip_export` on #130 lineage |
| Crash after insert flag | No partial authoritative visibility without COMMIT | `#130` crash hooks |
| Quota failure after reserve | `release_admission` refunds | `tests/test_foundation01_quota_admission.py` |
| Provider failure after reserve | Routes call `release_admission` on error paths | `orca/serve/api.py` chat/stream/ultra/vision |
| Temporary finish | Contents deleted; lock unlinked after flock | `temporary_chat._unlink_lock` |

## Redis outage

- Advisory save/CAS returns false / soft-fail; chat path must not 500 solely because Redis is down.
- Commit authority remains SQLite fencing.

## Gaps

- Full process-kill matrix across export/reconcile/migration on this tip still needs Antigravity adversarial runs.
- Do not equate unit crash flags with production chaos testing.
