# Antigravity Handoff — Targeted Retest (PARTIALLY_QUALIFIED remediation)

## Freeze for independent retesting

1. Prior independently tested FOUNDATION-02 code SHA: `4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4` (CI `40860060023`).
2. Audited defective tip (PARTIALLY_QUALIFIED): `98069d833051c18a46f3fcfd42011cf7c83f7f6c`.
3. **Remediation code-bearing tip (probe + digest authority):** `78e6ad65617741cd92af6df4b4a37543930e4ced`
4. Exact-head green tip `7609602ea322093151c8264ff71831291ebb6537` on `cursor/foundation-02-phase1-evidence-closure-8108` (PR #140). Test Suite [`40894646633`](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40894646633) — 9/9 success (`9041 passed, 389 skipped, 43 deselected, 7 xfailed`). See `ANTIGRAVITY_REMEDIATION_EXACT_HEAD_CI.md`.
5. Evidence/docs commits after the code tip may advance HEAD; **do not treat docs-only commits as a new code tip**. Digests in `FOUNDATION_02_VERIFICATION_PROBES.json` must match files at the remediation code tip (and still match after docs-only commits that do not touch implementation paths).
6. Primary report: `ORNEUR_PRETRAINING_FOUNDATION_FINAL_MASTER_ENGINEERING_REPORT.md`
7. Evidence manifest: `FINAL_EVIDENCE_MANIFEST.json`
8. Freeze package: `TRAINING_FREEZE_MANIFEST.json` — status **NOT_FROZEN** / **NO-GO**

## Corrected defects (must reproduce as refusals)

| ID | Prior Antigravity repro | Required corrected behavior |
|---|---|---|
| P1 | `12 passed, 22 skipped` → `passed_probe=True` | `passed_probe=False`, `SKIPS_PRESENT` |
| P2 | `recorded_candidate_sha=None` silent pass | `CANDIDATE_SHA_MISSING` (also empty/malformed) |
| Gate A | matrix/probes SHA `ad2b26f` lagging tip; stale `pipeline.py` digest | probes/matrix `candidate_sha=78e6ad6…`; `pipeline.py` digest matches file |
| Matrix | 25 VERIFIED including unsupported rows | nine downgrades → **16** VERIFIED; histogram honest |

### Nine remediation downgrades (IMPLEMENTED_UNVERIFIED)

`C09`, `C10`, `C11`, `C12`, `C13`, `C14`, `C15`, `C45`, `QUAL-2`

Original acceptance conditions are **not** replaced by software-test probes.

### Remaining VERIFIED_ENGINEERING (16)

`G4`, `G5`, `C01`, `C02`, `C04`, `C05`, `C17`, `C18`, `C19`, `C20`, `C21`, `DATA-1`, `DATA-2`, `TRAIN-1`, `TRAIN-2`, `AUTH-1`

## Required confirmations

```bash
python scripts/acceptance/validate_register_graph.py --check
# expect: pretraining=95 numerator=0

python -m pytest \
  tests/test_foundation02_probe_honesty.py \
  tests/test_foundation02_requirement_matrix.py \
  tests/test_pretraining_phase_closure.py \
  tests/test_pretraining_call_chain_integration.py \
  -q

# Mixed skip must refuse:
python - <<'PY'
from orca.pretrain_foundation.probe_honesty import classify_probe
v=classify_probe(exit_code=0, stdout="12 passed, 22 skipped in 0.73s\n",
    expected_candidate_sha="78e6ad65617741cd92af6df4b4a37543930e4ced",
    recorded_candidate_sha="78e6ad65617741cd92af6df4b4a37543930e4ced")
assert v.passed_probe is False and "SKIPS_PRESENT" in v.refusal_codes
print("P1 fixed")
v2=classify_probe(exit_code=0, stdout="10 passed in 0.2s\n",
    expected_candidate_sha="78e6ad65617741cd92af6df4b4a37543930e4ced",
    recorded_candidate_sha=None)
assert v2.passed_probe is False and "CANDIDATE_SHA_MISSING" in v2.refusal_codes
print("P2 fixed")
PY
```

Confirm:

- Ledger empty; formal acceptance **0/95**
- Training authorization **NO-GO**
- Probes schema v3; complete 40-hex candidate SHAs; zero skips on VERIFIED rows
- Implementation digests match current files (especially `orca/genesis/data/pipeline.py`)
- Call-chain tests cover corpus remote refusal, training-bound license jail, and finetune auth choke point
- Hardware boundary refuses synthetic-as-acceptance
- C27 unauthorized class-K workaround refused
- C16 Cursor self-cert as second codec refused
- Phases 0–9 are **not** claimed fully complete while protected gates remain open

## Unresolved findings (do not waive)

- Founder: G1, G8, G10, DEC-K, R65, C08/C44, FINAL-2, DATA-3/DATA-5, MODEL-1/MODEL-2R, QUAL-1
- Physical: HW-*, Crown/Forge/Witness custody, TPM/Secure Boot/attestation, C27 class-K path, P2 env
- Independent second OCR1 codec (C16)
- Mainline merge + exact-mainline CI (G2/G3)
- Audit-tail external sealed anchor (P2 residual)
- Nine downgraded rows pending original acceptance artifacts

## Non-claims

Do **not** inherit Cursor self-cert as G13.  
Do **not** authorize training.  
Do **not** treat engineering VERIFIED rows as formal acceptance.  
Do **not** claim fully complete Phases 0–9 while protected or external mandatory gates remain open.
