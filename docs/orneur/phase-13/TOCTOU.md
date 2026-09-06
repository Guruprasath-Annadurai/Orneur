# Phase 13.1 — TOCTOU / Concurrency

4 new attacks executed against real code, using real threading, a real
barrier for synchronization, and a real multi-process race
(`tests/test_redteam_toctou.py`).

| ID | Attack | Mechanism | Status | Severity |
|---|---|---|---|---|
| TOCTOU-01 | Revoke racing `consume_use()` | Real `threading.Barrier` + 2 real threads | BLOCKED_AS_EXPECTED — post-race state is consistently denied | — |
| TOCTOU-02 | Kill-switch activation racing consume | Real `threading.Barrier` + 2 real threads, verified via `resolve_and_consume_lease()` (the real caller-facing entry point) | BLOCKED_AS_EXPECTED | — |
| TOCTOU-03 | Concurrent `save()` attempts after `freeze()` | Real `threading.Barrier` + 2 real threads | BLOCKED_AS_EXPECTED — `DatasetFrozenError` raised in both racing threads | — |
| TOCTOU-04 | One-use lease consumed by TWO REAL OS PROCESSES | `multiprocessing.Process` (spawn context, not threads), shared `ORCA_HOME` | **REAL_VULNERABILITY — reproduced in Phase 13.1, FIXED in Phase 13.2** | MEDIUM (was HIGH if ever deployed multi-process without a fix) |

## The real finding (TOCTOU-04)

`orca.godmode.lease_store`'s own module docstring already states its
atomicity is "atomic across concurrent callers **within this process**"
— a per-lease-id `threading.Lock`. This phase's spec explicitly demanded
verifying this claim with a REAL multi-process test rather than assuming
process-level atomicity from thread tests (§36: "Do not silently assume
process-level atomicity from thread tests").

**Test**: `test_toctou04_real_multiprocess_race_on_one_use_lease` spawns
two genuine, separate OS processes (`multiprocessing.get_context("spawn")`,
which re-execs and re-imports fresh — not `fork`, which could
accidentally share in-memory lock state) against ONE real, file-backed,
one-use `CapabilityLease`, with `ORCA_HOME` set to the same directory for
both. `consume_use()`'s read-modify-write (`get()` reads the JSON file,
`save()` writes it back) has **no file-level lock** — no `fcntl.flock` or
equivalent advisory lock on the lease file itself. Two independent
processes, each with their own separate in-memory `threading.Lock`
object, can both read `uses_remaining == 1` before either writes back
`0`.

**Result at Phase 13.1 close**: the test was written to `pytest.xfail()`
with a full, non-hidden explanation whenever BOTH processes reported a
successful consumption (`successful_consumptions > 1`) — confirmed
reproduced, recorded in the deterministic suite as `1 xfailed`, never
silently green.

## Phase 13.2 — FIXED

`orca/godmode/lease_store.py` was rewritten to a SQLite-backed store
using `BEGIN IMMEDIATE` transactions for `consume_use()`/`revoke()` — see
`GODMODE_DISTRIBUTED_ATOMICITY.md` for the full design. The `xfail` was
removed entirely; `test_toctou04_real_multiprocess_race_on_one_use_lease`
is now a permanent, passing regression guard
(`assert successful_consumptions == 1`, no escape hatch). A dedicated,
much more thorough regression suite,
`tests/test_godmode_distributed_atomicity.py` (11 tests), additionally
covers repeated-iteration 2-process races, 8-process/3-use high
contention, revocation/kill-switch/expiry races, restart safety,
corruption handling, and the real `resolve_and_consume_lease()`/file-
elevation caller paths.

Zero `xfail`/`@pytest.mark.xfail` markers remain anywhere in the
repository (confirmed by `grep -rn "pytest.xfail\|@pytest.mark.xfail" tests/*.py` — no matches).
