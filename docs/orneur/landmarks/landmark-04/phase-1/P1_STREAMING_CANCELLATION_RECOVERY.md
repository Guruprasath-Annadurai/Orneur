# P1-C — Streaming, Stop, Cancellation and Recovery

The existing Kernel/SSE architecture was preserved. This phase added independent confirmations and fixed nothing in the stream path.

| Scenario | Evidence | Result |
|---|---|---|
| Real upstream progressive tokens | real Ollama, 12/12 answers had many chunks; fixture 16-piece stream observed piece by piece in the DOM (B01 J2) | VERIFIED |
| Delivery labelled truthfully | final event `delivery: upstream`; buffered/replayed paths keep their own labels | VERIFIED (existing tests, re-run) |
| Stop before first token / mid-stream / after finish / repeated Stop / concurrent | `test_b01_cancel_race_live.py` (re-run green in the 39-test group) | VERIFIED |
| Stop on a **touch device** | browser N1: tap Stop → UI leaves stop-mode, provider stream hung up, partial answer not stored as complete | VERIFIED |
| Client disconnect | `test_p1_quota_live.py::Q4`: provider hung up, no stored completion, 0 open provider streams | VERIFIED |
| Cancellation latency | provider hang-up observed **0.506 s** (p50 and p95, n=8, fixture provider) after the client left; leak check: 0 open provider streams, server fds 25 | measured |
| Provider outage then recovery without a phantom turn | B01 J10 (re-run green) | VERIFIED |
| Refresh / reopen shows the committed transcript only | B01 J6/J7, manage M5 | VERIFIED |
| Server restart then reopen exact conversation | B01 R1/R2; real-model `test_C2…`; perf run (14 sessions present after restart) | VERIFIED |
| Worker kill / Redis interruption | L02 recovery + operations suites (25 passed in the re-run, Redis restarted by command) | VERIFIED (existing) |
| Revoked token ends the page and never reaches the model | B01 J12 | VERIFIED |
| Refused request costs nothing | Q2: refused burst and quota-refused request produced zero provider calls | VERIFIED |
| Failed provider turn is not charged | Q1 | VERIFIED |

Preserved security corrections (stream redactor, Kernel memory ingestion) were not modified; their suites ran green inside the Deterministic job (see the CI report).
Limits: Stop during the *persistence instant* and browser *navigation mid-stream* are covered only as far as the existing cancel-race suite goes; no new race tooling was written. Idempotency-key retry behaviour relies on the existing suites.
