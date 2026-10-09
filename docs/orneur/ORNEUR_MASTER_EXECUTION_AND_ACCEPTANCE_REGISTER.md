# ORNEUR Master Execution and Acceptance Register

NON_NORMATIVE. Not in Manifest V3. Does not amend RSE-ARCH-1.2. Does not authorize provisioning, purchase, secrets, corpus generation, qualification, model selection, GPU, spend, or training. Does not merge any pull request.

This register is separate from the three Phase 0 notes on PR #14. Those notes stay as scoped RSE deliverables. This file is the programme register those notes do not replace.

Checked 2026-10-09 against this branch's parent `55d133c94be65b1d9b843afa3da2f9a2cc4eb701` and `gh pr list`. Canonical main: `464b602f3f259b56f139c3304828baa660e6b860`. No GitHub review is recorded on PR #8, #9, #10, or #14.

Default for every row unless the row says otherwise: implementation owner `UNASSIGNED`, independent reviewer `NONE_RECORDED`. A copied verdict string is not evidence. Status `ACCEPTED` is not used anywhere in this file.

## How 100% is calculated

Two denominators. They are not added together.

**Pre-training denominator.** Rows with class `MANDATORY` and phase `PRE_TRAINING`. A row counts as complete only when its status is changed, by a later independent review, to a status this file does not yet use: `ACCEPTED`, with the evidence required column satisfied. Until then the numerator is 0.

**Application denominator.** Rows with class `MANDATORY` and phase `APPLICATION`. Same rule. These rows do not block or satisfy the pre-training percentage.

**Post-training launch.** Rows with phase `POST_TRAINING_LAUNCH` are outside both percentages.

**NOT_VERIFIABLE.** Any `MANDATORY` row still `NOT_VERIFIABLE` blocks a claim of 100% even if every other row were later accepted. This file does not drop those rows from the denominator. It refuses to invent their contents.

No percentage is computed in this draft because the numerator is empty and R65 is unverifiable.

## Tracks

| Track | Meaning |
| --- | --- |
| RSE | Frozen RSE-ARCH-1.2 security programme. Not the assistant application. |
| APP | Application and API behaviour. Not an RSE gate and not a training gate. |
| SUPPLY | Build, image, and dependency qualification. |
| P1 | Real Crown, Forge, and Witness hardware and custody. |
| DATA | Dataset licensing, provenance, contamination, and the protected corpus. |
| MODEL | Foundation identity, revision, and license. |
| QUAL | Independent qualification and holdout. |
| P2 | Training infrastructure, attestation, egress, compute. |
| TRAIN | Reproducible training software and synthetic dry runs. |
| AUTH | Budget, GPU, and founder authorization. |
| RULES | Founder rule source. Not invented here. |

## 1. RSE roadmap gates

Source for all G-rows: `docs/orneur/phase-21/rse/v1.2/RSE12_06_P1_ACCEPTANCE_OPERATIONS.md` §6–§8. That file was not edited.

| ID | Class | Phase | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G1 | MANDATORY | PRE_TRAINING | A review by someone who did not author the architecture, stored where a later reader can open it. | The freeze still names this as the next action. No such review file was found in this pass. | NOT_VERIFIABLE | None inside this repo | The review exists and is identifiable without copying a verdict slogan. |
| G2 | MANDATORY | PRE_TRAINING | Freeze commit on canonical main. | Main is `464b602f3f259b56f139c3304828baa660e6b860`. Manifest V3 is present and was not edited here. | PRESENT_ON_MAIN | G1 as the freeze's own ordering | Main still matches the manifest, re-checked at integration time. |
| G3 | MANDATORY | PRE_TRAINING | Software on main plus an independent code review of that commit. | IMP-2/3/4 code is on unmerged PR #8 at `da567d9`. PR #9 `c127780` and PR #10 `f424dbf` are stacked and unmerged. GitHub reviews on those PRs are empty. `RSE_MASTER_BLOCK_1_EVIDENCE.md` on `da567d9` still says independent acceptance is pending. | UNMERGED_NOT_ACCEPTED | G2 | The merged SHA has its own main push CI and a review that is not a copied slogan. |
| G4 | MANDATORY | PRE_TRAINING | A purchase authorization and a named hardware selection. | Freeze: nothing is bought. `NO_HARDWARE_PURCHASE_AUTHORIZED` stands. | NOT_AUTHORIZED | G3 is not sufficient | Founder purchase authorization exists, and a selection record names the machines. |
| G5 | MANDATORY | PRE_TRAINING | Provisioning and key-creation authorization, then a ceremony record with no secret in git. | Locks return false. No ceremony record. | NOT_AUTHORIZED | G4 | Authorization file status changes only by a founder act this register does not perform. |
| G6 | MANDATORY | PRE_TRAINING | Real-hardware logs for the C-rows whose REAL_HW cell is yes, plus adversarial notes. | Synthetic tests and labels only. See C22–C38. | NOT_STARTED | G5 | Each REAL_HW row has an objective artifact, not a synthetic pass. |
| G7 | MANDATORY | PRE_TRAINING | A dedicated Crown before any real corpus. | No Crown inventory. C38 is designed only. | NOT_STARTED | G6 | Custody record for a machine that is not the daily driver. |
| G8 | MANDATORY | PRE_TRAINING | Corpus grant. | `docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION.json` status `NOT_AUTHORIZED`. | NOT_AUTHORIZED | G7 | That file's status is authorized by a signed grant, not by this register. |
| G9 | MANDATORY | PRE_TRAINING | A second Crown milestone before qualification or training. | Not started. | NOT_STARTED | G8 | Independent dedicated Crown recorded. |
| G10 | MANDATORY | PRE_TRAINING | Qualification chamber accepted. | `QUALIFICATION_RUNNER_REGISTRY.json` one record, state `REGISTERED_NOT_AUTHORIZED`. | NOT_AUTHORIZED | G9 | Chamber design implemented and a reviewer accepts it. |
| G11 | MANDATORY | PRE_TRAINING | P2 attested environment, egress, counters, spend controls. | Freeze residual R-EXF says this blocks training authorization. C46 and C47 are `DESIGNED (future)`. | NOT_STARTED | G10 | R-EXF is closed by evidence, not by prose. |
| G12 | MANDATORY | PRE_TRAINING | Separate authorizations for training infrastructure and for the Genesis run. | `training_authorized()` returns false. `MODEL_EVAL_AUTHORIZATION.json` status `NOT_AUTHORIZED`, `gpu_allowed` false, `max_spend_usd` 0. | NOT_AUTHORIZED | G11 and AUTH rows | Founder authorization names the run. This file is not that act. |

## 2. RSE acceptance controls C01–C50

Source: the same freeze file, §4. Every AUDIT cell there is `yes`, with the sentence that nothing is audited yet. That sentence was not edited by later software work. Class for every C-row: `MANDATORY`. Phase: `PRE_TRAINING`. Track: `RSE`. Owner: `UNASSIGNED`. Reviewer: `NONE_RECORDED`.

Current evidence for every C-row, unless the row adds a fact: the control is `DESIGNED` in the freeze. Where code exists, it is on unmerged PR #8 and is not on main. That code is not acceptance.

| ID | Property | Evidence required | Extra current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- |
| C01 | Crown refuses unregistered IDs | Refusal log from the signed registry path | Software pieces exist only on PR #8 | UNMERGED_NOT_ACCEPTED | G3 | Independent review of the merged code |
| C02 | Consumer repeats registry validation | Consumer refusal record | Same | UNMERGED_NOT_ACCEPTED | G3 | Same |
| C03 | Registry canonical and dual-token signed | Verify log | IMP-1 is on main inside the RSE tree; dual-token hardware tokens are not | DESIGNED_ONLY | G2 | Token row C08/C44 also closed |
| C04 | Ceilings within POLICY caps | Refusal record | Code on PR #8 | UNMERGED_NOT_ACCEPTED | G3 | Review of merged code |
| C05 | Names non-confusable | Validator output | Code on main IMP-1 / PR #8 stack | UNMERGED_NOT_ACCEPTED | G3 | Review |
| C06 | Consumer renders from signed bytes | Rendered-card digest | Designed | DESIGNED_ONLY | G3 | Test evidence on the merged SHA |
| C07 | Typed SAS and Intent Sheet | Typed-entry record | Software rehearsal is not a human ceremony | DESIGNED_ONLY | G7 | Ceremony record |
| C08 | Dual-token threshold | Verify log with two distinct tokens | REAL_HW cell is `tokens`. No tokens issued | NOT_AUTHORIZED | G5 | Two physical tokens, distinct keys |
| C09 | Challenge single-use | Journal record | Code on PR #8. Cap 8192 is a synthetic ceiling, not acceptance | UNMERGED_NOT_ACCEPTED | G3 | Review, and a production ceiling decision |
| C10 | Offline clock is advisory | Refusal record | Code on PR #8 | UNMERGED_NOT_ACCEPTED | G3 | Review |
| C11 | No ACTIVE before witnessed checkpoint | State log | Code on PR #8. Witnesses are synthetic | UNMERGED_NOT_ACCEPTED | G6 | Real witness acks |
| C12 | Witness cosignature | Verify log | Synthetic keys only | UNMERGED_NOT_ACCEPTED | G6 | Real M1/M2 |
| C13 | Monitor refuses forks and shrinkage | Witness log | `SyntheticFence` is not TPM NV | UNMERGED_NOT_ACCEPTED | G6 | Hardware fence plus review |
| C14 | Result egress gating | Refusal record | Code on PR #8 | UNMERGED_NOT_ACCEPTED | G3 | Review |
| C15 | Crash never double-executes | Journal replay report | In-process sink tests are not a disk power-cut | UNMERGED_NOT_ACCEPTED | C26 | C26 evidence plus review |
| C16 | OCR1 grammar | Second implementation agrees | Freeze maturity: structural codec evidence only | DESIGNED_ONLY | G3 | Agreement with an independent codec |
| C17 | `enc` validity and zero shared secret | Vector test | Code on PR #8 | UNMERGED_NOT_ACCEPTED | G3 | Review |
| C18 | Key and nonce uniqueness | Test log | RFC 9180 vectors exist as software tests on PR #8 | UNMERGED_NOT_ACCEPTED | G3 | Review |
| C19 | Frame-set rules | Per-case verdicts | Code on PR #8 | UNMERGED_NOT_ACCEPTED | G3 | Review |
| C20 | Enrolment binding | Resolver log | Code on PR #8 | UNMERGED_NOT_ACCEPTED | G3 | Review |
| C21 | Origin signature before key use | Verify log | Code on PR #8 | UNMERGED_NOT_ACCEPTED | G3 | Review |
| C22 | Key-absent Phase 1 keeps the vault locked | Mount and key-state record. REAL_HW yes | No vault | NOT_STARTED | G5 | Hardware log |
| C23 | Plaintext sandbox | Sandbox policy dump. REAL_HW yes | Checker label `SYNTHETIC_NOT_A_SANDBOX` | NOT_STARTED | G6 | Real sandbox log |
| C24 | Key release bound to measured boot | TPM error codes. HW | None | NOT_STARTED | G4 | TPM policy test |
| C25 | NV fence denies an old image | Counter value. HW | Synthetic fence only | NOT_STARTED | G4 | TPM NV test |
| C26 | NV update safe at power cut | Per-step report. REAL_HW yes. Freeze allows a simulator only as partial | No simulator report and no hardware report in this pass | NOT_STARTED | G4 | Power-cut report |
| C27 | Board replacement without rollback | Re-enrolment records. REAL_HW yes | Class K is unsupported in the software | NOT_STARTED | G5 | K-grant ceremony |
| C28 | Owner Secure Boot keys only | Firmware key list. HW | None | NOT_STARTED | G4 | Firmware record |
| C29 | Offline quote | Quote record. REAL_HW yes | None | NOT_STARTED | G4 | Quote verified offline |
| C30 | DMA protection | Kernel report. HW | None | NOT_STARTED | G4 | IOMMU or absent-bus record |
| C31 | USB default-deny | Kernel log. REAL_HW yes | None | NOT_STARTED | G4 | Policy log |
| C32 | Radios absent or hardware-off | Enumeration digest. HW | None | NOT_STARTED | G4 | Enumeration |
| C33 | No usable network device | Measured netdev digest. REAL_HW yes | None | NOT_STARTED | G4 | Digest |
| C34 | ME/OOB absent or verifiably disabled | Platform report. HW | None. Freeze disqualifies hardware that cannot meet this | NOT_STARTED | G4 | Platform report |
| C35 | Firmware password and locked boot order | Settings record. HW | None | NOT_STARTED | G4 | Settings record |
| C36 | LUKS2 at rest | Header check. REAL_HW yes | None | NOT_STARTED | G4 | Header check |
| C37 | No plaintext on persistent channels | Scan report. REAL_HW yes | None | NOT_STARTED | G6 | Scan of the real machine |
| C38 | Crown isolation inventory | Inventory digest. REAL_HW yes | None | NOT_STARTED | G7 | Inventory |
| C39 | Two independent builds match | Both build reports | None in this pass | NOT_STARTED | SUP-1 | Two digests compared on Crown |
| C40 | Registry rollback floors | Floor-check log | Software floors are not a sealed Crown card | DESIGNED_ONLY | C41 | Card plus sealed floor |
| C41 | Owner Floor Card integrity | Signed comparison of two serials | None | NOT_STARTED | G7 | Receipt with both serials |
| C42 | Recovery stays at or above the floor | Refusal log | No recovery kit | DESIGNED_ONLY | C40 | Kit test |
| C43 | Recovery-media theft response | Epoch and rotation record | None | NOT_STARTED | G5 | Ceremony record |
| C44 | One token cannot satisfy a two-token class | Verify log. REAL_HW `tokens` | No tokens | NOT_AUTHORIZED | C08 | Token test |
| C45 | Impossible lifecycle transitions rejected | Transition log | Code on PR #8. QUARANTINED has no exit. Class K is not implemented | UNMERGED_NOT_ACCEPTED | G3 | Review. K remains a separate ACR, not this row's exit |
| C46 | Qualification bit budget | Budget counter. Table marks P2 and future | Not implemented | NOT_STARTED | G10 | Chamber test |
| C47 | Qualification counters do not roll back | Hardware monotonic evidence. Type UNP. P2 | Not implemented | NOT_STARTED | G11 | Evidence that is not a synthetic counter |
| C48 | W and D stay separate from training | Refusal records | Parser refuses those classes. That is not a completed export control | DESIGNED_ONLY | G3 | Review of the refusal, plus a real grant test when authorized |
| C49 | Foundation approval before use | Provenance entry | See MODEL rows. Freeze maturity: future | NOT_STARTED | MODEL-3 | Registry entry with digests |
| C50 | Operator budget measured in drills | Drill measurement | Budget numbers exist in the freeze. No drill record | NOT_STARTED | G7 | A measurement, not a "drill completed" sentence |

## 3. Application and API

Track `APP`. These rows do not enter the pre-training percentage. They are a separate readiness claim.

| ID | Class | Phase | Source | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| APP-1 | MANDATORY | APPLICATION | PR #11, observed open, head `6e30dd9f31215f0046a2612653794291ada6688f`, base `main` | Independent review of the streaming and error-leak fix, then its own CI | This register did not read the diff and did not run its tests | OPEN_PR_UNREVIEWED | None from RSE | Reviewer names the SHA and the tests |
| APP-2 | MANDATORY | APPLICATION | PR #12, observed open, head `63ece2a5dd673d69a06effdf766d7046f1973fc8`, base `claude/phase-a-assistant-baseline` | Same, for the checkpoint-2 claims (pool bound, secret logging, SSE) | Not reviewed here. GitHub reviews length 0 | OPEN_PR_UNREVIEWED | APP-1 if the branch stack is real | Same |
| APP-3 | NONBLOCKING | POST_TRAINING_LAUNCH | `docs/LAUNCH_PLAN.md` public-claim and SOC 2 items | Launch evidence | Planning text only | NOT_STARTED | A trained model that does not exist | Out of the pre-training denominator |

## 4. Docker and supply chain

| ID | Class | Phase | Source | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SUP-1 | MANDATORY | PRE_TRAINING | `RSE12_06` C39; Dockerfiles under `infra/tier0-local/docker/` and `docker/genesis_v2_sandbox/Dockerfile` | Two independent build digests and a lock of the training image | Files exist. No pair of build reports was produced here. PR #13 (`d21937941e823909a5a8594ffc04e2d45ef30183`, base `main`) is a draft harness repair and was not reviewed | NOT_STARTED | G3 | C39 evidence |
| SUP-2 | MANDATORY | APPLICATION | `.github/workflows/test.yml` job `container-build` on this branch | A green exact-SHA job for the SHA that is claimed | Job exists in the file. This register's own commit has no CI result yet. Main does not contain the RSE audit job added on PR #10 | NOT_ACCEPTED | The SHA under claim | Job log for that SHA |
| SUP-3 | MANDATORY | PRE_TRAINING | `requirements/rse.txt` on PR #10; `pyproject.toml` pins | Hash install plus an audit log that is not the base-install job | On `f424dbf`, push run `37893124711` job `RSE dependency lock and vulnerability scan` logged no known vulnerabilities for that lock. The base job remains informational and does not include pyhpke. Not on main | UNMERGED_NOT_ACCEPTED | G3 | The same job on the merge commit on main |
| SUP-4 | NONBLOCKING | POST_TRAINING_LAUNCH | Workflow comment naming chromadb `PYSEC-2026-311` and diskcache `PYSEC-2026-2447` | A fresh advisory decision | Disclosed as base-install findings. Not closed here | OPEN | None for training | Separate from the RSE lock |

## 5. P1 physical security

Track `P1`. Class `MANDATORY`. Phase `PRE_TRAINING`. Source: `RSE12_06` §1 rows 1–25 and §6. Evidence required: the objective artifact named in §4 for the matching C-row. Current evidence: none. Status: `NOT_STARTED`. Dependency: G4. Exit: a hardware record. Owner remains `UNASSIGNED` until a purchase authorization names an operator.

The §1 mandatory or disqualifying properties are: dedicated machine, TPM 2.0, NV counter, owner Secure Boot, measured boot, role-code measurement, PCR policy, owner-built Linux UKI, LUKS2, TPM-bound release plus PIN, paper recovery passphrase, firmware password and locked boot order, ME/OOB policy, DMA/IOMMU, radios hardware-disabled, wired port disabled, USB default-deny, offline updates, artifact registry, physical custody, enough CPU/RAM, and no GPU on the Witness. Preferred and optional rows (spare machine, discrete versus firmware TPM, TPM RNG) are `NONBLOCKING` for the first P1 gate only where the freeze class is P or O. They are not a waiver of the M and D rows.

FACT: no serial, quote, photograph, or purchase record is in this tree. Synthetic M1/M2 checks use test keys and are not two machines.

## 6. Dataset, provenance, contamination, protected corpus

| ID | Class | Phase | Source | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DATA-1 | MANDATORY | PRE_TRAINING | `GENESIS_PRETRAINING_QUALIFICATION.md` citing `GENESIS_DATASET_V3.md` | License and provenance for every record that would be trained on | The note describes a small v1+v2+v3 set and a token proxy. It says it does not authorize training | NOT_ACCEPTED | MODEL-1 | A manifest with source, license, and digest per record |
| DATA-2 | MANDATORY | PRE_TRAINING | `RSE12_05` contamination oracle; `RSE12_01` corpus field `contamination_status_ref` | A set-level contamination result against the holdout, with no item-level leak | Specification only. `GENESIS_FRONTIER_HOLDOUT_SPEC.md` says zero-contamination is not claimed proven | NOT_STARTED | QUAL-1, G8 | Oracle output bound to a corpus digest |
| DATA-3 | MANDATORY | PRE_TRAINING | `CORPUS_GENERATION_AUTHORIZATION.json`; `RSE12_06` §6 | Protected private corpus only after P1 | Status `NOT_AUTHORIZED`. The small documented set is not that corpus | NOT_AUTHORIZED | G8 | Grant |
| DATA-4 | NONBLOCKING | POST_TRAINING_LAUNCH | Public dataset marketing claims | A published data card | Not started | NOT_STARTED | DATA-1 | After training exists |

## 7. Foundation model

| ID | Class | Phase | Source | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MODEL-1 | MANDATORY | PRE_TRAINING | `orca/registry/model_spec.py` lines for family `genesis` | A founder selection act. Code presence is not that act | Code sets `base_model` `unsloth/Qwen2.5-3B-Instruct`, revision and tokenizer revision `7548fff1f997f57b2e9e8ab1ec7be96949b00ed0`, `license_name` `qwen-research`, `license_commercial_use` `RESTRICTED`. `model_selection_authorized()` still returns false | NOT_AUTHORIZED | AUTH-3 | Founder selection recorded. The code pin can stay or change only by that act |
| MODEL-2 | MANDATORY | PRE_TRAINING | `GENESIS_BASE_MODEL_QUALIFICATION.md` | License text decision for the chosen revision | The note records a non-commercial Qwen research license and calls commercial use blocked. It does not grant a commercial license | BLOCKED_LICENSE | MODEL-1 | Either a commercial grant from the rights holder, or an explicit research-only scope that forbids a commercial release |
| MODEL-3 | MANDATORY | PRE_TRAINING | `RSE12_06` C49 | Registry entry with provenance digests before use | Not in the registry as an approved foundation | NOT_STARTED | MODEL-2, G3 | C49 evidence |
| MODEL-4 | NONBLOCKING | PRE_TRAINING | `GENESIS_STAGE0_LICENSE_MATRIX.md` | Not a selection | Other candidates are listed with license notes. The matrix says it is not legal advice and does not authorize a download | NOT_A_SELECTION | None | Must not be read as a replacement for MODEL-1 |

## 8. Qualification and holdout

| ID | Class | Phase | Source | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| QUAL-1 | MANDATORY | PRE_TRAINING | `QUALIFICATION_RUNNER_REGISTRY.json`; `GENESIS_V2_QUALIFICATION_RUNNER_QUALIFICATION_RECORD.json` is named by that file | Runner authorized, holdout unreadable by training | State `REGISTERED_NOT_AUTHORIZED`. `os_runtime` text says the local Mac is the canonical CPU runner. That is a binding note, not an authorization. Network policy in the record is `none` | NOT_AUTHORIZED | G10 | Status change by a founder act |
| QUAL-2 | MANDATORY | PRE_TRAINING | `eval_private/genesis_capability_eval_v1/holdout.jsonl` and `holdout_fingerprints.json` exist as paths | Proof the training job cannot read them | Paths exist. No isolation proof was run here | NOT_STARTED | QUAL-1, P2-2 | A failed read from the training identity |
| QUAL-3 | MANDATORY | PRE_TRAINING | `GENESIS_PRETRAINING_QUALIFICATION.md` regression policy | Pre-registered thresholds before any candidate result | Critical categories are named. Numeric thresholds for the other categories are explicitly not set | NOT_STARTED | A baseline that is not authorized | Thresholds frozen before the candidate run |
| QUAL-4 | NONBLOCKING | POST_TRAINING_LAUNCH | Public benchmark claims | A report that does not treat holdout as a marketing set | Not started | NOT_STARTED | A finished model | Out of the pre-training denominator |

## 9. P2 training infrastructure

| ID | Class | Phase | Source | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P2-1 | MANDATORY | PRE_TRAINING | `RSE12_06` §6 and the cloud-provider threat row | Attestation story for whatever compute is used. No provider is selected | Residual says provider root of trust is UNPROVEN | NOT_STARTED | G11 | Named environment plus attestation evidence |
| P2-2 | MANDATORY | PRE_TRAINING | R-EXF in `RSE12_06` §5 | Egress control that blocks training authorization until present | Residual text only | NOT_STARTED | G11 | Egress test |
| P2-3 | MANDATORY | PRE_TRAINING | C46, C47 | Counters and bit budget | Not implemented | NOT_STARTED | G10 | Those rows' evidence |
| P2-4 | MANDATORY | PRE_TRAINING | `MODEL_EVAL_AUTHORIZATION.json` | Spend cap greater than zero only if authorized | `max_spend_usd` is 0. `network_provider_inference_allowed` is false | NOT_AUTHORIZED | AUTH-2 | Founder changes the file. This register does not |

## 10. Training software and synthetic dry runs

| ID | Class | Phase | Source | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TRAIN-1 | MANDATORY | PRE_TRAINING | Training entry points under `orca/train/` and `pyproject.toml` extra `train` | A pinned, reproducible command and a lockfile for that extra | The extra lists version ranges. No hash lock for `train` was found in this pass. `uv.lock` is not what CI installs | NOT_STARTED | SUP-3 is the RSE extra only | A lock and a dry-run log on a named SHA |
| TRAIN-2 | MANDATORY | PRE_TRAINING | Authorization locks | A synthetic dry run that cannot flip training, corpus, or GPU locks | `rehearse` is described in the block-1 evidence note as returning not authorized. That note is not a dry-run log of a full trainer | NOT_STARTED | TRAIN-1 | Log shows locks still false after the run |
| TRAIN-3 | NONBLOCKING | PRE_TRAINING | Historical Phase 0.5 dataset notes under `docs/orneur/phase-0/` | Not this programme's corpus | Those notes say no training was started | HISTORICAL | None | Do not cite them as DATA-3 |

## 11. Cost, budget, GPU

| ID | Class | Phase | Source | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AUTH-1 | MANDATORY | PRE_TRAINING | Founder budget approval, which is not a file yet | A number, a currency, and a signature or equivalent owner record | No budget record found | NOT_VERIFIABLE | None | The record exists. Until then this row blocks 100% |
| AUTH-2 | MANDATORY | PRE_TRAINING | `MODEL_EVAL_AUTHORIZATION.json` | `gpu_allowed` true only after AUTH-1 and G12 | `gpu_allowed` false. `max_spend_usd` 0. Status `NOT_AUTHORIZED` | NOT_AUTHORIZED | AUTH-1, G12 | File change by the founder |
| AUTH-3 | MANDATORY | PRE_TRAINING | `orca/rse/imp1/locks.py` | `model_selection_authorized`, `qualification_authorized`, and `training_authorized` become true only by a real authorization, not by editing the return to true in secret | All three return false | NOT_AUTHORIZED | MODEL-1, G10, G12 | The authorization files and the functions agree, and a reviewer saw the diff |

## 12. Final integrated acceptance

| ID | Class | Phase | Source | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FINAL-1 | MANDATORY | PRE_TRAINING | This register's calculation rule | Numerator equals the pre-training denominator, and no mandatory row is `NOT_VERIFIABLE` | Numerator is 0. R65 and AUTH-1 and G1 are `NOT_VERIFIABLE` | NOT_STARTED | Every MANDATORY PRE_TRAINING row | An independent reviewer recomputes the count |
| FINAL-2 | MANDATORY | PRE_TRAINING | Founder execution authorization for the first Genesis training run | A record that names the SHA, the dataset manifest, the foundation revision, the spend cap, and the GPU permission | Not present | NOT_AUTHORIZED | FINAL-1 | The founder writes it. This register is not that writing |

## 13. Founder canonical rules

| ID | Class | Phase | Source | Evidence required | Current evidence | Status | Dependency | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R65 | MANDATORY | PRE_TRAINING | The founder's canonical 65 rules. A repository search found no file that contains that set | The source text, then one child row per rule with the same columns | No source. Child rules are not listed | NOT_VERIFIABLE | The source being added to the tree | Map each rule after the source exists. Do not invent rule text. 100% stays blocked while this row is `NOT_VERIFIABLE` |

## Reconciliation

| Item | Fact used above |
| --- | --- |
| main | `464b602f3f259b56f139c3304828baa660e6b860` |
| PR #8 | Open draft. Head `da567d927b61c41e253b42732aad249b5fdbb104`. Base `main`. Push run `37884389862` success. Not a review |
| PR #9 | Open draft. Head `c127780abbe6790cd0ba76beb6755615752af9b2`. Base is the PR #8 branch |
| PR #10 | Open draft. Head `f424dbf51eb8ed03f5fbe57cbd0ef3c2fa72fcdb`. Push run `37893124711` success, seven jobs. Not on main |
| PR #14 | Open draft. The three Phase 0 notes. This register does not replace them |
| PR #11, #12, #13 | Open. Heads `6e30dd9`, `63ece2a5dd673d69a06effdf766d7046f1973fc8`, `d21937941e823909a5a8594ffc04e2d45ef30183`. GitHub reviews length 0. Diffs not read |
| PR #5, #6 | Open. Not used as training evidence |

## Scope gaps

- The 65 rules have no source, so the pre-training denominator is not fully enumerable.
- G1 has no review artifact in the tree, so it is `NOT_VERIFIABLE` rather than failed.
- AUTH-1 has no budget document.
- Application PR diffs were not read. Their rows stay unreviewed on purpose.
- No hardware, corpus, qualification, or training evidence was created.
- This file is an author draft. Reviewer column is `NONE_RECORDED` on every row.

## Independent review request

Review this file only. Do not treat it as acceptance.

1. Confirm every G-row and C-row matches `RSE12_06` and that no acceptance slogan was used as evidence.
2. Confirm PR SHAs against GitHub.
3. Confirm `model_spec.py` and the two authorization JSON files match the MODEL and AUTH rows.
4. Confirm R65 lists no invented rules.
5. Confirm the pre-training percentage excludes APP and POST_TRAINING_LAUNCH rows.
6. Do not merge. Do not authorize a protected operation.
