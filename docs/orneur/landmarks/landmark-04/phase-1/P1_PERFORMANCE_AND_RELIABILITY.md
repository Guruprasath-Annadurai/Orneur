# P1 — Performance and Reliability Measurements

**Hardware:** AMD Ryzen 7 9700X (16 threads), 15.2 GB RAM, WSL2. **Provider:** local Ollama `llama3.2:1b`. **Workload:** synthetic short prompts, one synthetic account (plus four for the concurrency run). Script: `evidence/p1_perf.py`; results `p1_perf_results.json` (branch) and `p1_perf_baseline_main_0a4c518.json` (pristine `main`, identical script, same machine, same minutes).
**Not a capacity claim.** One workstation and a 1B model say nothing about public-user scale.

| Metric (sample size) | `main` 0a4c518 | Branch | Reading |
|---|---|---|---|
| Server start → `/livez` (1) | 0.55 s | 0.54 s | no change |
| Time to first token, sequential (n=12) p50 / p95 | 0.79 / 1.94 s | 0.43 / 1.72 s | model/GPU-cache variance; **no regression claim and no improvement claim** (single run each) |
| End-to-end latency, sequential (n=12) p50 / p95 | 1.70 / 2.69 s | 1.28 / 2.66 s | same |
| Chunks per answer (median) | — | 95.5; all 12 progressive | |
| 4 concurrent streams (n=4) | 4/4 ok, wall 1.44 s | 4/4 ok, wall 2.73 s | failure rate 0 in both; wall time differs by run (Ollama scheduling); not attributed to the change |
| Concurrent failure/error rate | 0 % | 0 % | |
| Server RSS after concurrent run | 91.9 MB | 90.9 MB | |
| Server fds after concurrent run | 57 | 47 | |
| Server CPU seconds consumed by the whole run | 2.27 | 2.26 | |
| Cancellation: client leaves → provider hang-up (n=8, fixture) p50 / p95 | 0.506 / 0.506 s | 0.506 / 0.507 s | identical; 0 provider streams left open |
| Browser load of `/conversation` (n=10) DOMContentLoaded / load, p50 | — / 22.6 ms | 30.9 / 31.8 ms | **+9 ms**, page grew 225 503 → 247 740 bytes (+9.9 %: account dialog + auth steps) |
| Sign-in form visible, p50 / p95 | — | 53.7 / 86.0 ms | |
| Sessions present after a full server restart | — | 14 of 14 | persistence |

Acceptance thresholds set *before* judging (for this workstation and model): zero failed requests in the sequential and concurrent runs; every answer progressive; provider hang-up < 2 s after Stop; no leaked provider stream or fd growth after the run; page load < 200 ms. All met.

## Reliability scenarios covered (existing suites re-run green, plus new)
Redis frozen/restored, locked/unusable stores, worker kill -9, restart, saturation, drain, provider outage, quota boundary, cancel races (25 + 39 + 15 + 3 passed in the regression run after the CSP/auth changes). Not newly run: disk-pressure, database-unavailable and slow-provider fixtures beyond what those suites contain.
