# Antigravity Handoff — Requirement-integrity / safe-closure retest

## Freeze for independent retesting

1. Prior independently qualified remediation tip: `97d4c83a16f56fca3c934cd7954ae8db6cfeb6d1` — verdict **INDEPENDENTLY_QUALIFIED_ENGINEERING — LIMITED TO TESTED SCOPE**.
2. **Integrity code tip (probe + digest authority):** `3484d0372bd0bf04649fdc6c9b939b94fc4f912a` (TRAIN-2 probe avoids SyntheticOnlyGuard pollution; prior register-alignment tip `54bb272d4329b59c4694ff5ab41605a7dc6539c7`)
3. Preserve qualified remediation; do not re-litigate skip/SHA honesty unless digests/code change those paths.
4. Primary report: `ORNEUR_PRETRAINING_FOUNDATION_FINAL_MASTER_ENGINEERING_REPORT.md`
5. Eight-row reconciliation: `INDEPENDENT_AUDIT_EIGHT_ROW_RECONCILIATION.json`
6. Freeze package: `TRAINING_FREEZE_MANIFEST.json` — **NOT_FROZEN** / **NO-GO**
7. Formal acceptance: **0/95**. Training: **STRICT NO-GO**.

## What changed since 97d4c83 (targeted)

| Change | Why |
|---|---|
| Matrix remapped to `register_graph.json` `evidence_required` | Prior VERIFIED rows used unrelated implementations (e.g. C01→transformer, C02→tokenizer) |
| C01/C02 probes | Signed-registry unregistered id (ABSENT) + stale/unknown registry consumer refusal |
| G4/G5/AUTH-1 → **BLOCKED** | Founder purchase / ceremony / signed budget artifacts absent |
| DATA-1/DATA-2 → **IMPLEMENTED_UNVERIFIED** | No protected corpus / DATA-3-bound evidence |
| TRAIN-1/TRAIN-2 remapped | Hash-locked `requirements/train.txt` + synthetic dry-run locks-false evidence |
| Data admission | Recorded as **qualified uncounted** capability (no fabricated eighth ID) |
| Independently qualified counted IDs preserved | **C04, C05, C17, C18, C19, C20, C21** |

## Exact engineering-verified IDs (11)

`C01`, `C02`, `C04`, `C05`, `C17`, `C18`, `C19`, `C20`, `C21`, `TRAIN-1`, `TRAIN-2`

Histogram: `BLOCKED=19`, `IMPLEMENTED_UNVERIFIED=17`, `VERIFIED_ENGINEERING=11`, `NOT_IMPLEMENTED=48`

## Required confirmations

```bash
python scripts/acceptance/validate_register_graph.py --check
# expect: pretraining=95 numerator=0

python -m pytest \
  tests/rse/test_c01_c02_registry_refusal.py \
  tests/test_train2_dryrun_locks_evidence.py \
  tests/test_trainprep_lock_env.py \
  tests/rse/test_imp1_registry_crown.py \
  tests/rse/test_imp4_ocr1.py \
  tests/test_foundation02_requirement_matrix.py \
  -q
```

Confirm:

- C01/C02 implementations cite `orca/rse/imp1/*`, not genesis transformer/tokenizer
- G4/G5/AUTH-1 are BLOCKED
- DATA admission has `canonical_requirement_id: null` in reconciliation / matrix
- TRAIN-2 sample / lock snapshot show all locks false; gate NOT_AUTHORIZED
- Digests in probes match current implementation files
- No formal acceptance; training NO-GO

## Unresolved (do not waive)

- Founder: G1, G4, G5, G8, G10, AUTH-1, DEC-K, C08/C44, FINAL-2, DATA-3/DATA-5, MODEL-1/MODEL-2R, QUAL-1
- Physical HW / Crown / Forge / Witness / TPM / class-K
- C16 independent second codec
- Mainline merge G2/G3
- Journal/witness rows C09–C15/C45 remain IMPLEMENTED_UNVERIFIED

## Non-claims

Do not claim fully complete Phases 0–9.  
Do not treat VERIFIED_ENGINEERING as formal acceptance.  
Do not authorize training.
