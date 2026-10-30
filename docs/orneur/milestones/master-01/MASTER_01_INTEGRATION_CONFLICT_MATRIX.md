# MASTER-01 — Integration Conflict Matrix

**Scope:** Disposable worktree/local-branch experiments only. No protected PR heads modified. No main updates. No prod/persistent infra.

## 1. Experiment topology

| Disposable branch (local only) | Constituent merge order | Result tip | Tree SHA |
|---|---|---|---|
| `cursor/master-01-int-foundation-stack-951d` | main → F02 → F03 | `d89b3bcbf4f34288f294a7f5ddfdd2c1281ce87a` | `42f929cdc7506471c7806b88857c7e9f53a72a40` |
| `cursor/master-01-int-landmark-stack-951d` | main → L01 → L02 → B3 | `e8e515a4e5f559c0dd04cab0c6266503530c1711` | `3fa6d426f17aa00b836ccf1ec11061c93f8fae3a` |
| `cursor/master-01-int-l02-b6-only-951d` | L02 → B6 | `bdda9b7da6b02dbfc84b212f86a9d16936140c5f` | `b00a38bda89464ccdebefdabd5498799bb66b2fa` |
| `cursor/master-01-int-full-candidate-951d` | main → F02 → F03 → L01 → L02 → B3 (**no B6**) | `ee8cb2a8e54a1d3ee398c2d48378761ca4d8c9f1` | `7a980d4ae918bc4dbec374772a2ec20e36d3107f` |
| B3+B6 either order | L02 → B3 → B6 **or** L02 → B6 → B3 | **STOPPED — CONFLICT** | — |

Integration candidates remain **local/unmerged**. Not pushed to protected heads.

## 2. Merge outcomes

| Combination | Conflicts? | Files | Disposition |
|---|---|---|---|
| F02 → F03 | No | — | Clean |
| L01 → L02 → B3 | No | — | Clean |
| L02 → B6 | No | — | Clean |
| F02+F03+L01+L02+B3 | No | — | Clean (surprising but measured) |
| **B3 + B6 (any order)** | **YES** | `.github/workflows/test.yml`, `docs/orneur/landmarks/landmark-02/evidence/l02_04_login_timing.json` | **STOP — unsafe to present as integrated without intentional dual-PR resolve** |

### B3∩B6 conflict detail

1. **`.github/workflows/test.yml`** — both append a distinct live journey file to the same Journeys pytest invocation (`test_l02_b3_apikey_reauth_live.py` vs `test_l02_b6_backup_live.py`). Union is mechanically possible but **not auto-merged**; requires deliberate CI edit.
2. **`l02_04_login_timing.json`** — both rewrite measured timing floats from the same workstation evidence file (different sample means/ratios). Evidence artifact collision; picking one silently drops the other measurement.

**No force-resolve performed** for a shippable candidate. Combination classified blocked for integration packaging.

## 3. Topic matrix (full candidate without B6 unless noted)

| Topic | Observation on disposable combined tree | Risk / action |
|---|---|---|
| **Imports / packaging** | `pip install -e .` + RSE extras (`pyhpke`, `cryptography`) succeeded; F02 adds `sentencepiece` optional; L01 adds `journey_live` pytest marker — both present after merge | Low for install; marker registration depends on `pyproject.toml` merge (clean) |
| **FastAPI startup / serving** | `from orca.serve.api import app` → **PASS**; title `ORNEUR API`; **69 routes** | Smoke only — not load/soak |
| **Auth / user-data** | Invalid-bearer suite + B3 API-key reauth unit suite **PASS** on combined tip | Session/JWT paths from L01+L02+B3 compose; no F02 auth collision observed |
| **Streaming / cancel** | `test_b01_raw_delta_lifecycle`, `test_kernel_streaming`, `test_b01_stream_cleanup`, `test_l02_turn_recovery` **PASS** (requires `pytest-asyncio`) | Env gap if asyncio plugin missing (see evidence doc) — not a code conflict |
| **RAG / memory** | `test_l02_document_rag`, dispatch, judge trust, tool authority **107 passed** | Fixture/provider only; real-Ollama RAG **NOT RUN** |
| **Native vs third-party model disclosure** | `capability_truth.serving_facts()` → `weights_origin=third_party`, `native_orneur_weights=false`; system facts instruct model not to claim Genesis/Novus/Aeternum | Present via L02; F02 native-learning code coexists without overwriting disclosure |
| **Training auth fail-closed** | `TRAINING_AUTHORIZATION.json` status `NOT_AUTHORIZED`; `gpu_allowed=false`; readiness gate suite **40 passed** | Preserved on combined tip; register numerator still 0 |
| **Backup / restore + legacy bypass** | On L02/B3 path: plaintext `MANIFEST.json` directory format still live. B6 encrypts (`orneur-backup/2`) but **excluded from combined candidate** per assignment — unresolved legacy plaintext / `--unsafe-without-deletion-history` / auth `orca backup` plaintext / not independently qualified | **STOP including #143** as integration-ready |
| **CI / locks** | Workflow auto-merged for F02∩Landmark; B3∩B6 CI line conflicts | Dual-stack CI job density high; B3+B6 needs manual union |
| **Migrations / rollback** | No DB migration framework collision observed. B3 adds `auth_stepup_totp_used` table in SQLite+Postgres schema paths. B6 adds `deletion_ledger.jsonl` (non-SQL) + format break for backups | B6 restore journals / `.pre-restore-*` plaintext rollback copies are B6-only concerns |
| **RSE C06/C07** | Impl present from F03; 16/16 + 130/130 RSE passed on combined tip | Software scope only; formal rows not promoted |

## 4. Combinations explicitly stopped

| Combination | Reason |
|---|---|
| Any tree including **#143 as “ready”** | Assignment: unresolved legacy plaintext backup/restore bypass; **not independently qualified** |
| **B3 + B6** without intentional conflict resolve | Content conflicts in CI workflow + evidence JSON |
| Promote C06/C07/G2/G3 from local evidence | Formal ledger must stay **0/95**; histogram preserved |
| Merge to main / retarget protected PR heads | Out of scope |

## 5. Residual packaging notes

- Landmark async tests fail loudly without `pytest-asyncio` (environment), identical on landmark-only and full candidate — **not** a cross-stack regression.
- Live Ollama / Chromium / two-worker / real-mail journeys **not executed** in this disposable environment (no GPU/corpus/paid infra; fixture suites used where available).
- Antigravity F03 suite cannot run as-committed here: hardcodes `/home/pc/projects/Orneur-pr142-f03`.
