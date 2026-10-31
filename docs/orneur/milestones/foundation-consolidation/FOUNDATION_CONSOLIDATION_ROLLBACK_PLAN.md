# FOUNDATION CONSOLIDATION — Rollback Plan

```
STATUS: PREFLIGHT — PLAN ONLY; NOTHING TO ROLL BACK ON MAIN TODAY
git ≠ data
```

**Phase H:** INACTIVE. This document plans *hypothetical* post-merge recovery. It does **not** authorize merge or deploy.

---

## 1) Current state (no merge performed)

| Fact | Value |
|---|---|
| `origin/main` | `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` (unchanged by this preflight) |
| Candidate PRs | #145 / #146 / #148 remain **draft**, unmerged |
| Tags from this work | **none** |
| Production deploy | **none** |

**There is nothing to roll back on `main` from Phases A–G.**

---

## 2) Git rollback options (if Phase H ever lands the stack)

| Strategy | When usable | Limits |
|---|---|---|
| Revert merge commit(s) | If founder used `--no-ff` merge(s) onto `main` | Reverts code tree; does **not** erase runtime data |
| Reset / force-push `main` | Only with explicit founder + protection bypass authority | **Forbidden** in this programme without separate auth; rewrite risk |
| Staged reverse merges | If stack landed as `main←145←146←148` with intermediate tags | Intermediate tags **do not exist today** — full-stack revert is the default |
| Leave drafts closed / unmerged | Pre-Phase-H | Preferred control: simply **do not merge** |

Stack size vs current `main`: ~**642 files**, **+101387 / −941**. Rollback is a **full stack** operation, not a surgical MASTER-04-only undo, unless founder merges in staged tagged order (not present).

---

## 3) Data plane ≠ git (critical)

| Data class | Git revert restores? | Notes |
|---|---|---|
| Encrypted backup archives | **No** | Requires key custody (founder-owned; undecided) |
| Deletion ledgers | **No** | Policy/retention founder-owned |
| Vector / Chroma collections on disk | **No** | Outside git; code rollback leaves collections |
| Postgres customer data | **No** | Dump/restore is operational, not git |
| Serving locks / owner sockets | **No** | Runtime artifacts |

**Rule: `git ≠ data`.** Any post-deploy recovery plan must cover key custody, ledger retention, vector store lifecycle, and DB restore independently of git history.

---

## 4) Recommended pre-Phase-H controls (when founder authorizes later)

1. Confirm explicit Phase H authorization text (scope: which PRs, merge method, no deploy unless separately authorized).  
2. Prefer merge commits preserving attribution (see ATTRIBUTION_REVIEW).  
3. Tag pre-merge `main` and post-merge tip **only if founder authorizes tags** (currently **not** authorized by this preflight).  
4. Do **not** enable production vector backend / bake Chroma or backup crypto into public image without separate founder decisions.  
5. Keep TRAINING_AUTHORIZATION **NOT_AUTHORIZED** and formal acceptance **0/95** unless separately authorized.

---

## 5) Immediate rollback for this preflight package

| Artifact | Rollback |
|---|---|
| Local dry-run worktrees | Already discarded |
| Docs draft branch / PR for this package | Close PR / delete branch if founder rejects docs package (optional) |
| Project store docs | Leave as audit trail or archive per coordinator |

No production impact from Phases A–G.
