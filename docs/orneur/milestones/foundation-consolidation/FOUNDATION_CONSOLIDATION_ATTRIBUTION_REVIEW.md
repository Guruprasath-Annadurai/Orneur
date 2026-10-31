# FOUNDATION CONSOLIDATION — Attribution Review

```
STATUS: PREFLIGHT — NO SILENT REWRITE; PRESERVE AUTHORS / CO-AUTHORS
```

**Range:** `main` `20a8546…` .. #148 `da699a0…` (**265** commits)  
**Policy:** No history rewrite; no author scrubbing; no silent re-authoring in Phase H if/when authorized.

---

## 1) Author inventory (commit `Author:`)

| Author | Email | Commits in range |
|---|---|---|
| Cursor Agent | `cursoragent@cursor.com` | **108** |
| Guruprasath-Annadurai | `192743778+Guruprasath-Annadurai@users.noreply.github.com` | **83** |
| Techezz Infos | `Techezzinfos@gmail.com` | **74** |

Unique author emails: exactly the three above.

---

## 2) Co-authored-by trailers

| Trailer identity | Approx. commits carrying trailer |
|---|---|
| `techezzinfos <techezzinfos@gmail.com>` | **25** (includes stack merge/docs tips such as F02/F03/B3/B6/L03/M03/M04 tips) |
| `Claude Sonnet 5.5 <noreply@anthropic.com>` | **130** (Landmark / genesis lineage commits) |

Case variants (`Co-authored-by` / `Co-Authored-By`) both present; treat as the same attribution class.

---

## 3) Techezz / founder-adjacent attribution

- **74** commits authored as `Techezz Infos <Techezzinfos@gmail.com>` (genesis audit/hardening lineage preserved through stack merges).
- **25** commits carry explicit `Co-authored-by: techezzinfos <techezzinfos@gmail.com>` on Cursor Agent / integration commits (including #145/#146/#148 tip docs and merge markers).
- Email casing differs (`Techezzinfos@gmail.com` vs `techezzinfos@gmail.com`) but is the same mailbox identity for attribution purposes.
- **Do not** squash/rebase in a way that drops these authors or trailers without explicit founder-directed rewrite policy (currently **forbidden** by this preflight).

---

## 4) Merge-marker commits (must remain reachable)

Preserve as first-class history if Phase H ever uses merge commits (preferred for attribution fidelity over squash-to-main of the whole stack):

- F02 `25b794a…`, F03 `d064b67…`, L02-B3 `7fb78a3…`, L02-B6 `34b6688…`, L03→M03 `4295550…`

A single squash of 265 commits onto `main` would **destroy** intermediate attribution and marker SHAs — **discouraged** unless founder explicitly accepts attribution loss (out of scope; rewrite prohibited in this preflight).

---

## 5) Preflight actions taken / not taken

| Action | Status |
|---|---|
| Inventory authors / Co-authored-by | **Done** |
| Rewrite / filter-branch / force-push candidates | **Not done** |
| Amend tip commits on #145/#146/#148 | **Not done** |
| Silent re-author of docs PR commits | **Not done** |

**Recommendation for any future Phase H:** prefer merge commits (or FF of the existing DAG) so author and Co-authored-by metadata remain intact; forbid silent history rewrite.
