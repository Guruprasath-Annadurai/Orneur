# Phase 13.1 — Deep Red-Team Closure

**Repository**: orca | **Branch**: session-update-2026-08-25

**Superseded by Phase 13.2's own closure below** — Finding 3 (Godmode
cross-process lease race), open and `xfail`ed at the time this document
was first written, is now FIXED. Kept here unedited otherwise as the
honest historical record of what was known and reported at Phase 13.1
closure time.

## What Phase 13.1 did differently from Phase 13

Phase 13's own closure was rejected as insufficient: only 6 new attacks
were executed, with most campaigns satisfied by citing existing
coverage. Phase 13.1 required active, new adversarial discovery per
campaign. This phase executed **55 new attacks** across 8 new test
files, finding and fixing **2 real vulnerabilities** and documenting
**1 real, unfixed residual finding** — none of which existed or were
known before this phase's own active attack work.

## Real vulnerabilities found and fixed

1. **RAG source-independence never consulted** (`orca/truth/state.py`) —
   an evidence set of N mutually-derived (mirrored/syndicated) sources
   reached `SUFFICIENT` exactly as if independently corroborated. Fixed:
   downgrades to `PARTIAL` when all sources are `LIKELY_DERIVED`.
2. **Godmode canonicalizer recursion crash** (`orca/godmode/canonical.py`) —
   a 500-level-deep argument payload crashed `issue_lease()`/
   `resolve_lease()` with an uncaught `RecursionError`. Fixed: bounded
   depth counter raising a typed `ArgumentTooDeeplyNestedError`.

## Real finding, documented, not fixed this pass

3. **Godmode one-use lease cross-process race** (`orca/godmode/lease_store.py`) —
   a genuine multi-process test proves the module's atomicity claim is
   in-process only. Reproduced, `xfail`ed with full documentation, not
   hidden. Recommended priority follow-up before any multi-process
   Godmode deployment.

## Test results (fresh, this closure)

| Suite | Result |
|---|---|
| Full application suite (deterministic) | 1448 passed, 0 failed, 1 xfailed, 43 deselected |
| Authoritative security suite (89 files) | 790 passed, 0 failed, 1 xfailed, 4 deselected |
| Live suite (`-m live_ollama_smoke`) | **43 passed, 0 failed** (726.77s) |
| New red-team tests | 55/55 executed, 52 passed clean, 2 real findings fixed, 1 real finding documented/xfailed |

## Vulnerability accounting (honest, spec §45/§73-75)

- NEW_ATTACKS_EXECUTED: **55**
- EXISTING_SECURITY_TESTS_REUSED: **733** (unmodified, reconfirmed green; now 790 total after this phase's 9 new files joined the inventory)
- REAL_VULNERABILITIES_FOUND: **3**
- REAL_VULNERABILITIES_FIXED: **2**
- OPEN_FINDINGS: **1** (documented, `xfail`ed, disclosed — not silently passed)
- FALSE_POSITIVES: **1** (RAG-06's initial hypothesis, corrected after actually running the test)

## Severity

CRITICAL: 0 | HIGH: 0 | MEDIUM: 3 (2 fixed, 1 residual) | LOW: 0

## PROCESS_EXECUTION Godmode

Remains **disabled** — not enabled to test it, unchanged from Phase 13.

## Model lifecycle

Genesis/Novus/Aeternum unchanged — no red-team fix in this phase touched
any model checkpoint, registry entry, or lifecycle state.

## Known residual risks (disclosed)

1. Godmode one-use lease cross-process race (Finding 3) — not fixed,
   documented, recommended priority follow-up.
2. RAG citation-confusion attacks (negation/entity/numeric) against the
   deterministic lexical FALLBACK path are disclosed, pre-existing
   limitations (ceiling verified to hold) — not newly introduced, not
   fixed (would require real NLI capability the live judge already
   provides on the non-degraded path).
3. Structured-input bomb testing against the live API/serve layer (as
   opposed to the AgentPlan/Godmode/Truth-budget layers actually
   attacked) was not newly executed this phase.
4. Regex/parser DoS was measured via timing on one representative
   function (`redact_secrets`); a full audit of every security-sensitive
   regex in the codebase was not exhaustively re-timed.

## Remaining Phase-13 blockers

None — Finding 3 is disclosed residual risk, not a blocker, per spec
§75's "some risks may remain intentionally... do not claim perfect
security."

**READY TO ADVANCE TO PHASE 14: YES** *(superseded — see Phase 13.2 below for the final answer)*

---

# Phase 13.2 — Distributed-Authority Security Closure

**Repository**: orca | **Branch**: session-update-2026-08-25

## What Phase 13.2 closed

The one real security blocker left open by Phase 13.1: Godmode one-use
leases were atomic only within a single Python process. Fixed by
rewriting `orca/godmode/lease_store.py`'s persistence backend to SQLite
with `BEGIN IMMEDIATE` transactions — see `GODMODE_DISTRIBUTED_ATOMICITY.md`
for the full audit and design.

While building the required delegation-race test for that fix (spec
§17), a SECOND, distinct real vulnerability was found and fixed in the
same pass: `orca.godmode.delegation.delegate_lease()` never actually
reserved uses from the parent lease, allowing authority multiplication
(a 5-use parent could spawn a 5-use child, doubling total authority to
10). Fixed with a new atomic `reserve_uses()` function using the same
transaction discipline.

## Original exploit (re-confirmed as the pre-fix baseline)

Before implementation changes, the existing `xfail`ed reproducer
(`tests/test_redteam_toctou.py::test_toctou04_real_multiprocess_race_on_one_use_lease`)
was re-run and confirmed to still demonstrate the bug (per spec §1's
explicit requirement not to fix blind) — 2 real OS processes, a
`max_uses=1` lease, and (pre-fix) both processes could report a
successful consumption.

## The fix

SQLite-backed lease store (`ORCA_HOME/godmode/leases.db`, stdlib
`sqlite3`, no new dependency). `consume_use()`/`revoke()` run their
entire read-validate-mutate-persist sequence inside one `BEGIN IMMEDIATE`
transaction — a RESERVED lock enforced by SQLite's own file-locking,
genuinely visible across process boundaries. Lock/transaction failure
fails closed (deny), bounded at a 5-second timeout. All existing
function signatures preserved — zero changes needed to `resolution.py`,
`issuance.py`, `session.py`, or any of the 82 pre-existing Godmode tests.

## Test results (fresh, this closure)

| Suite | Result |
|---|---|
| Full application suite (deterministic) | **1461 passed, 0 failed, 0 xfailed** (up from 1448/0/1) |
| Authoritative security suite (90 files) | **803 passed, 0 failed, 0 xfailed** (up from 790/0/1) |
| Live suite (`-m live_ollama_smoke`) | see the final chat-delivered report for the confirmed post-fix result |
| New regression tests | 12/12 (`tests/test_godmode_distributed_atomicity.py`) — 2-process repeated race, 8-process high contention, revocation/kill-switch/expiry races, delegation race (Finding 4), restart safety, corruption, real-caller-path (AgentRuntime-compatible + file elevation), performance baseline |

## Multiprocess evidence

- **2-process, max_uses=1, 5 repeated iterations**: exactly 1 success and `uses_remaining=0` every single iteration.
- **8-process, max_uses=3, high contention**: exactly 3 successes, `uses_remaining=0`, never negative.
- **Real caller path** (`resolve_and_consume_lease()`, the actual function AgentRuntime/connector elevation call): 2 processes, only 1 reaches `ALLOW`.
- **File elevation path** (`elevated_write_file()`): 2 processes, only 1 privileged write authorized.
- **Delegation race** (Finding 4): 2 processes each attempting to delegate 3 uses from a shared 5-use parent (2×3=6>5) — exactly 1 succeeds, parent ends at `uses_remaining=2`.

## Vulnerability accounting (final)

- REAL_VULNERABILITIES_FOUND (Phase 13.1 + 13.2 combined): **4**
- REAL_VULNERABILITIES_FIXED: **4** (all four)
- OPEN_FINDINGS: **0**
- MULTIPROCESS_LEASE_USE_RACE: **0**, based on 12 passing, executable, real-multiprocess regression tests — not structural reasoning.

## Severity (final)

CRITICAL: 0 | HIGH: 0 | MEDIUM: 4 (all fixed) | LOW: 0

## Xfail policy compliance (spec §33)

`grep -rn "pytest.xfail\|@pytest.mark.xfail" tests/*.py` — **zero matches**
anywhere in the repository. No hidden duplicate reproducer exists.

## PROCESS_EXECUTION Godmode

Remains **disabled** — unchanged, not enabled to test it.

## Phase 14 compatibility

This fix guarantees correctness for multiple LOCAL processes sharing one
host's authority store — explicitly NOT a distributed (multi-host)
solution (no Kubernetes service, no Redis cluster, no consensus
protocol was built, per spec §40's explicit prohibition). A future
Phase 14 multi-host architecture would need a real distributed
transactional store behind the same, deliberately-unchanged
`lease_store` function signatures.

## Known residual risks (disclosed)

1. RAG citation-confusion attacks against the deterministic lexical
   fallback path remain a pre-existing, honestly-labeled limitation
   (unchanged from Phase 13.1).
2. Structured-input bomb testing against the live API/serve layer was
   not newly executed.
3. This fix is host-local only (SQLite file locking) — a genuinely
   distributed (multi-host) deployment is explicitly out of scope,
   reserved for Phase 14 per spec §39-40.
4. Connector elevation's multiprocess path was NOT separately tested
   with a dedicated worker (only file elevation got one) — both share
   the exact same underlying `resolve_and_consume_lease()` function,
   already proven atomic via the AgentRuntime-compatible and file-
   elevation tests, but a connector-specific reproduction was not built.
5. "Crash consistency" (spec §19) was tested via a module-reload-based
   restart-safety check, not a literal `kill -9` mid-transaction
   injection — SQLite's own rollback-journal durability provides real
   protection here by design, but this phase did not construct an
   explicit hard-kill test to demonstrate it directly.
6. A pre-existing, unrelated live test
   (`tests/test_truth_fabric_integration.py::test_verify_answer_supports_a_grounded_claim`)
   showed a transient `TruthTimeoutError` under sustained full-suite
   load in earlier runs this session — confirmed unrelated to any
   Phase 13.2 change (zero code overlap) and confirmed to pass reliably
   in isolation; see the final report for this run's actual result.

## Remaining Phase-13 blockers

None.

**READY TO ADVANCE TO PHASE 14: YES** *(superseded — see Phase 13.3 below for the final answer)*

---

# Phase 13.3 — Final Distributed-Authority Qualification

## What Phase 13.3 closed

The two evidence gaps Phase 13.2 disclosed as residual risks (#4 and #5
in its own list above), and nothing else — per the governing spec's
explicit instruction to close only these two gaps and not begin Phase 14
work in the same pass.

1. **Real crash consistency**: five test-only, env-var-gated checkpoint
   hooks added to `orca/godmode/lease_store.py` (inert unless
   `GODMODE_TEST_CRASH_CHECKPOINT` is set, which no production
   deployment sets); a real `multiprocessing.Process.kill()` (SIGKILL)
   sent to a real child process at each checkpoint, for `consume_use()`,
   `revoke()`, and `reserve_uses()`. Full results:
   [`CRASH_CONSISTENCY.md`](CRASH_CONSISTENCY.md).
2. **Connector multiprocess E2E**: a dedicated multiprocess race through
   the real `evaluate_connector_policy_with_elevation()` path (not
   direct `lease_store` calls), using Phase 9's existing deterministic
   fake connector/provider — no new provider integrations. Includes
   wrong-action, wrong-tenant, and revocation-race controls, with an
   explicit marker-file proof that authorization gating (not provider
   idempotency) is what limits writes to exactly one. Full results:
   [`CONNECTOR_MULTIPROCESS_AUTHORITY.md`](CONNECTOR_MULTIPROCESS_AUTHORITY.md).

## New findings

None. This phase closed disclosed evidence gaps rather than hunting for
new vulnerability classes — see `FINDINGS.md`'s Phase 13.3 section.

## New tests added

- `tests/test_godmode_crash_consistency.py` — 11 tests (pre-commit crash
  ×4 checkpoints, post-commit crash, revocation crash ×3 checkpoints,
  delegation crash ×3 checkpoints).
- `tests/test_connector_multiprocess_authority.py` — 4 tests (core race,
  wrong-action control, wrong-tenant control, revocation race).

Both files added to `docs/orneur/phase-9/security_suite_files.txt`.

## Production code changes

One file: `orca/godmode/lease_store.py` — five `_test_checkpoint()` call
sites added (no-ops in production), plus the `_test_checkpoint()`
function itself. No other production behavior changed. Performance is
unchanged from Phase 13.2 (the full pre-existing godmode suite continues
to run in the same sub-second range it did before this phase).

## Vulnerability accounting (final, Phases 13.1-13.3 combined)

- REAL_VULNERABILITIES_FOUND: **4** (unchanged from Phase 13.2)
- REAL_VULNERABILITIES_FIXED: **4** (all four)
- OPEN_FINDINGS: **0**
- New Phase 13.3 audit counters, all confirmed **0**:
  `AUTHORITY_CRASH_EXTRA_USE`, `AUTHORITY_CRASH_CORRUPTION`,
  `AUTHORITY_COMMIT_RESPONSE_LOSS_RETRY`,
  `CONNECTOR_MULTIPROCESS_DOUBLE_EXECUTION`.

## Known residual risks (disclosed, carried forward)

1. This work proves process-crash consistency (real SIGKILL), not
   physical-disk/power-loss durability — see `CRASH_CONSISTENCY.md`'s
   durability-scope section for the precise, conservative claim.
2. A dedicated connector-specific kill-switch race was intentionally not
   added as a second race test, on top of the connector revocation race
   that was added — justified in
   `CONNECTOR_MULTIPROCESS_AUTHORITY.md` by the fact that connector
   elevation shares the exact kill-switch-check code path already
   proven race-safe by Phase 13.2's own kill-switch-race test.
3. All Phase 13.2 residual risks not specifically targeted by this phase
   (host-local-only SQLite locking; RAG fallback-path limitations;
   structured-input bomb testing against the live API/serve layer not
   newly executed) remain unchanged and are not re-litigated here.

## Remaining Phase-13 blockers

None.

**READY TO ADVANCE TO PHASE 14: YES**
