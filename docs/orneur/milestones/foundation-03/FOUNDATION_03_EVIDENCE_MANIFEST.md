# FOUNDATION-03 Evidence Manifest — C06 / C07

Exact-SHA binding for FOUNDATION-03 engineering verification.  
**No formal acceptance claim. Formal acceptance unchanged at 0/95.**

## SHAs

| Role | SHA |
|---|---|
| Baseline (PR #140 qualified HEAD) | `649d90f84069fc618ba4d69b4c26a66bed731caa` |
| PR #140 branch | `cursor/foundation-02-phase1-evidence-closure-8108` |
| Qualified code tip (impl + tests) | `0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51` |
| Parent of qualified code tip | `649d90f84069fc618ba4d69b4c26a66bed731caa` |
| Antigravity independent qualification | `75a7a648984d9883774292f35a511089e6ffd474` |

Branch: `cursor/foundation-03-rse-consumer-verification-9658`  
Draft PR: https://github.com/Guruprasath-Annadurai/Orneur/pull/142  
PR base (retargeted): `cursor/foundation-02-phase1-evidence-closure-8108`

## Implementation artifacts (qualified code tip `0fe98e0`)

| Path | Purpose |
|---|---|
| `orca/rse/imp1/consumer_verification.py` | C06 rendered-card evidence + C07 typed-entry record path |
| `tests/rse/test_c06_c07_consumer_verification.py` | Adversarial + positive engineering probes |

## Handoff / closure artifacts (this milestone docs commit)

| Path | Purpose |
|---|---|
| `docs/orneur/milestones/foundation-03/FOUNDATION_03_ENGINEERING_REPORT.md` | Engineering report + limitations |
| `docs/orneur/milestones/foundation-03/FOUNDATION_03_EVIDENCE_MANIFEST.md` | This manifest |
| `docs/orneur/milestones/foundation-03/FOUNDATION_03_ANTIGRAVITY_HANDOFF.md` | Independent qualification handoff + `75a7a64` verdict |

## Evidence artifact schemas

### C06 — rendered-card digest

- `requirement_id`: `C06`
- `grant_raw_digest` / `signed_region_digest` / `card` / `card_digest`
- `binding_digest`: SHA-256(`OCR-C06-CARD-v1` ‖ 0x00 ‖ grant_raw ‖ 0x00 ‖ card_utf8)
- `authority_usable`: always `false`

Acceptance condition addressed: *“Rendered-card digest showing the consumer rendered the received signed bytes.”*  
**Limitation:** in-memory rendering + crypto binding — **not** operator observation of a physical/GUI display (Antigravity `75a7a64`).

### C07 — typed-entry record

- `requirement_id`: `C07`
- `typed_sas` / `computed_sas` (60-bit, `OCR-SAS-v1`)
- `typed_intent` / `grant_derived_intent` (public fields only)
- `record_digest`: SHA-256(`OCR-C07-TYPED-v1` ‖ 0x00 ‖ canonical JSON body)
- `authority_usable`: always `false`

Acceptance condition addressed: *“Typed-entry record for the SAS and the Intent Sheet fields.”*  
**Limitation:** software SAS/Intent Sheet comparison — **not** proof of genuine independent human entry; tautological derivation from the grant can satisfy the machine check while authority stays denied (Antigravity `75a7a64`).

## Local verification (qualified code tip `0fe98e0`)

| Command | Result |
|---|---|
| `python -m pytest tests/rse/test_c06_c07_consumer_verification.py -v` | **16 passed** |
| `python -m pytest tests/rse/ -q` | **130 passed** |
| `python scripts/acceptance/validate_register_graph.py --check` | `pretraining=95 numerator=0 application=3 execution=2 post=1` |

## Exact-head CI (qualified code tip `0fe98e0`)

| Field | Value |
|---|---|
| Status | **GREEN** — all 19 checks success, 0 failures |
| Exact tip | `0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51` |
| Primary Test Suite (PR event) | run **41036294221** |
| Test Suite URL | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41036294221 |
| Push Test Suite (same tip) | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41036267309 |
| Eval Static Checks | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41036294253 |

Post–doc-closure tip CI is recorded in the closure report after the docs commit lands.

## Antigravity independent qualification (`75a7a64`)

| Field | Value |
|---|---|
| Full SHA | `75a7a648984d9883774292f35a511089e6ffd474` |
| Message | `test(qualification): add independent foundation-03 c06 c07 adversarial qualification suite` |
| Artifact | `tests/qualification/test_foundation03_c06_c07_qualification.py` |
| Candidate audited | `0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51` |
| Verdict class | **Limited-scope** software adversarial qualification — **not** formal register OWN_EVIDENCE acceptance |
| Explicit residuals | C06 in-memory only; C07 tautological IntentSheet derivation risk; authority lockout preserved; missing in-repo handoff docs (addressed by this milestone path) |

## Claim classifications (engineering)

| ID | Classification | Independent qualification |
|---|---|---|
| C06 | `VERIFIED_ENGINEERING` | Limited-scope Antigravity `75a7a64` — NOT formal acceptance |
| C07 | `VERIFIED_ENGINEERING` | Limited-scope Antigravity `75a7a64` — NOT formal acceptance |

## Explicit non-claims / non-edits

- Prior histogram **11 / 17 / 19 / 48** not rewritten in canonical programme reports.
- Formal acceptance remains **0 / 95**.
- `docs/orneur/acceptance/register_graph.json` status fields not modified.
- No founder authorization, training freeze, or protected merge.
- No fabricated coverage.
