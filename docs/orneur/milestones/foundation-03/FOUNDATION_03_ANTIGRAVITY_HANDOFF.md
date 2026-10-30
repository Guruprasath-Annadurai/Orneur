# FOUNDATION-03 Antigravity Handoff — Independent Qualification of C06 / C07

**Audience:** Independent reviewer (Antigravity / Claude OWN_EVIDENCE).  
**Author posture:** Cursor engineering only. Engineering does **not** self-certify formal acceptance.

## 1. What was qualified (limited scope)

| Row | Exact acceptance condition (register) | Qualified code tip |
|---|---|---|
| C06 | Rendered-card digest showing the consumer rendered the received signed bytes. | `0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51` |
| C07 | Typed-entry record for the SAS and the Intent Sheet fields. | same |

Draft PR: https://github.com/Guruprasath-Annadurai/Orneur/pull/142  
Branch: `cursor/foundation-03-rse-consumer-verification-9658`  
PR base: `cursor/foundation-02-phase1-evidence-closure-8108` (PR #140)  
Baseline: PR #140 HEAD `649d90f84069fc618ba4d69b4c26a66bed731caa`

## 2. Antigravity independent qualification commit

| Field | Value |
|---|---|
| Commit | `75a7a648984d9883774292f35a511089e6ffd474` |
| Short | `75a7a64` |
| Message | `test(qualification): add independent foundation-03 c06 c07 adversarial qualification suite` |
| Suite | `tests/qualification/test_foundation03_c06_c07_qualification.py` |
| Candidate | PR #142 tip `0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51` |

### Limited-scope verdict (must preserve)

Antigravity’s suite exercised C06 binding / Crown B1≠B2 refusal, C07 SAS Unicode/confusable/form refusals, Intent Sheet field tampering, stale/void challenge, environment mismatch, and non-authoritative lockout. The **recorded scope limits** are:

1. **C06** — In-memory rendering and cryptographic binding only (`test_c06_scope_is_in_memory_formatting_only`). **Not** operator observation of a real Crown/consumer display.
2. **C07** — Software SAS and Intent Sheet comparison only. **Not** genuine independent human entry. `test_c07_tautological_intent_derivation_risk` documents that deriving the Intent Sheet from the grant can satisfy the machine check; authority remains `authority_usable=False` / training denied.
3. **Governance** — Formal acceptance ledger remains **0/95**; training/spending denial verified; protected files must stay 0-diff versus parent.
4. **Missing in-repo handoff docs** — Finding at qualification time that Cursor store handoff docs were not in git. Addressed by committing this milestone under `docs/orneur/milestones/foundation-03/`.

This is **not** a claim of formal register OWN_EVIDENCE acceptance or real operational authority.

## 3. Reproduce engineering probes

```bash
git fetch origin pull/142/head
git checkout 0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51
python -m pytest tests/rse/test_c06_c07_consumer_verification.py -v
python -m pytest tests/rse/ -q
python scripts/acceptance/validate_register_graph.py --check
# expect: pretraining=95 numerator=0
```

Exact-head CI on the qualified code tip:

- Test Suite: https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41036294221 (`41036294221`)
- All 19 commit checks: success (0 failures)

## 4. Challenge points (do not rubber-stamp)

1. **C06 binding:** `binding_digest` must include the exact received grant bytes and the rendered card. A Crown B1 display string must not authenticate against B2 received bytes (`CARD_MISMATCH`).
2. **Not parser-only:** Passing OCR1/codec unit tests alone is **not** C06 evidence. Require the rendered-card evidence object with digests.
3. **C07 independence residual:** Machine comparison is necessary but not sufficient for “independently entered” operator intent if the caller derives the sheet from the grant.
4. **SAS form:** Unicode, confusable out-of-alphabet characters, lowercase, and non `XXXX-XXXX-XXXX` forms must refuse.
5. **Stale / cross-session:** Challenge mismatch and voided ledger must fail closed and stay void.
6. **Authority:** Success payloads must keep `authority_usable=False`, `executable=False`, spending/training/GPU denied.
7. **Ledger honesty:** Confirm register numerator still 0; C06/C07 register status remains `DESIGNED_ONLY` until OWN_EVIDENCE on a merged SHA.
8. **No histogram inflation:** Prior 11 VERIFIED_ENGINEERING counted rows must not be silently rewritten.

## 5. Spec anchors

- `docs/orneur/phase-21/rse/v1.2/RSE12_06_P1_ACCEPTANCE_OPERATIONS.md` §4 rows C06, C07
- `docs/orneur/phase-21/rse/v1.2/RSE12_01_REGISTRY_CROWN.md` §4 (SAS + Intent Sheet)
- `docs/orneur/phase-21/rse/v1.2/RSE12_07_SELF_ATTACK.md` F1 (compromised Crown / typed intent)
- `docs/orneur/acceptance/register_graph.json` evidence_required for C06 / C07

## 6. Implementation map

| Concern | Code |
|---|---|
| C06 render + binding | `orca/rse/imp1/consumer_verification.py` → `render_from_signed_bytes` |
| C07 typed SAS + intent | same → `verify_typed_sas_and_intent` |
| Combined drill path | same → `consumer_confirm_from_signed_bytes` |
| IMP-1 primitives reused | `orca/rse/imp1/authority.py`, `codec.py` |
| Engineering probes | `tests/rse/test_c06_c07_consumer_verification.py` |
| Antigravity suite | `tests/qualification/test_foundation03_c06_c07_qualification.py` @ `75a7a64` |

## 7. Unresolved deps (still BLOCKED for real authority)

- G3 merged-SHA / non-slogan review
- Trust anchors absent
- Physical dual-token (C08) founder ceremony
- Training authorization absent
- Formal OWN_EVIDENCE row acceptance on a merged SHA

## 8. Stop

Leave PR #142 **draft and unmerged**. Do not authorize training. Do not alter the 95-row register or baseline histogram.
