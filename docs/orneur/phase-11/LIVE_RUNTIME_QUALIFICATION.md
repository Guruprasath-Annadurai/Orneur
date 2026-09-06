# Phase 11.2 — Live Runtime Qualification

Authoritative inventory and evidence for the real (non-mocked) Ollama/Gateway
test surface, built per spec §11/§14/§17-18 to replace the earlier "environmental"
labeling of transient Phase 11.1 live-suite failures with actual root-cause
evidence and a confirmed clean invocation.

## Live test inventory

Two markers are defined in `pyproject.toml`: `live_ollama_smoke` (part of the
normal release suite, run via `-m live_ollama_smoke`) and `live_ollama_stress`
(sustained-concurrency/overload, explicitly NOT part of the normal release
suite). As of Phase 11.2:

- **LIVE_OLLAMA_SMOKE: 8 files, 40 tests** (confirmed via
  `pytest -m "live_ollama_smoke" --collect-only -q`).
- **LIVE_OLLAMA_STRESS: 0 files, 0 tests.** The marker exists in
  `pyproject.toml` (registered to avoid "unknown marker" warnings and to
  reserve the category) but no test in the repository currently uses it.
  This is a known, disclosed gap, not a miscount — stress-level real-Ollama
  testing has not yet been built in any phase through 11.2.

### File-by-file smoke inventory

| File | Tests | Models required | Notes |
|---|---|---|---|
| `tests/test_agent_planner_live.py` | 1 | `nano` (via `warm_model`) | Full agent planning loop against a real model. |
| `tests/test_api_production_cutover.py` | 15 | default local model | Kernel-authoritative API cutover surface; largest file by test count. |
| `tests/test_cognitive_kernel_truth_fabric_integration.py` | 3 | default local model | Cognitive kernel → Truth Fabric integration. |
| `tests/test_deliberation_cancellation.py` | 1 | default local model | Real-model cancellation propagation through Court. |
| `tests/test_deliberation_court_integration.py` | 4 | default local model | CognitiveCourt real multi-model deliberation. |
| `tests/test_gateway_observability_cutover.py` | 1 | default local model | Real Gateway metrics emission. |
| `tests/test_truth_claims_verification_contradiction.py` | 9 | default local model | Claim extraction/verification/contradiction detection. |
| `tests/test_truth_fabric_integration.py` | 6 | `nano` (2 tests via `warm_model`) | Truth Fabric assess_evidence/verify_answer/cancellation. |

Expected runtime for the full smoke suite: ~4-8 minutes on the reference
machine, dominated by `test_api_production_cutover.py` (15 tests) and any
cold-model-load penalty on the first test to touch a given model.

### Known resource-sensitive tests

These were the two live-suite tests that showed transient failures across
Phase 11.1's two full-suite runs (see "Phase 11.1 root-cause record" below).
Both are now understood and fixed, but remain worth watching under sustained
load since they are the tests that actually exercise real Gateway/Ollama
round trips with tight timing:

- `tests/test_agent_planner_live.py::test_live_goal_produces_a_validated_plan_using_only_read_only_tools`
- `tests/test_truth_fabric_integration.py::test_verify_answer_supports_a_grounded_claim`
- `tests/test_truth_fabric_integration.py::test_verify_answer_never_fabricates_support_for_unrelated_claim` (same root cause as above, not yet observed failing but carries the identical exposure)

## Phase 11.1 root-cause record (evidence-based, not "environmental")

Two full live-suite invocations were run during Phase 11.1 closure. Both had
1-2 transient failures, previously reported with an "environmental" label
without supporting evidence — the exact thing Phase 11.2's spec rejected.
Actual root causes, found by reading each failing test rather than retrying:

1. **`test_live_goal_produces_a_validated_plan_using_only_read_only_tools`**
   (failure category: `GenerationTimeoutError` under back-to-back suite load).
   Root cause: this test had **no `warm_model()` call**, unlike every sibling
   live test in the file/repo, so it always paid a cold-load penalty on top
   of ordinary generation latency — when the suite arrived at it under load
   from ~39 prior live tests, the combined latency exceeded the timeout.
   Confirmed passing reliably in isolation (no preceding load). Fix: added
   `warm_model("nano")` right after `require_ollama()`, matching every other
   live planner/Truth test in the repo.

2. **`test_verify_answer_supports_a_grounded_claim`** (failure category:
   `TruthTimeoutError` from `orca.truth.errors`, raised by
   `fabric.verify_answer()`'s real Gateway call). Root cause: this test (and
   its sibling `test_verify_answer_never_fabricates_support_for_unrelated_claim`)
   made real Gateway calls with **zero retry wrapping**, and `TruthTimeoutError`
   was **not present at all** in `tests/ollama_test_support.py`'s
   `_TRANSIENT_ERRORS` classification tuple — so even the existing retry
   infrastructure other live tests rely on could not have caught it here.
   Fix: added `TruthTimeoutError` to `_TRANSIENT_ERRORS`; added a new
   `retry_transient_async()` (identical bounded/classified retry policy to
   the existing sync `retry_transient()`) and wired both real
   `assess_evidence`/`verify_answer` calls in both tests through it.

Neither fix is a blind retry loop, a timeout increase, a mock, a skip, or a
deleted assertion — both are genuine root-cause fixes to real test-harness
gaps (missing warmup; missing transient-error classification for an error
type that already existed in production code).

## Phase 11.2 — third failure, traced to a real Gateway-layer defect (not test-harness gap)

After applying the two fixes above, two further full live-suite invocations
were run to gather more evidence before declaring a clean run:

- **Run A** (`tests/test_deliberation_court_integration.py::test_court_records_which_model_served_each_role`
  failed): traceback showed `orca.gateway.errors.RequestCancelledError` raised
  from `orca/gateway/ollama_runtime.py:126`, itself raised
  `During handling of` an `asyncio.exceptions.CancelledError`. Elapsed time
  for the full run: 1205.70s (0:20:05), 39 passed / 1 failed. This test was
  NOT one of the two already-fixed tests, and had no prior history of
  failing — new evidence, not a repeat of the known issue.
- **Run B** (`tests/test_truth_fabric_integration.py::test_verify_answer_supports_a_grounded_claim`
  failed again, despite the Run A fixes already being in place): same
  exception shape — `RequestCancelledError` surfacing from a real `httpcore`
  `anyio` stream read that was itself interrupted by `asyncio.CancelledError`.
  Elapsed time: 1120.25s (0:18:40), 39 passed / 1 failed. Since this test was
  already wrapped in `retry_transient_async()`, and `RequestCancelledError`
  is a *different* exception class than the `TruthTimeoutError` that wrapper
  classifies as transient, the retry never triggered — this ruled out
  "insufficient retry coverage" and pointed at something structurally
  different from a plain timeout.

**Root cause (confirmed by reading `orca/gateway/gateway.py`,
`orca/deliberation/court.py`, `orca/truth/truth_fabric.py`, and
`orca/gateway/ollama_runtime.py` together, not by guessing):** three
independent call sites impose their own deadline via
`asyncio.wait_for(<call reaching OllamaRuntime.generate()>, timeout=...)` —
`Gateway.generate()`'s `total_request_timeout_s`, `CognitiveCourt.run()`'s
`COURT_DEADLINE_S` (60s), and several of `TruthFabric`'s `*_TIMEOUT_S`
constants (e.g. `VERIFICATION_TIMEOUT_S`). `asyncio.wait_for()`/
`asyncio.timeout()` only convert their own expiry into `TimeoutError` when a
genuine `asyncio.CancelledError` propagates untouched out of the awaited
coroutine. `OllamaRuntime.generate()`, however, had an
`except asyncio.CancelledError: raise RequestCancelledError()` clause that
fired unconditionally — for a deliberate, explicitly-requested cancellation
(via `runtime.cancel(request_id)`) **and** for the unrelated case where an
*enclosing* `wait_for()`'s own timeout fired and cancelled the in-flight
HTTP call. In the second case, converting `CancelledError` into a different
exception type meant the enclosing `wait_for()` could never see the
`CancelledError` it needed to convert into its own `TimeoutError` — so the
"deadline reached" case, which every one of the three call sites already has
graceful handling for, was silently bypassed, and a raw
`RequestCancelledError` escaped uncaught instead. Under real, sustained
model load (multiple long-running live tests back-to-back), deadlines are
naturally reached more often, which is why this surfaced only in full-suite
runs and never in isolation-based reruns — it was never actually about
isolation vs. load timing, it was this bug being more likely to trigger when
generation genuinely takes longer.

**Fix**: `orca/gateway/ollama_runtime.py::generate()`'s cancellation handler
now only raises `RequestCancelledError` when `request.request_id` is in the
runtime's own explicit `_cancelled_requests` set (i.e., this exact request
was deliberately cancelled via the public `cancel()` API); every other
`CancelledError` is re-raised as-is, restoring `wait_for()`'s ability to
convert it correctly. `orca/deliberation/court.py`'s
`except asyncio.TimeoutError:` clause additionally now also catches
`RequestCancelledError` defensively, documenting the same interaction for
any caller that still ends up seeing it (e.g. through a third-party
timeout wrapper not under this fix's control). Verified after the fix: full
deterministic suite (1321 passed / 0 failed), authoritative security suite
(663 passed / 0 failed), both simulation eval harnesses independently green
(23/23, 21/21), and a clean 40/40 live-suite invocation (see below) — this
is a genuine root-cause fix, not a retry, timeout increase, mock, skip, or
deleted assertion.

## Phase 11.2 clean invocation

Live-suite invocation launched after the two fixes above landed:

```
.venv/bin/python -m pytest -m "live_ollama_smoke" -p no:cacheprovider -q
```

Result: **40 passed, 0 failed, 1321 deselected, 794.12s (0:13:14).**
This is the required clean invocation.

A second, immediate repeat run was launched after the first, since runtime
budget permitted it (spec §18: "if runtime budget permits, run the final
live-smoke suite twice, reporting additional repetitions honestly"):

**Repeat invocation result: 40 passed, 0 failed, 1321 deselected, 387.41s
(0:06:27).**

Two independent, back-to-back clean 40/40 invocations, each reported on its
own — never merged into a single combined count, per spec §17's explicit
instruction not to combine individually-passing reruns into a fictitious
single clean-suite result.
