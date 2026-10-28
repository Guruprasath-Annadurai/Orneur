# DISTRIBUTED_CONCURRENCY_REPORT

**Tip:** `7c8f7b0e3a2724e77f3be971f7b36cc17ebe530f`  
**Label:** VERIFIED_ENGINEERING for unit/multiprocess fixtures; not a cloud multi-node soak.

## Architecture under test

- SQLite `session_authority` epochs + `conversation_turns` (authoritative).
- Redis session lease / revision (advisory).
- Quota reservations in auth DB (atomic).

## Scenarios

| Scenario | Result | How verified |
|---|---|---|
| Same-session stale worker after lease/authority expiry | Stale commit refused (`stale_authority` / `authority_expired`) | `tests/test_p0_transcript_integrity.py`, `tests/test_p0_transcript_commit.py` |
| Successor takeover increments epoch | Prior fence cannot commit | Same |
| Concurrent quota at 49/50 | Exactly one admit of three | `tests/test_foundation01_quota_admission.py` |
| Cross-user request_id theft | Refused | Same |
| Consumed replay | No second dispatch | Same |
| Two application processes sharing Redis | Partially covered by ancestor workers (`tests/_quota_worker.py`, `_transcript_lease_worker.py`) | Run explicitly with real Redis before claiming G8 complete |
| Redis outage | Advisory paths fail soft; SQLite authority remains | Design contract; dedicated outage soak outstanding |
| Temporary-chat close during generation | Publish gate + finish cascade | temporary_chat + stream publish helpers |
| Per-process-only locks | Not claimed as cross-process protection | SQLite + Redis used for cross-process |

## Commands

```bash
.venv/bin/pytest -q tests/test_p0_transcript_integrity.py tests/test_p0_transcript_commit.py tests/test_foundation01_quota_admission.py tests/test_p0_reservation_ownership.py
```

## Gaps (honest)

- Full two-worker Redis restart/outage matrix on this exact tip not yet executed in this agent environment.
- Do not treat local unit green as “global distributed readiness.”
