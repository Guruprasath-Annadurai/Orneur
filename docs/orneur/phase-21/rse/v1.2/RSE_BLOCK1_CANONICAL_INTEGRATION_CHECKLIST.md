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
| 9 | Owner ratification of OMJ1, OFJ1 v2, OBS1 v2, OCJ1, ORJ1 v2 | Open. Package: `RSE_BLOCK1_OWNER_RATIFICATION_PACKAGE.md`. Classification: non-normative profiles. Not signed. |
| 10 | Owner decision on OCK1 and OCH1 domains | Open. `RSE_BLOCK1_ARCHITECTURE_CHANGE_REQUESTS.md` ACR-B1-1. No code change until the owner chooses. The recommended choice does not change signed bytes. |
| 11 | Owner decision on cross-role quarantine and class K | Open. ACR-B1-2. Stays unimplemented and fail-closed. Not required to describe the software gate. Required before any later implementation. |
| 12 | Documentation of the accepted behavior | Met for the software record in `RSE_MASTER_BLOCK_1_EVIDENCE.md` and `RSE_MASTER_BLOCK_1_TRACEABILITY.md` on `da567d9`, plus this package. Those evidence files are non-normative. |
| 13 | Dependency and scan corrections | Open. Proposed patch only, in `RSE_BLOCK1_DEPENDENCY_AND_WORKFLOW_REVIEW.md`. Not applied. Base scan does not cover `.[rse]`. |
| 14 | `cursor/**` workflow policy | Disclosed and recommended to keep until replaced. Not owner-signed. The workflow file on `da567d9` was not edited for this package. |
| 15 | Candidate integrity | `da567d9` is the reviewed tree. A later integration commit must name its parent. If the parent is not `da567d9`, publish the full diff and retest. |
| 16 | Independent delta review | Required if the integration diff is not empty relative to `da567d9`. A docs-only delta needs a documentation review. It does not reopen B-1, B-2, or B-3. An implementation delta needs a new independent pass on the new SHA. |
| 17 | Post-integration exact-main CI | Not started. After a future merge to `464b602` or its successor, the proof is a new push run on `main` whose `headSha` is the merge commit. Do not cite `37884389862` as that proof. |
| 18 | IMP-5 and IMP-6 | Not authorized. Not started. |
| 19 | Enterprise residuals | Recorded, not closed. `RSE_BLOCK1_ENTERPRISE_RESIDUAL_RISK_REGISTER.md`. They do not by themselves reopen the software gate. They do block a secure-environment claim. |

## Integration commit rules

1. Do not merge while rows 9 and 10 are unsigned, unless the owner explicitly integrates with those items still marked unratified. Row 11 may remain an open ACR. It must remain fail-closed in the code.
2. Do not edit hashed normative files to "make the profiles official."
3. Do not apply the dependency patch in the same commit as a paperwork-only merge unless the owner authorized that patch and a new push CI is planned.
4. Do not modify Docker, WhitePact, or protected benchmarks in the integration diff.
5. Re-run `tests/rse`, the lock proof, and the manifest check on the SHA that will be merged. Then wait for that SHA's six-job push CI.

## Current gate

Canonical integration is blocked on the open owner rows above. The software gate on `da567d9` is the accepted input to that decision. It is not the merge.
