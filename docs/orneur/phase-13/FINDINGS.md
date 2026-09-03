# Phase 13 — Findings

Per spec §72: "a discovered failure is success of the red-team process.
Do not suppress it." This phase's actual, honest results follow.

## Summary

| Metric | Count |
|---|---|
| ATTACKS_EXECUTED (new, this phase) | 6 (4 in `test_frontier_runtime_cancellation.py` + 2 in `test_redteam_cross_layer_chains.py`) |
| EXPECTED_BLOCKS | 6 (all 6 new attacks produced the expected security-holding outcome) |
| REAL_VULNERABILITIES_FOUND | 0 |
| REAL_VULNERABILITIES_FIXED | 0 (none found to fix) |
| RESIDUAL_OPEN_FINDINGS | 0 confirmed vulnerabilities; several **disclosed scope gaps** (see below — these are untested surfaces, not confirmed vulnerabilities) |
| FALSE_POSITIVES | 0 |

**No vulnerability was discovered and fixed in this pass.** This is
reported honestly per spec §73's explicit instruction not to report "0
vulnerabilities" as if it means completeness — it means exactly what it
says: the specific attacks this phase executed did not find one, and a
large fraction of the spec's full attack list was not executed as new,
bespoke tests this pass (see "Scope not covered" below).

## Investigated and DISPROVED (not a vulnerability, but genuinely checked)

### Finding: `orca/gateway/frontier_runtime.py` cancellation-vs-timeout risk

- **Category**: PROTOCOL_CONFUSION
- **Severity**: N/A (disproved)
- **Affected subsystem**: `orca.gateway.frontier_runtime.FrontierRuntime.generate()`
- **Attack preconditions**: an enclosing `asyncio.wait_for()` deadline
  (Gateway's `total_request_timeout_s`, or any caller's own timeout)
  expires while `generate()` is awaiting `asyncio.to_thread(backend.generate, ...)`.
- **Hypothesis** (from spec §23-24, by analogy to the real Phase 11.2
  `orca/gateway/ollama_runtime.py` bug): the enclosing timeout's
  `CancelledError` might get caught and converted into a different
  exception type (`RequestCancelledError` or `RuntimeExecutionError`),
  defeating `wait_for()`'s ability to convert its own expiry into
  `TimeoutError`.
- **Observed behavior** (real test,
  `tests/test_frontier_runtime_cancellation.py::test_outer_wait_for_timeout_produces_real_timeout_not_a_cancelled_error_disguise`):
  `asyncio.wait_for(runtime.generate(request), timeout=0.1)` against a
  backend that genuinely blocks for 2 seconds correctly raises
  `asyncio.TimeoutError`, not `RequestCancelledError`.
- **Root cause of why this differs from the Ollama bug**: `generate()`'s
  only except clause is `except Exception as e: raise RuntimeExecutionError(...)`.
  Since Python 3.8, `asyncio.CancelledError` is a `BaseException` subclass,
  NOT an `Exception` subclass — so this broad except clause structurally
  cannot catch it. A genuine `CancelledError` propagates untouched, which
  is exactly what `asyncio.wait_for()`/`asyncio.timeout()` need to see to
  correctly perform their own timeout conversion.
- **Fix status**: `DISPROVED` — no fix needed, no code changed.
  `tests/test_frontier_runtime_cancellation.py` (4 tests) is now a
  permanent regression guard proving this stays true, distinguishing
  explicit task cancellation (`asyncio.CancelledError`), an outer
  deadline (`asyncio.TimeoutError`), the one genuine application-level
  cancellation path (`RequestCancelledError`, pre-check only), and a real
  backend failure (`RuntimeExecutionError`) as four DISTINCT, correctly
  separated outcomes.
- **Disclosed limitation of this finding**: `generate()`'s explicit
  pre-check cancellation (`self._cancelled_requests`) is only checked
  ONCE, before the blocking call starts — calling `.cancel(request_id)`
  WHILE `asyncio.to_thread(...)` is in flight has no effect on that
  specific call (the thread keeps running to completion; Python cannot
  forcibly kill it). This is already honestly disclosed in the module's
  own docstring (`cancel()`: "Best-effort only... this only stops the
  word-by-word buffered-streaming loop... not an in-flight API call")
  and in `capabilities().cancellation=False` — not a new finding, a
  pre-existing, disclosed design limitation, confirmed still accurate.

## Behavioral cross-layer confirmations (not vulnerabilities — expected blocks)

Both new cross-layer tests in `tests/test_redteam_cross_layer_chains.py`
produced the expected, correct denial:

1. Retrieved prompt injection claiming "capability granted" → real
   `AgentRuntime` execution → second action denied
   (`CAPABILITY_MISSING`/`POLICY_DENIED`).
2. Connector-sourced injected content → real `CourtCase`/`CourtVerdict`
   with `ACCEPT` → no code path exists from that verdict to
   `orca.godmode.issuance.issue_lease()`.

## Scope not covered this phase (disclosed, not silently omitted)

- RAG source-independence / citation-confusion / temporal-truth attacks
  (spec §12-15) — audited (existing coverage confirmed present for the
  general injection-exclusion property), no new bespoke poisoned-corpus
  tests built.
- Memory staleness-vs-fresh-Truth reconciliation (spec §19) — not newly
  tested.
- JSON/structured-input bomb testing against the API layer (spec §53).
- Regex/parser DoS formal analysis (spec §54) — only a quick visual audit
  performed, not a timing/fuzz analysis.
- Bounded fuzz/property testing (spec §58-59) — not implemented.
- Penetration-style API endpoint tests (spec §66) — not newly executed
  this phase beyond existing `test_auth_*`/`test_org_store.py` coverage.
- Log injection / audit tampering formal analysis (spec §68-69) — not
  newly tested.
- Live-model red-team resistance tests (spec §60, §65) — not run this
  phase (would require live Ollama calls; existing
  `tests/test_redteam_jailbreak_trials.py`/`test_redteam_bias_trials.py`
  already cover the closest existing equivalent).

These are genuine, disclosed gaps in this pass's coverage — not claims
that the underlying subsystems are insecure, and not vulnerabilities.
They are documented here so a future pass has an honest starting point
rather than a false "fully red-teamed" claim.

## Severity table (genuine findings only)

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 0 |
| LOW | 0 |

(Zero because zero real vulnerabilities were found — see summary above
for why this is reported honestly rather than omitted.)
