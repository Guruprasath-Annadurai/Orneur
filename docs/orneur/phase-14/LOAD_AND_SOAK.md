# Phase 14 §46-48, §73-74, §96-97 — Load and Soak Testing

## Scope discipline (spec §73)

Per spec's own explicit instruction: "Do not benchmark the MacBook as
if it represents production GPU capacity. Separate framework overhead
from model compute limitations." Everything below measures **this
codebase's own request-handling framework overhead** on a single
uvicorn process on a MacBook — it says nothing about production
capacity, GPU-backed model inference throughput, or multi-worker
scaling, none of which exist in this environment. `/livez` was
deliberately chosen as the target because it does zero model/dependency
I/O (see `HEALTH_AND_READINESS.md`) — this isolates FastAPI/Starlette/
uvicorn framework overhead specifically, exactly separating it from
model compute time as instructed.

## Load test — real, executed

**Setup**: one real `uvicorn` process running `orca.serve.api:app`
(no reload, `--log-level warning`), a real `httpx.AsyncClient` load
generator, 20 concurrent workers, 30-second bounded duration, target
`GET /livez`.

**Result**:

| Metric | Value |
|---|---|
| Duration | 30.00s |
| Concurrency | 20 |
| Total requests | 10,090 |
| Successful | 10,090 |
| Errors | 0 |
| Throughput | 336.3 req/s |
| p50 | 30.93 ms |
| p95 | 178.34 ms |
| p99 | 351.73 ms |
| Mean | 59.42 ms |

Zero errors across 10,090 requests at 20-way concurrency — the
`/livez` path itself has no failure mode under this load on this
machine. The p50→p99 spread (31ms → 352ms) reflects single-process
event-loop contention under 20-way concurrency on shared laptop
hardware (this session's other work was also running concurrently on
the same machine), not a claim about production latency.

## Soak test — real, executed, bounded

**Setup**: same server process, ~110 seconds of continuous sequential
requests to `/livez` from a separate client process, with RSS memory
and open file descriptor count sampled every 20 seconds via `ps`/`lsof`
(no `psutil` available in this environment — sampled via shell tools
instead, real data either way).

| t (s) | RSS (KB) | Open FDs |
|---|---|---|
| 0 (baseline) | 17,712 | 23 |
| 20 | 29,056 | 24 |
| 40 | 29,184 | 24 |
| 60 | 27,520 | 24 |
| 80 | 27,504 | 24 |
| 100 | 26,224 | 24 |

RSS grew from baseline once real traffic started (expected — buffer/
connection-pool warmup) then held flat and trended slightly **down**
over the remaining ~90 seconds; open FD count was constant at 24
throughout. **No memory growth, no FD leak, no queue buildup observed**
over this bounded window. This is a real but short soak (110 seconds,
one lightweight endpoint, single process) — it does not stand in for a
multi-hour or multi-day production soak, which this environment cannot
run.

## Not executed this phase (disclosed)

- Load/soak against an endpoint that exercises the full model-serving
  path (`/api/chat`), which would require a working authenticated
  session and real Ollama round-trips under load — not attempted this
  pass given time/scope, and because it would conflate framework
  overhead with model inference time, which spec §73 explicitly says to
  keep separate. A future pass should measure these independently:
  framework overhead (this document) and model inference time
  (separately, against the Gateway/Ollama layer directly).
- Multi-worker load test (2+ uvicorn processes behind a real load
  balancer) — no load balancer was stood up locally this phase (see
  `MULTI_WORKER.md`).
- Any cloud-scale load test (spec §46's "primary cloud eventually runs
  real bounded load test") — gated on real cloud infrastructure not
  existing yet.
