# Antigravity handoff — PR #128 transcript integrity (corrective)

**Branch:** `cursor/inference-transcript-integrity-c12b`  
**Parent candidate (preserve):** PR #127 @ `22225086873cba5274d3ad44aab9e7ef5a913230` (exact-head CI 9/9; Antigravity **FAILED_QUALIFICATION**)  
**Scope:** Corrective isolation of the conversation-commit protocol only. Do not treat green CI alone as qualification.

## Consistency contract

| Layer | Role |
| --- | --- |
| **SQLite** (`session_authority`, `conversation_turns`, `session_export_state`) | **Authoritative** commit authority, fencing epochs, committed revisions, migration state |
| **Redis** (lease + `claim_turn_commit`) | **Advisory** coordination/cache only. A Redis revision claim alone never authorizes a SQLite insert |
| **JSONL** | **Derived export** rebuilt from committed SQLite rows after COMMIT via temp-file replace. Never read as truth |

Fail closed: unavailable / unverifiable authority → reject commit. SQLite read errors → empty transcript with `error`, never JSONL fallback. Empty SQLite is never automatic permission to trust JSONL (requires `reconcile_legacy_session` → `migration_state='verified'`).

## Commit boundary

1. **Acquire (short txn):** Redis advisory lease + SQLite `session_authority` insert/renew/takeover. Takeover increments `epoch`, invalidating prior fence tokens. Transaction is **not** held open during model generation.
2. **Generate:** model / stream work outside any write txn; optional `renew_authority` keeps expiry alive.
3. **Commit (short txn):** validate fence + epoch + expiry + owner + `committed_revision + 1` CAS; insert paired user/assistant turn; mark `export_pending=1`; COMMIT.
4. **Export (post-commit):** rebuild JSONL from SQLite; clear `export_pending`. Export failure cannot alter conversation truth.
5. **Release:** expire authority + Redis lease.

Crash after insert / before COMMIT → rollback (`_test_crash_after_insert`). Crash after COMMIT / before export → `reconcile_pending_exports()` rebuilds JSONL; truth already durable.

## Antigravity original failures (closed)

| # | Attack | Closure |
| --- | --- | --- |
| 1 | Worker A claim → pause → lease expires → B claim+commit → A resumes | SQLite epoch fencing; A's commit → `stale_authority` |
| 2 | Process kill after write work before txn completion | Crash boundary rolls back; transcript empty |
| 3 | Failed/rolled-back turn in model history | `_session_messages` / `transcript` read SQLite only |

Additional coverage: B claimed but not committed when A resumes; SQLite busy / disk-full export / partial export; Redis restart; duplicate turn_id/revision; two OS workers; different users/sessions; temp-chat close; edits/rebuild via SQLite SoT; legacy JSONL migration.

**Evidence:** `tests/test_p0_transcript_integrity.py`, `tests/test_p0_transcript_commit.py`.

### Failing-before / passing-after (attack #1 shape)

Parent defect shape (revision `UNIQUE` only — reconstructed): after B commits revision 2, A can still insert superseded revision 1 → both `A-STALE` and `B-ok` visible.

```
FAILING_BEFORE parent-shape: [(1, 'A-STALE'), (2, 'B-ok')]
PASSING_AFTER: stale_authority; messages == ['B', 'Bb']
```

Recorded locally against this corrective protocol; re-verify on tip SHA.

## `/api/chat` and `/api/stream` integration

`api._persist_turn` now: `acquire_authority` → `commit_turn` → `release_authority` (same SoT as `/api/inference/*`). Message list/export routes call `reconcile_legacy_session` before `transcript`. Quota admission on `/api/stream` remains check-then-increment (not reservation-fenced) — out of scope for this corrective. PR #126 conversation-context work is **not** completed here.

## Preservation (P0-E)

Do not regress independently qualified streaming DLP, quota ownership/replay, server-authoritative catalog, session isolation, Redis advisory fencing, frontend response contracts. Re-run:

- `tests/test_p0_stream_dlp_closure.py`
- `tests/test_p0_reservation_ownership.py`
- `tests/test_serving_policy_adversarial.py`
- `tests/test_inference_gateway.py`
- `tests/test_critical_sse_dlp.py`

## Environment notes

- Real Redis: `redis://localhost:6379/15` for integrity tests (isolated DB).
- Live Ollama: use environment daemon when present; otherwise synthetic fixture transports.
- No protected merges, deploy, paid infra, or native training.

## Remaining limits (disclose)

- Pattern DLP remains floor-not-ceiling.
- `/api/stream` quota is still not reservation-fenced (separate journey).
- JSONL export is best-effort; truth is SQLite. Operators must run/allow `reconcile_pending_exports` after unclean shutdown if derived files matter.
- Legacy JSONL is invisible until explicit `reconcile_legacy_session`.
- Authority TTL renewals are caller-driven; a hung worker that never renews will be superseded after expiry (intended).

## Independent qualification checklist

1. Record exact tip SHA of this branch.
2. Run integrity + preservation modules against real Redis.
3. Re-attack the three original Antigravity scenarios plus multi-process/crash boundaries.
4. Confirm exact-head CI green.
5. Stop at independent qualification — do not merge.
