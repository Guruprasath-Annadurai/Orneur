# Antigravity handoff — PR #128 P0-3 transcript integrity correction

**Branch:** `cursor/transcript-integrity-p03-7679`  
**Base:** PR #127 branch `cursor/inference-p0-security-closure-c12b` @ `22225086873cba5274d3ad44aab9e7ef5a913230` (FAILED_QUALIFICATION for P0-3; preserved unchanged)  
**Corrective tip SHA:** the tip of `cursor/transcript-integrity-p03-7679` (never `22225086873cba5274d3ad44aab9e7ef5a913230`). Exact value is the PR head SHA.

P0-1 (streaming DLP) and P0-2 (quota reservation replay) remain independently qualified on #127 and are **not rewritten** here.

## Why #127 P0-3 failed

Antigravity FAILED_QUALIFICATION against exact SHA `22225086873cba5274d3ad44aab9e7ef5a913230`:

1. Worker A could still commit after Worker B took over the lease (Redis claim treated as a durable write ticket; SQLite insert did not re-check the fence).
2. JSONL was written inside an uncommitted SQLite transaction — crash/rollback left phantom export lines with no authoritative turn.
3. Inference prompt builders read JSONL via `transcript()`, so uncommitted / phantom content entered subsequent LLM context.

Evidence: `docs/orneur/status/P0_TRANSCRIPT_INTEGRITY_FAILING_BEFORE.json` (3/3 defects observed on the #127 protocol).

## Closure mechanism (this PR)

| Control | Mechanism |
| --- | --- |
| Commit authority | `commit_turn` runs `BEGIN IMMEDIATE`, invokes `authority_check` (Redis `lease_held`) **inside** the txn, then inserts |
| Monotonic revisions | Next revision allocated from SQLite `MAX(revision)+1` (SoT); caller tickets cannot insert after successor |
| JSONL ordering | Derived export runs **only after** SQLite `COMMIT`; never inside the txn |
| Prompt context | `_session_messages` → `committed_messages()` (SQLite only); no JSONL fallback |
| Unavailable SQLite | `transcript(source=auto)` returns empty with `source=sqlite_unavailable` — no JSONL fallback |
| Crash-safe export | `reconcile_export(session_id)` rewrites JSONL from SQLite |
| Legacy history | `migrate_legacy_jsonl(session_id)` explicit one-shot import (never implicit) |

## Failing-before / passing-after

```bash
# Against broken #127 protocol (captured):
python3 scripts/p0_transcript_integrity_repro.py \
  --out docs/orneur/status/P0_TRANSCRIPT_INTEGRITY_FAILING_BEFORE.json
# defects_observed == 3

# Against this corrective tip:
python3 scripts/p0_transcript_integrity_repro.py --expect-fixed \
  --out docs/orneur/status/P0_TRANSCRIPT_INTEGRITY_PASSING_AFTER.json
# defects_observed == 0
```

Primary regressions: `tests/test_p0_transcript_commit.py` (lease expiry, preclaimed ticket, multi-process lease takeover, crash reconcile, prompt poison, legacy migration, rollback/retry, SQLite-unavailable).

Preserved: `tests/test_p0_stream_dlp_closure.py`, `tests/test_p0_reservation_ownership.py`.

## Independent qualification checklist

1. Check out this branch tip SHA (record exact commit — must **not** be `2222508…`).
2. Run `tests/test_p0_transcript_commit.py` against real Redis (`redis://localhost:6379/14`).
3. Re-run the three Antigravity attacks (stale persist after lease takeover; JSONL-before-commit crash; prompt contamination).
4. Confirm P0-1 / P0-2 suites still green without code changes to those closures.
5. Confirm CI on the exact tip SHA.
6. Do **not** treat PR #127 tip as P0-3 closed.

## Out of scope

No protected merges, staging/production deploy, paid infrastructure, or native training.
`/api/stream` journey (J-1 / J-2) remains open per `P0_INFERENCE_API_STREAM_COMPATIBILITY.md`.
