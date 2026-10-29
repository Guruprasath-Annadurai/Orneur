# Antigravity Handoff — Pretraining Closure (Phases 0–9 engineering)

## Freeze for independent testing

1. Prior independently tested FOUNDATION-02 code SHA: `4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4` (CI `40860060023`).
2. Honesty tip: `cd1e557a685b529c57bf4bf2f594b088cbeb5172`.
3. Retest exact-head green tip `98069d833051c18a46f3fcfd42011cf7c83f7f6c` on `cursor/foundation-02-phase1-evidence-closure-8108` (PR #140). Test Suite [`40887059729`](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40887059729) — 9/9 success (`9022 passed, 389 skipped, 43 deselected, 7 xfailed`). See `PHASES_2_9_EXACT_HEAD_CI.md`. Engineering probe tip remains `ad2b26fe054cad45c33f60da469fdbff31a9f652`.
4. Primary report: `ORNEUR_PRETRAINING_FOUNDATION_FINAL_MASTER_ENGINEERING_REPORT.md`
5. Evidence manifest: `FINAL_EVIDENCE_MANIFEST.json`
6. Freeze package: `TRAINING_FREEZE_MANIFEST.json` — status **NOT_FROZEN** / **NO-GO**

## Required confirmations

```bash
python scripts/acceptance/validate_register_graph.py --check
# expect: pretraining=95 numerator=0

python -m pytest \
  tests/test_foundation02_probe_honesty.py \
  tests/test_foundation02_requirement_matrix.py \
  tests/test_pretraining_phase_closure.py \
  -q

python scripts/foundation02/build_requirement_matrix.py
python scripts/foundation02/build_final_master_report.py
```

Confirm:

- Ledger empty; formal acceptance **0/95**
- Training authorization **NO-GO**
- Probes schema v3; no `/home/ubuntu/` machine paths in recorded argv
- xfail/skip/zero-collected cannot become VERIFIED_ENGINEERING
- Hardware boundary refuses synthetic-as-acceptance
- C27 unauthorized class-K workaround refused
- C16 Cursor self-cert as second codec refused
- G4 audit-tail strict xfail remains failing (≠ PASS)

## Unresolved findings (do not waive)

- Founder: G1, G8, G10, DEC-K, R65, C08/C44, FINAL-2, DATA-3/DATA-5, MODEL-1/MODEL-2R, QUAL-1
- Physical: HW-*, Crown/Forge/Witness custody, TPM/Secure Boot/attestation, C27 class-K path, P2 env
- Independent second OCR1 codec (C16)
- Mainline merge + exact-mainline CI (G2/G3)
- Audit-tail external sealed anchor (P2 residual)

## Non-claims

Do **not** inherit Cursor self-cert as G13.  
Do **not** authorize training.  
Do **not** treat engineering VERIFIED rows as formal acceptance.
