# FOUNDATION CONSOLIDATION — CI Register

```
STATUS: PREFLIGHT — EXACT-HEAD GREEN ON QUALIFIED TIPS
```

Refreshed from GitHub Actions API 2026-10-31. No tip mutation of #145/#146/#148.

---

## 1) Qualified stack tips

| Role | SHA | Run | Workflow | Jobs | Conclusion |
|---|---|---|---|---|---|
| MASTER-04 eng tip | `cadad0e525c5f84698af9945d048b9ba36aa4f0e` | [41196122676](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41196122676) | Test Suite | **10/10** | **success** |
| MASTER-04 PR HEAD (#148) | `da699a01bdb811ac54ef00cf0c9585f70eb74a57` | [41197716243](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41197716243) | Test Suite | **10/10** | **success** |
| MASTER-03 (#146) | `b96cc3260078b6f677a22381b05fe1f72026256f` | [41178651529](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41178651529) | Test Suite | **10/10** | **success** |
| MASTER-02 (#145) | `d8827409248dcdb5da55a010d8224d9e0e3bddbe` | [41060779081](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41060779081) (+ twin [41060768314](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41060768314); Eval Static [41060779145](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41060779145)) | Test Suite / Eval Static | all SUCCESS | **success** |

### Job family (10) — eng tip `cadad0e` / PR HEAD `da699a0`

1. Deterministic Unit Tests  
2. Training Math Unit Tests (Torch)  
3. Production Container Build + Boot Smoke  
4. SSE Diagnostics  
5. Journeys (real servers + Redis + Chromium)  
6. Genesis V2 Security  
7. Genesis V2 Sandbox  
8. Dependency Vulnerability Scan (informational)  
9. RSE dependency lock and vulnerability scan  
10. RSE Docker Synthetic Integration Lab  

Eng tip Deterministic: **9730 passed**, 0 failed (per MASTER_04_CI_EVIDENCE).

---

## 2) Supporting lineage CI (pre-existing)

| Ref | Run | Result |
|---|---|---|
| L03 code `c8b0f54…` | [41189270383](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41189270383) | success |
| L03 doc `bfeaae2…` | [41190351398](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41190351398) | success |

---

## 3) Disclosed failing-before (historical; not current tips)

| Tip | Run | Outcome |
|---|---|---|
| `000ee2a…` | [41192500593](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41192500593) | FAIL — Deterministic + Journeys (vector/serving-lock) |
| `5ab87f3…` | [41194297136](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41194297136) | FAIL — sticky service mode + shallow Journeys ancestry |

Repairs landed on `cadad0e…`. Current qualified tips are green.

---

## 4) Docs-only PR #149

| SHA | Runs | Note |
|---|---|---|
| `44e130e7ef6421370f48c4144f2c30a74c6f521b` | [41204647604](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41204647604), [41204632892](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41204632892) | Observed in-progress at refresh; docs-only delta vs `main` — **not** a substitute for #145/#146/#148 CI |

---

## 5) Reconciliation notes

- Required-check visibility for protected `main` is limited by API **403** (see `FOUNDATION_CONSOLIDATION_BRANCH_PROTECTION.md`). Observed green job set on candidate tips is treated as the engineering CI register, not as merge authorization.
- PR HEAD `da699a0` is docs-only evidence binding vs eng `cadad0e`; both 10/10 success.
- This preflight did **not** re-trigger CI on #145/#146/#148.
