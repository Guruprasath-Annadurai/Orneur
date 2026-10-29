# ORNEUR LANDMARK-01 — CORRECTIVE ASSIGNMENT MATRIX
## Engineering Ownership and Requalification Scope for Subsequent Milestone

**Qualification Authority:** Antigravity  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 29 October 2026  
**Candidate Under Test:** Claude PR #134 (`8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`)  

---

### 1. Corrective Engineering Assignments

No implementation work is authorized until the CTO and Founder complete formal review and approve the remediation scope.

| Item ID | Severity | Assigned Team | Primary Components | Required Engineering Deliverable | Mandatory Acceptance Test |
| :---: | :---: | :---: | :--- | :--- | :--- |
| **B-01** | **P1** | **Cursor (Lead) + Claude (Co-Lead)** | `orca/cognitive/kernel.py`<br>`orca/serve/api.py`<br>`orca/serve/web/conversation.html` | 1. Add `on_chunk: Callable[[str], None]` callback to `CognitiveRequest`.<br>2. In `CognitiveKernel._answer_directly`, call `gateway.stream(...)` when `on_chunk` is present, forwarding deltas to the caller.<br>3. In `api.py::_stream_dispatch`, execute the kernel as an async task, stream deltas through `StreamRedactor`, and emit SSE `chunk` events with `delivery: "upstream"`.<br>4. Wire frontend "Stop" button to cancel generation mid-stream. | `test_journey_browser.py::test_browser_step[B1_new_conversation_streams_real_answer]` must assert `stream.delivery == "upstream"`, $\ge 3$ distinct DOM updates with measurable time spread, and successful Stop cancellation. |
| **B-04** | **P2** | **Claude** | `.github/workflows/test.yml` | Add a GitHub Actions CI job that downloads a lightweight pinned model (or runs against a dedicated runner) and executes `test_journey_api_live.py`. | GitHub Actions workflow completes green on PR branch including live journey step. |
| **B-05** | **P2** | **Cursor** | `orca/memory/turn_ingest.py`<br>`orca/serve/temporary_chat.py` | Implement physical collection purge and vacuum on ChromaDB vector store upon session closure. | Raw filesystem byte scan after `POST /api/session/{sid}/temporary/close` finds zero matching embeddings. |
| **B-06** | **P2** | **Cursor** | `orca/serve/api.py` | Check session document store count before dispatching direct answer; route document sessions directly to RAG planner to eliminate duplicate model calls. | Assert total Ollama requests $\le 1$ per document session turn. |
| **B-07** | **P3** | **Claude** | `orca/serve/web/conversation.html` | Add client-side reconnect inquiry querying turn status after a dropped connection. | Disconnect client during generation; reconnect; verify UI displays confirmed persistence state. |
| **B-08** | **P3** | **Cursor** | `orca/serve/api.py` | Add structured exception mapping for cognitive execute errors. | Direct POST to `/api/cognitive/execute` with malformed plan returns 422/400 instead of generic 500. |

---

### 2. Antigravity Requalification Requirements

Upon delivery of the corrective candidate addressing P1 blocker B-01:
1. Candidate SHA must be frozen and pushed to draft PR.
2. Mandatory CI must pass 100% green.
3. Antigravity will execute the Playwright browser journey to verify true token streaming (`delivery: "upstream"`), mid-generation DOM mutation states, and functional Stop button cancellation.
4. Red-team DLP and SQLite fencing suites must be re-verified to ensure streaming deltas do not bypass redaction buffers.
