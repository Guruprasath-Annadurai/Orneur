# Hardware Trust Evidence (Phase 6)

**Disposition:** `BLOCKED_BY_PROTECTED_DECISION`  
**Training authorization:** **NO-GO**

## Software boundary

`orca/pretrain_foundation/hardware_evidence_boundary.py` classifies physical-adjacent claims and **refuses mock/synthetic evidence as physical acceptance**.

Covered requirement families include G6/G7/G9/G11, C22–C28, C39–C43, C46–C50, HW-*, P2-*.

## Physical evidence status

**Not present in this environment.** No TPM quotes, Secure Boot key lists, Crown/Forge serial custody receipts, or floor-card comparisons were fabricated.

Minimum prerequisite for each blocked physical row: authorized real hardware + independently checked receipt artifacts.
