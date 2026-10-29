# Exact-Head CI Report

**Starting SHA:** `15befec7191a1992286d7fa027236002f7d385db`  
**Integration tip (pre-CI-fix):** `19322133181d71ed39d229187564ebb0e9100501`  
**CI failure:** run `40839269051` — Deterministic Unit Tests (11 failures)  
**Corrective tip:** `e6547634a9d531504df070447dd9b90095f6f571` (awaiting exact-head CI)  

## Failure root causes (1932213)

1. Kernel deferral (`output is None`) on the concurrent B-01 path emitted
   `invalid_request` instead of falling through to AgentLoop streaming —
   broke CODEY / serve_streaming agent-path tests.
2. `_run_cognitive_kernel` test doubles rejected `on_raw_delta=` (TypeError).
3. `FakeOllama.reply` setter always overwrote `chunks`, destroying
   explicit multi-chunk / `truncate_after` scenarios.
4. Legacy S2 / product-flow assertions still expected `delivery: replayed`
   for ollama Kernel-direct turns (B-01 changed that to upstream).

## Corrective verification (local)

Related suites after the fix: 108 passed, 1 skipped
(`product_flows`, `s2_customer_correctness`, `serve_streaming`,
`b01_stream_kernel_upstream`, `raw_delta_channel_lifecycle`,
`canonical_turn_authority`, `canonical_route_dlp`, truncated-stream
reliability case).

Mandatory CI run IDs and Deterministic counts recorded after GitHub completes
on the corrective tip.
