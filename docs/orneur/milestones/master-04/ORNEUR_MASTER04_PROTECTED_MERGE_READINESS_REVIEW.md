# ORNEUR MASTER-04 — Protected Merge Readiness Review

```
STATUS: PROTECTED MERGE READINESS PACKAGE — FOUNDER DECISION REQUIRED
```

**Classification:** Engineering assessment only (Path B).  
**Not** merge authorization. **Not** production authorization. **Not** training authorization.  
**Successful conflict-free simulation ≠ permission to merge to protected `main`.**

**Review authority:** Cursor engineering (this package)  
**Independent qualification:** Antigravity FINAL — Path B gate passed  
**Date:** 2026-10-31  
**Review branch:** `cursor/master-04-protected-merge-readiness-bb5d` (docs-only; draft PR against `main` for visibility only — does not land candidate code)

---

## 0) Executive GO / NO-GO for CTO / founder

| Decision surface | Engineering recommendation |
|---|---|
| Merge #145 / #146 / #148 (or stack) to protected `main` | **NO-GO** without explicit CTO/founder authorization |
| Mark draft PRs ready for review / merge | **NO-GO** without founder authorization |
| Deploy / enable production vector backend / bake Chroma or backup crypto into public image | **NO-GO** (founder-blocked) |
| Training / GPU / spend / corpus / Crown / freeze | **NO-GO** — `TRAINING_AUTHORIZATION.status=NOT_AUTHORIZED`; `training_authorized()→False` |
| Promote formal pretraining acceptance | **NO-GO** — ledger remains **0/95** |
| Treat Path B simulation success as merge auth | **NO-GO** — simulation is conflict evidence only |
| Engineering readiness of candidate stack for founder decision | **READY FOR FOUNDER DECISION** (package complete; residual risks documented) |

**Overall package status:** `PROTECTED MERGE READINESS PACKAGE — FOUNDER DECISION REQUIRED`

---

## 1) Exact refreshed identities (verified 2026-10-31)

| Role | Ref / PR | SHA | TREE |
|---|---|---|---|
| Protected `main` | `origin/main` | `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` | `4707492d800aea61a4c6f159a1adf3d59d8a23d6` |
| MASTER-02 tip | PR **#145** / `cursor/master-02-integration-candidate-316a` | `d8827409248dcdb5da55a010d8224d9e0e3bddbe` | `615c6a3483e64acc3bdb6ccc2d2351d4f63ca96e` |
| MASTER-03 tip | PR **#146** / `cursor/master-03-security-corrected-b882` | `b96cc3260078b6f677a22381b05fe1f72026256f` | `168a6a2c75bd11e0cbac113e06ff4d50e88f9cae` |
| MASTER-04 engineering code tip | ancestor of #148 | `cadad0e525c5f84698af9945d048b9ba36aa4f0e` | `d1742759c1ecf25629f7bca1376719a75bd52d71` |
| MASTER-04 PR HEAD (evidence-binding) | PR **#148** / `cursor/master-04-vector-backup-security-integration` | `da699a01bdb811ac54ef00cf0c9585f70eb74a57` | `106487db24a66672c7ca3e660a1d1e0792281238` |
| M04×L03 merge | on #148 ancestry | `4295550b7991972e7a6b5cd1d25123b58355cbf1` | (parents below) |
| L03 code / doc | PR #147 line | `c8b0f54bafe364c18e507425570d34be1e7b8dd7` / `bfeaae2bc7470251262b3526e32fede7412996d8` | — |
| Antigravity FINAL qual tip | `antigravity/phase01-independent-qualification` | `83978d48f071fac575f360605baadf35c3fac1e0` | `9c04e89515330a9a4735e1beef47ed06e72856e3` |

Merge `4295550` parents: `b96cc3260078b6f677a22381b05fe1f72026256f` + `bfeaae2bc7470251262b3526e32fede7412996d8`.

`main` was **not** mutated by this review. No tags created. No ancestry rewrite. Temporary simulation worktrees/branches were discarded locally after use.

---

## 2) A — Stacked ancestry verification

### 2.1 Git ancestry (fail-closed checks)

| Claim | Result |
|---|---|
| `main` ⊂ #145 | **OK** (`20a8546` ancestor of `d882740`) |
| #145 ⊂ #146 | **OK** (`d882740` ancestor of `b96cc32`) |
| #146 ⊂ #148 | **OK** (`b96cc32` ancestor of `da699a0`) |
| `main` ⊂ #146 and #148 | **OK** |
| eng tip `cadad0e` ⊂ PR HEAD `da699a0` | **OK** (docs-only binding commit after eng tip) |
| Antigravity audit tip `167e0ca` ⊂ #148 | **Not required / not ancestor** (reference-only; documented previously) |

### 2.2 PR stack topology (draft bases)

| PR | Draft | Base | Head branch | Mergeable (as reported) |
|---|---|---|---|---|
| #145 | **yes** | `main` | `cursor/master-02-integration-candidate-316a` | MERGEABLE / CLEAN |
| #146 | **yes** | `cursor/master-02-integration-candidate-316a` | `cursor/master-03-security-corrected-b882` | MERGEABLE / CLEAN |
| #148 | **yes** | `cursor/master-03-security-corrected-b882` | `cursor/master-04-vector-backup-security-integration` | MERGEABLE / CLEAN |

Sequence `main → #145 → #146 → #148` is the actual GitHub draft stack. #148 is **not** opened directly against protected `main`.

### 2.3 History preservation (F02 / F03 / Landmark / B3 / B6)

Reachable from #148 tip `da699a0` (and preserved through discarded stack simulation tip):

| Marker | SHA | Subject |
|---|---|---|
| F02 integrate | `25b794a…` | `merge(master-02): integrate F02 #140 @ 649d90f…` |
| F03 integrate | `d064b67…` | `merge(master-02): integrate F03 #142 @ 9cdc22b…` |
| L02-B3 integrate | `7fb78a3…` | `merge(master-02): integrate L02-B3 #141 @ 66ce8ae…` |
| L02-B6 integrate | `34b6688…` | `merge(master-03): integrate L02-B6 #143 @ 4ab809d…` |
| L03 into M03 | `4295550…` | `merge(master-04): integrate LANDMARK-03 vector containment into MASTER-03 tip` |

Local preserve logs on candidate tip: B3 suite **22 passed**; B6 suite **69 passed** (`docs/orneur/milestones/master-04/evidence/b3_preserve.log`, `b6_preserve.log`).

---

## 3) B — Branch protection / policy reconciliation

### 3.1 Observed facts

- Default branch: `main` @ `20a8546…` (unchanged throughout this assessment).
- Candidate PRs #145 / #146 / #148 remain **Draft**; reviewDecision empty; no agent action marked them ready.
- Repo merge settings (API): merge commit / squash / rebase allowed; `allow_auto_merge=false`; `delete_branch_on_merge=false`.
- Required checks observed green on current PR tips (10-job `Test Suite` family — Deterministic, Training Math, Prod Container, SSE, Journeys, Genesis V2 Security/Sandbox, Dependency scans, RSE lock+lab).
- This agent did **not** bypass protection, force-push `main`, merge any of #145/#146/#148, or convert drafts to ready.

### 3.2 Protection API limitation (documented)

`GET /repos/.../branches/main/protection` and rulesets listing returned **403 Resource not accessible by integration** / empty rulesets for this token.  
**Engineering stance:** treat `main` as **protected / founder-gated** per programme governance regardless of API visibility. Absence of readable ruleset JSON is **not** authorization to merge.

### 3.3 Governance-sensitive surfaces in the candidate delta vs `main`

Large stacked delta (~642 files, +101387 / −941 vs `main`), including:

- Auth / account security (`orca/auth/**`, TOTP, API-key reauth B3 path)
- Encrypted backup + datadir lock (`orca/serve/backup*.py`, `datadir_lock.py`, `deletion_ledger.py`)
- Out-of-process vector owner (`orca/vectorstore/**`)
- Authorization / acceptance ledgers under `docs/orneur/authorization/**`, `docs/orneur/acceptance/**`
- CI workflow `.github/workflows/test.yml` (incl. Journeys `fetch-depth: 0`)
- `Dockerfile` still installs only `.[postgres]` (no silent Chroma/crypto bake-in)
- Pretraining foundation / genesis training modules remain **denied** by locks

Independent qual refs (Antigravity) live on separate branch tip `83978d4…` and are **not** merged into #148; they bind candidate SHAs by citation.

### 3.4 Conflicts vs current `main`

See §4 — isolated merge simulations completed with **zero conflicts**. Candidate tips need **no** conflict-driven rewrite for a hypothetical future founder-authorized merge of current SHAs. If founder later requires tip mutation, that creates a **new** candidate needing retest/qualification.

---

## 4) C — Isolated integration simulation (temporary worktree only)

### 4.1 Procedure

- Worktrees under `/tmp/master04-*-sim-*` based at `main` `20a8546…`
- `git merge --no-commit` / sequential `--no-ff` of tips
- **No push**, **no tags**, **no rewrite** of remote ancestry
- Local sim branches deleted after discard; `origin/main` reconfirmed `20a8546…`

### 4.2 Results

| Simulation | Result | Conflicts |
|---|---|---|
| Fast-forward-capable merge of #148 tip into `main` (`--no-commit --no-ff`) | exit 0; auto-merge clean | **none** |
| Sequential `main ← #145 ← #146 ← #148` | all three merges exit 0 | **none** |
| F02/F03/B3/B6/L03 markers after sequential sim | preserved | — |

Local-only sequential sim tip (discarded, never pushed): `a5bc21a27e0a05620e28d4a43949da68069cccb2`.

**Interpretation:** Git integration of the current stack onto current `main` is conflict-clean. This is **not** merge authorization and does **not** satisfy founder/production gates.

---

## 5) D — Acceptance / model truth verification (candidate tip `da699a0`)

| Invariant | Evidence on tip | Status |
|---|---|---|
| Formal pretraining acceptance **0/95** | `docs/orneur/acceptance/register_graph.json`: `numerator_pretraining=0`, `denominator_pretraining_ids` length **95**, `published_pretraining_percentage=null` | **HOLD** |
| `TRAINING_AUTHORIZATION` false / NOT_AUTHORIZED | `docs/orneur/authorization/TRAINING_AUTHORIZATION.json` → `"status": "NOT_AUTHORIZED"`, `gpu_allowed: false`, null ids/signatures; `orca/rse/imp1/locks.py` → `training_authorized() → False` (hard-coded deny) | **NO-GO** |
| GENESIS `INTERFACE_ONLY` | `orca/genesis/model/family_registry.py` + `orca/serve/capability_truth.py` | **Confirmed** |
| NOVUS / AETERNUM `NOT_AVAILABLE` | same registries | **Confirmed** |
| No native training claim | Antigravity Gate K + residual M04-B12 HOLD; engineering reports restated | **Confirmed** |
| No fabricated prod readiness | Packaging: Dockerfile `uv pip install --system -e ".[postgres]"` only; memory/backup extras optional | **Confirmed** |

Master-04 evidence logs on tip: acceptance register gate **1 passed**; pretraining gate **4 passed**.

---

## 6) Independent qualification refs (Path B gate)

| Field | Value |
|---|---|
| Branch | `antigravity/phase01-independent-qualification` |
| Tip | `83978d48f071fac575f360605baadf35c3fac1e0` |
| Report | `docs/qualification/ORNEUR_MASTER04_INDEPENDENT_INTEGRATION_QUALIFICATION_REPORT.md` |
| Disposition | `MASTER-04 FINAL LIMITED-SCOPE EVIDENCE CLOSED` |
| Bound candidate PR HEAD | `da699a01bdb811ac54ef00cf0c9585f70eb74a57` |
| Bound code SHA | `cadad0e525c5f84698af9945d048b9ba36aa4f0e` |
| Suite | `tests/qualification/test_master04_independent_qualification.py` — **16 passed** |
| Path | **B** — closure without confirmed P0/P1 blocking defects |
| Status note (store) | `/cursor/stores/self/docs/master-04/ANTIGRAVITY_VERDICT_STATUS.md` |

### Residual register (Antigravity §9)

| ID | Status |
|---|---|
| M04-B1 … M04-B9 | RESOLVED / Verified Pass |
| M04-B10 Same-UID FS socket token local boundary | **DOCUMENTED RISK** |
| M04-B11 Prod Docker image requires optional extras | **DOCUMENTED RISK** |
| M04-B12 Formal pretraining admissions 0/95 | **UNRESOLVED (HOLD)** |

---

## 7) CI evidence (candidate)

| Tip | Run | Result |
|---|---|---|
| Eng `cadad0e` | [41196122676](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41196122676) | success **10/10** (Deterministic 9730 passed) |
| PR HEAD `da699a0` | [41197716243](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41197716243) | success **10/10** (docs-only delta vs eng) |
| MASTER-03 `b96cc32` | [41178651529](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41178651529) | all jobs PASS |
| L03 code / doc | [41189270383](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41189270383) / [41190351398](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41190351398) | success |

Failing-before tips preserved in `MASTER_04_CI_EVIDENCE.md` / `MASTER_04_RED_TO_GREEN.md` (`000ee2a`, `5ab87f3`).

---

## 8) Security-critical change summary (vs `main`, stacked)

High-signal modules introduced or substantially extended on the stack (not exhaustive):

1. **Vector isolation** — `orca/vectorstore/{server,client,host,protocol}.py`: AF_UNIX owner process, serving lock participation with restore.
2. **Backup consistency / crypto** — `orca/serve/backup.py`, `backup_crypto.py`, `datadir_lock.py`, deletion ledger; quiesce / inconsistent-flag fail-closed.
3. **Account security** — API-key fresh reauth (B3), TOTP clock discipline, middleware/token hardening.
4. **Authz locks** — training/corpus/GPU/spend remain NOT_AUTHORIZED; capability truth honest unavailable states.
5. **Packaging** — public image does **not** install `memory`/`backup` extras; enabling them is founder-scoped (M04-B11).
6. **Documented residual risk** — same-UID socket token boundary (M04-B10); not claimed as multi-tenant OS isolation.

Physical / forensic erasure of deleted customer bytes is **not** claimed (Antigravity errata).

---

## 9) Remaining founder decisions (unauthorized until explicit auth)

From `MASTER_04_FOUNDER_BLOCKERS.md` + this review — still **BLOCKED / unauthorized**:

1. Protected branch merge of #145 / #146 / #148 (any order) to `main`
2. Marking draft PRs ready / requesting merge
3. Production vector backend enablement
4. Baking Chroma into the public production image
5. Key custody model for backup keys
6. Retention policy decisions
7. Off-host deletion-history anchor
8. Postgres dump integration
9. Multi-host / NFS lock reliability acceptance
10. Paid infrastructure / launch authorization
11. Training authorization / freeze / corpus / Crown / GPU spend
12. Formal acceptance promotion above **0/95**
13. Release tags / production deploy / customer data exposure

---

## 10) Production restrictions & rollback limits

### Production restrictions (current truth)

- Slim prod image: relational path only (`.[postgres]`); vector owner / encrypted backup tooling require explicit extras.
- No training, no GPU, no native GENESIS/NOVUS/AETERNUM weights.
- Draft stack must remain draft until founder says otherwise.
- Independent qual lives on Antigravity branch — not a substitute for merge approval.

### Rollback limits (if a future authorized merge ever occurs)

- Stack is ~642 files / +100k lines vs current `main`: rollback is a **full stack revert**, not a surgical MASTER-04-only undo, unless founder merges in staged order with intermediate tags (not present today).
- Encrypted backup archives and deletion ledgers created post-deploy are **not** automatically reversible by git revert; operational recovery depends on key custody and ledger policy (both founder-owned, currently undecided).
- Vector collections / Chroma state are outside git; code rollback does not erase on-disk vector data.
- This review created **no** merge commit on `main`; there is nothing to roll back from this Path B package itself.

---

## 11) Explicit engineering GO / NO-GO matrix (CTO review)

| Question | Answer |
|---|---|
| Is Path B Antigravity FINAL evidence closed on bound SHAs? | **YES** — `83978d4` / disposition LIMITED-SCOPE EVIDENCE CLOSED |
| Is stacked ancestry main→145→146→148 valid? | **YES** |
| Are F02/F03/Landmark/B3/B6 history markers preserved? | **YES** |
| Are draft PRs still draft / not against unauthorized main mutation of candidates? | **YES** (#148 bases on #146 branch) |
| Is isolated merge onto current `main` conflict-free? | **YES** (sim discarded) |
| Does that authorize merge? | **NO** |
| Formal acceptance 0/95 + training NOT_AUTHORIZED? | **YES** (invariants hold) |
| Confirmed P0/P1 blocking defects for Path A? | **NONE** per Antigravity |
| Residual documented risks requiring founder awareness? | **YES** — B10, B11; B12 HOLD |
| **Authorize protected merge to `main`?** | **NO-GO — FOUNDER DECISION REQUIRED** |

---

## 12) What this agent did / did not do

**Did:** refresh refs; verify ancestry; reconcile draft/CI/governance signals; isolated worktree merge sims (discarded); verify acceptance/model truth; publish this review on a **separate docs-only** draft branch; mirror to Project store.

**Did not:** merge #145/#146/#148; push to `main`; create release tags; rewrite ancestry; mark drafts ready; deploy; train; spend; promote formal acceptance; claim production readiness.

---

## 13) Cross-links

| Artifact | Location |
|---|---|
| This review (repo) | `docs/orneur/milestones/master-04/ORNEUR_MASTER04_PROTECTED_MERGE_READINESS_REVIEW.md` |
| Store mirror | `/cursor/stores/self/docs/master-04/ORNEUR_MASTER04_PROTECTED_MERGE_READINESS_REVIEW.md` |
| Antigravity verdict status | `/cursor/stores/self/docs/master-04/ANTIGRAVITY_VERDICT_STATUS.md` |
| Independent qual report | tip `83978d4` path above |
| Prior MASTER-04 eng package | `docs/orneur/milestones/master-04/MASTER_04_*.md` + store `docs/master-04/` |
| MASTER-03 / MASTER-02 context | store `docs/master-03/`, `docs/master-02/` |

---

**Signed (engineering assessment only):** Cursor — MASTER-04 Path B Protected Merge Readiness Package  
**Requires:** CTO / founder explicit decision before any protected merge or production/training action.
