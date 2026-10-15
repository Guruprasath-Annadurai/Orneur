# RSE Phase 0 — PR #8, #9, and #10 dependency assessment

NON_NORMATIVE. Not in Manifest V3. This assessment does not merge any pull request.

Checked with `gh pr view` and `gh run view` against `Guruprasath-Annadurai/Orneur` on 2026-10-09. Canonical main at that check: `464b602f3f259b56f139c3304828baa660e6b860`.

## Identities

| PR | State | Base | Head | Draft | Merged |
| --- | --- | --- | --- | --- | --- |
| #8 | OPEN | `main` | `da567d927b61c41e253b42732aad249b5fdbb104` on `cursor/rse-master-imp2-imp4-c04e` | yes | no |
| #9 | OPEN | `cursor/rse-master-imp2-imp4-c04e` | `c127780abbe6790cd0ba76beb6755615752af9b2` on `cursor/rse-block1-owner-ratification-c04e` | yes | no |
| #10 | OPEN | `cursor/rse-block1-owner-ratification-c04e` | `f424dbf51eb8ed03f5fbe57cbd0ef3c2fa72fcdb` on `cursor/rse-block1-governance-closure-c04e` | yes | no |

Ancestry, verified by `git log` on the governance branch:

`464b602` (main) → … → `da567d9` (PR #8) → `c127780` (PR #9) → `518488d` → `f424dbf` (PR #10).

FACT: `518488d` is an ancestor of `f424dbf`, not an alternate candidate. Its push run `37892311517` failed Deterministic Unit Tests. It does not certify `f424dbf`.

## What each PR contains

FACT from the commit subjects and the diffs recorded in the owner notes:

- PR #8 is the IMP-2/IMP-3/IMP-4 software implementation, including the B-1/B-2/B-3 fence and quarantine fixes. Exact-SHA push CI: run `37884389862`, event `push`, head `da567d9`, conclusion success. That run is six jobs. It does not include the later RSE dependency-audit job.
- PR #9 is documentation only: the ratification package, architecture-change requests, dependency review, residual-risk register, and integration checklist. It does not change `orca/rse`.
- PR #10 records owner Approvals 1–5 and applies `pyhpke==0.6.5` plus `requirements/rse.txt`. It does not change `orca/rse` implementation modules. Exact-SHA push CI: run `37893124711`, event `push`, head `f424dbf`, conclusion success, seven jobs including `RSE dependency lock and vulnerability scan` (`No known vulnerabilities found` in that job log). Deterministic job on that run: 7105 passed, 342 skipped, 43 deselected. Those skips are the suite's recorded skips, not a claim that RSE tests were skipped.

## Dependency rules

1. Merging PR #8 into `main` does not contain PR #9 or PR #10. The documentation and the pyhpke pin would still be absent.
2. PR #9's base is the PR #8 branch. Merging PR #9 into that branch does not update `main`. After PR #8 is on `main`, PR #9 must be retargeted. Its commit parent is `da567d9`, so it should merge as that one commit, not as a second copy of the implementation.
3. PR #10's base is the PR #9 branch. The combined review tree is `f424dbf`. Landing it on `main` requires PR #8 and PR #9 to be ancestors first, then a retarget. Merging PR #10 into its current base does not reach `main`.
4. A pull-request CI run is a merge ref. It is not exact-SHA evidence. The proof for each head is the push run named above.
5. After any future merge, `main` needs a new push run whose head is the merge commit. Branch CI is not that run.

## Acceptance evidence, separated

FACT: GitHub reviews on PR #8, #9, and #10 are empty (`reviews` length 0). No review decision is set.

FACT: `docs/orneur/phase-21/rse/v1.2/RSE_MASTER_BLOCK_1_EVIDENCE.md` on `da567d9` still lists IMP-2, IMP-3, and IMP-4 as implemented pending independent acceptance. That file was not rewritten by PR #9 or PR #10.

FACT: The strings `RSE_MASTER_BLOCK_1_ACCEPTED` and `IMP_2_ACCEPTED_FOR_SOFTWARE_GATE` (and the IMP-3 and IMP-4 equivalents) appear in the non-normative ratification and approval notes. They were copied from the product-management directive in the engineering session. This repository does not contain a separate auditor-signed report.

ASSUMPTION NOT MADE: Those copied strings are not treated here as a re-readable independent audit artifact. They are a product statement that still needs an independent reviewer who can point at `da567d9` and at `f424dbf` separately. `f424dbf` changed tests, `pyproject.toml`, the workflow, and the lock. Run `37884389862` does not certify it. A delta review of `f424dbf` was requested and is not present as a GitHub review.

FACT: Owner Approvals 1–5 are written in `RSE_BLOCK1_OWNER_APPROVAL_RECORD.md` on PR #10. That file says it records bounded decisions. It is not Manifest V3. The OCK1/OCH1 addendum is not a manifest row. ACR-B1-2 (cross-role quarantine and class K) is deferred and unimplemented.

## What is blocked

- Canonical integration of the three PRs: blocked on a separate merge authorization, on the retarget order above, and on an independent delta review of `f424dbf` that is not yet in GitHub.
- Training, corpus generation, qualification, GPU, and spend: blocked by the lock files and by `RSE12_06` §6–§7. Merging these PRs would not open those locks.
- PR #11, PR #12, and PR #13 are open and are not parents of this stack. This assessment does not verify them. PR #12 head observed as `29f3cad5644ac20dbaf6e19acc7ece67bf882069`. PR #13 head observed as `d21937941e823909a5a8594ffc04e2d45ef30183`.

## Safe next action

Independent delta review of `f424dbf` against `da567d9`, using push run `37893124711` as the CI evidence for that SHA only. Do not merge.
