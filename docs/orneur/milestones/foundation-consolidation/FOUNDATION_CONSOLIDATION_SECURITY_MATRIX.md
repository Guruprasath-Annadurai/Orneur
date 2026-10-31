# FOUNDATION CONSOLIDATION — Security / Functional Regression Preservation

```
STATUS: PREFLIGHT — SUITES REUSED; NO PHASE-H MERGE
```

**Tip under assessment:** PR #148 HEAD `da699a01bdb811ac54ef00cf0c9585f70eb74a57` (eng tip `cadad0e525c5f84698af9945d048b9ba36aa4f0e`)  
**Base:** protected `main` `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`  
**Phase H:** INACTIVE

---

## 1) Preservation strategy

| Lever | Action this preflight |
|---|---|
| Full CI Test Suite (10 jobs) | **Reuse** green exact-head runs on eng + PR tips |
| B3 API-key reauth suite | **Reuse** preserve log: **22 passed** |
| B6 backup privacy / corrective | **Reuse** preserve log: **69 passed** |
| Antigravity independent qual | **Reuse** FINAL Path B tip `83978d4…` — 16 passed; LIMITED-SCOPE EVIDENCE CLOSED |
| Acceptance / training / capability invariants | **Fresh lightweight verification** on #148 tip (pass) |
| Full local pytest re-run | Not required for preflight; CI already exact-head green |

No tip mutation of #145/#146/#148. No new production-facing code in this package.

---

## 2) Governance invariants (fresh check on #148 tip)

| Invariant | Result |
|---|---|
| Formal pretraining acceptance **0/95** | **HOLD** — `numerator_pretraining=0`, denominator length **95**, `published_pretraining_percentage=null` |
| `TRAINING_AUTHORIZATION.status` | **NOT_AUTHORIZED**; `gpu_allowed: false` |
| `training_authorized()` | **False** (hard deny in `orca/rse/imp1/locks.py`) |
| GENESIS | **INTERFACE_ONLY** |
| NOVUS / AETERNUM | **NOT_AVAILABLE** |
| Dockerfile public image | `uv pip install --system -e ".[postgres]"` only — no Chroma/crypto bake-in |

---

## 3) Security-critical surfaces preserved / introduced by stack (vs `main`)

| Surface | Modules / paths | Preservation evidence |
|---|---|---|
| Account security / API-key fresh reauth (B3) | `orca/auth/**`, `tests/test_l02_b3_apikey_reauth.py`, journey live | B3 **22 passed**; CI green |
| TOTP / token / middleware hardening | `orca/auth/totp.py`, `tokens.py`, `middleware.py` | Covered by deterministic CI on tip |
| Encrypted backup + datadir lock (B6) | `orca/serve/backup*.py`, `datadir_lock.py`, deletion ledger | B6 **69 passed**; live journey green on CI |
| Vector isolation (L03) | `orca/vectorstore/{server,client,host,protocol}.py` | L03 suites + M04 integration on CI; Antigravity Path B |
| Authz / spend / corpus locks | `docs/orneur/authorization/**`, `orca/rse/imp1/locks.py` | Fresh invariant check + CI |
| Capability truth honesty | `orca/serve/capability_truth.py`, family registry | Fresh check |
| CI ancestry fail-closed | `.github/workflows/test.yml` Journeys `fetch-depth: 0` | Landed on eng tip; CI 10/10 |

---

## 4) Residual risks (founder awareness; not Phase-H blockers for *preflight*)

| ID | Status | Note |
|---|---|---|
| M04-B10 Same-UID FS socket token local boundary | DOCUMENTED RISK | Not multi-tenant OS isolation |
| M04-B11 Prod Docker image requires optional extras | DOCUMENTED RISK | Founder-scoped enablement |
| M04-B12 Formal pretraining admissions 0/95 | **HOLD** | Must remain until separate authorization |

Physical / forensic erasure of deleted customer bytes is **not** claimed.

---

## 5) Functional regression register (reuse)

| Suite / gate | Evidence | Result |
|---|---|---|
| Deterministic Unit Tests | CI `41196122676` / `41197716243` | PASS (9730 passed on eng tip) |
| Training Math | same | PASS |
| Prod Container Build + Boot | same | PASS |
| SSE Diagnostics | same | PASS |
| Journeys | same | PASS |
| Genesis V2 Security / Sandbox | same | PASS |
| Dependency / RSE lock + lab | same | PASS |
| Acceptance register gate | store `evidence/acceptance_register.log` | PASS |
| Pretraining gate | store `evidence/pretraining_gate.log` | PASS |
| B3 preserve | store `evidence/b3_preserve.log` | **22 passed** |
| B6 preserve | store `evidence/b6_preserve.log` | **69 passed** |

---

## 6) Explicit non-claims

- This matrix does **not** authorize merge, deploy, training, spend, tags, or acceptance promotion.
- Successful suite reuse ≠ production readiness.
- Phase H remains **INACTIVE**.
