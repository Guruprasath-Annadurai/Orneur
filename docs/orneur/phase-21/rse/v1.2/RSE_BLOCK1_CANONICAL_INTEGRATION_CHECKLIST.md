# RSE block 1 — canonical integration checklist

NON_NORMATIVE. Not in Manifest V3. This checklist does not merge PR #8 and does not modify canonical main `464b602f3f259b56f139c3304828baa660e6b860`. Owner ratification has not occurred.

Accepted implementation identity, which this documentation commit does not replace:

| Item | Value |
| --- | --- |
| PR | #8, branch `cursor/rse-master-imp2-imp4-c04e` |
| Accepted SHA | `da567d927b61c41e253b42732aad249b5fdbb104` |
| Parent | `53de28d647038bdeb0509d5640828beb57a1bec1` |
| Exact-SHA push CI | `37884389862`, event `push`, conclusion success |
| Independent verdict | `RSE_MASTER_BLOCK_1_ACCEPTED` |
| Software gates | `IMP_2_ACCEPTED_FOR_SOFTWARE_GATE`, `IMP_3_ACCEPTED_FOR_SOFTWARE_GATE`, `IMP_4_ACCEPTED_FOR_SOFTWARE_GATE` |

If any byte of that tree changes after Claude's acceptance, the new SHA needs its own tests and its own push CI. Run `37884389862` does not certify the new SHA. A documentation commit stacked on `da567d9` is not a new implementation candidate and is not a re-audit of B-1, B-2, or B-3. Do not retarget "accepted SHA" at the documentation commit.

## Checklist

| # | Prerequisite | Status on this preparation pass |
| --- | --- | --- |
| 1 | Accepted candidate SHA recorded and unchanged | Met for `da567d9`. Do not move it in order to land these notes. |
| 2 | Independent Claude acceptance recorded | Met as an external verdict on that SHA. This repository does not contain Claude's private working notes. The verdict strings above are the product record of that acceptance. B-1, B-2, and B-3 stay closed unless new evidence appears. |
| 3 | Six push-CI jobs on that SHA | Met. Run `37884389862`: Deterministic Unit Tests, Training Math Unit Tests (Torch), Production Container Build + Boot Smoke, Genesis V2 Security, Genesis V2 Sandbox, Dependency Vulnerability Scan. The scan job is informational and base-install only. |
| 4 | Pull-request run not used as the exact-SHA proof | Met as a rule. Run `37884393043` is the pull_request event and is not the proof. |
| 5 | Manifest V3 32/32 | Met on the accepted tree at preparation time (`32 ok 0 bad` against `RSE_ARCH_1_2_FREEZE_MANIFEST_V3.txt`). These ratification files are not manifest rows. Re-check after any future commit that touches `docs/orneur/phase-21/rse/`. |
| 6 | IMP-1 regressions preserved | Met on the accepted tree: `tests/rse/test_imp1r_final.py` is in the 103 passed `tests/rse` run. IMP-1 modules were not edited for B-1, B-2, or B-3. Re-run on any new SHA. |
| 7 | Authorization locks still denied | Met. `prove_authorization_locks` remains in the suite. Lock JSON files were not edited. Re-check the diff of any integration commit for `CORPUS_GENERATION_AUTHORIZATION.json`, `MODEL_EVAL_AUTHORIZATION.json`, and `QUALIFICATION_RUNNER_REGISTRY.json`. |
| 8 | Protected benchmarks unchanged | Required at integration time. This preparation did not read or edit benchmark bodies. The integration diff must show no benchmark path changes. |
| 9 | Owner ratification of OMJ1, OFJ1 v2, OBS1 v2, OCJ1, ORJ1 v2 | Approved for synthetic software-gate use. Non-normative. Not in Manifest V3. Record: `RSE_BLOCK1_OWNER_APPROVAL_RECORD.md` Approval 1. Caps are synthetic-stage limits. |
| 10 | Owner decision on OCK1 and OCH1 domains | Conditions met. Addendum records the implemented domains. `records.py` and Manifest V3 are not edited. |
| 11 | Owner decision on cross-role quarantine and class K | Deferred by Approval 3. Stays unimplemented and fail-closed. |
| 12 | Documentation of the accepted behavior | Met for the software record on `da567d9`, plus this package and the approval record. Evidence files from `da567d9` are not rewritten. |
| 13 | Dependency and scan corrections | Applied on the successor, not on `da567d9`. Hash lock `requirements/rse.txt`. Separate audit job. Base scan still does not cover pyhpke. Successor CI is required and is not run `37884389862`. |
| 14 | `cursor/**` workflow policy | Approved to keep, push only. No new permissions. Six original jobs unchanged. |
| 15 | Candidate integrity | `da567d9` is the reviewed tree. A later integration commit must name its parent. If the parent is not `da567d9`, publish the full diff and retest. |
| 16 | Independent delta review | Required if the integration diff is not empty relative to `da567d9`. A docs-only delta needs a documentation review. It does not reopen B-1, B-2, or B-3. An implementation delta needs a new independent pass on the new SHA. |
| 17 | Post-integration exact-main CI | Not started. After a future merge to `464b602` or its successor, the proof is a new push run on `main` whose `headSha` is the merge commit. Do not cite `37884389862` as that proof. |
| 18 | IMP-5 and IMP-6 | Not authorized. Not started. |
| 19 | Enterprise residuals | Recorded, not closed. `RSE_BLOCK1_ENTERPRISE_RESIDUAL_RISK_REGISTER.md`. They do not by themselves reopen the software gate. They do block a secure-environment claim. |

## Integration sequence

Do not merge under the governance-closure instruction. After a separate merge authorization, use this order so the stacked documentation is not applied twice and `da567d9` stays an ancestor:

1. Merge PR #8 into `main`. The accepted implementation commit is `da567d9`. Proof is a new push run on `main`, not run `37884389862`.
2. PR #9's base is the PR #8 branch, and its only commit is `c127780` (parent `da567d9`). After step 1, retarget PR #9 onto `main` and merge that documentation commit. Do not squash it into a second copy of the implementation.
3. The governance-closure branch is parented on `c127780`. After step 2, retarget that pull request onto `main` and merge it. Its head is the combined tree. Proof is another new push run on `main`. Branch CI is not that proof.
4. Claude's delta review must accept the combined head before step 3. Row 11 stays deferred and fail-closed. Rows 9 and 10 are satisfied only as recorded above: profiles are non-normative, and the signature addendum is not a Manifest V3 edit.

## Integration commit rules

1. Row 11 may remain an open ACR. It must remain fail-closed in the code.
2. Do not edit hashed normative files to make the profiles or the signature addendum official.
3. Do not modify Docker, WhitePact, or protected benchmarks in the integration diff.
4. Re-run `tests/rse`, the lock proof, and the manifest check on the SHA that will be merged. Then wait for that SHA's push CI, including the RSE dependency audit.

## Current gate

Owner decisions 1 through 5 are recorded. Canonical integration is not done. It waits on exact-SHA CI of the successor, Claude's delta review, and a separate merge authorization. The software gate on `da567d9` remains the accepted implementation identity.
