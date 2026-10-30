# MASTER-02 — CI and Retest Evidence

**Classification:** Local agent re-execution + GitHub Actions on pushed tip.  
**Not** independent Antigravity OWN_EVIDENCE. **Not** mainline acceptance.  
**Formal acceptance ledger unchanged: 0 / 95.**

## 1. Identities under test

| Identity | SHA |
|---|---|
| Merge-tip HEAD (content integration) | `7fb78a3d9c522edff26335a551ceadc5d500f941` |
| Merge-tip TREE | `7a980d4ae918bc4dbec374772a2ec20e36d3107f` |
| PR tip | See PR / `git rev-parse` after harness+docs commits (separately traceable) |

Environment: Cursor Cloud Agent VM, Python 3.12.3, `pip install -e .[dev]` + `pyhpke`/`cryptography`/`pytest-asyncio`.  
**No GPU / corpus / paid runners / real customer data.** Docker **not available** in this local VM → container smoke, RSE Docker lab, Redis-backed journeys deferred to GitHub Actions.

## 2. Local results on merge tip (before harness commit)

| Gate | Command / scope | Result | Class |
|---|---|---|---|
| Register validator | `validate_register_graph.py --check` | `pretraining=95 numerator=0` | **PASS** (preserved) |
| C06/C07 engineering | `tests/rse/test_c06_c07_consumer_verification.py` | **16 passed** | PASS (engineering) |
| RSE adjacent | `tests/rse/` | **130 passed** | PASS |
| Training fail-closed | readiness + genesis governance auth | **40 passed** | PASS |
| Landmark targeted | auth/B3/stream/recovery/model truth/canonical | **113 passed, 1 skipped** | PASS |
| RAG / judge / tool | L02 document + judge + tool authority | **107 passed** | PASS |
| Streaming extra | B01 lifecycle + kernel + cleanup | **31 passed, 1 skipped** | PASS |
| FastAPI smoke | `from orca.serve.api import app` | title ORNEUR API, **69 routes** | PASS (smoke) |
| Genesis V2 Security | `scripts/ci/run_genesis_v2_security_tests.sh` | **560 passed**, 0 skip/xfail | PASS |
| SSE diagnostics | `tests/frontend/test_sse_diagnostics.mjs` | **5 passed** | PASS |
| Frontend shell | logout / inline edit / view ownership | **13 + 15+ + 20 passed** | PASS |
| RSE dependency audit | `scripts/ci/run_rse_dependency_audit.sh` | No known vulnerabilities | PASS |
| Portable F03 harness | `tests/qualification/test_master02_f03_portable_harness.py` | **15 passed** (on tip after harness present) | PASS (engineering re-exec) |

### Skips (reported, not suppressed)

| Item | Notes |
|---|---|
| 1 skip in landmark targeted set | Pre-existing conditional skip (same as MASTER-01) |
| 1 skip in streaming extra | Pre-existing conditional skip |

### Not run locally (environment gaps — must not be silent)

| Gate | Reason | Disposition |
|---|---|---|
| Production container build + boot smoke | No `docker` on agent VM | **Deferred to GitHub Actions** |
| Genesis V2 Sandbox | Script requires Docker | **Deferred to GitHub Actions** |
| RSE Docker Lab | Requires Docker | **Deferred to GitHub Actions** |
| Journeys (fixture + Redis + Chromium) | No Docker Redis service | **Deferred to GitHub Actions** |
| Real-Ollama live journeys | No Ollama / paid runners | **NOT RUN** (documented) |
| Full deterministic ~9k suite | Local duration; CI job authoritative | **Deferred to GitHub Actions** |
| Torch training-math job | Heavyweight optional deps | **Deferred to GitHub Actions** |
| Dependency vulnerability scan (CI job) | CI workflow | **Deferred to GitHub Actions** |
| Original Antigravity suite as-committed | Hardcodes `/home/pc/projects/Orneur-pr142-f03`; asserts HEAD==`0fe98e0` | **NOT RUN as-is**; portable harness used; original archived verbatim |

## 3. Independent re-execution notes

- MASTER-01 disposable local evidence reproduced on identical tree `7a980d4…`.
- F03 Antigravity suite (`75a7a64`) archived verbatim under repo evidence; portable harness is a **separate commit** and does not edit original audit evidence.
- Portable harness verifies: engineering SHA ancestor of HEAD; `consumer_verification.py` blob identity with `0fe98e0`; formal 0/95; adversarial C06/C07 body.

## 4. GitHub Actions

Record exact run IDs / check conclusions on the pushed PR tip in `MASTER_02_GITHUB_CI.md` once terminal. Subscribe via branch `cursor/master-02-integration-candidate-316a`.

## 5. Explicit non-claims

- Local green ≠ independent qualification ≠ mainline acceptance.
- C06/C07 remain non-accepted register rows.
- Histogram / formal ledger not rewritten.
- #143 not included and not evidenced as integration-ready.
