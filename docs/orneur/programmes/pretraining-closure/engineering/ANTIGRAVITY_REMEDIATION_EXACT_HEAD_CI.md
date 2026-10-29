# Antigravity remediation — exact-head CI binding

| Item | Value |
|---|---|
| Remediation code tip (probe authority) | `78e6ad65617741cd92af6df4b4a37543930e4ced` |
| Evidence commit tip | `42a3b79b0d82ff1655f4c02c23c1e0837be85d0f` |
| Exact-head green tip (branch HEAD) | `7609602ea322093151c8264ff71831291ebb6537` |
| CI | [40894646633](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40894646633) — **9/9 success** |
| Deterministic | `9041 passed, 389 skipped, 43 deselected, 7 xfailed` |
| Formal acceptance | **0/95** |
| Training | **NO-GO** |
| VERIFIED_ENGINEERING | **16** |
| Disposition histogram | `BLOCKED=16`, `IMPLEMENTED_UNVERIFIED=15`, `VERIFIED_ENGINEERING=16`, `NOT_IMPLEMENTED=48` |
| Nine downgrades | C09, C10, C11, C12, C13, C14, C15, C45, QUAL-2 |

Implementation digests in `FOUNDATION_02_VERIFICATION_PROBES.json` were regenerated on the remediation code tip, including `orca/genesis/data/pipeline.py`.

Mandatory probe suites for VERIFIED rows recorded **zero skips**. Global CI suite skips remain non-qualification residual and do not mint VERIFIED_ENGINEERING.
