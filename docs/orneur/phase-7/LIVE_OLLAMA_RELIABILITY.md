# Live Ollama Test Reliability — Observability Test (Phase 7.2 spec §19-23)

## Reproduction (spec §19)

`tests/test_gateway_observability_cutover.py::test_real_api_request_emits_real_gateway_metrics`
was run 5× in isolation before any fix: **5/5 passed**, 3.9-6.9s each. No
failure reproduced in isolation. This matches the original full-suite
failure being a single, non-reproducing-in-isolation event — genuine
environmental flakiness, not a deterministic bug in the test's own logic.

## Root cause (spec §20-21)

The test was **not marked `live_ollama_smoke`** despite making a real,
unmocked HTTP call through the full app to a local Ollama instance. This
meant:

1. It silently ran inside every "deterministic" (`-m "not live_ollama_smoke"`)
   suite pass, alongside ~1000 other tests in one long pytest session,
   fully exposed to whatever real-Ollama contention existed at that exact
   moment (this session independently reproduced a much more severe,
   confirmed-environmental version of the same class of issue: running
   two full pytest processes concurrently against the same local Ollama
   instance caused an apparent 8-minute "hang" that was actually queued,
   not broken — see this session's own investigation history).
2. The test's prompt (`"hi"`) has **no bound on reply length** -- a
   nano-tier model can answer "hi" with anywhere from one word to several
   sentences, making the real generation duration -- and therefore the
   test's exposure window to transient Ollama slowness -- unpredictable.
3. It duplicated its own `_ollama_reachable()` reachability check instead
   of the project's centralized `tests/ollama_test_support.py::require_ollama()`,
   and performed no warmup step (`warm_model()`), so any cold-model-load
   latency (a real, independently-documented class of latency spike --
   see `docs/orneur/phase-3/OLLAMA_TEST_RELIABILITY.md`) would be charged
   against this specific test's own (implicit, FastAPI-default) timeout
   rather than absorbed in a dedicated warmup step.

## Fix (spec §21-23)

1. **Correct classification**: `@pytest.mark.live_ollama_smoke` added.
   This is NOT skipping the test -- it moves it into the correctly
   accounted execution class the project already has for exactly this
   situation (real, non-mocked, live-Ollama tests), matching every other
   live gateway/Court/Truth-Fabric test in this codebase.
2. **Centralized readiness**: replaced the duplicated `_ollama_reachable()`
   with `tests/ollama_test_support.require_ollama()` (skip, never fail, if
   no Ollama instance is reachable) and added `warm_model("nano")` before
   the timed assertion.
3. **Bounded, low-variance generation**: prompt changed from `"hi"` to
   `"Reply with exactly one word: OK."` -- a real runtime call through the
   real app, NOT a mock, but engineered for a short, predictable reply
   (matching the exact pattern already used by other live tests in this
   codebase, e.g. `tests/test_api_ultra_gateway_cutover.py`'s "Say hi in
   one word").
4. **No blind retry added** -- the fix addresses the actual root causes
   (misclassification + unbounded generation + no warmup) rather than
   wrapping the assertion in a retry loop, per spec §23's explicit
   prohibition.

The functional assertion is UNCHANGED: a real `/api/stream` request
through the real FastAPI app must produce real, recorded Gateway metrics
(`per_deployment` non-empty, `requests >= 1`, `successes >= 1`).

## Verification

- 3× isolated re-runs post-fix, marked `live_ollama_smoke`: 3/3 passed,
  3.8-4.4s each.
- Confirmed correctly excluded from the deterministic suite
  (`pytest -m "not live_ollama_smoke"` → `1 deselected`).
- Full deterministic suite + full live suite results: see
  `PHASE_7_FINAL_CLOSURE.md`.

## A broader finding, deliberately NOT fixed in this phase (scope discipline)

The same unmarked-live-test pattern (a duplicated reachability check, no
`live_ollama_smoke` marker) was found in seven OTHER test files during
this investigation
(`test_api_cognitive_kernel_cutover.py`, `test_api_gateway_integration.py`,
`test_gateway_ollama_runtime.py`, `test_cognitive_kernel.py`,
`test_api_ultra_gateway_cutover.py`, `test_gateway_compat_brain.py`,
`test_healthz_gateway_readiness.py`). Phase 7.2's spec scopes this task to
the ONE named failing test; the broader cleanup has been filed as a
separate follow-on task rather than expanded into this phase's scope.
