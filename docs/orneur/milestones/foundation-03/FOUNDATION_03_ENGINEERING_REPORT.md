# FOUNDATION-03 Engineering Report — RSE C06 / C07 Consumer Verification

**Mission:** FOUNDATION-03 — RSE Consumer Verification (C06 + C07)  
**Classification posture:** Engineering verification only. **No independent qualification claim as formal acceptance.**  
**Training authorization:** NO-GO (unchanged)  
**Formal acceptance:** **0 / 95** (unchanged; register numerator preserved)

## 1. Baseline and branch

| Item | Value |
|---|---|
| Qualified baseline (PR #140 HEAD) | `649d90f84069fc618ba4d69b4c26a66bed731caa` |
| PR #140 branch (PR #142 base) | `cursor/foundation-02-phase1-evidence-closure-8108` |
| Isolated branch | `cursor/foundation-03-rse-consumer-verification-9658` |
| Qualified code SHA | `0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51` |
| Draft PR | https://github.com/Guruprasath-Annadurai/Orneur/pull/142 |
| Antigravity qualification commit | `75a7a648984d9883774292f35a511089e6ffd474` |

## 2. What was implemented

### C06 — Signed-byte consumer rendering

Module: `orca/rse/imp1/consumer_verification.py` → `render_from_signed_bytes`.

- Validates received grant bytes via IMP-1 load (canonical parse + dual-token signature verify + registry authenticity).
- Renders the operator-visible card **only** from verified signed bytes + authenticated registry (`render_card`).
- Produces **rendered-card evidence** with:
  - `grant_raw_digest` = SHA-256(received grant bytes)
  - `signed_region_digest` = SHA-256(signed region)
  - `card_digest` = SHA-256(UTF-8 card)
  - `binding_digest` = SHA-256(`OCR-C06-CARD-v1` ‖ 0x00 ‖ grant_raw ‖ 0x00 ‖ card_utf8)
- Refuses malformed / altered / non-canonical / magic-wrong inputs.
- Refuses a Crown-supplied (B1) `claimed_card` that does not equal the card rendered from received bytes (B2).
- Refusal and success records set `authority_usable=False` and deny spending/training/GPU/corpus/qualification.

### C07 — SAS and independent Intent Sheet

Module path: `verify_typed_sas_and_intent` in the same module.

- Recomputes 60-bit SAS per RSE 1.2: `Base32(first 60 bits of SHA-256("OCR-SAS-v1" ‖ 0x00 ‖ class ‖ signed-region))`.
- Accepts typed SAS **only** in `XXXX-XXXX-XXXX` over the RFC 4648 Base32 alphabet; Unicode, lowercase, confusable out-of-alphabet glyphs, and alternate separators fail closed.
- Compares independently typed Intent Sheet fields via IMP-1 `compare_intent` (class, artifact, destination, ceilings, role, counterpart, sequence, SAS).
- Fails closed on incorrect SAS, altered intent, stale/superseded snapshot, voided/cross-session challenge, wrong role identity, wrong environment measurement, inconsistent signed bytes.
- Persists a deterministic **typed-entry record** (`OCR-C07-TYPED-v1` digest) with no private keys or seeds.

### Combined confirmation

`consumer_confirm_from_signed_bytes` runs C06 then C07. Either refusal short-circuits. Success reason `C06_C07_CONFIRMED` still carries `authority_usable=False`.

## 3. Reuse (no duplication of IMP-1)

Reused without reimplementation: `parse_grant` / signature verify, `authenticate_registry`, `render_card`, `grant_sas`, `compare_intent`, `ceilings_of`, `typed_artifact`, grant/consumer snapshot checks, ChallengeLedger semantics, synthetic fixtures in `tests/rse/support.py`.

## 4. Claim classifications

| ID | Claim | Notes |
|---|---|---|
| C06 | **VERIFIED_ENGINEERING** | Adversarial + positive evidence probes green; exact-head CI green on qualified code tip `0fe98e0` (Test Suite run `41036294221`) |
| C07 | **VERIFIED_ENGINEERING** | Same |
| Independent qualification | **LIMITED-SCOPE** (Antigravity `75a7a64`) — **not** formal OWN_EVIDENCE row acceptance | See §7 / Antigravity handoff |
| Formal acceptance / register row pass | **NOT_CLAIMED** | Ledgers untouched; numerator remains 0 |
| Real authority / training | **BLOCKED** / NO-GO | Upstream trust/auth deps unresolved |

Allowed vocabulary used only: `IMPLEMENTED` | `VERIFIED_ENGINEERING` | `IMPLEMENTED_UNVERIFIED` | `BLOCKED`.

## 5. Prior histogram preserved (tracked separately)

Prior FOUNDATION closure disposition histogram remains:

- `VERIFIED_ENGINEERING` = 11
- `IMPLEMENTED_UNVERIFIED` = 17
- `BLOCKED` = 19
- `NOT_IMPLEMENTED` = 48
- Formal acceptance = **0 / 95**

C06/C07 engineering evidence from this mission is **tracked separately**. Canonical acceptance ledgers, SCORECARD, founder authorization, and training-freeze artifacts were **not** edited.

## 6. Verification executed (qualified code SHA `0fe98e0`)

| Gate | Result |
|---|---|
| Targeted C06/C07 suite | 16 passed (`tests/rse/test_c06_c07_consumer_verification.py`) |
| Adjacent RSE regressions | 130 passed (`tests/rse/`) |
| Register validator | `pretraining=95 numerator=0 application=3 execution=2 post=1` |
| Exact-head full CI | **GREEN** on tip `0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51` — Test Suite run [`41036294221`](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41036294221); all 19 checks success |

Adversarial coverage includes: truncated/malformed, altered byte / wrong signature, Crown B1≠received B2 card substitution, non-canonical padding/magic, Unicode/confusable/lowercase/form SAS, altered intent fields, stale grant / cross-session challenge void, wrong role identity / environment, grant A intent against grant B bytes, unexpected kwargs fail-closed, IMP-1 `consumer_verify` semantic preservation.

## 7. Audit limitations (preserved; Antigravity limited-scope verdict)

Independent qualification commit **`75a7a648984d9883774292f35a511089e6ffd474`**
(`test(qualification): add independent foundation-03 c06 c07 adversarial qualification suite`)
audited the qualified code SHA above under limited scope. Its documented limits **must not be diluted**:

1. **C06 = in-memory rendering + cryptographic binding, not operator observation.**  
   The path produces formatted card text and digests in process memory. It does **not** prove a human operator saw a Crown/consumer GUI/TUI display, nor that a physical screen matched the card.
2. **C07 = software SAS / Intent Sheet comparison, not genuine independent human entry.**  
   Machine comparison of typed-form fields fails closed when values differ, but a caller that **derives** the Intent Sheet from the grant (tautological derivation) can satisfy the comparison without a real operator-independent sheet. Antigravity recorded this residual risk explicitly while confirming authority remains denied.
3. **Real authority remains blocked** by upstream trust / governance dependencies (G3, trust anchors, physical dual-token C08, training authorization, independent formal OWN_EVIDENCE on a merged SHA). Success payloads keep `authority_usable=False`.
4. **Not formal acceptance.** Register rows C06/C07 remain `DESIGNED_ONLY` until independent OWN_EVIDENCE acceptance on a merged SHA.
5. **Synthetic tokens only.** No physical tokens, founder secrets, or fake founder-signature authority.
6. **No training / GPU / corpus / purchases / infra** authorized by this work.

## 8. Restrictions honored

- No edits to the 95-row acceptance register, baseline engineering histogram, training authority, or founder-controlled decisions.
- No changes to Claude application-security PRs.
- No force-push or modification of PR #140.
- No protected merge; draft PR only.

## 9. Stop

Engineering and handoff-doc closure stop here. Do not merge PR #142. Do not start a subsequent mission. Do not authorize training.
