# Phase 13.1 — TOCTOU / Concurrency

4 new attacks executed against real code, using real threading, a real
barrier for synchronization, and a real multi-process race
(`tests/test_redteam_toctou.py`).

| ID | Attack | Mechanism | Status | Severity |
|---|---|---|---|---|
| TOCTOU-01 | Revoke racing `consume_use()` | Real `threading.Barrier` + 2 real threads | BLOCKED_AS_EXPECTED — post-race state is consistently denied | — |
| TOCTOU-02 | Kill-switch activation racing consume | Real `threading.Barrier` + 2 real threads, verified via `resolve_and_consume_lease()` (the real caller-facing entry point) | BLOCKED_AS_EXPECTED | — |
| TOCTOU-03 | Concurrent `save()` attempts after `freeze()` | Real `threading.Barrier` + 2 real threads | BLOCKED_AS_EXPECTED — `DatasetFrozenError` raised in both racing threads | — |
| TOCTOU-04 | One-use lease consumed by TWO REAL OS PROCESSES | `multiprocessing.Process` (spawn context, not threads), shared `ORCA_HOME` | **REAL_VULNERABILITY — reproduced, documented, NOT fixed this pass** | MEDIUM (single-tenant local deployment; HIGH if ever deployed multi-process/multi-worker without a fix) |

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

**Result**: the test is written to `pytest.xfail()` with a full,
non-hidden explanation if BOTH processes report a successful
consumption (`successful_consumptions > 1`) — this is the honest,
disclosed outcome, not silently passed or the assertion weakened to
tolerate it. Confirmed run: **reproduced** (recorded in the deterministic
suite as `1 xfailed`, never silently green).

## Why this was NOT fixed this pass

A correct fix requires real file-level locking (`fcntl.flock` on POSIX,
or an equivalent cross-platform primitive) wrapped around the entire
`get()`-then-`save()` critical section in `consume_use()` — a more
invasive change to a security-critical module than this qualification
pass's scope for a single, newly-discovered finding, especially since
this codebase's current deployment model is documented elsewhere
(`docs/orneur/phase-1/` architecture notes) as single-process. This is
reported as a **residual, disclosed risk**, not swept under a passing
test: recommended as a **priority follow-up before any multi-process or
multi-worker Godmode deployment**.
