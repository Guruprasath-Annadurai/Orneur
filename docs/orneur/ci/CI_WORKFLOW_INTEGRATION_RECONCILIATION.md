# CI / integration-dependency report — exact-SHA snapshot

Written while Antigravity's audit of PR #16 is outstanding, as part of the
temporary primary-engineering-lead assignment (Cursor unavailable). Does not
change RSE-ARCH-1.2, Manifest V3, any authorization lock, or any other open
branch's history. Does not merge anything.

## 1. Repository and PR state (checked 2026-10-10)

`main` is at `464b602f3f259b56f139c3304828baa660e6b860`.

| PR | Branch | Base | Head SHA | State |
|---|---|---|---|---|
| #1, #2, #4, #7 | various | — | — | MERGED into `main` already |
| #5 | `orneur-public-branding-main` | `main` | `55733d4d...` | OPEN, draft=false, **mergeable=CONFLICTING** — branding-only, unrelated to RSE/acceptance work |
| #6 | `cursor/rse-gap-characterization-8436` | `main` | `269745dc...` | OPEN, draft — diffs against current `main` show net **deletions** (`tests/rse/test_imp1r_final.py` removed, −7344/+422 lines overall); this branch diverged before several since-merged changes and reads as stale relative to current `main`, not a ready integration candidate |
| #8 | `cursor/rse-master-imp2-imp4-c04e` | `main` | `da567d92...` | OPEN, draft — RSE Block 1 IMP-2/3/4, previously independently audited, ended `RSE_MASTER_BLOCK_1_ACCEPTED` (software gate only) |
| #9 | `cursor/rse-block1-owner-ratification-c04e` | PR #8 branch | `c1277780...` | OPEN, draft — stacked on #8 |
| #10 | `cursor/rse-block1-governance-closure-c04e` | PR #9 branch | `f424dbf5...` | OPEN, draft — stacked on #9; previously reviewed, ended `RSE_BLOCK1_DELTA_REVIEW_ACCEPTED` |
| #11 | `claude/phase-a-assistant-baseline` | `main` | `6e30dd9f...` | OPEN, draft — Phase A application baseline |
| #12 | `claude/phase-a-checkpoint-2` | PR #11 branch | `348fb882...` | OPEN, draft — stacked on #11; CI 7/7 green at this SHA |
| #13 | `docker/rse-synthetic-integration-lab` | `main` | `03281233...` | OPEN, draft — local Docker lab repair; CI 7/7 green at this SHA |
| #14 | `cursor/rse-phase0-register-c04e` | PR #10 branch | `55d133c9...` | OPEN, draft — stacked on #10 |
| #15 | `cursor/orneur-master-acceptance-register-c04e` | PR #14 branch | `3f221a23...` | OPEN, draft — stacked on #14; the branch this handoff started from |
| #16 | `claude/phase0-acceptance-remediation` | PR #15 branch | `ef6e12d3...` | OPEN, draft, **mine, under Antigravity audit — left untouched by this report** |

Stacked chain (each base is the prior branch's head, not `main`):

```
main (464b602)
 └─ PR #8  (da567d9)
     └─ PR #9  (c127780)
         └─ PR #10 (f424dbf)
             └─ PR #14 (55d133c)
                 └─ PR #15 (3f221a2)
                     └─ PR #16 (ef6e12d)   <- awaiting Antigravity, untouched here
```

Independent of that chain, off `main` directly:

```
main (464b602)
 ├─ PR #11 (6e30dd9) ── PR #12 (348fb88)
 ├─ PR #13 (0328123)
 ├─ PR #6  (269745d)   stale, see above
 └─ PR #5  (55733d4)   branding only, conflicting
```

## 2. Overlapping-workflow conflict evidence

`.github/workflows/test.yml` is the only file touched by more than one of
the independent (non-stacked) branches. Three branches each independently
added one push-trigger glob and one trailing job, at the same anchor
points:

| Branch | Trigger glob added | Job added |
|---|---|---|
| PR #12 (`claude/phase-a-checkpoint-2`) | `claude/**` | `sse-diagnostics` |
| PR #13 (`docker/rse-synthetic-integration-lab`) | `docker/**` | `rse-docker-lab` |
| PR #16's chain (`claude/phase0-acceptance-remediation`) | `cursor/**` (inherited from its own base chain) + `claude/**` (added independently) | `rse-dependency-audit` |

Real, reproduced conflict evidence (not just a theoretical risk), via
`git merge-tree --write-tree`, run today:

```
$ git merge-tree --write-tree origin/claude/phase0-acceptance-remediation origin/claude/phase-a-checkpoint-2
CONFLICT (content): Merge conflict in .github/workflows/test.yml

$ git merge-tree --write-tree origin/claude/phase0-acceptance-remediation origin/docker/rse-synthetic-integration-lab
CONFLICT (content): Merge conflict in .github/workflows/test.yml
```

(PR #12 vs PR #13 was already documented as conflicting by both of those
branches' own commit comments; the two checks above confirm PR #16's chain
conflicts with each of them too, for the same reason — three independent
insertions at the same anchor lines.)

The six jobs common to all three (`pytest`, `torch-loss-tests`,
`container-build`, `genesis-v2-security`, `genesis-v2-sandbox`,
`security-audit`) are byte-identical across all three branches (checked via
per-job extraction + checksum) — **this is a textual conflict from
independent insertion, not a semantic disagreement.** A hand reconciliation
carrying all six push globs and all nine jobs is possible without dropping
or altering anything either branch added.

### Reference reconciliation (this change)

`docs/orneur/ci/RECONCILED_TEST_WORKFLOW_PREVIEW.yml` is that hand
reconciliation, built from the exact job bodies on each branch's head SHA
above. It is **not** placed under `.github/workflows/` and will never run as
a live workflow: two of its jobs (`sse-diagnostics`, `rse-docker-lab`)
reference files (`tests/frontend/test_sse_diagnostics.mjs`,
`orca/serve/web/sse_diagnostics.js`, `docker-rse-integration-lab.yml`,
`scripts/rse_docker_lab_verify.sh`) that exist only on PR #12's and PR #13's
branches respectively, not on `main` or this branch — registering it as a
real workflow here would silently fail on every push. It is validated as
real, parseable YAML with the exact expected trigger globs and job names via
`scripts/ci/validate_reconciled_workflow_preview.py` and
`tests/test_ci_workflow_reconciliation.py`.

**Whoever actually integrates PR #12, #13, and the #8→#16 chain onto one
branch must still resolve `.github/workflows/test.yml` as a real git merge
conflict at that point** (this preview is not a patch and is not applied to
any other branch) **and must then observe all nine jobs pass in one real CI
run on the combined tree** — a clean code merge is not evidence the merged
CI config is also correct, per the same standard PR #12/#13 already held
each other to.

## 3. Recommended integration sequence

1. Land PR #8 → #9 → #10 → #14 → #15 in order (each is stacked on the prior
   and has no file-level conflict with anything else in this list except
   the shared tail into PR #16, which is excluded here).
2. **Do not land PR #16 until Antigravity's independent audit returns a
   verdict.** It sits on top of #15 and carries no conflicts with #11/#12/#13.
3. PR #11 → #12 can land independently of the #8–#16 chain (disjoint files:
   `orca/serve/*`, `tests/test_serve_*`, `tests/frontend/*` vs
   `scripts/acceptance/*`, `orca/rse/*`, `docs/orneur/*`).
4. PR #13 can land independently of both of the above (disjoint files:
   `docker/*`, `scripts/rse_docker_lab_verify.sh`).
5. **Whichever of {PR #12, PR #13, the #8–#16 chain} lands last must resolve
   `.github/workflows/test.yml` by hand** (keep all six push globs, all nine
   jobs) **and must get one green CI run on the resulting merged tree**
   before that integration step is considered complete.
6. PR #6 is stale relative to current `main` (large deletions when diffed
   against `464b602`) and PR #5 is already flagged `CONFLICTING` by GitHub
   itself — neither is a ready integration candidate; both need an owner
   decision (rebase-and-resubmit or close) before they factor into sequencing.

## 4. Protected-file invariants (unchanged by this report and by PR #16)

- `RSE-ARCH-1.2`, Manifest V3, Clarification 1 — frozen, not touched by any
  branch in this list.
- `docs/orneur/acceptance/acceptance_ledger.json`,
  `reviewer_trust.json`, `founder_root_keys.json` — all three committed
  empty on PR #16; `validate_register_graph.py --check` enforces the exact
  empty-baseline bytes for all three.
- `docs/orneur/acceptance/register_graph.json` — 95-row pre-training
  inventory, published numerator 0, `R65` `NOT_VERIFIABLE`, `C27` mandatory —
  unchanged by PR #16 (no diff in that file; only the published markdown's
  narrative sentence changed).
- `orca/rse/imp1/locks.py`'s lock order and the `POSTURE` fixed-constant
  gate — not touched by any branch in this list.
- No branch in this list provisions hardware, purchases anything, creates a
  real secret or credential, generates or accesses protected-corpus content,
  authorizes a GPU, or trains a model.

## 5. Next dependency-safe software milestone

This reconciliation itself is the milestone delivered in this change:
**CI-hardening / integration preparation (program scope items 4 and 6)**,
chosen specifically because it:

- does not depend on PR #16's pending Antigravity audit outcome (it is
  pure CI/workflow bookkeeping across *other* branches, and does not modify
  PR #16's own files or SHA at all),
- requires no architecture change, hardware, protected corpus, GPU, or
  founder authorization,
- is independently testable (`tests/test_ci_workflow_reconciliation.py`),
  and
- was already flagged as outstanding, in writing, by two other branches'
  own commit messages (PR #12 and PR #13 each predicted this exact
  conflict) — this closes that loop with real evidence instead of leaving
  it as a prediction.

**Proposed next milestone after this one** (not started in this change,
named here per item 4 of the assignment): the register (`build_nodes()` in
`scripts/acceptance/validate_register_graph.py`) lists a number of
`PRE_TRAINING`, `MANDATORY`, `CURSOR`-owned / `CLAUDE`-reviewed,
`founder_approval: NOT_REQUIRED` software rows still at `status:
NOT_STARTED` or `UNMERGED_NOT_ACCEPTED` that do not depend on PR #16's
acceptance-engine machinery to implement (only to eventually *accept*,
which is a separate, later step). Before starting any of those, the
concrete next action is to enumerate exactly which `C`-series rows qualify
under that filter, since that enumeration itself has not been done in this
session and should not be asserted without reading the current register
output first.

## Verdict

`READY_FOR_INDEPENDENT_RETEST` for this change specifically (the
reconciliation preview and its validator). This is CI/documentation
bookkeeping, not security-relevant software, and does not require the same
adversarial audit depth as PR #16 — but it is still not self-certified:
Antigravity or the founder should confirm the reconciliation plan before
anyone acts on the integration sequence in section 3.
