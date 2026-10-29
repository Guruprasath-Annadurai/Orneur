# ORNEUR — PRETRAINING FOUNDATION FINAL MASTER ENGINEERING REPORT

**Generated (UTC):** 2026-10-29T13:56:39Z  
**Final engineering SHA:** `ad2b26fe054cad45c33f60da469fdbff31a9f652`  
**Prior qualified code SHA:** `4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4`  
**Training authorization:** **NO-GO**  
**Formal acceptance:** **0 / 95**  

## A. Programme summary

- Starting main SHA: `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`
- PR lineage: #138 FOUNDATION-02, #140 Phase 0/1 honesty + Phases 2-9 closure
- Honesty probe tip: `cd1e557a685b529c57bf4bf2f594b088cbeb5172`
- Disposition histogram: `{"BLOCKED": 16, "IMPLEMENTED_UNVERIFIED": 6, "NOT_IMPLEMENTED": 48, "VERIFIED_ENGINEERING": 25}`
- VERIFIED_ENGINEERING IDs: G4, G5, C01, C02, C04, C05, C09, C10, C11, C12, C13, C14, C17, C18, C19, C20, C21, C45, C15, DATA-1, DATA-2, QUAL-2, TRAIN-1, TRAIN-2, AUTH-1
- Readiness blockers: r65_unmapped, c27_unmet, trust_anchors_absent, protected_corpus_evidence_absent, private_evaluation_unfrozen, foundation_not_selected, compute_unqualified, independent_reviews_missing, real_data_licensing_unresolved, training_authorization_absent

## B. Phase-by-phase results

| Phase | Focus | Disposition |
|---:|---|---|
| 0 | Technical baseline | ENGINEERING_COMPLETE — AWAITING_INDEPENDENT_REVIEW |
| 1 | Evidence honesty / foundation software | ENGINEERING_COMPLETE — AWAITING_INDEPENDENT_REVIEW |
| 2 | RSE/security software (+ C27 investigation) | PARTIAL_ENGINEERING — physical/class-K blocked |
| 3 | GENESIS feasibility (analytical) | PARTIAL_ENGINEERING — DEC-K/MODEL blocked |
| 4 | Data pipeline (synthetic only) | PARTIAL_ENGINEERING — G8/DATA-3 blocked |
| 5 | Eval harness + holdout denial | PARTIAL_ENGINEERING — QUAL-1/private custody blocked |
| 6 | Hardware-trust boundary software | BLOCKED_BY_PROTECTED_DECISION (physical) |
| 7 | Training infra identity (CPU) | PARTIAL_ENGINEERING — GPU/P2 blocked |
| 8 | Integration preparation | BLOCKED_BY_PROTECTED_DECISION (mainline merge) |
| 9 | Freeze package NO-GO | ENGINEERING_COMPLETE package / NOT_FROZEN |
| 10 | Training execution | PROHIBITED |

### C27 feasibility

- Software can model generation counters and refuse a lower generation in synthetic tests, but C27 acceptance requires authorized class-K re-enrolment records from real hardware. Shipping a local counter file or mock TPM as PASS would be an unauthorized workaround and is refused.
- Disposition: `BLOCKED_BY_PROTECTED_DECISION`

### C16 codec

- `IMPLEMENTED_UNVERIFIED_PRIMARY_ONLY — awaiting independent second codec`

## C. Complete requirement accounting

| ID | Engineering | Formal | Independent | Physical | Missing / next action |
|---|---|---|---|---|---|
| G1 | `BLOCKED` | False | NOT_CLAIMED | False | Name a reviewer who did not author RSE-ARCH-1.2, and record where the review is stored. |
| G2 | `IMPLEMENTED_UNVERIFIED` | False | NOT_CLAIMED | False | The integration check still matches the manifest. |
| G3 | `IMPLEMENTED_UNVERIFIED` | False | NOT_CLAIMED | False | The merged SHA has its own main push CI and a review that is not a copied slogan. |
| G4 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | The authorization names the machines. This register does not purchase them. |
| G5 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A founder act changes the authorization. This register does not create a secret. |
| G6 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the operator who runs the acceptance. The reviewer is not that operator. Purchase stays on G4. |
| G7 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the Crown custodian. No purchase is authorized here. Purchase stays on G4. |
| G8 | `BLOCKED` | False | NOT_CLAIMED | False | The founder changes that file. This register does not. |
| G9 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the device. This row does not purchase it. Purchase stays on G4. |
| G10 | `BLOCKED` | False | NOT_CLAIMED | False | The reviewer accepts the design record. Runner authorization is QUAL-1, a separate artifact. |
| G11 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the P2 operator. No provider is selected here. |
| G12 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | The infrastructure record exists. GPU permission is FINAL-2, after readiness. |
| C01 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C02 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C04 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C05 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C09 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C10 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C11 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C12 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C13 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C14 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C17 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C18 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C19 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C20 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C21 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C45 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C15 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C03 | `IMPLEMENTED_UNVERIFIED` | False | NOT_CLAIMED | False | The verify log shows two distinct tokens. C08 remains its own row. |
| C06 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C07 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | A reviewer accepts this row's own artifact on the merged SHA. |
| C08 | `BLOCKED` | False | NOT_CLAIMED | False | Two physical tokens produce the log. This row does not create a secret by itself. |
| C16 | `IMPLEMENTED_UNVERIFIED` | False | NOT_CLAIMED | False | Name a second codec implementer who is not Cursor. |
| C44 | `BLOCKED` | False | NOT_CLAIMED | False | The single-token refusal is logged on hardware tokens. |
| C22 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C23 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C24 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C25 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C26 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C28 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C29 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C30 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C31 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C32 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C33 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C34 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C35 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C36 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C37 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| C38 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | Founder names the operator. This row authorizes no purchase and no secret. Purchase stays on G4. |
| DEC-K | `BLOCKED` | False | NOT_CLAIMED | False | The decision is recorded. C27 is still a separate mandatory row. |
| C27 | `BLOCKED` | False | NOT_CLAIMED | True | Do not implement class K under this row. Wait for a founder architecture-change authorization that is not this register. |
| C39 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | The comparison record is accepted. SUP-1's harness log is not this comparison. |
| C40 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | The floor-check log is accepted together with a sealed floor. C41 remains separate. |
| C41 | `BLOCKED` | False | NOT_CLAIMED | True | The receipt names both serials. |
| C42 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | The below-floor kit is refused in the log. |
| C43 | `BLOCKED` | False | NOT_CLAIMED | True | The epoch record exists and contains no secret. |
| C46 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | The budget log is accepted. C47 is a separate monotonicity artifact. |
| C47 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Name the chamber operator. A synthetic counter is not this artifact. |
| C48 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | A reviewer accepts this row's own artifact on the merged SHA. |
| C49 | `BLOCKED` | False | NOT_CLAIMED | False | The registry entry is accepted. The selection record remains MODEL-1. |
| C50 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the operator who runs the drill. Purchase stays on G4. |
| HW-01 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-02 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-03 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-06 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-08 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-11 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-16 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-18 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-19 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-20 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-21 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-24 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names a P1 operator who is not the reviewer. No purchase is authorized by this row. |
| HW-FORGE | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the Forge custodian. No purchase is authorized here. Purchase stays on G4. |
| SUP-1 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | C39's comparison exists. A harness repair log does not pass C39. |
| SUP-3 | `IMPLEMENTED_UNVERIFIED` | False | NOT_CLAIMED | False | The same job is green on the merge commit on main. |
| P2-1 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | Founder names the environment operator. No provider contract is authorized here. |
| P2-2 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | The egress test log is accepted. |
| P2-4 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | True | The refusal test is accepted. Raising the cap is FINAL-2. |
| DATA-1 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | Founder names who assembles the manifest. This row generates no corpus. |
| DATA-2 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | The oracle output is accepted. G8 does not pass this row. |
| DATA-3 | `BLOCKED` | False | NOT_CLAIMED | False | Founder names the corpus operator after G8. This row does not generate a corpus and does not implement class K. |
| DATA-5 | `BLOCKED` | False | NOT_CLAIMED | False | Founder names a custodian who did not create the corpus. This row does not generate a corpus. |
| MODEL-2R | `BLOCKED` | False | NOT_CLAIMED | False | The research-only scope record exists. Commercial rights remain MODEL-2C. |
| MODEL-1 | `BLOCKED` | False | NOT_CLAIMED | False | The selection record exists and stays inside the research-only scope. It does not set training_authorized(). |
| QUAL-1 | `BLOCKED` | False | NOT_CLAIMED | False | The founder changes the runner state. This register does not. |
| QUAL-2 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | The failed-read log is accepted. |
| QUAL-3 | `NOT_IMPLEMENTED` | False | NOT_CLAIMED | False | The threshold freeze is recorded before a candidate run. |
| TRAIN-1 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | The lock and the command log name the same SHA. |
| TRAIN-2 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | The log shows the locks still false. The run does not flip them. |
| AUTH-1 | `VERIFIED_ENGINEERING` | False | NOT_CLAIMED | False | The record exists. Until then this row blocks a readiness percentage. |
| R65 | `BLOCKED` | False | NOT_CLAIMED | False | Founder supplies the complete exact text. Do not paraphrase it. |
| FINAL-1 | `IMPLEMENTED_UNVERIFIED` | False | NOT_CLAIMED | False | The worksheet matches a fresh run of the validator. Founder authorization is still FINAL-2. |

## D. Native model status

- GENESIS: `INTERFACE_ONLY` — arch `genesis-arch-v1`, tier `10M-smoke`, params `10350864`
- NOVUS: `NOT_AVAILABLE`
- AETERNUM: `NOT_AVAILABLE`
- Official foundation selected: **False**
- Weights downloaded: **False**
- Frontier pretraining available: **False**
- Available compute: synthetic_cpu: developer CPU, unit-test process (frontier_pretraining=False)

## E. Security and governance

- Authorization remains fail-closed / NOT_AUTHORIZED / empty registry.
- Audit-tail truncation residual remains P2 (strict xfail ≠ PASS).
- Trust anchors / founder signatures not fabricated.
- Physical HW gates refuse mock-as-acceptance.
- Freeze package status: `NOT_FROZEN` / `NO-GO`

## F. Final qualification evidence

- Candidate SHA: `ad2b26fe054cad45c33f60da469fdbff31a9f652`
- Artifact digests: `{"freeze_manifest": "12e73b25969292a36a9ac70369e8950835ec3a54305f34f8d16dd29b24331972", "ledger": "37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570", "matrix": "c897b730520ff840e2f98913f14c25f8477ae6a2544c635f484d73dd0fcced56", "probes": "96bc0eae393f5f4f9d7761c3817d287de296bc30a520e47bd41036bd36cc7bf5", "register_graph": "b8f745182ddb6d4ff25d79a542e5242986901790ee4195186143bfb78039aaf7"}`
- Reproduction:
  - `python scripts/acceptance/validate_register_graph.py --check`
  - `python -m pytest tests/test_foundation02_probe_honesty.py tests/test_pretraining_phase_closure.py -q`
  - `python scripts/foundation02/build_requirement_matrix.py`
  - `python scripts/foundation02/build_final_master_report.py`

## G. Honest final disposition

- **engineering_completed:** Phase 0/1 evidence honesty; RSE software probes for C04-C15/C17-C21/C45; QUAL-2 holdout denial; Phase 2-9 boundary modules; freeze package NO-GO
- **engineering_incomplete:** Physical/custody HW gates; independent second codec (C16); mainline merge (G2/G3); formal acceptance process
- **founder_controlled_blockers:** G1, G8, G10, DEC-K, C08, C44, C27, R65, DATA-3, DATA-5, MODEL-1, MODEL-2R, QUAL-1, FINAL-2
- **external_blockers:** C22, C23, C24, C25, C26, C27, C28, C39, C40, C41, C42, C43, C46, C47, C48, C50, G11, G6, G7, G9, HW-01, HW-02, HW-03, HW-06, HW-08, HW-11, HW-16, HW-18, HW-19, HW-20, HW-21, HW-24, HW-FORGE, P2-1, P2-2, P2-4
- **independent_qualification_pending:** True
- **formal_acceptance_count:** 0/95
- **training_authorization_status:** NO-GO

This report is engineering evidence for CTO review and Antigravity audit. It is **not** formal acceptance and **not** training authorization.
