# MASTER-01 — Security and Governance Gaps

Assessment across active streams. **Does not** authorize merge, training, spend, or formal acceptance.

## 1. Formal posture (preserved)

| Control | State on F02/F03 tips + combined candidate |
|---|---|
| Formal acceptance | **0 / 95** |
| Disposition histogram (F02 master report) | `VERIFIED_ENGINEERING=11`, `IMPLEMENTED_UNVERIFIED=17`, `BLOCKED=19`, `NOT_IMPLEMENTED=48` |
| `register_graph.json` C06 / C07 | `DESIGNED_ONLY` (register status); F02 matrix still lists C06/C07 as `NOT_IMPLEMENTED` for counted disposition — F03 engineering is **tracked separately**, not ledger-promoted |
| G2 | Register `PRESENT_ON_MAIN` / matrix `IMPLEMENTED_UNVERIFIED` — **not** OWN_EVIDENCE accepted |
| G3 | `UNMERGED_NOT_ACCEPTED` / `IMPLEMENTED_UNVERIFIED` — independent merged-SHA review missing |
| `TRAINING_AUTHORIZATION.json` | `status=NOT_AUTHORIZED`, `gpu_allowed=false` |
| Training freeze package | `NOT_FROZEN`, `training_authorization=NO-GO` |

**Do not promote C06/C07/G2/G3 or any row from local MASTER-01 evidence alone.**

## 2. Gap classes

### A. Implemented + independently tested (limited scope) — still not formal acceptance

| Item | Evidence | Residual |
|---|---|---|
| F03 C06/C07 software path | Engineering 16+130; Antigravity `75a7a64` limited-scope vs candidate `0fe98e0` | In-memory C06; tautological C07 IntentSheet risk; suite not on #142 tip; authority_usable=False |
| F02 TRAIN-1/2, C01/C02 (and listed VE set) | F02 matrix + Antigravity limited-scope on prior tips | Own-evidence on **merged** SHA still required |
| Per-PR CI greens | #140/#142/#136/#139/#141/#143 author CI | Green ≠ cross-stack / ≠ independent qual |

### B. Implemented — unqualified (engineering only)

| Item | PR | Gap |
|---|---|---|
| L01 B-01 SSE/cancel/integration | #136 | B-02: no independent qualification of exact head |
| L02 trust/reliability bundle | #139 | L02-Q: no independent qualification |
| L02-B3 API-key reauth | #141 | Engineering VERIFIED; no independent qual; residual password+session without 2FA |
| L02 plaintext data-backup (pre-B6) | #139/#141 | Customer data readable in backup directory format (B6 baseline R1–R4 confirmed) |
| F02 IMPLEMENTED_UNVERIFIED rows (C03,C09–C16,C45,G2,G3,…) | #140 | Await second codec / independent review / merge |

### C. Missing / incomplete software

| Item | Notes |
|---|---|
| Histogram `NOT_IMPLEMENTED` = 48 | Includes operator-ceremony rows, many C22–C48, etc. |
| C06/C07 formal OWN_EVIDENCE on merged SHA | Software exists on #142 only |
| Combined-tip CI + independent retest | Never run (candidate local) |
| B3+B6 integrated packaging | Conflict-stopped |

### D. Physical / hardware / class-K

| Item | Notes |
|---|---|
| C08 dual physical tokens | BLOCKED — ceremony / secrets |
| Hardware-trust boundary | BLOCKED_BY_PROTECTED_DECISION (physical) |
| Frontier / GPU compute qualification | Unprovisioned; spend forbidden here |

### E. Founder decisions (cannot be closed by engineering alone)

| Decision | Why blocked |
|---|---|
| Training grant / FINAL-2 | Authorization absent; freeze NOT_FROZEN |
| G8 corpus grant / DATA-3 protected corpus | Not created; readiness blockers |
| Trust anchors / Crown custodian / operators (G5–G7, G9, G11, …) | Founder naming acts |
| DEC-K / C27 architecture | Founder architecture-change authorization |
| Backup key custody + retention/off-host policy | Explicit B6 §6 BLOCKED even if B6 were otherwise ready |
| Whether to accept `--unsafe-without-deletion-history` as allowed disaster path | Founder/ops policy |
| Mainline merge sequencing / which sibling (B3 vs B6) lands first | Integration packaging |
| Paid CI runners with Ollama | L01 B-04 / L02-B1 external |

### F. Post-mainline-only

| Item | Notes |
|---|---|
| Formal row acceptance on merged SHA + main push CI | G3 exit; C06/C07 exit |
| Production deploy / customer data migration | Out of MASTER-01 scope; forbidden here |
| Irreversible offline backup erasure | Impossible in-app; ops after mainline |

## 3. #143 plaintext / bypass posture (must not be integration-ready)

Assignment constraint: **PR #143 has unresolved legacy plaintext backup/restore bypass — NOT independently qualified.**

Measured facts:

1. On L02 without B6, `orca/serve/backup.py` still creates/restores **plaintext** `MANIFEST.json` directories (baseline R1–R4 all confirmed).
2. B6 replaces format with encrypted `orneur-backup/2` and refuses old format create/restore — **engineering claim only**; Antigravity independent qual **not** recorded as done.
3. Remaining bypass / plaintext surfaces even in B6 design: `--unsafe-without-deletion-history`, auth-DB `orca backup` (separate plaintext path), `.pre-restore-*` rollback plaintext, scratch snapshots during create.
4. B3∩B6 merge conflicts prevent casual dual inclusion.

**Classification for #143:** `ENGINEERING_REMEDIATION_REQUIRED` + `REQUIRES_INDEPENDENT_QUALIFICATION` — **never present as integration-ready** in MASTER-01.

## 4. Auth / training fail-closed (combined tip)

- Invalid bearer → 401 path covered by L01 tests (passed on combined tip).
- API-key minting requires fresh password (+ TOTP if enabled) on B3 (passed).
- Training authorization document remains `NOT_AUTHORIZED`; readiness probes passed fail-closed.
- RSE success payloads keep `authority_usable=False` (F03 design).

## 5. Disclosure

Native vs third-party serving facts remain honest on combined tip (`weights_origin=third_party`, native families INTERFACE_ONLY / NOT_AVAILABLE). F02 genesis learning code does not override L02 disclosure in the probed API.
