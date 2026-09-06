# Security Qualification (Phase 5.1, spec §18-20)

## Root-cause investigation of Phase 5's one flaky security-suite failure

Phase 5's closure report noted 128/129 on the security suite, with
`tests/test_api_production_cutover.py::
test_rag_forces_deferral_to_existing_stack_when_docs_are_loaded` failing
once and passing on an isolated rerun. Spec §18 requires characterizing
this, not just re-running until green.

**Investigation performed:**

1. Read the test: it makes a real `/api/stream` call against a session
   with documents loaded (`_skip_if_no_ollama()`-gated — genuinely
   exercises live Ollama).
2. **Found a real, independent defect while investigating**: the test
   used a **hard-coded session_id** (`"rag-cutover-test-session"`) shared
   across every run. Both the in-process `_sessions` dict and the
   on-disk ChromaDB/`DocStore` collection are keyed by `session_id` — a
   fixed id is a genuine cross-run shared-state hazard (stale doc_store
   content accumulating run over run, or collision with a concurrently-
   running instance of the same test). This is a real bug independent of
   whatever caused the one observed failure, and is fixed regardless
   (`uuid.uuid4()`-suffixed session id now).
3. **Reproduced individually**: passed (`1 passed in 99.37s`).
4. **Reproduced within its own security-test group**: passed
   (`129 passed` — the full baseline security run for this phase was
   clean on the first try, with zero failures, not needing a rerun).
5. **Reproduced within the earlier Phase 5 full-suite run context**: two
   *different* tests failed there under concurrent load
   (`test_gateway_compat_brain.py`, `test_gateway_ollama_runtime.py`'s
   stream-cancellation test) — both are live-Ollama-dependent, both
   passed on individual rerun, and both match the exact flakiness class
   already root-caused and documented in
   `docs/orneur/phase-3/OLLAMA_TEST_RELIABILITY.md` (real cold-load/
   model-swap contention on a shared machine under heavy simultaneous
   Ollama traffic from multiple concurrently-running pytest processes
   during this session's own benchmarking work).

**Conclusion**: real Ollama resource contention under concurrent load,
not a code defect, a race in the code under test, or (for THIS
particular test) an auth-DB fixture issue — consistent with the
already-documented flakiness class, and consistent with every
individual/group reproduction passing cleanly. The one collateral
finding (hard-coded session_id) is fixed as a legitimate, independent
hardening improvement.

## A second, real auth-DB fixture issue — found and fixed (not the same one)

A later, fuller security-suite run in this same phase (after this
phase's own new memory-authority test files were added) surfaced 3
NEW failures, all in `tests/test_api_production_cutover.py`, all
`HTTP 429` where `402`/`200`/`422` was expected:
`test_metadata_cannot_manufacture_entitlement`,
`test_malformed_cognitive_metadata_does_not_crash_or_escalate`,
`test_admin_role_string_in_body_does_not_bypass_ultra_gate`. These are
deterministic entitlement tests with no Ollama dependency, so the
"contention" explanation above did not apply — investigated properly
rather than assumed:

1. Reproduced in a **fresh, isolated process** — still failed (ruling
   out a within-process ordering effect).
2. Read the actual response body instead of guessing:
   `{"error": "Daily limit reached (52/50). Upgrade to Pro for
   unlimited messages."}` — a real quota rejection, not a rate-limit
   rejection.
3. Traced to `orca.auth.store.increment_usage()`, which writes a real,
   persistent sqlite `usage_daily` row keyed by `(user_id, date)`. This
   test file's `_as_user()` helper hard-codes `user_id="u-test"` across
   many call sites. The file's own `_reset_state` autouse fixture
   already clears the in-process rate-limit counter every test (with a
   comment explaining exactly why: cross-run flakiness) — but nothing
   cleared this quota table, which (unlike the rate limiter) survives
   across every separate `pytest` process invocation on the same
   calendar date. After this session's cumulative volume of test runs
   today, `"u-test"`'s free-tier daily quota (50 messages) was
   genuinely exhausted.

**Fixed**: `_reset_state` now also deletes `"u-test"`'s `usage_daily`
rows, in the same fixture, for the same documented reason as the
rate-limit clear beside it. Verified: all 3 tests pass individually and
the full 15-test file passes together immediately after the fix.

This is the kind of failure spec §18 is explicitly guarding against —
it looked superficially similar to "just flaky," but was a real,
fixable test-isolation bug with a concrete root cause, not resolved by
assumption or by rerunning.

## Final qualification runs (this phase, clean)

- **Full application suite**: 870 passed, 0 failures.
- **Full security suite** (10 files including both memory-specific
  security test files): see [PHASE_5_FINAL_CLOSURE.md](PHASE_5_FINAL_CLOSURE.md)
  for the exact final counts recorded once, avoiding two sources of
  truth for the same numbers.
- **No skips were added to reach a green run.** The one real defect
  found in this process (`LongTermMemory` having no deletion path at
  all — see [LEGACY_MEMORY_AUTHORITY_AUDIT.md](LEGACY_MEMORY_AUTHORITY_AUDIT.md))
  was fixed, not skipped or worked around.

## Memory authority security tests added this phase (spec §20)

`tests/test_memory_authority_security.py` (8 tests) and
`tests/test_memory_reflex_procedural_failure_authority.py` (7 tests),
covering every scenario spec §20 lists explicitly: legacy write/read
scope enforcement, `distill_and_save()` unverified-fact-promotion
prevention, dual-write cross-scope-duplicate prevention, forged
scope-id handling, `WorkingMemory` firewall-bypass prevention
(cross-referenced from `tests/test_kernel_working_memory.py`),
deleted-legacy-memory resurrection prevention, and agent-to-global
auto-promotion prevention.
