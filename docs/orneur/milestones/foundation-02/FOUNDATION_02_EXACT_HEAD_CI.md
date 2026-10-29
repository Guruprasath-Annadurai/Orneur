# FOUNDATION-02 Exact-Head CI

**Starting SHA:** `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`  
**Reviewed candidate:** `b384348fa3bc789585bf69d81a772c8a4d75d493`  
**Code corrective SHA:** `442e9cfb26700153ca1ae2d939ca3081eb8d21ff`  
**Matrix probe SHA:** `9ea450123f1a0f8ec34a6e92be50c216cea51326`  
**Branch tip:** _filled after push_  
**CI URL:** _filled after green run on tip_

## Local corrective verification

- Serving-contract adversarial: **15 passed**
- Matrix integrity: **4 passed**
- Probe-backed VERIFIED_ENGINEERING: **9** — G4, G5, C01, C02, DATA-1, DATA-2, TRAIN-1, TRAIN-2, AUTH-1
- Disposition: `{"BLOCKED": 16, "IMPLEMENTED_UNVERIFIED": 19, "VERIFIED_ENGINEERING": 9, "NOT_IMPLEMENTED": 51}`
- Acceptance validator: `pretraining=95 numerator=0`
- Audit-tail residual: P2 documented; strict xfail remains (not a pass)

## Rules

- Skip ≠ PASS; xfail ≠ PASS
- Engineering CI ≠ independent qualification
- Synthetic ≠ live training
