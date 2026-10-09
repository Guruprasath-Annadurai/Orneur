# ORNEUR Master Execution and Acceptance Register

NON_NORMATIVE. Not in Manifest V3. Does not amend RSE-ARCH-1.2. Does not authorize provisioning, purchase, secrets, corpus generation, qualification, model selection, GPU, spend, or training. Does not merge any pull request.

This file remediates the register at `de7188d76a8db633886812277272c8e51080e11e`. The three Phase 0 notes on PR #14 stay as they are. Author disposition of this remediation: READY_FOR_INDEPENDENT_RETEST. That disposition is not readiness acceptance.

## Events

Three sequential events stay distinct.

1. `PRETRAINING_READINESS_ACCEPTED` is FINAL-1. It is a worksheet over the pre-training inventory. Founder training permission is not one of its inputs.
2. `FOUNDER_AUTHORIZATION_GRANTED` is FINAL-2. It depends only on FINAL-1. It names the SHA, dataset manifest, foundation revision, research-only scope, spend cap, and GPU permission.
3. `TRAINING_EXECUTION_ALLOWED` is EXEC-1. It depends only on FINAL-2. It is the start record. The locks have to agree with FINAL-2.

Intermediate founder acts sit inside readiness because later evidence needs them: purchase, provisioning, corpus grant, budget, research-only scope, model selection, runner authorization, and the class-K decision. Each of those rows says intermediate. None of them is FINAL-2.

## Counting

The published status column is an observation. It is not an acceptance bit. `pass_rule` is `OWN_EVIDENCE` on every row. Aliases and covered rows are identifiable and add nothing to a denominator. A predecessor becoming complete leaves every dependent unchanged.

Pre-training denominator size: 95. Numerator: 0. Application denominator size: 3. Post-training launch denominator size: 1. Execution denominator size: 2.

No pre-training percentage is published. R65 is `NOT_VERIFIABLE` and stands for an unmapped set. G1 and AUTH-1 are also `NOT_VERIFIABLE`. When a founder-approved source of the 65 rules exists, R65 is replaced by one child row per rule and the denominator changes. Until then the child rules are absent on purpose.

## Future acceptance

A later row can advance only through `scripts/acceptance/acceptance_engine.py`. The engine reads a ledger that is separate from this register. Each record must carry a detached signature over the requirement id, evidence key, artifact class, artifact digest, git SHA, denominator, and reviewer role. The committed ledger `docs/orneur/acceptance/acceptance_ledger.json` is empty. The committed trust store `docs/orneur/acceptance/reviewer_trust.json` has no keys. This publication therefore accepts nothing and authorizes nothing.

Editing a status cell, the Markdown, or the graph JSON does not accept a row. `--check` rejects a status of ACCEPTED and rejects a non-empty committed ledger or trust store. The engine ignores the published status field. A signature fails closed when it is missing, forged, duplicated, stale, aimed at the wrong requirement, reused for another control, signed by the implementer, signed by an unnamed reviewer, outside that row's denominator, or presented before a counted predecessor has its own accepted record. FINAL-2 stays after FINAL-1. EXEC-1 stays after FINAL-2. R65 cannot be signed into acceptance while it is the unmapped placeholder. FINAL-1 fails while any counted pre-training row, including R65, lacks its own acceptance.

## Protected corpus

Five counted artifacts stay separate. G8 is only the founder corpus-generation grant. DATA-3 is creation of the protected corpus. DATA-1 is the provenance manifest bound to that creation digest. DATA-5 is independent custody and integrity. DATA-2 is contamination and holdout separation. The grant does not pass DATA-3, DATA-1, DATA-5, or DATA-2, and it does not imply that a corpus exists. The small documented dataset note is not the protected corpus.

## Roles

Cursor implements RSE software and drafts this register. Claude reviews Cursor's RSE software and is the author of the application PRs and the Docker lab, so Claude does not review those. Antigravity is the proposed independent retester for application and Docker work. Product Management checks programme records and founder-record completeness. The founder, Guruprasath Annadurai, is the only role that can approve purchase, provisioning, corpus, scope, selection, budget, and the later training authorization. Founder approval is a separate column from implementation and from review.

`UNRESOLVED_EXTERNAL` means the person is not one of those roles yet. The escalation cell says what the founder or Product Management must name. This register does not hire them.

## Evidence vocabulary

`SOURCE_VERIFIED` means a file in this checkout was read. `SHA_CI_PASSED` means a push run for that exact SHA succeeded. `PULL_REQUEST_CI_PASSED` is a pull-request run and is not exact-SHA proof. `CI_IN_PROGRESS` means the push run had not finished at the check. `SHA_CI_PASSED_ON_ANCESTOR` does not cover the live head. `EXTERNALLY_REPORTED` means Product Management pointed at a report that is not in git and not a GitHub review. None of these states is acceptance.

## Repairs

FINAL-1 depends on the pre-training inventory and does not depend on FINAL-2. FINAL-2 depends only on FINAL-1. G12 is the infrastructure record and does not depend on GPU permission. AUTH-2 is an alias of FINAL-2. MODEL-1 depends on the research-scope record and does not depend on the training lock. AUTH-3 is an alias of EXEC-1. The validator rejects any readiness edge into FINAL-2 or EXEC-1.

C27 stays mandatory. DEC-K asks the founder to keep class K deferred, and to keep C27 unmet, until a later architecture-change authorization. DEC-K does not implement class K. Accepting DEC-K does not accept C27.

P1 section 1 rows 1–25 each have an id. Where the objective artifact is already a C row, the hardware id is an alias and the frozen class is copied onto both. Preferred and optional rows stay in the inventory and outside the mandatory denominator. HW-16, the wired-port firmware record, stays separate from C33, the netdev digest. HW-02, TPM presence, stays separate from C24, the release test. HW-FORGE is the Forge serial required by the section 6 P1 definition.

APP-1 and APP-2 are mandatory application work. `orca/train` does not import `orca.serve`, and the first Genesis run is not defined to boot the public assistant. They are outside the pre-training denominator for that reason. SUP-2 is the production assistant image and is classified the same way. MODEL-2C is the commercial-release right and is mandatory for a commercial launch. MODEL-2R is only the research-or-evaluation scope.

## External reports

EV-AG-APP and EV-AG-DOCKER record that Product Management says Antigravity previously retested the application and Docker work. The report text, the tested SHA, and the result are not in this repository. GitHub review counts on those pull requests are 0. Those nodes do not change APP-1, APP-2, SUP-1, or C39.

## Reconciliation

| Item | Value |
| --- | --- |
| Checked | 2026-10-09 |
| main | `464b602f3f259b56f139c3304828baa660e6b860` |
| Reviewed register | `de7188d76a8db633886812277272c8e51080e11e` push run 37972785102 success |
| PR #8 | head `da567d927b61c41e253b42732aad249b5fdbb104` reviews 0 37884389862 push success |
| PR #9 | head `c127780abbe6790cd0ba76beb6755615752af9b2` reviews 0 37889422564 push success |
| PR #10 | head `f424dbf51eb8ed03f5fbe57cbd0ef3c2fa72fcdb` reviews 0 37893124711 push success; 37892311517 push failure sha 518488dbd404cc4b3cac662b30237a93bedba5bf |
| PR #11 | head `6e30dd9f31215f0046a2612653794291ada6688f` reviews 0 37921622633 pull_request success |
| PR #12 | head `348fb882dce86d95b351a932a799a45d09f37940` reviews 0 37973804538 push success sha 348fb882dce86d95b351a932a799a45d09f37940; 37972182734 push success sha 63ece2a5dd673d69a06effdf766d7046f1973fc8 |
| PR #13 | head `0328123361756b9732fc57886754d6d09c4b9c46` reviews 0 37973767347 push success sha 0328123361756b9732fc57886754d6d09c4b9c46; 37973770477 pull_request success sha 0328123361756b9732fc57886754d6d09c4b9c46; 37972786151 push success sha cd95befd196c57d1885be208532a1c9a32991a39 |
| PR #14 | head `55d133c94be65b1d9b843afa3da2f9a2cc4eb701` reviews 0 Three Phase 0 notes. Preserved. This register does not replace them. |
| PR #15 | head `de7188d76a8db633886812277272c8e51080e11e` reviews 0  |

The new publication SHA is the git commit that adds this remediation. Its GitHub CI did not exist when the graph was built. The run above covers only the reviewed SHA.

## Unknowns

- The 65-rule source is absent. R65 has no children.
- G1 has no review artifact.
- AUTH-1 has no budget record.
- Antigravity's report body is not in the repository.
- PR #12 push run 37973804538 and PR #13 push run 37973767347 later completed with conclusion success. GitHub reviews on both pull requests are still 0.
- PR #11 has a pull-request run and no listed push run.
- PR #13's live head is `0328123361756b9732fc57886754d6d09c4b9c46`, which is newer than `cd95befd196c57d1885be208532a1c9a32991a39`.
- Application diffs were not read.
- No hardware, corpus, qualification, or training evidence was created.

## Independent review request

Review this file and `docs/orneur/acceptance/register_graph.json`. Run `python3 scripts/acceptance/validate_register_graph.py --check`.

1. Confirm the graph is acyclic and that no readiness id depends on FINAL-2 or EXEC-1.
2. Confirm every C01–C50 id and every section 1 row 1–25 is present, and that aliases are absent from the pre-training denominator.
3. Confirm PR heads and run ids against GitHub. A later head needs its own push run.
4. Confirm R65 has no invented rule text.
5. Confirm APP-1, APP-2, SUP-2, and MODEL-2C are outside the pre-training denominator for the reasons written on those rows.
6. Confirm EV-AG-APP and EV-AG-DOCKER are not used as acceptance.
7. Confirm the committed acceptance ledger and reviewer trust store are empty.
8. Confirm the acceptance engine rejects a reused artifact, a wrong SHA, a missing reviewer, a self-review, a missing predecessor, a scope mismatch, and FINAL-1 while any counted pre-training row is open.
9. Do not merge. Do not authorize a protected operation.

## Inventory

| ID | Class | Frozen | Denominator | Counts | Status | States | Owner | Reviewer | Founder | Depends | Evidence required | Current evidence | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G1 | MANDATORY | M | PRE_TRAINING | yes | NOT_VERIFIABLE | NONE | UNRESOLVED_EXTERNAL | UNRESOLVED_EXTERNAL | NOT_REQUIRED | - | An architecture review, stored where a later reader can open it, by a person who did not author RSE-ARCH-1.2. | No such review file was found in this pass. | The review is identifiable without a verdict slogan. |
| G2 | MANDATORY | M | PRE_TRAINING | yes | PRESENT_ON_MAIN | SOURCE_VERIFIED | RECORDED_ON_MAIN | PRODUCT_MANAGEMENT | NOT_REQUIRED | G1 | Freeze commit on canonical main, re-checked against Manifest V3 at integration time. | Main is 464b602f3f259b56f139c3304828baa660e6b860. Manifest V3 was not edited. | The integration check still matches the manifest. |
| G3 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G2 | Independent code review of the merged software SHA, plus that SHA's own main push CI. | IMP-2/3/4 code is unmerged on PR #8. PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. RSE_MASTER_BLOCK_1_EVIDENCE.md on that SHA still says independent acceptance is pending. | The merged SHA has its own main push CI and a review that is not a copied slogan. |
| G4 | MANDATORY | M | PRE_TRAINING | yes | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | G3 | A founder purchase authorization and a named hardware selection. | The freeze states nothing is bought. NO_HARDWARE_PURCHASE_AUTHORIZED stands. | The authorization names the machines. This register does not purchase them. |
| G5 | MANDATORY | M | PRE_TRAINING | yes | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | G4 | Provisioning and key-creation authorization, then a ceremony record that contains no secret. | Locks return false. No ceremony record. | A founder act changes the authorization. This register does not create a secret. |
| G6 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G5,C08,C22,C23,C24,C25,C26,C27,C28,C29,C30,C31,C32,C33,C34,C35,C36,C37,C38,C44,HW-01,HW-02,HW-03,HW-06,HW-08,HW-11,HW-16,HW-18,HW-19,HW-20,HW-21,HW-24,HW-FORGE | One acceptance-run record that cites each real-hardware artifact by its own id. The record is not a copy of those artifacts. | Synthetic tests only. No hardware log. | The run record exists. Each cited row still needs its own accepted artifact. |
| G7 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G6 | Custody record for a Crown machine that is not the daily driver, with its own serial. | No Crown inventory. | The Crown serial is recorded and differs from Witness and Forge. |
| G8 | MANDATORY | M | PRE_TRAINING | yes | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | G7 | A founder corpus-generation grant, and nothing else. The grant does not create a corpus and does not carry a corpus digest. | CORPUS_GENERATION_AUTHORIZATION.json status is NOT_AUTHORIZED. No protected corpus exists. | The founder changes that file. This register does not. |
| G9 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G8 | A second Crown milestone: an independent dedicated Crown device, with its own serial, before qualification or training. | Not started. | The second Crown serial is recorded. |
| G10 | MANDATORY | M | PRE_TRAINING | yes | NOT_AUTHORIZED | SOURCE_VERIFIED | CURSOR | CLAUDE | NOT_REQUIRED | G9 | A chamber-design review that names the design SHA and the tests the reviewer ran. | QUALIFICATION_RUNNER_REGISTRY.json state is REGISTERED_NOT_AUTHORIZED. | The reviewer accepts the design record. Runner authorization is QUAL-1, a separate artifact. |
| G11 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G10,P2-1,P2-2,C46,C47 | A P2 gate record that names the environment. Attestation, egress, and counter logs stay on their own rows. | R-EXF in RSE12_06 §5 says egress control blocks training authorization. No environment is named. | The gate record exists. P2-1, P2-2, C46, and C47 remain separately accepted. |
| G12 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | CURSOR | CLAUDE | NOT_REQUIRED | G11,TRAIN-1,TRAIN-2 | A training-infrastructure record: pinned software identity, dry-run log pointer, and the P2 environment id. | training_authorized() returns false. No infrastructure record. | The infrastructure record exists. GPU permission is FINAL-2, after readiness. |
| C01 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Refusal log from the signed registry path showing an unregistered id refused. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C02 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Consumer refusal record for a stale or unknown registry. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C04 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Refusal record for a ceiling above the policy cap. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C05 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Validator output refusing a confusable name. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C09 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Journal record of challenge reuse refused. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C10 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Refusal record showing a set-back clock does not extend a consumed challenge. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C11 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | State log showing no ACTIVE state before a witnessed checkpoint. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C12 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Verify log of a witness cosignature, including a forged ack refused. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C13 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Witness log refusing a fork or a smaller tree. A synthetic fence is not this artifact. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C14 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Refusal record for a bundle that lacks a witnessed result. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C17 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Vector test for enc validity and the zero-shared-secret abort. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C18 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Test log reproducing the RFC 9180 vectors used by this profile. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C19 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Per-case verdicts for missing, duplicate, reordered, extra, truncated, and foreign frames. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C20 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Resolver log refusing an unknown or revoked sender. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C21 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Verify log showing a bad origin signature is rejected before key use. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C45 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Transition log refusing an impossible lifecycle edge. Class K remains a separate decision. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C15 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3,C26 | Journal replay report for a crash at each specified step, including the C26 power-cut report. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C03 | MANDATORY | M | PRE_TRAINING | yes | DESIGNED_ONLY | SOURCE_VERIFIED,SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3,C08 | Verify log of a canonical registry update with two distinct owner tokens. | IMP-1 registry code is on main. Distinct hardware tokens are not issued. PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | The verify log shows two distinct tokens. C08 remains its own row. |
| C06 | MANDATORY | M | PRE_TRAINING | yes | DESIGNED_ONLY | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Rendered-card digest showing the consumer rendered the received signed bytes. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C07 | MANDATORY | M | PRE_TRAINING | yes | DESIGNED_ONLY | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Typed-entry record for the SAS and the Intent Sheet fields. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C08 | MANDATORY | M | PRE_TRAINING | yes | NOT_AUTHORIZED | NONE | FOUNDER | CLAUDE | REQUIRED | G5 | Verify log from two distinct physical tokens. One token used twice is refused. | No tokens issued. REAL_HW cell is tokens. | Two physical tokens produce the log. This row does not create a secret by itself. |
| C16 | MANDATORY | M | PRE_TRAINING | yes | DESIGNED_ONLY | SHA_CI_PASSED | CURSOR | UNRESOLVED_EXTERNAL | NOT_REQUIRED | G3 | A second codec implementation, not Cursor's, agrees on the OCR1 verdict vector. | Freeze maturity is structural codec evidence only. PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | The second implementation's digest matches on the merged SHA. |
| C44 | MANDATORY | M | PRE_TRAINING | yes | NOT_AUTHORIZED | NONE | FOUNDER | CLAUDE | REQUIRED | C08 | Verify log that one token cannot satisfy a two-token class. | No tokens issued. | The single-token refusal is logged on hardware tokens. |
| C22 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G5,HW-02 | Mount and key-state record showing the vault stayed locked through key-absent phase 1. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C23 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G5,HW-01 | Sandbox policy dump from a real checker showing no key, no network, and bounded I/O. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C24 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4,HW-02 | TPM policy test: image PCR and PCR 7 named, wrong PCR denied, wrong PIN denied, altered UKI denied. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C25 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4,HW-03 | TPM NV denial record for an older image, including the counter value. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C26 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4,HW-03 | Per-step power-cut report for the NV update. A simulator report is only the partial credit the freeze allows. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C28 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4,HW-02 | Firmware key list showing only owner Secure Boot keys. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C29 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4,HW-02 | Offline quote record against the pinned attestation key, including measured PCR values. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C30 | MANDATORY | M: IOMMU mandatory when a DMA bus exists; D if such a bus exists and no IOMMU | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Kernel report that IOMMU groups are enforced, or that the named DMA buses are absent. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C31 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Kernel log of USB default-deny with the single allow-listed medium class. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C32 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Enumeration digest showing radios absent or hardware-off. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C33 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4,HW-16 | Measured netdev digest showing no usable network device per link class. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C34 | MANDATORY | M; D if present, network-capable and not disableable | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Platform report for management engine or out-of-band management. A network-capable controller that cannot be disabled disqualifies the machine. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C35 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Firmware settings record: setup password, locked boot order, internal drive only, network boot disabled. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C36 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4,HW-02 | LUKS2 header check. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C37 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G5,HW-01 | Storage scan report, before and after, with a planted marker found by the negative test. | No hardware report for this control. | The artifact named above is accepted on its own. |
| C38 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Crown isolation inventory digest with its own serial. | No hardware report for this control. | The artifact named above is accepted on its own. |
| DEC-K | MANDATORY | M | PRE_TRAINING | yes | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | - | A founder decision that class K recovery stays deferred, and that C27 therefore stays unmet, until a later architecture-change authorization exists. | Approval 3 defers ACR-B1-2. Class K returns UNSUPPORTED_CURRENT_MILESTONE. No implementation is authorized by this row. | The decision is recorded. C27 is still a separate mandatory row. |
| C27 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | UNRESOLVED_EXTERNAL | CLAUDE | REQUIRED | DEC-K,G5,HW-02 | Re-enrolment records for a TPM or board replacement that refuse a lower-generation restore, produced by an authorized class-K path. | Class K is unsupported. No re-enrolment record. | The re-enrolment record exists after class K is authorized elsewhere. A decision record alone does not pass C27. |
| C39 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | CLAUDE | ANTIGRAVITY | NOT_REQUIRED | SUP-1 | Two independent build reports whose digests match, compared on Crown. | No pair of build reports was produced in this pass. | The comparison record is accepted. SUP-1's harness log is not this comparison. |
| C40 | MANDATORY | M | PRE_TRAINING | yes | DESIGNED_ONLY | NONE | CURSOR | CLAUDE | NOT_REQUIRED | C41 | Floor-check log refusing a lower card and a lower sealed floor. | Software floors are not a sealed Crown card. | The floor-check log is accepted together with a sealed floor. C41 remains separate. |
| C41 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | G7 | Signed comparison receipt containing both floor-card serials. | No floor card. | The receipt names both serials. |
| C42 | MANDATORY | M | PRE_TRAINING | yes | DESIGNED_ONLY | NONE | CURSOR | CLAUDE | NOT_REQUIRED | C40 | Refusal log for a recovery kit below the effective floor. | No recovery kit. | The below-floor kit is refused in the log. |
| C43 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | G5 | Epoch checkpoint and LUKS slot rotation record after recovery-media theft response. | No ceremony record. | The epoch record exists and contains no secret. |
| C46 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | CURSOR | CLAUDE | NOT_REQUIRED | G10 | Qualification bit-budget counter log from the chamber. | Not implemented. Table marks P2 and future. | The budget log is accepted. C47 is a separate monotonicity artifact. |
| C47 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G10 | Evidence that restoring qualification state does not refund the budget. The freeze types this UNP. | Not implemented. | The monotonicity evidence is accepted. |
| C48 | MANDATORY | M | PRE_TRAINING | yes | DESIGNED_ONLY | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Refusal records showing a T-complete record cannot authorize W, and W-complete cannot authorize D. | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. | A reviewer accepts this row's own artifact on the merged SHA. |
| C49 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | CURSOR | CLAUDE | REQUIRED | MODEL-1 | Registry entry containing the foundation provenance digests before any use. | No approved foundation entry. model_selection_authorized() returns false. | The registry entry is accepted. The selection record remains MODEL-1. |
| C50 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G7 | A drill measurement of boots, media moves, witness trips, token touches, and typed SAS counts. | Budget numbers exist in the freeze. No drill record. | The measurement is recorded. A sentence that a drill happened is not the measurement. |
| HW-01 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Witness serial recorded on a machine used for nothing else, different from the Crown serial and the Forge serial. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-02 | MANDATORY | D | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | TPM 2.0 capability record for the Witness. Absence disqualifies the machine. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-03 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | TPM NV capability record showing a counter index and policy comparison on NV. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-04 | MANDATORY | M | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Same artifact as C28. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-05 | MANDATORY | M | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Same artifact as C29. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-06 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Measurement record showing the role code and its version inside the measured image. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-07 | MANDATORY | M | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Same artifact as C24. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-08 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Build record of the owner-signed unified kernel image and the boot measurement that matches it. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-09 | MANDATORY | M | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Same artifact as C36. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-10 | MANDATORY | M | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Same artifact as C24. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-11 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G5 | Custody record that a paper recovery passphrase exists, with no secret and no passphrase value in git. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-12 | MANDATORY | M | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Same artifact as C35. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-13 | MANDATORY | M; D if present, network-capable and not disableable | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Same artifact as C34. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-14 | MANDATORY | M: IOMMU mandatory when a DMA bus exists; D if such a bus exists and no IOMMU | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Same artifact as C30. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-15 | MANDATORY | M | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Same artifact as C32. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-16 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Firmware or physical record that the wired port is unused, blocked, or firmware-disabled. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-17 | MANDATORY | M | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Same artifact as C31. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-18 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Update log showing firmware and OS updates came only from the owner-approved offline registry. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-19 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G2 | Registry record of the approved artifacts and the offline distribution used to install them. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-20 | MANDATORY | M (custody) | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Custody record for the Witness location. Seals are HW-20P and do not satisfy this row. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-20P | NONBLOCKING | P (seals) | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Photograph of tamper-evident seals. Preferred only. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-21 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Capacity record for RAM, storage, and CPU against the largest planned bundle and the sandboxed checker. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-22 | NONBLOCKING | P | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | TPM RNG availability note. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-23 | NONBLOCKING | O | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Record of discrete TPM versus firmware TPM. Neither is claimed immune. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-24 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Inventory showing the Witness has no GPU. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-25 | NONBLOCKING | O | NONE | no | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | - | Cold spare serial, if a spare is kept. | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. | The named artifact exists and a reviewer accepts that artifact. |
| HW-FORGE | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G4 | Forge serial different from the Witness serial and the Crown serial. | No Forge inventory. | The Forge serial is recorded. |
| SUP-1 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SHA_CI_PASSED,SHA_CI_PASSED_ON_ANCESTOR | CLAUDE | ANTIGRAVITY | NOT_REQUIRED | G3 | Two independent build digests of the training image, plus the lock used to build them. | PR #13 live head 0328123361756b9732fc57886754d6d09c4b9c46. Push run 37973767347 succeeded for that head. Pull-request run 37973770477 also succeeded and is not the exact-SHA proof. Ancestor cd95befd196c57d1885be208532a1c9a32991a39 push run 37972786151 succeeded. GitHub reviews length 0. A green harness run is not two independent training-image digests. | C39's comparison exists. A harness repair log does not pass C39. |
| SUP-2 | MANDATORY | M | APPLICATION | yes | NOT_ACCEPTED | SOURCE_VERIFIED | CLAUDE | ANTIGRAVITY | NOT_REQUIRED | - | A green exact-SHA production-container job for the application SHA under claim. | The job is in the workflow file. A green run of the register branch does not qualify the application image. | The reviewer names the application SHA and the job log. |
| SUP-3 | MANDATORY | M | PRE_TRAINING | yes | UNMERGED_NOT_ACCEPTED | SHA_CI_PASSED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | Hash-locked install of the RSE extra and a fail-closed audit log of that lock, on the SHA that is merged to main. | On f424dbf51eb8ed03f5fbe57cbd0ef3c2fa72fcdb, push run 37893124711 job RSE dependency lock and vulnerability scan reported no known vulnerabilities for that lock. Not on main. The base job does not include pyhpke. | The same job is green on the merge commit on main. |
| SUP-4 | NONBLOCKING |  | NONE | no | OPEN | SOURCE_VERIFIED | CURSOR | CLAUDE | NOT_REQUIRED | - | A fresh advisory decision. | Disclosed on the base install. chromadb is not in the train extra. diskcache is a base dependency. | A separate advisory decision. |
| P2-1 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G10 | Attestation evidence for a named training environment. No provider is selected by this row. | The freeze marks provider root of trust UNPROVEN. | The attestation package is accepted. |
| P2-2 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | CURSOR | CLAUDE | NOT_REQUIRED | G10 | An egress test showing the training identity cannot open a forbidden path. | Residual text only. | The egress test log is accepted. |
| P2-3 | MANDATORY | M | NONE | no | NOT_STARTED | NONE | CURSOR | CLAUDE | NOT_REQUIRED | - | Covered by C46 and C47. | See those rows. | C46 and C47 each pass on their own artifacts. |
| P2-4 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | CURSOR | CLAUDE | NOT_REQUIRED | G10 | A training-environment test that a spend above the configured cap is refused. The cap value may remain 0. | max_spend_usd is 0. network_provider_inference_allowed is false. gpu_allowed is false. | The refusal test is accepted. Raising the cap is FINAL-2. |
| DATA-1 | MANDATORY | M | PRE_TRAINING | yes | NOT_ACCEPTED | SOURCE_VERIFIED | UNRESOLVED_EXTERNAL | PRODUCT_MANAGEMENT | NOT_REQUIRED | DATA-3 | A provenance manifest listing source, license, and per-record digest, bound to the creation digest from DATA-3. The founder grant is not this manifest. | The qualification note describes a small v1+v2+v3 set and a token proxy. That note is not a protected-corpus manifest and does not authorize training. | The manifest is accepted against the creation digest. G8 does not pass this row. |
| DATA-2 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | CURSOR | CLAUDE | NOT_REQUIRED | DATA-1,DATA-3,DATA-5,QUAL-2 | A contamination and holdout-separation result bound to the creation digest and the holdout fingerprint set, with no item-level leak. The founder grant is not this result. | GENESIS_FRONTIER_HOLDOUT_SPEC.md says zero-contamination is not proven. No protected corpus exists to test. | The oracle output is accepted. G8 does not pass this row. |
| DATA-3 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | UNRESOLVED_EXTERNAL | CLAUDE | NOT_REQUIRED | G8 | A protected-corpus creation record that names the corpus digest and the creating operator. The founder grant is not this record. | No creation record. CORPUS_GENERATION_AUTHORIZATION.json remains NOT_AUTHORIZED and contains no corpus. | The creation record exists. The grant alone leaves this row unmet. |
| DATA-5 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | UNRESOLVED_EXTERNAL | PRODUCT_MANAGEMENT | NOT_REQUIRED | DATA-3 | An independent custody and integrity receipt that re-hashes the protected corpus and names a custodian who is not the creator. The founder grant is not this receipt. | No protected corpus and no custody receipt. | The receipt matches the creation digest. Creation alone does not pass this row. |
| DATA-4 | NONBLOCKING |  | NONE | no | NOT_STARTED | NONE | PRODUCT_MANAGEMENT | CLAUDE | NOT_REQUIRED | - | A published data card. | No trained model and no public card. | The card is published after a model exists. |
| MODEL-0 | NONBLOCKING |  | NONE | no | NOT_A_SELECTION | SOURCE_VERIFIED | RECORDED_ON_MAIN | PRODUCT_MANAGEMENT | NOT_REQUIRED | - | The code pin, read from the file. | base_model unsloth/Qwen2.5-3B-Instruct, revision and tokenizer revision 7548fff1f997f57b2e9e8ab1ec7be96949b00ed0, license_name qwen-research, license_commercial_use RESTRICTED. model_selection_authorized() returns false. | A reader can open the pin. Selection is MODEL-1. |
| MODEL-2R | MANDATORY | M | PRE_TRAINING | yes | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | MODEL-0 | A founder scope record that the first run, when later authorized, is research or evaluation only under the qwen-research terms. | The qualification note quotes a non-commercial research license and says commercial release is blocked. It also says the term does not by itself block research or internal evaluation. No founder scope record exists. This row does not grant either scope. | The research-only scope record exists. Commercial rights remain MODEL-2C. |
| MODEL-1 | MANDATORY | M | PRE_TRAINING | yes | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | MODEL-2R | A founder selection record naming the repository and the exact revision. The code pin is not that record. | The pin in MODEL-0 is present. model_selection_authorized() returns false. | The selection record exists and stays inside the research-only scope. It does not set training_authorized(). |
| MODEL-2C | MANDATORY | M | POST_TRAINING_LAUNCH | yes | BLOCKED_LICENSE | SOURCE_VERIFIED | UNRESOLVED_EXTERNAL | PRODUCT_MANAGEMENT | REQUIRED | - | A commercial grant from the rights holder, or a founder record that no commercial release will be made from this base. | The qualification note says commercial use of this base requires a license from Alibaba Cloud. No grant is in the tree. | The commercial grant or the no-commercial-release record exists. |
| MODEL-3 | MANDATORY | M | NONE | no | NOT_STARTED | NONE | CURSOR | CLAUDE | NOT_REQUIRED | - | Same artifact as C49. | See C49. | C49 passes on its own registry entry. |
| MODEL-4 | NONBLOCKING |  | NONE | no | NOT_A_SELECTION | SOURCE_VERIFIED | RECORDED_ON_MAIN | PRODUCT_MANAGEMENT | NOT_REQUIRED | - | Not a selection. | Other candidates are listed with license notes. The matrix says it is not legal advice and does not authorize a download. | Readers use MODEL-1 for selection. |
| QUAL-1 | MANDATORY | M | PRE_TRAINING | yes | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | G10 | Founder authorization of the qualification runner. The binding note is not that authorization. | State REGISTERED_NOT_AUTHORIZED. runner_class SELF_HOSTED_CPU. os_runtime says the local Mac is the canonical CPU runner. Network policy in the record is none. | The founder changes the runner state. This register does not. |
| QUAL-2 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | CURSOR | CLAUDE | NOT_REQUIRED | QUAL-1,P2-2 | A failed read of the holdout by the training identity. | The paths exist. No isolation proof was run in this pass. | The failed-read log is accepted. |
| QUAL-3 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | PRODUCT_MANAGEMENT | CLAUDE | NOT_REQUIRED | G10 | Numeric thresholds frozen before any candidate result, for every category the policy says is critical and for the categories it leaves unset. | Critical categories are named. Numeric thresholds for the other categories are not set. | The threshold freeze is recorded before a candidate run. |
| QUAL-4 | NONBLOCKING |  | NONE | no | NOT_STARTED | NONE | PRODUCT_MANAGEMENT | CLAUDE | NOT_REQUIRED | - | A report that keeps the holdout out of marketing. | No finished model. | The report exists after a model exists. |
| TRAIN-1 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | CURSOR | CLAUDE | NOT_REQUIRED | G3 | A hash lock of the train extra and one dry-run command pinned to a SHA. | The extra lists version ranges. No hash lock for the train extra was found. uv.lock is not what CI installs. | The lock and the command log name the same SHA. |
| TRAIN-2 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | SOURCE_VERIFIED | CURSOR | CLAUDE | NOT_REQUIRED | TRAIN-1 | A synthetic dry-run log showing corpus, qualification, model-selection, GPU, and training locks still false afterward. | No full-trainer dry-run log is in this pass. | The log shows the locks still false. The run does not flip them. |
| TRAIN-3 | NONBLOCKING |  | NONE | no | HISTORICAL | SOURCE_VERIFIED | RECORDED_ON_MAIN | PRODUCT_MANAGEMENT | NOT_REQUIRED | - | Not used. | Historical notes say no training was started. | Do not cite these notes as DATA-3. |
| AUTH-1 | MANDATORY | M | PRE_TRAINING | yes | NOT_VERIFIABLE | NONE | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | - | A budget record with a number, a currency, and the founder's signature or equivalent. | No budget record found. | The record exists. Until then this row blocks a readiness percentage. |
| APP-1 | MANDATORY | M | APPLICATION | yes | OPEN_PR_UNREVIEWED | PULL_REQUEST_CI_PASSED | CLAUDE | ANTIGRAVITY | NOT_REQUIRED | - | Independent review of head 6e30dd9f31215f0046a2612653794291ada6688f for the streaming and error-leak fix, plus an exact-SHA push CI for that head. | Head unchanged. GitHub reviews length 0. Pull-request run 37921622633 succeeded. No push run was listed. This register did not read the diff. | Antigravity's report names the SHA and is stored as an artifact. A PR-body sentence is not that artifact. |
| APP-2 | MANDATORY | M | APPLICATION | yes | OPEN_PR_UNREVIEWED | SHA_CI_PASSED,SHA_CI_PASSED_ON_ANCESTOR | CLAUDE | ANTIGRAVITY | NOT_REQUIRED | APP-1 | Independent review of the live head for pool bounds, secret logging, and SSE diagnostics, plus that head's push CI. | Live head 348fb882dce86d95b351a932a799a45d09f37940. Push run 37973804538 succeeded for that head. Ancestor 63ece2a5dd673d69a06effdf766d7046f1973fc8 push run 37972182734 succeeded. GitHub reviews length 0. Diff not read. | The retest report names 348fb882 or a later reviewed head. |
| APP-3 | NONBLOCKING |  | NONE | no | NOT_STARTED | SOURCE_VERIFIED | PRODUCT_MANAGEMENT | CLAUDE | NOT_REQUIRED | - | Launch evidence for public claims. | Planning text only. | After a trained model exists. |
| EV-AG-APP | NONBLOCKING |  | NONE | no | EXTERNALLY_REPORTED | EXTERNALLY_REPORTED | ANTIGRAVITY | PRODUCT_MANAGEMENT | NOT_REQUIRED | - | The Antigravity application retest report, including the SHA it tested and the result. | The directive states Antigravity previously retested the application. No report text, tested SHA, or result is in this repository. GitHub reviews on PR #11 and PR #12 have length 0. PR bodies are author narrative and are not this report. | The stored report can be read. Until then APP-1 and APP-2 stay unreviewed. |
| EV-AG-DOCKER | NONBLOCKING |  | NONE | no | EXTERNALLY_REPORTED | EXTERNALLY_REPORTED | ANTIGRAVITY | PRODUCT_MANAGEMENT | NOT_REQUIRED | - | The Antigravity Docker retest report, including the SHA it tested and the result. | The directive states Antigravity previously retested Docker. No report text, tested SHA, or result is in this repository. GitHub reviews on PR #13 have length 0. The PR body is the author's local log, not Antigravity's report. | The stored report can be read. It does not pass SUP-1 or C39. |
| R65 | MANDATORY | M | PRE_TRAINING | yes | NOT_VERIFIABLE | NONE | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | - | The exact source text, founder-approved, then one child row per rule. | No source. No child rule is listed. | Sixty-five child rows replace this placeholder after the source is approved. |
| FINAL-1 | MANDATORY | M | PRE_TRAINING | yes | NOT_STARTED | NONE | CURSOR | PRODUCT_MANAGEMENT | NOT_REQUIRED | 94 pre-training ids, excluding FINAL-1 | An independent recomputation worksheet that lists every counted pre-training id and its own status. | Numerator is 0. G1, AUTH-1, and R65 are NOT_VERIFIABLE. | The worksheet matches a fresh run of the validator. Founder authorization is still FINAL-2. |
| FINAL-2 | MANDATORY | M | EXECUTION | yes | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | FINAL-1 | One founder record naming the SHA, the dataset manifest, the foundation revision, the research-only scope, the spend cap, and the GPU permission. | Not present. gpu_allowed is false. max_spend_usd is 0. training_authorized() returns false. | The record exists after FINAL-1. This register is not that record. |
| EXEC-1 | MANDATORY | M | EXECUTION | yes | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | CLAUDE | REQUIRED | FINAL-2 | A start record, distinct from FINAL-2, showing the locks and the authorization files agree with FINAL-2 and that a run was permitted to start. | model_selection_authorized, qualification_authorized, gpu_authorized, and training_authorized return false. | The start record exists. Editing a lock to return true without FINAL-2 fails this row. |
| AUTH-2 | MANDATORY | M | NONE | no | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | PRODUCT_MANAGEMENT | REQUIRED | - | Same artifact as FINAL-2. | gpu_allowed false. max_spend_usd 0. status NOT_AUTHORIZED. | FINAL-2 carries the GPU and spend permission. |
| AUTH-3 | MANDATORY | M | NONE | no | NOT_AUTHORIZED | SOURCE_VERIFIED | FOUNDER | CLAUDE | REQUIRED | - | Same artifact as EXEC-1. | The three authorization predicates return false. | EXEC-1 checks the locks. |

Source, escalation, rationale, canonical id, and covered-by are in the JSON object for each id.

## Edges

Each edge points from a row to a predecessor. A predecessor completing does not complete the row.

| From | To |
| --- | --- |
| G2 | G1 |
| G3 | G2 |
| G4 | G3 |
| G5 | G4 |
| G6 | G5 |
| G6 | C08 |
| G6 | C22 |
| G6 | C23 |
| G6 | C24 |
| G6 | C25 |
| G6 | C26 |
| G6 | C27 |
| G6 | C28 |
| G6 | C29 |
| G6 | C30 |
| G6 | C31 |
| G6 | C32 |
| G6 | C33 |
| G6 | C34 |
| G6 | C35 |
| G6 | C36 |
| G6 | C37 |
| G6 | C38 |
| G6 | C44 |
| G6 | HW-01 |
| G6 | HW-02 |
| G6 | HW-03 |
| G6 | HW-06 |
| G6 | HW-08 |
| G6 | HW-11 |
| G6 | HW-16 |
| G6 | HW-18 |
| G6 | HW-19 |
| G6 | HW-20 |
| G6 | HW-21 |
| G6 | HW-24 |
| G6 | HW-FORGE |
| G7 | G6 |
| G8 | G7 |
| G9 | G8 |
| G10 | G9 |
| G11 | G10 |
| G11 | P2-1 |
| G11 | P2-2 |
| G11 | C46 |
| G11 | C47 |
| G12 | G11 |
| G12 | TRAIN-1 |
| G12 | TRAIN-2 |
| C01 | G3 |
| C02 | G3 |
| C04 | G3 |
| C05 | G3 |
| C09 | G3 |
| C10 | G3 |
| C11 | G3 |
| C12 | G3 |
| C13 | G3 |
| C14 | G3 |
| C17 | G3 |
| C18 | G3 |
| C19 | G3 |
| C20 | G3 |
| C21 | G3 |
| C45 | G3 |
| C15 | G3 |
| C15 | C26 |
| C03 | G3 |
| C03 | C08 |
| C06 | G3 |
| C07 | G3 |
| C08 | G5 |
| C16 | G3 |
| C44 | C08 |
| C22 | G5 |
| C22 | HW-02 |
| C23 | G5 |
| C23 | HW-01 |
| C24 | G4 |
| C24 | HW-02 |
| C25 | G4 |
| C25 | HW-03 |
| C26 | G4 |
| C26 | HW-03 |
| C28 | G4 |
| C28 | HW-02 |
| C29 | G4 |
| C29 | HW-02 |
| C30 | G4 |
| C31 | G4 |
| C32 | G4 |
| C33 | G4 |
| C33 | HW-16 |
| C34 | G4 |
| C35 | G4 |
| C36 | G4 |
| C36 | HW-02 |
| C37 | G5 |
| C37 | HW-01 |
| C38 | G4 |
| C27 | DEC-K |
| C27 | G5 |
| C27 | HW-02 |
| C39 | SUP-1 |
| C40 | C41 |
| C41 | G7 |
| C42 | C40 |
| C43 | G5 |
| C46 | G10 |
| C47 | G10 |
| C48 | G3 |
| C49 | MODEL-1 |
| C50 | G7 |
| HW-01 | G4 |
| HW-02 | G4 |
| HW-03 | G4 |
| HW-06 | G4 |
| HW-08 | G4 |
| HW-11 | G5 |
| HW-16 | G4 |
| HW-18 | G4 |
| HW-19 | G2 |
| HW-20 | G4 |
| HW-21 | G4 |
| HW-24 | G4 |
| HW-FORGE | G4 |
| SUP-1 | G3 |
| SUP-3 | G3 |
| P2-1 | G10 |
| P2-2 | G10 |
| P2-4 | G10 |
| DATA-1 | DATA-3 |
| DATA-2 | DATA-1 |
| DATA-2 | DATA-3 |
| DATA-2 | DATA-5 |
| DATA-2 | QUAL-2 |
| DATA-3 | G8 |
| DATA-5 | DATA-3 |
| MODEL-2R | MODEL-0 |
| MODEL-1 | MODEL-2R |
| QUAL-1 | G10 |
| QUAL-2 | QUAL-1 |
| QUAL-2 | P2-2 |
| QUAL-3 | G10 |
| TRAIN-1 | G3 |
| TRAIN-2 | TRAIN-1 |
| APP-2 | APP-1 |
| FINAL-2 | FINAL-1 |
| EXEC-1 | FINAL-2 |
| FINAL-1 | each of the other 94 pre-training ids |

