# ORNEUR — LANDMARK-01 B-01 final streaming integration: engineering report

Evidence state: **VERIFIED_ENGINEERING**. Not independently qualified; no release authorization is implied.

* Base: PR #135 `15befec7191a1992286d7fa027236002f7d385db` (Kernel streaming), on the PR #134 lineage `8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`. No ref divergence at start.
* Candidate: draft PR #136, branch `claude/b01-real-sse-chatbot-integration`, code-bearing SHA `01444cb084e530cd2aca1f5ed24a5e767c8b143d`; later commits are documentation only, except `d462152` which rewords one comment in `.github/workflows/test.yml` (governance guard). Exact-head CI: run 40837020404 on `d462152`, 10/10 jobs success (see `B01_FINAL_EXACT_HEAD_CI_REPORT.md`; two earlier runs failed on that guard and are recorded there).

## 1. What changed
* `orca/cognitive/streaming.py` — channel rewritten (terminal state is an attribute, no sentinel, no task) and `KernelRun` supervisor added.
* `orca/serve/api.py` — `/api/stream` starts the response and runs the Kernel concurrently for Ollama + no-document sessions; every delta passes `StreamRedactor`; commit via the existing SQLite-authoritative transaction; `_ReleasingStreamingResponse` guarantees release even when the body is never iterated.
* `orca/serve/stream_dlp.py` — tail-leak, lost-last-letter and PEM-bypass fixes.
* `orca/cognitive/{kernel,contracts}.py` — Truth-Fabric draft tokens withheld, `on_served`, redaction before working-memory ingestion.
* `orca/serve/web/conversation.html` — `stream` event handler and truthful Stop wording only.
* Contract: `B01_KERNEL_TO_SSE_CONTRACT.md`. Lifecycle proof: `B01_PRODUCER_CONSUMER_LIFECYCLE_PROOF.md`.

## 2. Defects reproduced and resolved
See `B01_FINAL_BLOCKER_REGISTER.md` §A (B-01a…B-01e) plus: a client hanging up before the first body byte stranded the quota keepalive and the authority heartbeat (found by the gate-adjacent cleanup test; reproduced by mutation in `evidence/mutation_no_response_level_release.txt`; fixed).

## 3. Verification (local, workstation)
| Run | Result |
|---|---|
| Full deterministic gate (clean worktree, `4e68b90`) | 9137 passed, 340 skipped, 6 xfailed, **3 failed**: two tests that pinned the old replay contract / old `_answer_directly` signature (fixed, see matrix §3) and `test_browser_engine.py::test_network_policy_refusals`, which passes in isolation (load flake; the same file flaked once on PR #134). Log summary: `evidence/deterministic_gate_4e68b90.summary.txt`. |
| Targeted deterministic rerun on final code | 302 passed, 1 skipped, 2 xfailed |
| Node frontend suites | 89 pass, 0 fail (`evidence/node_tests.txt`) |
| All journey suites, literal `llama3.2:1b` | 106 passed (52 real-model, 54 fixture-provider) |
| Red baseline: new live tests vs `15befec` | 12 failed / 5 passed (`evidence/red_baseline_15befec_streaming_live.txt`) |
Exact-head CI: `B01_FINAL_EXACT_HEAD_CI_REPORT.md`.

## 4. Status
Kernel streaming PASS · lifecycle PASS · default SSE progressive PASS · real Ollama PASS · real Chromium PASS · Stop PASS · DLP PASS · quota PASS · SQLite PASS · fencing PASS · auth PASS · temp-chat PASS. Open: B-02 (independent qualification), B-04, B-06, L-01…L-06.
