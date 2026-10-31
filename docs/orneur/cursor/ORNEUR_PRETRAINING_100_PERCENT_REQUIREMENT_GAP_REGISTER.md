# ORNEUR pretraining requirement gap register

The title means every counted pretraining requirement is listed. It does not mean readiness is accepted.

This document is non-normative. It copies fields from `docs/orneur/acceptance/register_graph.json` and records measurements from the acceptance engine. It does not change the denominator, the numerator, the ledger, the policy, or any trust file.

## Baseline measured by regenerating this file

- Branch base SHA: `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`.
- Counted pretraining ids: 95.
- Unique counted ids: 95.
- Graph numerator: 0.
- Published percentage: None.
- Ledger JSON: `[]`.
- `acceptance_engine.evaluate` on that ledger returned `0` accepted ids.
- `assert_published_baseline` returned 0 errors.
- Rows whose register status is ACCEPTED: 0.
- R65 child ids in the graph: 0.
- Class K code point 75 is in `DEFERRED_CLASSES`: True.
- Class K code point is in `SEMANTIC_CLASSES`: False.
- Draft PR #99 GitHub head inspected and not modified: `c395dba09c54f10d626156ed57512dc635f1e9b8`.
- Draft PR #99 body also names `a5d4e1f705e4635848bb44093c4c95f135b0d01b`. That object was not in the fetched repository at inspection, so it is not treated as the audit head.

Authority file hashes at generation:

- `acceptance_ledger.json` `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`
- `register_graph.json` `b8f745182ddb6d4ff25d79a542e5242986901790ee4195186143bfb78039aaf7`
- `ACCEPTANCE_POLICY.md` `58ca980053d0fab1a2185a6294d605890fbba38365183fe0c8ca023a599053d5`
- `BOOTSTRAP_ROOT_KEY.json` `d42a7bb979cf273415d89bf4745a20c30fdc1267c64215ee6f572c877de2e35d`
- `founder_root_keys.json` `8fbbd1eeabbfe88d935ed4854aaca411921cf87e29504bd940442cea70b62353`
- `reviewer_trust.json` `2933ef2d71bf9bcf6ab799124f70c4291013dc271fbdb4502f8b3ee504d10073`
- `TRUST_CHECKPOINT.json` `8811449a0cb5b31ed223b8458f9bfb16dd77384c36d27208157ca0c1096c56db`
- `TRUST_CHECKPOINT_PIN.json` `d8319b7b287884da12445c8e112cda4df205fa7c45902004b375716ba0d640e6`

The engine names three events. None is recorded in the ledger, and this document does not assert that any of them occurred: `PRETRAINING_READINESS_ACCEPTED`, `FOUNDER_AUTHORIZATION_GRANTED`, `TRAINING_EXECUTION_ALLOWED`.

## R65

Source authority, copied from the graph: The founder's canonical 65 rules. No file in this tree contains that set.

Approval dependency: `founder_approval` is REQUIRED. The implementation owner is FOUNDER. The independent reviewer is PRODUCT_MANAGEMENT.

This pass did not find a founder-approved source file and did not construct an expansion proposal. Child rules are absent. R65 remains the unmapped placeholder. The acceptance engine rejects an acceptance record whose id is `R65` or begins with `R65-`.

## G1

Source authority: RSE12_06 §7 step 1 and §8.

Required artifact: an architecture review, stored where a later reader can open it, by a person who did not author RSE-ARCH-1.2.

Register-recorded evidence: no such review file was found. This pass did not name a reviewer and did not add a review. `independent_reviewer` and `implementation_owner` are both `UNRESOLVED_EXTERNAL`.

## DEC-K and C27

DEC-K asks for a founder decision that class K recovery stays deferred and that C27 therefore stays unmet, until a later architecture-change authorization exists. The graph status of DEC-K is `NOT_AUTHORIZED`. Accepting that decision would not accept C27 and would not implement class K.

C27 requires re-enrolment records for a TPM or board replacement that refuse a lower-generation restore, produced by an authorized class-K path. Its dependencies are DEC-K, G5, and HW-02. Its graph status is `NOT_STARTED`.

Measured code: `orca/rse/imp1/profiles.py` places `ord("K")` in `DEFERRED_CLASSES` and keeps `SEMANTIC_CLASSES` to `ord("G")` and `ord("V")`. `orca/rse/imp1/authority.py` raises `UNSUPPORTED_CURRENT_MILESTONE` when a grant class is outside `SEMANTIC_CLASSES`. This pass does not authorize or implement class K.

## Acceptance trust procedure

The committed trust files are empty. `BOOTSTRAP_ROOT_KEY.json` has an empty `public_key_hex`. `founder_root_keys.json` has no roots. `reviewer_trust.json` has no entries. `TRUST_CHECKPOINT.json` has empty hashes and an empty signature. `TRUST_CHECKPOINT_PIN.json` has an empty pin. `PINNED_BOOTSTRAP_ROOT_KEYS` in the acceptance engine is empty, so no caller-supplied bootstrap key can verify a real root state.

Procedure when a real founder later chooses to enroll, without this document creating a key:

1. The founder generates the bootstrap key outside this repository. The private key is not committed.
2. A reviewed change records the public key in `BOOTSTRAP_ROOT_KEY.json` and in `PINNED_BOOTSTRAP_ROOT_KEYS`. Either location alone is not sufficient.
3. The founder signs `founder_root_keys.json` for the exact commit SHA under evaluation.
4. The founder signs `reviewer_trust.json` for that same SHA. Each reviewer key's role must equal the row's `independent_reviewer`, and that role must differ from the row's `implementation_owner`.
5. The founder signs `TRUST_CHECKPOINT.json` over the hashes of that root state and that trust snapshot. The checkpoint hash is pinned in `TRUST_CHECKPOINT_PIN.json` from outside the engine. The engine compares the pin. It does not choose the newest generation.
6. Revocation is a new root state, a new trust snapshot, and a new checkpoint pin bound to the new commit. A snapshot that names an ancestor SHA is stale. A same-commit snapshot whose checkpoint hash does not equal the pin is refused.
7. A signed ledger record still has to present artifact bytes, or a non-disclosing custody signature for a protected corpus class. A signature over a digest is not possession.

This pass performed none of those steps.

## Counted rows

Each row below is copied from the graph. `acceptance_eligibility` is `NOT_ELIGIBLE` because the ledger accepts nothing and the trust anchors are empty. That is a measurement, not a new register status.

### G1

| Field | Value |
|---|---|
| stable_requirement_id | G1 |
| exact_source_authority | RSE12_06 §7 step 1 and §8 |
| intended_technical_meaning | The audit is an input to readiness. It is not the training authorization. |
| register_recorded_evidence | No such review file was found in this pass. |
| required_artifact | An architecture review, stored where a later reader can open it, by a person who did not author RSE-ARCH-1.2. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | UNRESOLVED_EXTERNAL |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | (none) |
| register_status | NOT_VERIFIABLE |
| remaining_blocker | Name a reviewer who did not author RSE-ARCH-1.2, and record where the review is stored. |
| exit_condition | The review is identifiable without a verdict slogan. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_VERIFIABLE; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G2

| Field | Value |
|---|---|
| stable_requirement_id | G2 |
| exact_source_authority | RSE12_06 §7 step 2 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Main is 464b602f3f259b56f139c3304828baa660e6b860. Manifest V3 was not edited. |
| required_artifact | Freeze commit on canonical main, re-checked against Manifest V3 at integration time. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G1 |
| register_status | PRESENT_ON_MAIN |
| remaining_blocker | (empty) |
| exit_condition | The integration check still matches the manifest. |
| engineering_owner | RECORDED_ON_MAIN |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=PRESENT_ON_MAIN; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G3

| Field | Value |
|---|---|
| stable_requirement_id | G3 |
| exact_source_authority | RSE12_06 §7 steps 4 and 5 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | IMP-2/3/4 code is unmerged on PR #8. PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. RSE_MASTER_BLOCK_1_EVIDENCE.md on that SHA still says independent acceptance is pending. |
| required_artifact | Independent code review of the merged software SHA, plus that SHA's own main push CI. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G2 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | The merged SHA has its own main push CI and a review that is not a copied slogan. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G4

| Field | Value |
|---|---|
| stable_requirement_id | G4 |
| exact_source_authority | RSE12_06 §7 step 6 |
| intended_technical_meaning | Intermediate founder act. Purchase is an input to hardware evidence. It is not contingent on full readiness. |
| register_recorded_evidence | The freeze states nothing is bought. NO_HARDWARE_PURCHASE_AUTHORIZED stands. |
| required_artifact | A founder purchase authorization and a named hardware selection. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | G3 |
| register_status | NOT_AUTHORIZED |
| remaining_blocker | (empty) |
| exit_condition | The authorization names the machines. This register does not purchase them. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_AUTHORIZED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G5

| Field | Value |
|---|---|
| stable_requirement_id | G5 |
| exact_source_authority | RSE12_06 §7 step 7 |
| intended_technical_meaning | Intermediate founder act. Key creation is an input to later hardware tests. It is not the training authorization. |
| register_recorded_evidence | Locks return false. No ceremony record. |
| required_artifact | Provisioning and key-creation authorization, then a ceremony record that contains no secret. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | G4 |
| register_status | NOT_AUTHORIZED |
| remaining_blocker | (empty) |
| exit_condition | A founder act changes the authorization. This register does not create a secret. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_AUTHORIZED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G6

| Field | Value |
|---|---|
| stable_requirement_id | G6 |
| exact_source_authority | RSE12_06 §7 step 8 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Synthetic tests only. No hardware log. |
| required_artifact | One acceptance-run record that cites each real-hardware artifact by its own id. The record is not a copy of those artifacts. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G5, C08, C22, C23, C24, C25, C26, C27, C28, C29, C30, C31, C32, C33, C34, C35, C36, C37, C38, C44, HW-01, HW-02, HW-03, HW-06, HW-08, HW-11, HW-16, HW-18, HW-19, HW-20, HW-21, HW-24, HW-FORGE |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator who runs the acceptance. The reviewer is not that operator. Purchase stays on G4. |
| exit_condition | The run record exists. Each cited row still needs its own accepted artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G7

| Field | Value |
|---|---|
| stable_requirement_id | G7 |
| exact_source_authority | RSE12_06 §7 step 9 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No Crown inventory. |
| required_artifact | Custody record for a Crown machine that is not the daily driver, with its own serial. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G6 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the Crown custodian. No purchase is authorized here. Purchase stays on G4. |
| exit_condition | The Crown serial is recorded and differs from Witness and Forge. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G8

| Field | Value |
|---|---|
| stable_requirement_id | G8 |
| exact_source_authority | RSE12_06 §7 step 10; CORPUS_GENERATION_AUTHORIZATION.json |
| intended_technical_meaning | Intermediate founder act. The corpus grant is an input to later data rows. It is not contingent on full training readiness. |
| register_recorded_evidence | CORPUS_GENERATION_AUTHORIZATION.json status is NOT_AUTHORIZED. No protected corpus exists. |
| required_artifact | A founder corpus-generation grant, and nothing else. The grant does not create a corpus and does not carry a corpus digest. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | G7 |
| register_status | NOT_AUTHORIZED |
| remaining_blocker | (empty) |
| exit_condition | The founder changes that file. This register does not. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_AUTHORIZED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G9

| Field | Value |
|---|---|
| stable_requirement_id | G9 |
| exact_source_authority | RSE12_06 §7 step 11 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Not started. |
| required_artifact | A second Crown milestone: an independent dedicated Crown device, with its own serial, before qualification or training. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G8 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the device. This row does not purchase it. Purchase stays on G4. |
| exit_condition | The second Crown serial is recorded. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G10

| Field | Value |
|---|---|
| stable_requirement_id | G10 |
| exact_source_authority | RSE12_06 §7 step 12 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | QUALIFICATION_RUNNER_REGISTRY.json state is REGISTERED_NOT_AUTHORIZED. |
| required_artifact | A chamber-design review that names the design SHA and the tests the reviewer ran. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G9 |
| register_status | NOT_AUTHORIZED |
| remaining_blocker | (empty) |
| exit_condition | The reviewer accepts the design record. Runner authorization is QUAL-1, a separate artifact. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_AUTHORIZED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G11

| Field | Value |
|---|---|
| stable_requirement_id | G11 |
| exact_source_authority | RSE12_06 §7 step 13 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | R-EXF in RSE12_06 §5 says egress control blocks training authorization. No environment is named. |
| required_artifact | A P2 gate record that names the environment. Attestation, egress, and counter logs stay on their own rows. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G10, P2-1, P2-2, C46, C47 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the P2 operator. No provider is selected here. |
| exit_condition | The gate record exists. P2-1, P2-2, C46, and C47 remain separately accepted. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### G12

| Field | Value |
|---|---|
| stable_requirement_id | G12 |
| exact_source_authority | RSE12_06 §7 step 14, infrastructure clause |
| intended_technical_meaning | Technical infrastructure only. GPU and spend permission are contingent on readiness and are not inputs to this row. |
| register_recorded_evidence | training_authorized() returns false. No infrastructure record. |
| required_artifact | A training-infrastructure record: pinned software identity, dry-run log pointer, and the P2 environment id. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G11, TRAIN-1, TRAIN-2 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The infrastructure record exists. GPU permission is FINAL-2, after readiness. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C01

| Field | Value |
|---|---|
| stable_requirement_id | C01 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Refusal log from the signed registry path showing an unregistered id refused. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C02

| Field | Value |
|---|---|
| stable_requirement_id | C02 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Consumer refusal record for a stale or unknown registry. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C04

| Field | Value |
|---|---|
| stable_requirement_id | C04 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Refusal record for a ceiling above the policy cap. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C05

| Field | Value |
|---|---|
| stable_requirement_id | C05 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Validator output refusing a confusable name. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C09

| Field | Value |
|---|---|
| stable_requirement_id | C09 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Journal record of challenge reuse refused. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C10

| Field | Value |
|---|---|
| stable_requirement_id | C10 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Refusal record showing a set-back clock does not extend a consumed challenge. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C11

| Field | Value |
|---|---|
| stable_requirement_id | C11 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | State log showing no ACTIVE state before a witnessed checkpoint. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C12

| Field | Value |
|---|---|
| stable_requirement_id | C12 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Verify log of a witness cosignature, including a forged ack refused. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C13

| Field | Value |
|---|---|
| stable_requirement_id | C13 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Witness log refusing a fork or a smaller tree. A synthetic fence is not this artifact. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C14

| Field | Value |
|---|---|
| stable_requirement_id | C14 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Refusal record for a bundle that lacks a witnessed result. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C17

| Field | Value |
|---|---|
| stable_requirement_id | C17 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Vector test for enc validity and the zero-shared-secret abort. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C18

| Field | Value |
|---|---|
| stable_requirement_id | C18 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Test log reproducing the RFC 9180 vectors used by this profile. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C19

| Field | Value |
|---|---|
| stable_requirement_id | C19 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Per-case verdicts for missing, duplicate, reordered, extra, truncated, and foreign frames. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C20

| Field | Value |
|---|---|
| stable_requirement_id | C20 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Resolver log refusing an unknown or revoked sender. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C21

| Field | Value |
|---|---|
| stable_requirement_id | C21 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Verify log showing a bad origin signature is rejected before key use. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C45

| Field | Value |
|---|---|
| stable_requirement_id | C45 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Transition log refusing an impossible lifecycle edge. Class K remains a separate decision. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C15

| Field | Value |
|---|---|
| stable_requirement_id | C15 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Journal replay report for a crash at each specified step, including the C26 power-cut report. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3, C26 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C03

| Field | Value |
|---|---|
| stable_requirement_id | C03 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | IMP-1 registry code is on main. Distinct hardware tokens are not issued. PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Verify log of a canonical registry update with two distinct owner tokens. |
| test_and_ci_evidence_states | SOURCE_VERIFIED, SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3, C08 |
| register_status | DESIGNED_ONLY |
| remaining_blocker | (empty) |
| exit_condition | The verify log shows two distinct tokens. C08 remains its own row. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=DESIGNED_ONLY; evidence_states=SOURCE_VERIFIED,SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C06

| Field | Value |
|---|---|
| stable_requirement_id | C06 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Rendered-card digest showing the consumer rendered the received signed bytes. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | DESIGNED_ONLY |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=DESIGNED_ONLY; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C07

| Field | Value |
|---|---|
| stable_requirement_id | C07 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Typed-entry record for the SAS and the Intent Sheet fields. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | DESIGNED_ONLY |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=DESIGNED_ONLY; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C08

| Field | Value |
|---|---|
| stable_requirement_id | C08 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | Intermediate token ceremony after G5. It is not the training authorization. |
| register_recorded_evidence | No tokens issued. REAL_HW cell is tokens. |
| required_artifact | Verify log from two distinct physical tokens. One token used twice is refused. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | G5 |
| register_status | NOT_AUTHORIZED |
| remaining_blocker | (empty) |
| exit_condition | Two physical tokens produce the log. This row does not create a secret by itself. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_AUTHORIZED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C16

| Field | Value |
|---|---|
| stable_requirement_id | C16 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Freeze maturity is structural codec evidence only. PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | A second codec implementation, not Cursor's, agrees on the OCR1 verdict vector. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | UNRESOLVED_EXTERNAL |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | DESIGNED_ONLY |
| remaining_blocker | Name a second codec implementer who is not Cursor. |
| exit_condition | The second implementation's digest matches on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=DESIGNED_ONLY; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C44

| Field | Value |
|---|---|
| stable_requirement_id | C44 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | Intermediate token test after C08. The refusal log is its own artifact. It is not the training authorization. |
| register_recorded_evidence | No tokens issued. |
| required_artifact | Verify log that one token cannot satisfy a two-token class. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | C08 |
| register_status | NOT_AUTHORIZED |
| remaining_blocker | (empty) |
| exit_condition | The single-token refusal is logged on hardware tokens. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_AUTHORIZED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C22

| Field | Value |
|---|---|
| stable_requirement_id | C22 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Mount and key-state record showing the vault stayed locked through key-absent phase 1. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G5, HW-02 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C23

| Field | Value |
|---|---|
| stable_requirement_id | C23 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Sandbox policy dump from a real checker showing no key, no network, and bounded I/O. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G5, HW-01 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C24

| Field | Value |
|---|---|
| stable_requirement_id | C24 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | TPM policy test: image PCR and PCR 7 named, wrong PCR denied, wrong PIN denied, altered UKI denied. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4, HW-02 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C25

| Field | Value |
|---|---|
| stable_requirement_id | C25 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | TPM NV denial record for an older image, including the counter value. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4, HW-03 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C26

| Field | Value |
|---|---|
| stable_requirement_id | C26 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Per-step power-cut report for the NV update. A simulator report is only the partial credit the freeze allows. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4, HW-03 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C28

| Field | Value |
|---|---|
| stable_requirement_id | C28 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Firmware key list showing only owner Secure Boot keys. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4, HW-02 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C29

| Field | Value |
|---|---|
| stable_requirement_id | C29 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Offline quote record against the pinned attestation key, including measured PCR values. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4, HW-02 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C30

| Field | Value |
|---|---|
| stable_requirement_id | C30 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Kernel report that IOMMU groups are enforced, or that the named DMA buses are absent. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C31

| Field | Value |
|---|---|
| stable_requirement_id | C31 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Kernel log of USB default-deny with the single allow-listed medium class. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C32

| Field | Value |
|---|---|
| stable_requirement_id | C32 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Enumeration digest showing radios absent or hardware-off. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C33

| Field | Value |
|---|---|
| stable_requirement_id | C33 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Measured netdev digest showing no usable network device per link class. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4, HW-16 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C34

| Field | Value |
|---|---|
| stable_requirement_id | C34 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Platform report for management engine or out-of-band management. A network-capable controller that cannot be disabled disqualifies the machine. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C35

| Field | Value |
|---|---|
| stable_requirement_id | C35 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Firmware settings record: setup password, locked boot order, internal drive only, network boot disabled. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C36

| Field | Value |
|---|---|
| stable_requirement_id | C36 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | LUKS2 header check. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4, HW-02 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C37

| Field | Value |
|---|---|
| stable_requirement_id | C37 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Storage scan report, before and after, with a planted marker found by the negative test. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G5, HW-01 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C38

| Field | Value |
|---|---|
| stable_requirement_id | C38 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No hardware report for this control. |
| required_artifact | Crown isolation inventory digest with its own serial. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| exit_condition | The artifact named above is accepted on its own. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### DEC-K

| Field | Value |
|---|---|
| stable_requirement_id | DEC-K |
| exact_source_authority | RSE12_06 C27; ACR-B1-2 deferral on PR #10 |
| intended_technical_meaning | Intermediate decision. It does not implement class K and it does not remove C27 from the denominator. |
| register_recorded_evidence | Approval 3 defers ACR-B1-2. Class K returns UNSUPPORTED_CURRENT_MILESTONE. No implementation is authorized by this row. |
| required_artifact | A founder decision that class K recovery stays deferred, and that C27 therefore stays unmet, until a later architecture-change authorization exists. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | (none) |
| register_status | NOT_AUTHORIZED |
| remaining_blocker | (empty) |
| exit_condition | The decision is recorded. C27 is still a separate mandatory row. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_AUTHORIZED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C27

| Field | Value |
|---|---|
| stable_requirement_id | C27 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | Intermediate recovery evidence. It waits on DEC-K and does not itself authorize class K. It is not the training authorization. |
| register_recorded_evidence | Class K is unsupported. No re-enrolment record. |
| required_artifact | Re-enrolment records for a TPM or board replacement that refuse a lower-generation restore, produced by an authorized class-K path. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | DEC-K, G5, HW-02 |
| register_status | NOT_STARTED |
| remaining_blocker | Do not implement class K under this row. Wait for a founder architecture-change authorization that is not this register. |
| exit_condition | The re-enrolment record exists after class K is authorized elsewhere. A decision record alone does not pass C27. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C39

| Field | Value |
|---|---|
| stable_requirement_id | C39 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No pair of build reports was produced in this pass. |
| required_artifact | Two independent build reports whose digests match, compared on Crown. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | ANTIGRAVITY |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | SUP-1 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The comparison record is accepted. SUP-1's harness log is not this comparison. |
| engineering_owner | CLAUDE |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C40

| Field | Value |
|---|---|
| stable_requirement_id | C40 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Software floors are not a sealed Crown card. |
| required_artifact | Floor-check log refusing a lower card and a lower sealed floor. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | C41 |
| register_status | DESIGNED_ONLY |
| remaining_blocker | (empty) |
| exit_condition | The floor-check log is accepted together with a sealed floor. C41 remains separate. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=DESIGNED_ONLY; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C41

| Field | Value |
|---|---|
| stable_requirement_id | C41 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | Intermediate custody act. It is not the training authorization. |
| register_recorded_evidence | No floor card. |
| required_artifact | Signed comparison receipt containing both floor-card serials. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | G7 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The receipt names both serials. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C42

| Field | Value |
|---|---|
| stable_requirement_id | C42 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No recovery kit. |
| required_artifact | Refusal log for a recovery kit below the effective floor. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | C40 |
| register_status | DESIGNED_ONLY |
| remaining_blocker | (empty) |
| exit_condition | The below-floor kit is refused in the log. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=DESIGNED_ONLY; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C43

| Field | Value |
|---|---|
| stable_requirement_id | C43 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | Intermediate ceremony. It is not the training authorization. |
| register_recorded_evidence | No ceremony record. |
| required_artifact | Epoch checkpoint and LUKS slot rotation record after recovery-media theft response. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | G5 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The epoch record exists and contains no secret. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C46

| Field | Value |
|---|---|
| stable_requirement_id | C46 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Not implemented. Table marks P2 and future. |
| required_artifact | Qualification bit-budget counter log from the chamber. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G10 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The budget log is accepted. C47 is a separate monotonicity artifact. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C47

| Field | Value |
|---|---|
| stable_requirement_id | C47 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Not implemented. |
| required_artifact | Evidence that restoring qualification state does not refund the budget. The freeze types this UNP. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G10 |
| register_status | NOT_STARTED |
| remaining_blocker | Name the chamber operator. A synthetic counter is not this artifact. |
| exit_condition | The monotonicity evidence is accepted. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C48

| Field | Value |
|---|---|
| stable_requirement_id | C48 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #8 head da567d927b61c41e253b42732aad249b5fdbb104, push run 37884389862 success. GitHub reviews length 0. The run is not row acceptance. |
| required_artifact | Refusal records showing a T-complete record cannot authorize W, and W-complete cannot authorize D. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | DESIGNED_ONLY |
| remaining_blocker | (empty) |
| exit_condition | A reviewer accepts this row's own artifact on the merged SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=DESIGNED_ONLY; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C49

| Field | Value |
|---|---|
| stable_requirement_id | C49 |
| exact_source_authority | RSE12_06 §4 |
| intended_technical_meaning | Intermediate registry entry after selection. It is not the training authorization. |
| register_recorded_evidence | No approved foundation entry. model_selection_authorized() returns false. |
| required_artifact | Registry entry containing the foundation provenance digests before any use. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | MODEL-1 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The registry entry is accepted. The selection record remains MODEL-1. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### C50

| Field | Value |
|---|---|
| stable_requirement_id | C50 |
| exact_source_authority | RSE12_06 §3 and §4 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Budget numbers exist in the freeze. No drill record. |
| required_artifact | A drill measurement of boots, media moves, witness trips, token touches, and typed SAS counts. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G7 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the operator who runs the drill. Purchase stays on G4. |
| exit_condition | The measurement is recorded. A sentence that a drill happened is not the measurement. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-01

| Field | Value |
|---|---|
| stable_requirement_id | HW-01 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | Witness serial recorded on a machine used for nothing else, different from the Crown serial and the Forge serial. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-02

| Field | Value |
|---|---|
| stable_requirement_id | HW-02 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | TPM 2.0 capability record for the Witness. Absence disqualifies the machine. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-03

| Field | Value |
|---|---|
| stable_requirement_id | HW-03 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | TPM NV capability record showing a counter index and policy comparison on NV. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-06

| Field | Value |
|---|---|
| stable_requirement_id | HW-06 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | Measurement record showing the role code and its version inside the measured image. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-08

| Field | Value |
|---|---|
| stable_requirement_id | HW-08 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | Build record of the owner-signed unified kernel image and the boot measurement that matches it. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-11

| Field | Value |
|---|---|
| stable_requirement_id | HW-11 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | Custody record that a paper recovery passphrase exists, with no secret and no passphrase value in git. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G5 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-16

| Field | Value |
|---|---|
| stable_requirement_id | HW-16 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | Firmware or physical record that the wired port is unused, blocked, or firmware-disabled. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-18

| Field | Value |
|---|---|
| stable_requirement_id | HW-18 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | Update log showing firmware and OS updates came only from the owner-approved offline registry. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-19

| Field | Value |
|---|---|
| stable_requirement_id | HW-19 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | Registry record of the approved artifacts and the offline distribution used to install them. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G2 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-20

| Field | Value |
|---|---|
| stable_requirement_id | HW-20 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | Custody record for the Witness location. Seals are HW-20P and do not satisfy this row. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-21

| Field | Value |
|---|---|
| stable_requirement_id | HW-21 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | Capacity record for RAM, storage, and CPU against the largest planned bundle and the sandboxed checker. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-24

| Field | Value |
|---|---|
| stable_requirement_id | HW-24 |
| exact_source_authority | RSE12_06 §1 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No serial, quote, photograph, purchase, or firmware record for this property is in the tree. |
| required_artifact | Inventory showing the Witness has no GPU. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| exit_condition | The named artifact exists and a reviewer accepts that artifact. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### HW-FORGE

| Field | Value |
|---|---|
| stable_requirement_id | HW-FORGE |
| exact_source_authority | RSE12_06 §6 P1 definition: Crown + Forge + independent Witness |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No Forge inventory. |
| required_artifact | Forge serial different from the Witness serial and the Crown serial. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G4 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the Forge custodian. No purchase is authorized here. Purchase stays on G4. |
| exit_condition | The Forge serial is recorded. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### SUP-1

| Field | Value |
|---|---|
| stable_requirement_id | SUP-1 |
| exact_source_authority | RSE12_06 C39; docker/rse_synthetic_integration_lab and infra/tier0-local/docker |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | PR #13 live head 0328123361756b9732fc57886754d6d09c4b9c46. Push run 37973767347 succeeded for that head. Pull-request run 37973770477 also succeeded and is not the exact-SHA proof. Ancestor cd95befd196c57d1885be208532a1c9a32991a39 push run 37972786151 succeeded. GitHub reviews length 0. A green harness run is not two independent training-image digests. |
| required_artifact | Two independent build digests of the training image, plus the lock used to build them. |
| test_and_ci_evidence_states | SHA_CI_PASSED, SHA_CI_PASSED_ON_ANCESTOR |
| independent_reviewer_identity | ANTIGRAVITY |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | C39's comparison exists. A harness repair log does not pass C39. |
| engineering_owner | CLAUDE |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SHA_CI_PASSED,SHA_CI_PASSED_ON_ANCESTOR; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### SUP-3

| Field | Value |
|---|---|
| stable_requirement_id | SUP-3 |
| exact_source_authority | requirements/rse.txt on PR #10 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | On f424dbf51eb8ed03f5fbe57cbd0ef3c2fa72fcdb, push run 37893124711 job RSE dependency lock and vulnerability scan reported no known vulnerabilities for that lock. Not on main. The base job does not include pyhpke. |
| required_artifact | Hash-locked install of the RSE extra and a fail-closed audit log of that lock, on the SHA that is merged to main. |
| test_and_ci_evidence_states | SHA_CI_PASSED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | UNMERGED_NOT_ACCEPTED |
| remaining_blocker | (empty) |
| exit_condition | The same job is green on the merge commit on main. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=UNMERGED_NOT_ACCEPTED; evidence_states=SHA_CI_PASSED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### P2-1

| Field | Value |
|---|---|
| stable_requirement_id | P2-1 |
| exact_source_authority | RSE12_06 §2 cloud-provider row and §7 step 13 |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | The freeze marks provider root of trust UNPROVEN. |
| required_artifact | Attestation evidence for a named training environment. No provider is selected by this row. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G10 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the environment operator. No provider contract is authorized here. |
| exit_condition | The attestation package is accepted. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### P2-2

| Field | Value |
|---|---|
| stable_requirement_id | P2-2 |
| exact_source_authority | RSE12_06 §5 R-EXF |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Residual text only. |
| required_artifact | An egress test showing the training identity cannot open a forbidden path. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G10 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The egress test log is accepted. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### P2-4

| Field | Value |
|---|---|
| stable_requirement_id | P2-4 |
| exact_source_authority | MODEL_EVAL_AUTHORIZATION.json |
| intended_technical_meaning | The enforcement test is a readiness input. Permission to spend or to use a GPU is contingent on readiness. |
| register_recorded_evidence | max_spend_usd is 0. network_provider_inference_allowed is false. gpu_allowed is false. |
| required_artifact | A training-environment test that a spend above the configured cap is refused. The cap value may remain 0. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G10 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The refusal test is accepted. Raising the cap is FINAL-2. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### DATA-1

| Field | Value |
|---|---|
| stable_requirement_id | DATA-1 |
| exact_source_authority | GENESIS_PRETRAINING_QUALIFICATION.md |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | The qualification note describes a small v1+v2+v3 set and a token proxy. That note is not a protected-corpus manifest and does not authorize training. |
| required_artifact | A provenance manifest listing source, license, and per-record digest, bound to the creation digest from DATA-3. The founder grant is not this manifest. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | DATA-3 |
| register_status | NOT_ACCEPTED |
| remaining_blocker | Founder names who assembles the manifest. This row generates no corpus. |
| exit_condition | The manifest is accepted against the creation digest. G8 does not pass this row. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_ACCEPTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### DATA-2

| Field | Value |
|---|---|
| stable_requirement_id | DATA-2 |
| exact_source_authority | RSE12_05 contamination oracle; RSE12_01 contamination_status_ref |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | GENESIS_FRONTIER_HOLDOUT_SPEC.md says zero-contamination is not proven. No protected corpus exists to test. |
| required_artifact | A contamination and holdout-separation result bound to the creation digest and the holdout fingerprint set, with no item-level leak. The founder grant is not this result. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | DATA-1, DATA-3, DATA-5, QUAL-2 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The oracle output is accepted. G8 does not pass this row. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### DATA-3

| Field | Value |
|---|---|
| stable_requirement_id | DATA-3 |
| exact_source_authority | RSE12_06 §6 real private corpus after P1; CORPUS_GENERATION_AUTHORIZATION.json is the grant, not the corpus |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No creation record. CORPUS_GENERATION_AUTHORIZATION.json remains NOT_AUTHORIZED and contains no corpus. |
| required_artifact | A protected-corpus creation record that names the corpus digest and the creating operator. The founder grant is not this record. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G8 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names the corpus operator after G8. This row does not generate a corpus and does not implement class K. |
| exit_condition | The creation record exists. The grant alone leaves this row unmet. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### DATA-5

| Field | Value |
|---|---|
| stable_requirement_id | DATA-5 |
| exact_source_authority | RSE12_06 §6 custody of the real private corpus |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No protected corpus and no custody receipt. |
| required_artifact | An independent custody and integrity receipt that re-hashes the protected corpus and names a custodian who is not the creator. The founder grant is not this receipt. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | DATA-3 |
| register_status | NOT_STARTED |
| remaining_blocker | Founder names a custodian who did not create the corpus. This row does not generate a corpus. |
| exit_condition | The receipt matches the creation digest. Creation alone does not pass this row. |
| engineering_owner | UNRESOLVED_EXTERNAL |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### MODEL-2R

| Field | Value |
|---|---|
| stable_requirement_id | MODEL-2R |
| exact_source_authority | GENESIS_BASE_MODEL_QUALIFICATION.md license section |
| intended_technical_meaning | Intermediate scope decision. Research-only training and commercial release are different rights. This row records only the research scope. |
| register_recorded_evidence | The qualification note quotes a non-commercial research license and says commercial release is blocked. It also says the term does not by itself block research or internal evaluation. No founder scope record exists. This row does not grant either scope. |
| required_artifact | A founder scope record that the first run, when later authorized, is research or evaluation only under the qwen-research terms. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | MODEL-0 |
| register_status | NOT_AUTHORIZED |
| remaining_blocker | (empty) |
| exit_condition | The research-only scope record exists. Commercial rights remain MODEL-2C. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_AUTHORIZED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### MODEL-1

| Field | Value |
|---|---|
| stable_requirement_id | MODEL-1 |
| exact_source_authority | orca/registry/model_spec.py; model_selection_authorized() |
| intended_technical_meaning | Intermediate selection. It is an input to readiness. It does not depend on the training lock. |
| register_recorded_evidence | The pin in MODEL-0 is present. model_selection_authorized() returns false. |
| required_artifact | A founder selection record naming the repository and the exact revision. The code pin is not that record. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | MODEL-2R |
| register_status | NOT_AUTHORIZED |
| remaining_blocker | (empty) |
| exit_condition | The selection record exists and stays inside the research-only scope. It does not set training_authorized(). |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_AUTHORIZED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### QUAL-1

| Field | Value |
|---|---|
| stable_requirement_id | QUAL-1 |
| exact_source_authority | QUALIFICATION_RUNNER_REGISTRY.json |
| intended_technical_meaning | Intermediate runner authorization after the chamber design. It is not contingent on full training readiness. |
| register_recorded_evidence | State REGISTERED_NOT_AUTHORIZED. runner_class SELF_HOSTED_CPU. os_runtime says the local Mac is the canonical CPU runner. Network policy in the record is none. |
| required_artifact | Founder authorization of the qualification runner. The binding note is not that authorization. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | G10 |
| register_status | NOT_AUTHORIZED |
| remaining_blocker | (empty) |
| exit_condition | The founder changes the runner state. This register does not. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_AUTHORIZED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### QUAL-2

| Field | Value |
|---|---|
| stable_requirement_id | QUAL-2 |
| exact_source_authority | eval_private/genesis_capability_eval_v1/holdout.jsonl and holdout_fingerprints.json |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | The paths exist. No isolation proof was run in this pass. |
| required_artifact | A failed read of the holdout by the training identity. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | QUAL-1, P2-2 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The failed-read log is accepted. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### QUAL-3

| Field | Value |
|---|---|
| stable_requirement_id | QUAL-3 |
| exact_source_authority | GENESIS_PRETRAINING_QUALIFICATION.md regression policy |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Critical categories are named. Numeric thresholds for the other categories are not set. |
| required_artifact | Numeric thresholds frozen before any candidate result, for every category the policy says is critical and for the categories it leaves unset. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G10 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The threshold freeze is recorded before a candidate run. |
| engineering_owner | PRODUCT_MANAGEMENT |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### TRAIN-1

| Field | Value |
|---|---|
| stable_requirement_id | TRAIN-1 |
| exact_source_authority | pyproject.toml extra train; orca/train |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | The extra lists version ranges. No hash lock for the train extra was found. uv.lock is not what CI installs. |
| required_artifact | A hash lock of the train extra and one dry-run command pinned to a SHA. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | G3 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The lock and the command log name the same SHA. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### TRAIN-2

| Field | Value |
|---|---|
| stable_requirement_id | TRAIN-2 |
| exact_source_authority | orca/rse/imp1/locks.py |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | No full-trainer dry-run log is in this pass. |
| required_artifact | A synthetic dry-run log showing corpus, qualification, model-selection, GPU, and training locks still false afterward. |
| test_and_ci_evidence_states | SOURCE_VERIFIED |
| independent_reviewer_identity | CLAUDE |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | TRAIN-1 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The log shows the locks still false. The run does not flip them. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=SOURCE_VERIFIED; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### AUTH-1

| Field | Value |
|---|---|
| stable_requirement_id | AUTH-1 |
| exact_source_authority | Founder budget approval, which is not a file yet |
| intended_technical_meaning | Intermediate budget act. It can exist before readiness is complete. It is not contingent on FINAL-1. |
| register_recorded_evidence | No budget record found. |
| required_artifact | A budget record with a number, a currency, and the founder's signature or equivalent. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | INTERMEDIATE |
| dependency_chain | (none) |
| register_status | NOT_VERIFIABLE |
| remaining_blocker | (empty) |
| exit_condition | The record exists. Until then this row blocks a readiness percentage. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_VERIFIABLE; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### R65

| Field | Value |
|---|---|
| stable_requirement_id | R65 |
| exact_source_authority | The founder's canonical 65 rules. No file in this tree contains that set. |
| intended_technical_meaning | Intermediate source requirement. The founder supplies the text before readiness can be complete. Child rules are not invented. A percentage stays unpublished while this row is NOT_VERIFIABLE. This row is not the training authorization. |
| register_recorded_evidence | No source. No child rule is listed. |
| required_artifact | The exact source text, founder-approved, then one child row per rule. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | REQUIRED |
| founder_act | NONE |
| dependency_chain | (none) |
| register_status | NOT_VERIFIABLE |
| remaining_blocker | Founder supplies the complete exact text. Do not paraphrase it. |
| exit_condition | Sixty-five child rows replace this placeholder after the source is approved. |
| engineering_owner | FOUNDER |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_VERIFIABLE; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

### FINAL-1

| Field | Value |
|---|---|
| stable_requirement_id | FINAL-1 |
| exact_source_authority | This register |
| intended_technical_meaning | (empty) |
| register_recorded_evidence | Numerator is 0. G1, AUTH-1, and R65 are NOT_VERIFIABLE. |
| required_artifact | An independent recomputation worksheet that lists every counted pre-training id and its own status. |
| test_and_ci_evidence_states | NONE |
| independent_reviewer_identity | PRODUCT_MANAGEMENT |
| founder_approval_requirement | NOT_REQUIRED |
| founder_act | NONE |
| dependency_chain | AUTH-1, C01, C02, C03, C04, C05, C06, C07, C08, C09, C10, C11, C12, C13, C14, C15, C16, C17, C18, C19, C20, C21, C22, C23, C24, C25, C26, C27, C28, C29, C30, C31, C32, C33, C34, C35, C36, C37, C38, C39, C40, C41, C42, C43, C44, C45, C46, C47, C48, C49, C50, DATA-1, DATA-2, DATA-3, DATA-5, DEC-K, G1, G10, G11, G12, G2, G3, G4, G5, G6, G7, G8, G9, HW-01, HW-02, HW-03, HW-06, HW-08, HW-11, HW-16, HW-18, HW-19, HW-20, HW-21, HW-24, HW-FORGE, MODEL-1, MODEL-2R, P2-1, P2-2, P2-4, QUAL-1, QUAL-2, QUAL-3, R65, SUP-1, SUP-3, TRAIN-1, TRAIN-2 |
| register_status | NOT_STARTED |
| remaining_blocker | (empty) |
| exit_condition | The worksheet matches a fresh run of the validator. Founder authorization is still FINAL-2. |
| engineering_owner | CURSOR |
| independent_qualification_requirement | OWN_EVIDENCE |
| class | MANDATORY |
| denominator | PRE_TRAINING |
| counts | True |
| actual_measured_state | register_status=NOT_STARTED; evidence_states=NONE; engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE |
| acceptance_eligibility | NOT_ELIGIBLE |

## Other denominators

The graph also counts 3 application ids, 2 execution ids, and 1 post-training ids. They are not added to the 95.

