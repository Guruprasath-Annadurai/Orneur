# FOUNDATION-02 Requirement Matrix

**Candidate SHA:** `ad2b26fe054cad45c33f60da469fdbff31a9f652`  
**Prior qualified code SHA:** `4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4`  
**Main base SHA:** `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`  
**Formal acceptance:** 0 / 95  
**Validator:** `pretraining=95 numerator=0`  
**Training authorization:** **NO-GO**  
**VERIFIED_ENGINEERING (honest probes):** 25 — G4, G5, C01, C02, C04, C05, C09, C10, C11, C12, C13, C14, C17, C18, C19, C20, C21, C45, C15, DATA-1, DATA-2, QUAL-2, TRAIN-1, TRAIN-2, AUTH-1  

## Disposition histogram (engineering only)

| Disposition | Count |
|---|---:|
| `BLOCKED` | 16 |
| `IMPLEMENTED_UNVERIFIED` | 6 |
| `NOT_IMPLEMENTED` | 48 |
| `VERIFIED_ENGINEERING` | 25 |

## VERIFIED_ENGINEERING evidence

| ID | Historical SHA | Candidate SHA | Tests | Result |
|---|---|---|---|---|
| G4 | `fc1eb1d` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/test_training_authorization_assurance.py | PASS (23 passed, 1 xfailed in 0.86s) passed=23 xfailed=1 skipped=0 |
| G5 | `fc1eb1d` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/test_training_authorization_gate.py | PASS (92 passed, 1 warning in 3.04s) passed=92 xfailed=0 skipped=0 |
| C01 | `fc1eb1d` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/test_genesis_model_architecture.py | PASS (23 passed in 1.23s) passed=23 xfailed=0 skipped=0 |
| C02 | `fc1eb1d` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/test_genesis_tokenizer.py; tests/test_cursor_tokenizer_robustness.py | PASS (34 passed in 0.34s) passed=34 xfailed=0 skipped=0 |
| C04 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp1_registry_crown.py | PASS (16 passed in 0.31s) passed=16 xfailed=0 skipped=0 |
| C05 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp1_registry_crown.py | PASS (16 passed in 0.31s) passed=16 xfailed=0 skipped=0 |
| C09 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp3_ledger.py | PASS (15 passed in 0.33s) passed=15 xfailed=0 skipped=0 |
| C10 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp3_ledger.py | PASS (15 passed in 0.33s) passed=15 xfailed=0 skipped=0 |
| C11 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_block1_remediation.py; tests/rse/test_imp2_machine.py | PASS (25 passed in 0.42s) passed=25 xfailed=0 skipped=0 |
| C12 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp3_ledger.py | PASS (15 passed in 0.33s) passed=15 xfailed=0 skipped=0 |
| C13 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp3_ledger.py | PASS (15 passed in 0.33s) passed=15 xfailed=0 skipped=0 |
| C14 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp3_ledger.py | PASS (15 passed in 0.33s) passed=15 xfailed=0 skipped=0 |
| C17 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp4_ocr1.py | PASS (22 passed in 0.42s) passed=22 xfailed=0 skipped=0 |
| C18 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp4_ocr1.py | PASS (22 passed in 0.42s) passed=22 xfailed=0 skipped=0 |
| C19 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp4_ocr1.py | PASS (22 passed in 0.42s) passed=22 xfailed=0 skipped=0 |
| C20 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp4_ocr1.py | PASS (22 passed in 0.42s) passed=22 xfailed=0 skipped=0 |
| C21 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp4_ocr1.py | PASS (22 passed in 0.43s) passed=22 xfailed=0 skipped=0 |
| C45 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp2_machine.py | PASS (13 passed in 0.25s) passed=13 xfailed=0 skipped=0 |
| C15 | `b384348` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/rse/test_imp3_ledger.py; tests/rse/test_block1_remediation.py | PASS (27 passed in 0.47s) passed=27 xfailed=0 skipped=0 |
| DATA-1 | `fc1eb1d` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/test_genesis_data_manifest.py; tests/test_cursor_pipeline_admission.py | PASS (37 passed in 0.40s) passed=37 xfailed=0 skipped=0 |
| DATA-2 | `fc1eb1d` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/test_genesis_data_contamination.py | PASS (18 passed in 0.31s) passed=18 xfailed=0 skipped=0 |
| QUAL-2 | `cd1e557` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/test_pretraining_phase_closure.py; tests/test_cursor_eval_integrity.py | PASS (19 passed in 0.33s) passed=19 xfailed=0 skipped=0 |
| TRAIN-1 | `fc1eb1d` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/test_cursor_training_math.py; tests/test_genesis_training_primitives.py | PASS (30 passed in 2.20s) passed=30 xfailed=0 skipped=0 |
| TRAIN-2 | `fc1eb1d` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/test_genesis_checkpoint_integrity.py; tests/test_genesis_resumable_checkpoint.py | PASS (52 passed in 9.14s) passed=52 xfailed=0 skipped=0 |
| AUTH-1 | `fc1eb1d` | `ad2b26fe054cad45c33f60da469fdbff31a9f652` | tests/test_training_authorization_gate.py; tests/test_genesis_governance_authorization.py | PASS (128 passed, 1 warning in 3.21s) passed=128 xfailed=0 skipped=0 |

## All rows

| ID | Register status | Engineering disposition | Founder-controlled |
|---|---|---|---|
| G1 | NOT_VERIFIABLE | `BLOCKED` | False |
| G2 | PRESENT_ON_MAIN | `IMPLEMENTED_UNVERIFIED` | False |
| G3 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| G4 | NOT_AUTHORIZED | `VERIFIED_ENGINEERING` | True |
| G5 | NOT_AUTHORIZED | `VERIFIED_ENGINEERING` | True |
| G6 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| G7 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| G8 | NOT_AUTHORIZED | `BLOCKED` | True |
| G9 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| G10 | NOT_AUTHORIZED | `BLOCKED` | False |
| G11 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| G12 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C01 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C02 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C04 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C05 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C09 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C10 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C11 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C12 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C13 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C14 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C17 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C18 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C19 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C20 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C21 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C45 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C15 | UNMERGED_NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| C03 | DESIGNED_ONLY | `IMPLEMENTED_UNVERIFIED` | False |
| C06 | DESIGNED_ONLY | `NOT_IMPLEMENTED` | False |
| C07 | DESIGNED_ONLY | `NOT_IMPLEMENTED` | False |
| C08 | NOT_AUTHORIZED | `BLOCKED` | True |
| C16 | DESIGNED_ONLY | `IMPLEMENTED_UNVERIFIED` | False |
| C44 | NOT_AUTHORIZED | `BLOCKED` | True |
| C22 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C23 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C24 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C25 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C26 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C28 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C29 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C30 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C31 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C32 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C33 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C34 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C35 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C36 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C37 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C38 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| DEC-K | NOT_AUTHORIZED | `BLOCKED` | True |
| C27 | NOT_STARTED | `BLOCKED` | True |
| C39 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C40 | DESIGNED_ONLY | `NOT_IMPLEMENTED` | False |
| C41 | NOT_STARTED | `BLOCKED` | True |
| C42 | DESIGNED_ONLY | `NOT_IMPLEMENTED` | False |
| C43 | NOT_STARTED | `BLOCKED` | True |
| C46 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C47 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| C48 | DESIGNED_ONLY | `NOT_IMPLEMENTED` | False |
| C49 | NOT_STARTED | `BLOCKED` | True |
| C50 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-01 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-02 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-03 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-06 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-08 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-11 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-16 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-18 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-19 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-20 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-21 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-24 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| HW-FORGE | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| SUP-1 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| SUP-3 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| P2-1 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| P2-2 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| P2-4 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| DATA-1 | NOT_ACCEPTED | `VERIFIED_ENGINEERING` | False |
| DATA-2 | NOT_STARTED | `VERIFIED_ENGINEERING` | False |
| DATA-3 | NOT_STARTED | `BLOCKED` | False |
| DATA-5 | NOT_STARTED | `BLOCKED` | False |
| MODEL-2R | NOT_AUTHORIZED | `BLOCKED` | True |
| MODEL-1 | NOT_AUTHORIZED | `BLOCKED` | True |
| QUAL-1 | NOT_AUTHORIZED | `BLOCKED` | True |
| QUAL-2 | NOT_STARTED | `VERIFIED_ENGINEERING` | False |
| QUAL-3 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
| TRAIN-1 | NOT_STARTED | `VERIFIED_ENGINEERING` | False |
| TRAIN-2 | NOT_STARTED | `VERIFIED_ENGINEERING` | False |
| AUTH-1 | NOT_VERIFIABLE | `VERIFIED_ENGINEERING` | True |
| R65 | NOT_VERIFIABLE | `BLOCKED` | True |
| FINAL-1 | NOT_STARTED | `IMPLEMENTED_UNVERIFIED` | False |

## Policy

- This matrix does **not** modify `acceptance_ledger.json`.
- A passed engineering test does not become `FORMALLY_ACCEPTED`.
- Training authorization remains **NO-GO**.
- Exit code 0 with zero collected / skip-only / xfail-only is **not** VERIFIED_ENGINEERING.
- `xfailed` residuals are distinguished from `passed`; an xfail is not a PASS.
- Probe commands must not embed machine-specific interpreter or site-package paths.
- `historical_source_sha` ≠ proof the tip was the only SHA ever tested; probes run on `candidate_sha`.
