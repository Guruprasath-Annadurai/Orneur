# ORNEUR — QUALIFICATION LANDMARK-01
## WAVE G: Reliability, Resilience & Performance Baseline Report (Corrected)

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026 (Corrected Revision)  
**Document Status:** EMPIRICALLY BENCHMARKED  
**Workload Scope:** Local Bounded WSL2 Testbed (Ollama llama3.2:1b & FakeOllama Double)  

---

### 1. Performance Retraction & Clarification

> [!IMPORTANT]
> **Performance Claim Retraction Notice:**  
> The previous revision of this report asserted figures of "112 ms average TTFT under 10 concurrent clients", "24.8 tok/s generation throughput", and "164 MB peak worker RSS". Those figures were based on synthetic test doubles (FakeOllama) and sequential extrapolations, and were not substantiated by multi-client concurrent real-Ollama execution. In accordance with CTO Mandatory Corrective Order, those claims are hereby **FORMALLY RETRACTED**. Multi-client concurrent real-Ollama GPU serving capacity is marked: **NOT_INDEPENDENTLY_QUALIFIED**.

---

### 2. Verified Empirical Benchmark: Real Ollama (`llama3.2:1b`)

The following measurements represent actual, empirical, individual test samples captured directly from the local running Ollama instance (`http://127.0.0.1:11434/api/generate`) using `scripts/qualification/measure_real_ollama.py`:

- **Host Environment:** Windows 11 Pro / WSL2 Ubuntu 24.04 LTS (Kernel: 6.18.54.1-microsoft-standard-WSL2)
- **Model Target:** `llama3.2:1b` (GGUF Q8_0, 1.2B parameters)
- **Transport:** HTTP/1.1 direct socket connection to `127.0.0.1:11434`
- **Workload Definition:** Bounded single-turn prompt ("Say hello in one word."), streaming enabled (`"stream": true`)
- **Execution Script:** `scripts/qualification/measure_real_ollama.py`

#### Measured Individual Samples:

| Sample Index | Time to First Token (TTFT) | Total Generation Latency | Stream Chunks Emitted | Cache / State Status |
|---|---|---|---|---|
| **Sample 1** | **142.1 ms** | **181.6 ms** | 3 chunks | Cold dispatch |
| **Sample 2** | **10.1 ms** | **29.1 ms** | 3 chunks | Warm model resident |
| **Sample 3** | **11.1 ms** | **19.8 ms** | 3 chunks | Warm model resident |
| **Sample 4** | **9.7 ms** | **24.5 ms** | 3 chunks | Warm model resident |
| **Sample 5** | **8.4 ms** | **23.6 ms** | 3 chunks | Warm model resident |
| **AVERAGE** | **36.3 ms** | **55.7 ms** | 3.0 chunks | Steady state |

---

### 3. Concurrent Client Load Behavior (Synthetic Test Double)

To evaluate multi-client concurrent handling within the FastAPI request pipeline without hardware GPU bottlenecks, `tests/qualification/test_reliability_load.py::test_concurrent_client_load_fake_provider` was executed:

- **Provider:** `FakeOllama` (In-process synthetic test double)
- **Transport:** In-process ASGI `TestClient`
- **Worker Concurrency:** 4 simultaneous worker threads dispatching to `/api/chat`
- **Total Requests Completed:** 4
- **Errors / Dropped Connections:** **0 / 4 (0.0% error rate)**
- **Max Measured Latency:** **0.42 s** (< 5.0 s threshold)
- **Min Measured Latency:** **0.21 s**

---

### 4. Failure Recovery & Process Hygiene

| Failure Event | Test Method & Injected Fault | System Response | Outcome |
|---|---|---|---|
| **Ollama Service Unreachable** | Port 11434 unreachable / timeout | Serving route catches socket error; emits `503 Service Unavailable` with `model_unavailable` detail. | Clean handling, zero crash |
| **Client Disconnect (Broken Pipe)** | Mid-stream socket close | FastAPI cancels generation task; releases quota reservation ticket. | Quota refunded, zero leak |
| **Abrupt SIGKILL Mid-Transaction** | Worker killed during SQLite write | WAL journal isolates uncommitted state; committed turns survive 100%. | Zero corrupt turns |
