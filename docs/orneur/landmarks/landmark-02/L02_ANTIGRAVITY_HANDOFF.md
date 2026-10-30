# LANDMARK-02 — handoff to Antigravity for independent qualification

**From:** Claude Code (engineering). **To:** Antigravity. Status of this candidate: `VERIFIED_ENGINEERING` — **not** independently qualified. Nothing here issues, implies or pre-empts your verdict; please do not copy this document's results into yours.

* Candidate: draft PR #139, branch `claude/landmark-02-customer-trust-reliability`, stacked on PR #136 head `9cb864c99ad323d11626063498a7d1cef0d7d4b5` (PR #136 was not modified, rebased or force-pushed). Code-bearing SHA and CI runs: `L02_EXACT_HEAD_CI.md`. Commits after the code-bearing SHA are documentation/evidence only.
* Not merged, not deployed, no paid infrastructure, no native-model claim, no training, no protected-record change.

## 1. Reproduce (worktree at the candidate SHA; `PY=<venv>/bin/python`; Node 22 for the frontend tests)
| Claim | Command | Look for |
|---|---|---|
| L02 deterministic suites | `$PY -m pytest tests/test_l02_*.py -p no:cacheprovider -q` | 246 passed, 0 skipped |
| Baseline red | check out `9cb864c`, copy the new tests, run them | `evidence/*baseline*` files show the failures |
| Deletion live | `$PY -m pytest tests/journey/test_l02_deletion_live.py -p no:cacheprovider` (Docker for D1; Ollama `nomic-embed-text` for D6) | 6 passed; `evidence/l02_deletion_live_*.json` |
| Recovery live | `… tests/journey/test_l02_recovery_live.py` | R1–R8, 8 passed |
| Operations live | `… tests/journey/test_l02_operations_live.py` | O1–O8, 8 passed; numbers in `evidence/l02_ops_live_*.json` |
| Account live | `… tests/journey/test_l02_account_live.py` | 2 passed |
| Hostile uploads, real parsers | `pip install --target /tmp/l02-doclibs pypdf python-docx pdfminer.six`; `ORNEUR_L02_DOC_LIBS=/tmp/l02-doclibs PYTHONPATH=.:/tmp/l02-doclibs $PY -m pytest tests/journey/test_l02_upload_parsers_live.py` | 7 passed (fails, never skips, without the libs) |
| Real-Ollama documents | `ORNEUR_JOURNEY_MODEL=llama3.2:1b … tests/journey/test_l02_document_real_live.py` | 3 passed |
| Customer journeys | `… tests/journey/test_l02_customer_journeys.py` (`-k fixture` / `-k real`) | 6 passed; `evidence/l02_journey_*.json` |
| LANDMARK-01 regressions | `tests/journey/test_b01_streaming_live.py`, `…real_ollama_live.py`, `…cancel_race_live.py`, `…browser_streaming.py`, `…journey_concurrency_live.py` | 17 / 2 / 1 / 26 / 11 passed |
| Frontend | `node --test tests/frontend/*.mjs` | 102 pass |
| Postgres | `pip install -e ".[pgtest]"`; `pytest tests/test_a_postgres_integration.py` | 13 passed (a schema-comment defect in this candidate once broke it: commit `7059629`) |

## 2. Adversarial extensions we did NOT run
* a hostile **answering** model that obeys document instructions (our mitigation is structural; try it against the tool gate and DLP);
* real SMTP / mail-scanner behaviour on verification links; link-prefetch by a real scanner;
* a genuinely full disk; fd exhaustion; sustained load beyond one workstation; multi-host clock skew;
* reverse proxies that buffer SSE; mobile browsers, non-Chromium engines, assistive tech;
* backup restore of a data directory created by an older version.

## 3. Review these first
`orca/serve/deletions.py`, `orca/serve/turn_requests.py`, `orca/serve/api.py` (turn lifecycle, deletion route, upload route, drain/admission), `orca/docs/{judge,safe_extract,_extract_worker,validation}.py`, `orca/tools/authorization.py`, `orca/auth/{account_security,routes}.py`, `orca/gateway/reconcile.py`, `orca/serve/{ops,backup,capability_truth}.py`, `orca/serve/web/conversation.html` (reconcile/Stop/verification handlers only).

## 4. Not proven here
Independent qualification; production behaviour; capacity/latency/SLOs; real mail delivery; real-Ollama results in CI; answer quality of the 1B third-party model. Changed existing assertions and reasons: `L02_SECURITY_REGRESSION_MATRIX.md`. Open risks: `L02_BLOCKER_REGISTER.md`.

Please record your verdict against the exact SHA in your own PR with your own evidence-class split.
