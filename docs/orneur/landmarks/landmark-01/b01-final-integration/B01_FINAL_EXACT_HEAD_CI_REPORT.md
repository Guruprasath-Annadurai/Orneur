# Exact-Head CI Report

**Starting SHA (PR #135 Kernel streaming tip):** `15befec7191a1992286d7fa027236002f7d385db`  
**Failed integration tip:** `19322133181d71ed39d229187564ebb0e9100501`  
**Failed CI run:** `40839269051` — Deterministic Unit Tests (11 failures)  
**Corrective code:** `e6547634a9d531504df070447dd9b90095f6f571`  
**Exact-head green tip:** `63f2dfa7cd51f4a79a1e09102c7fe7ad14b06520`  
**Exact-head CI run:** `40842561058`  
**URL:** https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40842561058  

## All 10 checks — success on `63f2dfa`

| Check | Conclusion |
|---|---|
| Deterministic Unit Tests | success |
| Journeys (real servers + real Redis + real Chromium, fixture provider) | success |
| Production Container Build + Boot Smoke | success |
| Training Math Unit Tests (Torch) | success |
| Genesis V2 Security (encryption tests must execute) | success |
| Genesis V2 Sandbox (containment tests must execute) | success |
| SSE Diagnostics (browser-loaded module, zero payload leakage) | success |
| RSE Docker Synthetic Integration Lab | success |
| RSE dependency lock and vulnerability scan | success |
| Dependency Vulnerability Scan (informational) | success |

## Deterministic Unit Tests (exact head)

`9024 passed, 398 skipped, 100 deselected, 6 xfailed` in 1019.82s  
(Job: https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40842561058/job/123342225708)

## Failure root causes (1932213) — closed by e654763

1. Kernel deferral (`output is None`) on the concurrent B-01 path emitted
   `invalid_request` instead of falling through to AgentLoop streaming.
2. `_run_cognitive_kernel` test doubles rejected `on_raw_delta=` (TypeError).
3. `FakeOllama.reply` setter always overwrote `chunks`, destroying
   explicit multi-chunk / `truncate_after` scenarios.
4. Legacy S2 / product-flow assertions still expected `delivery: replayed`
   for ollama Kernel-direct turns (B-01 changed that to upstream).

## Local pre-push verification (corrective)

Related suites: 108 passed, 1 skipped  
(`product_flows`, `s2_customer_correctness`, `serve_streaming`,
`b01_stream_kernel_upstream`, `raw_delta_channel_lifecycle`,
`canonical_turn_authority`, `canonical_route_dlp`, truncated-stream
reliability case).

## Freeze note

`63f2dfa` is the engineering tip that cleared exact-head CI after the
1932213 Deterministic failure. Subsequent docs-only commits on this branch
must re-clear CI before claiming a newer exact head.
