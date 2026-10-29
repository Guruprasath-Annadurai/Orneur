# B-01 — Handoff to Antigravity for independent requalification

**From:** Claude Code (engineering). **To:** Antigravity (independent qualification authority). **Status of this candidate:** `VERIFIED_ENGINEERING` — *not* independently qualified; nothing here issues, implies or pre-empts your verdict.

* Candidate: PR https://github.com/Guruprasath-Annadurai/Orneur/pull/136 (draft), branch `claude/b01-real-sse-chatbot-integration`, **code-bearing SHA `01444cb084e530cd2aca1f5ed24a5e767c8b143d`**, documentation-only head the head recorded in the CI report (see `B01_FINAL_EXACT_HEAD_CI_REPORT.md`).
* Base lineage (not merged, not substituted): PR #135 `15befec7191a1992286d7fa027236002f7d385db` ← PR #134 `8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`. `main` is untouched. PR #132 was not used.
* Governance reminders honoured: no merge, no deployment, no paid infrastructure, no native-model claim (the model is third-party `llama3.2:1b` weights served by Ollama), no UI redesign, no security assertion weakened.

## 1. What to try to break (and the reproducing command for each)

Use a worktree at the candidate SHA. `PY=/home/pc/projects/Orneur/.venv/bin/python`; the journey suites are opt-in and **fail (never skip)** when a capability is missing.

| Claim | Reproduce | Look for |
|---|---|---|
| Default path streams real gateway deltas | `pytest tests/journey/test_b01_streaming_live.py -k S1 -p no:cacheprovider` | `fixture_progressive_delivery.json`: provider write offsets vs client receive offsets differ by ms |
| Real Ollama streams progressively | `ORNEUR_JOURNEY_MODEL=llama3.2:1b pytest tests/journey/test_b01_real_ollama_live.py -p no:cacheprovider` | ≥ 20 chunk events over seconds; one `stream=true` answering dispatch on the recording tap |
| Stop really stops the model | same file, `test_S4_S5_S6_real_stop_…` ; and `tests/journey/test_b01_streaming_live.py -k S4` | tap `client_aborts` +1 within ~50 ms; relayed lines stop; `streams_open == 0` |
| Producer/consumer lifecycle | `pytest tests/test_b01_raw_delta_lifecycle.py tests/test_b01_stream_cleanup.py` and `PYTHONPATH=. $PY docs/orneur/landmarks/landmark-01/b01-final-integration/evidence/lifecycle_defect_repro.py` | the original hangs and spawns an untracked task; the candidate does neither |
| Stateful DLP across chunk boundaries | `pytest tests/test_b01_stream_dlp_equivalence.py` ; `PYTHONPATH=. $PY …/evidence/redactor_differential.py` ; `pytest tests/journey/test_b01_streaming_live.py -k S3` | streamed output ≡ one-shot redaction; no secret byte anywhere under `ORNEUR_HOME` |
| Atomic quota / refund / replay | `pytest tests/test_canonical_quota_admission.py tests/test_b01_refusal_protocol.py` ; live `-k "S7 or S8 or duplicate"` | 49/50 race admits one; refund before output; spent after |
| SQLite fencing, multi-worker | `pytest tests/journey/test_journey_concurrency_live.py` (real Redis DB 12 + two `orca serve` processes) | `test_S12_worker_stalled_MID_STREAM_…`, `test_S5_Stop_on_one_worker_…` |
| Cancel racing the commit | `pytest tests/journey/test_b01_cancel_race_live.py` | `cancel_race.json` (commit-won vs cancel-won counts; never partial) |
| Authentication | `pytest tests/test_auth_invalid_bearer_refused.py tests/test_b01_refusal_protocol.py` ; browser step J12 | 401 JSON; provider `requests` counter unchanged |
| Cross-user isolation / temporary chat | `pytest tests/test_session_ownership_isolation.py tests/test_temporary_chat_privacy.py tests/test_temporary_chat_multiprocess.py`; browser J9, J11 | |
| Real browser, approved page | `pytest tests/journey/test_b01_browser_streaming.py` (fixture 16 steps incl. outage+restart; real-Ollama 10 steps + Stop hang-up) | progressive DOM states, Stop wording, no phantom turn |
| Frontend | `node --test tests/frontend/*.mjs` | 89 tests |

Suggested adversarial extensions we did **not** run: a provider that emits a secret split across a *tool-call* boundary; a multi-megabyte single delta (the redactor fails closed at 8 192 chars/delta and 1 MiB total — verify the UX); very slow readers behind a real proxy that buffers SSE (`X-Accel-Buffering: no` is set, but an intermediary can ignore it); clock skew on the SQLite authority TTL across hosts.

## 2. What is explicitly *not* proven here

* Independent qualification of any kind.
* Streaming for document sessions and Truth-Fabric-routed turns (see `B01_FINAL_BLOCKER_REGISTER.md` L-01, B-06).
* Behaviour behind a production reverse proxy / CDN; multi-host clock behaviour; load beyond the single-workstation journeys.
* Real-Ollama journeys in CI (workstation only, B-04). The fixture-provider variants of every new suite *do* run in CI.

## 3. Changed files that deserve your review first

`orca/cognitive/streaming.py` (channel + `KernelRun`), `orca/serve/api.py` (`_stream_dispatch`, `_event_stream`), `orca/serve/stream_dlp.py` (redactor fixes), `orca/cognitive/kernel.py` + `contracts.py` (hook suppression for Truth Fabric, `on_served`, redaction before memory ingestion), `orca/serve/web/conversation.html` (the `stream` event and the Stop wording only; no visual change). Existing tests whose assertions changed (each with its reason) are listed in `B01_DLP_QUOTA_SQLITE_REGRESSION_MATRIX.md` §3.

## 4. Reconciliation of the existing Antigravity evidence record (we do not edit your documents; these are observations for you to confirm or correct)

The record in PR #133 (`independent-qualification/`, manifest 2.0.0, plus the earlier `qualification-01/` set) mixes evidence classes in a way that should be stated explicitly in your next revision:

1. **Fixture versus real counts.** `REAL_OLLAMA_AND_BROWSER_JOURNEYS.md` reports *"57 of 57 live journeys"* against *"real Ollama running the literal `llama3.2:1b`"*. By the test files' own docstrings the 57 split as: `test_journey_api_live.py` 19 (real Ollama) + `test_journey_browser.py` 19 (real Ollama) = **38 real-model**; `test_journey_browser_fixture.py` 10 (**FakeOllama fixture** provider) + `test_journey_concurrency_live.py` 9 (**FakeOllama fixture** provider; real Redis and real processes) = **19 fixture-provider**. The manifest classifies the concurrency file as `VERIFIED_REAL` and the browser-fixture file as `VERIFIED_DETERMINISTIC`, which disagrees with the report headline. Also, the suites default to the local alias `orneur-journey`; the literal tag requires `ORNEUR_JOURNEY_MODEL=llama3.2:1b`.
2. **Historical orchestrator failure.** By the lab's own description (`QUALIFICATION_01_FINAL_REPORT.md`), the first lab commit (`0183065`) shipped suites that referenced a non-existent `conversations.init_db` and a wrong temporary-chat endpoint, and an orchestrator without enforced candidate-tree isolation; `a74d163` repaired them (explicit candidate worktree, `PYTHONPATH` isolation, dual candidate/harness SHA recording, strict exit codes). The earlier manifest (`docs/orneur/landmarks/qualification-01/QUALIFICATION_01_EVIDENCE_MANIFEST.json`) still in the branch records `exit_code: 0 / passed: true` for suites with **6 skipped positive controls** (inference 2, storage 3, privacy 1). The final manifest reports `skipped: 0`. Both manifests coexist in the branch; the earlier one should be marked superseded so a reader cannot take a green exit code with skipped positive controls as evidence.
3. **Test totals do not add up.** In the final manifest (`test_execution_summary`) the twelve per-suite `passed` values sum to **183** (12+12+8+12+7+11+5+59+19+19+10+9), while `total_qualification_tests_executed` and `total_qualification_tests_passed` both say **173**. Please correct the total (or the rows) and publish the per-class split (real model / fixture provider / deterministic) next to it.

## 5. How to report back

Please record your verdict against the exact SHA, with your own class split, in your own PR; we will not copy, edit or pre-fill it. If any item above fails for you, the reproducing command in §1 is the contract — please attach its output.
