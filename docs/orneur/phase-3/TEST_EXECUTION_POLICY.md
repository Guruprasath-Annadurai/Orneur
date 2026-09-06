# Live-Runtime Test Execution Policy

## Classification

Every test in this repository falls into exactly one of these categories. Categories are enforced by pytest markers registered in `pyproject.toml` (`[tool.pytest.ini_options].markers`); a test with no marker is `PURE_UNIT` or `DETERMINISTIC_INTEGRATION` by default (no marker needed for the default, always-run case).

| Category | Marker | Runs by default | Description |
|---|---|---|---|
| **PURE_UNIT** | *(none)* | Yes | No I/O, no real infrastructure — e.g. every `orca/cognitive/*` classifier test, budget arithmetic, state-machine transitions. |
| **DETERMINISTIC_INTEGRATION** | *(none)* | Yes | Real code paths, fake/mocked runtime — e.g. `orca/gateway`'s unit tests against `_FakeRuntime`. |
| **LIVE_OLLAMA_SMOKE** | `@pytest.mark.live_ollama_smoke` | Yes (auto-skips if Ollama unreachable) | Real, non-mocked calls to a local Ollama instance — the actual serving path, streaming, cancellation, Gateway, Cognitive Kernel end-to-end. Bounded latency/output by design (see `OLLAMA_TEST_RELIABILITY.md`'s fix). Part of the normal release suite. |
| **LIVE_OLLAMA_STRESS** | `@pytest.mark.live_ollama_stress` | **No** — run explicitly via `pytest -m live_ollama_stress` | Sustained concurrency, overload, or deliberately adversarial load against real Ollama. None currently exist in this repository; the marker is registered and reserved so a future stress suite has a home that is never silently swept into the release gate. |
| **PERFORMANCE** | `@pytest.mark.performance` | *(none currently marked; see below)* | Benchmark/timing measurement — reports numbers, does not gate pass/fail on absolute latency. `scripts/measure_inference_baseline.py` and `scripts/measure_integrated_baseline.py` (Phase 2/2.1) are standalone scripts, not pytest tests, and are unaffected by this marker; it exists for any future in-suite benchmark test. |

## Why this exists

Root-cause analysis for this phase (`OLLAMA_TEST_RELIABILITY.md`) found that the normal release suite already contains 9 files making real, non-mocked calls to a local Ollama instance — a legitimate and valuable practice (this project's standing discipline is "do not rely only on mocked model behavior for integration claims"). The actual defect was not that these tests exist, but that nothing distinguished a lightweight smoke check from a test that happened to request an unbounded, multi-generation response — so the release suite could, by accident, behave like an uncontrolled stress benchmark for a handful of tests. This phase does not remove or weaken any real test; it makes the distinction explicit and fixes the one case where a test's own workload was heavier than its assertions required.

## Running each suite

```bash
# Fast release suite: everything except explicitly-marked stress tests
# (this is the default -- `pytest` with no -m filter already excludes
# nothing, since LIVE_OLLAMA_STRESS is the only category opted OUT of
# the default run by convention, not by pytest config)
pytest -m "not live_ollama_stress"

# Live Ollama suite only (smoke), useful for a focused re-run against
# real infrastructure without the full unit suite's runtime:
pytest -m live_ollama_smoke

# Stress suite (currently empty; reserved):
pytest -m live_ollama_stress

# Full suite, exactly as CI runs it today:
pytest
```

No test is ever marked `xfail` or `skip` to force a green run — every real capability this suite verifies remains verified. `live_ollama_smoke` tests auto-*skip* (not xfail, not silently pass) when no local Ollama instance is reachable, exactly as they did before this phase; that behavior is unchanged.

## Centralized live-Ollama test support

`tests/ollama_test_support.py` (new this phase) is the one place live-Ollama tests should get:

- `ollama_reachable()` / `require_ollama()` — the reachability check, deduplicated from 9 near-identical copies.
- `warm_model(tier)` — deliberate readiness: issues one small, `BACKGROUND`-priority generation before a test's own timed assertions run, so a cold model load is absorbed here instead of randomly charged against whichever test runs first. Never raises; a warmup failure just means the test proceeds cold and its own real call surfaces any genuine problem honestly.
- `retry_transient(fn, attempts=2, ...)` — a bounded, classified retry for the two `InferenceErrorCode` classes root-cause analysis actually observed as transient (`GenerationTimeoutError`, `QueueTimeoutError`). Never a blind retry: any other exception propagates immediately and unconditionally, every retry is logged, and the test still fails once the bounded attempt count is exhausted. Only usable where a test has a clean, un-swallowed exception boundary to the Gateway (see `OLLAMA_TEST_RELIABILITY.md` §6 for why this is not applied at the HTTP-layer tests).

Existing test files were not mechanically retrofitted to use every one of these helpers — only the two files root-cause analysis identified as actually flaky (`tests/test_api_production_cutover.py`, `tests/test_gateway_compat_brain.py`) were updated. The other 7 files still define their own local `_ollama_reachable()` copy; migrating them to the shared helper is a low-risk, disclosed follow-up (see `PHASE_3_FINAL_CLOSURE.md`'s known limitations), not required for this phase's reliability goal since they were not observed to be flaky.

## Timeout policy

Production `ModelGateway.TimeoutPolicy` defaults (`queue_timeout_s=30`, `first_token_timeout_s=30`, `total_request_timeout_s=180`) are **unchanged** by this phase — root-cause evidence did not support raising them (the actual problem was a test requesting more generation than its assertions needed, not the timeout budget being wrong for a legitimate single-turn CPU-only generation; see `OLLAMA_TEST_RELIABILITY.md` §3). No test-only timeout override was introduced either, since the bounded-workload fix addressed the root cause directly without needing one. If a future test genuinely needs a different budget than production defaults, it should construct its own `ModelGateway(timeout_policy=TimeoutPolicy(...))` explicitly (as `tests/test_gateway_compat_brain.py` already does for its `OllamaRuntime(timeout_s=90.0)`), documented at the call site — never a blanket change to the shared default.
