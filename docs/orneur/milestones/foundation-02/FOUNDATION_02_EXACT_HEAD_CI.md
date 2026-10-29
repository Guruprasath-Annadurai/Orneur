# FOUNDATION-02 Exact-Head CI

**Starting SHA:** `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`  
**Reviewed candidate:** `b384348fa3bc789585bf69d81a772c8a4d75d493`  
**Corrective tip:** `442e9cfb26700153ca1ae2d939ca3081eb8d21ff` (awaiting CI)  
**CI URL:** _filled after green run on corrective tip_

## Local corrective verification

- Serving-contract adversarial suite: 15 passed
- Matrix integrity: 4 passed
- Probe-backed matrix rebuild: VERIFIED_ENGINEERING=9
- Acceptance validator: `pretraining=95 numerator=0`

## Rules

- Skip ≠ PASS; xfail ≠ PASS
- Engineering CI ≠ independent qualification
- Synthetic ≠ live training
