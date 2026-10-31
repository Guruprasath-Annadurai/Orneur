# FOUNDATION CONSOLIDATION — Branch Protection Reconciliation

```
STATUS: PREFLIGHT — 403 ≠ ABSENT PROTECTION; MAIN TREATED AS FOUNDER-GATED
```

**Phase H:** INACTIVE — no merge, no bypass, no draft→ready conversion.

---

## 1) Observed API facts (refreshed)

| Probe | Result |
|---|---|
| `GET /repos/.../branches/main/protection` | **HTTP 403** — `Resource not accessible by integration` |
| `GET /repos/.../rulesets` | `[]` (empty list for this token) |
| Default branch | `main` @ `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` (unchanged) |
| `allow_merge_commit` / squash / rebase | true / true / true |
| `allow_auto_merge` | **false** |
| `delete_branch_on_merge` | **false** |
| Visibility | public |

---

## 2) Engineering stance (fail-closed)

1. **403 on protection API ≠ absence of protection.** Token scope cannot read admin protection/ruleset detail.
2. Programme governance treats `main` as **protected / founder-gated** regardless of readable JSON.
3. Absence of readable ruleset JSON is **not** authorization to merge, force-push, or bypass checks.
4. This agent did **not** attempt bypass, admin API mutation, or direct push to `main`.

---

## 3) Draft / mergeability surface (candidates)

| PR | Draft | Base | Head SHA | Mergeable (API) | Agent actions |
|---|---|---|---|---|---|
| #145 | **yes** | `main` | `d882740…` | MERGEABLE | none (no ready, no merge) |
| #146 | **yes** | #145 branch | `b96cc32…` | MERGEABLE | none |
| #148 | **yes** | #146 branch | `da699a0…` | MERGEABLE | none |
| #149 | **yes** | `main` | `44e130e…` | MERGEABLE | docs-only; not stack integration |

Stack sequence remains `main → #145 → #146 → #148`. #148 is **not** opened directly against protected `main`.

---

## 4) Governance-sensitive delta vs `main` (why protection matters)

Stacked delta ~642 files / +101387 / −941 includes auth, backup crypto, vector owner, authorization/acceptance ledgers, and CI workflow changes. Landing on `main` without founder authorization would violate Phase H inactivity and programme holds (training NOT_AUTHORIZED; formal 0/95; GENESIS INTERFACE_ONLY; NOVUS/AETERNUM NOT_AVAILABLE).

---

## 5) Explicit non-actions

- No branch-protection bypass  
- No force-push to `main`  
- No merge of #145/#146/#148  
- No marking drafts ready for review  
- No release tags  
- No history rewrite  

**Founder must explicitly authorize Phase H before any protected merge.**
