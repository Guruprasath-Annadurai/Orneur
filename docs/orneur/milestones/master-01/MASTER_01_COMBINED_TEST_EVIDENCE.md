# MASTER-01 — Combined Test Evidence

**Classification:** Local disposable integrated tests only.  
**Not** independent qualification. **Not** mainline acceptance.  
**Formal acceptance ledger unchanged: 0 / 95.**

## 1. Candidate identity

| Field | Value |
|---|---|
| Disposable branch | `cursor/master-01-int-full-candidate-951d` (local only) |
| Merge commit tip | `ee8cb2a8e54a1d3ee398c2d48378761ca4d8c9f1` |
| Tree SHA | `7a980d4ae918bc4dbec374772a2ec20e36d3107f` |
| Tree digest (sha256 of tree SHA hex) | `14a96085501bc36a2935ce569263dc6f6ce18c7aafb26315f0a55fb25ee99207` |
| Constituent SHAs | main `20a8546…` · F02 `649d90f…` · F03 `9cdc22b…` · L01 `9cb864c…` · L02 `38e0d31…` · B3 `66ce8ae…` |
| Explicitly excluded | L02-B6 `b1c56b9…` (#143) |

### Environment

| Item | Value |
|---|---|
| Host | Cursor Cloud Agent VM (Linux) |
| Python | 3.12.3 |
| Install | `pip install -e .` + `pyhpke` + `cryptography` + `pytest` + `pytest-asyncio` |
| `PYTHONPATH` | `.` (worktree root `/tmp/master01-wt/int-full`) |
| GPU / corpus / paid runners | **Not used** |
| Real customer data / secrets | **None** |

## 2. Commands and results

| Gate | Command | Result | Class |
|---|---|---|---|
| Register validator | `python3 scripts/acceptance/validate_register_graph.py --check` | `pretraining=95 numerator=0 application=3 execution=2 post=1` | **PASS** (numerator preserved) |
| C06/C07 engineering | `python3 -m pytest tests/rse/test_c06_c07_consumer_verification.py -q` | **16 passed** | PASS (engineering only) |
| RSE adjacent | `python3 -m pytest tests/rse/ -q` | **130 passed** | PASS |
| FastAPI import smoke | `from orca.serve.api import app` | **PASS** — 69 routes | PASS (smoke) |
| Training fail-closed | `tests/test_pretraining_readiness_gate.py` + `tests/test_genesis_governance_authorization.py` | **40 passed** | PASS |
| Auth + B3 + stream + recovery + model truth | see §3 | **113 passed, 1 skipped** | PASS |
| RAG / judge / tool authority | `tests/test_l02_document_{rag,dispatch}.py` + judge + tool_authority | **107 passed** | PASS |
| Model disclosure probe | `orca.serve.capability_truth` | third-party/Ollama disclosed; native weights false | PASS (probe) |

### §3 Landmark targeted suite (combined tip)

```text
python3 -m pytest \
  tests/test_auth_invalid_bearer_refused.py \
  tests/test_l02_b3_apikey_reauth.py \
  tests/test_b01_stream_cleanup.py \
  tests/test_b01_raw_delta_lifecycle.py \
  tests/test_kernel_streaming.py \
  tests/test_l02_turn_recovery.py \
  tests/test_l02_model_truth.py \
  tests/test_canonical_turn_authority.py -q
→ 113 passed, 1 skipped
```

Prior run **without** `pytest-asyncio`: 30 failed / 84 passed — failures were `async def functions are not natively supported` (env), reproduced identically on landmark-only tip. **Not** recorded as cross-stack product regression.

## 3. Unexpected failures

| Item | Notes |
|---|---|
| None after asyncio plugin installed | Earlier async failures = missing plugin |
| `capability_truth.capabilities_payload` name | Import name is `capabilities` / `serving_facts` — probe adjusted; not a product failure |

## 4. Skips / xfails / not run

| Item | Status |
|---|---|
| 1 skip in landmark targeted set | Pre-existing conditional skip (not investigated as new) |
| Real-Ollama streaming / document-real / D6 | **NOT RUN** (no Ollama runner in this env) |
| Chromium customer journeys | **NOT RUN** |
| Two-worker live B3 journey | **NOT RUN** |
| B6 backup suite | **NOT RUN on combined tip** (B6 excluded); baseline plaintext risks documented from #143 artifacts |
| Antigravity F03 suite `75a7a64` | **NOT RUN** — hardcodes `/home/pc/projects/Orneur-pr142-f03`; not on PR #142 tip |
| Full deterministic CI (~9k tests) | **NOT RUN** locally — rely on per-PR exact-head greens + targeted combined evidence |
| GPU / training execution | **NOT RUN** — NO-GO / unauthorized |

## 5. Coverage gaps (honest)

1. No combined-tip exact-head GitHub Actions run (candidate never pushed).
2. No independent Antigravity retest of the **combined** tree.
3. No B3+B6 packaged candidate (conflict stop).
4. No migration/rollback chaos beyond unit coverage already in constituents.
5. No proof of operator-observed C06 display or human-entered C07 Intent Sheet.
6. Streaming cancel under multi-worker load not re-measured here.

## 6. Founder / external decisions required (from evidence alone)

See also security/governance + CTO handoff. Local green combined tests **do not** authorize: mainline merge, training, spend, corpus activation, or formal row acceptance.

## 7. Explicit non-claims

- Local integrated tests ≠ independent qualification ≠ mainline acceptance.
- C06/C07 remain **non-accepted** register rows; engineering success on combined tip does **not** change 0/95.
- Histogram **11 / 17 / 19 / 48** not rewritten from this evidence.
- #143 not evidenced as integration-ready.
