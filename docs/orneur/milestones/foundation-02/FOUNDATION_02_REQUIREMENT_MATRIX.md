# FOUNDATION-02 Requirement Matrix

**Candidate SHA:** `b384348fa3bc789585bf69d81a772c8a4d75d493`  
**Main base SHA:** `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`  
**Formal acceptance:** 0 / 95  
**Validator:** `pretraining=95 numerator=0`  
**VERIFIED_ENGINEERING (probed):** 9 — G4, G5, C01, C02, DATA-1, DATA-2, TRAIN-1, TRAIN-2, AUTH-1  

## Disposition histogram (engineering only)

| Disposition | Count |
|---|---:|
| `BLOCKED` | 16 |
| `IMPLEMENTED_UNVERIFIED` | 19 |
| `NOT_IMPLEMENTED` | 51 |
| `VERIFIED_ENGINEERING` | 9 |

## VERIFIED_ENGINEERING evidence

| ID | Historical SHA | Candidate SHA | Tests | Result |
|---|---|---|---|---|
| G4 | `fc1eb1d` | `b384348fa3bc789585bf69d81a772c8a4d75d493` | tests/test_training_authorization_assurance.py | PASS (23 passed, 1 xfailed in 0.91s) |
| G5 | `fc1eb1d` | `b384348fa3bc789585bf69d81a772c8a4d75d493` | tests/test_training_authorization_gate.py | PASS (92 passed, 1 warning in 3.11s) |
| C01 | `fc1eb1d` | `b384348fa3bc789585bf69d81a772c8a4d75d493` | tests/test_genesis_model_architecture.py | PASS (23 passed in 1.20s) |
| C02 | `fc1eb1d` | `b384348fa3bc789585bf69d81a772c8a4d75d493` | tests/test_genesis_tokenizer.py; tests/test_cursor_tokenizer_robustness.py | PASS (34 passed in 0.36s) |
| DATA-1 | `fc1eb1d` | `b384348fa3bc789585bf69d81a772c8a4d75d493` | tests/test_genesis_data_manifest.py; tests/test_cursor_pipeline_admission.py | PASS (37 passed in 0.48s) |
| DATA-2 | `fc1eb1d` | `b384348fa3bc789585bf69d81a772c8a4d75d493` | tests/test_genesis_data_contamination.py | PASS (18 passed in 0.33s) |
| TRAIN-1 | `fc1eb1d` | `b384348fa3bc789585bf69d81a772c8a4d75d493` | tests/test_cursor_training_math.py; tests/test_genesis_training_primitives.py | PASS (30 passed in 2.10s) |
| TRAIN-2 | `fc1eb1d` | `b384348fa3bc789585bf69d81a772c8a4d75d493` | tests/test_genesis_checkpoint_integrity.py; tests/test_genesis_resumable_checkpoint.py | PASS (52 passed in 8.90s) |
| AUTH-1 | `fc1eb1d` | `b384348fa3bc789585bf69d81a772c8a4d75d493` | tests/test_training_authorization_gate.py; tests/test_genesis_governance_authorization.py | PASS (128 passed, 1 warning in 3.35s) |

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
| C04 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C05 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C09 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C10 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C11 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C12 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C13 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C14 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C17 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C18 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C19 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C20 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C21 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C45 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C15 | UNMERGED_NOT_ACCEPTED | `IMPLEMENTED_UNVERIFIED` | False |
| C03 | DESIGNED_ONLY | `NOT_IMPLEMENTED` | False |
| C06 | DESIGNED_ONLY | `NOT_IMPLEMENTED` | False |
| C07 | DESIGNED_ONLY | `NOT_IMPLEMENTED` | False |
| C08 | NOT_AUTHORIZED | `BLOCKED` | True |
| C16 | DESIGNED_ONLY | `NOT_IMPLEMENTED` | False |
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
| QUAL-2 | NOT_STARTED | `NOT_IMPLEMENTED` | False |
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
- `historical_source_sha` ≠ proof the tip was the only SHA ever tested; probes run on `candidate_sha`.
