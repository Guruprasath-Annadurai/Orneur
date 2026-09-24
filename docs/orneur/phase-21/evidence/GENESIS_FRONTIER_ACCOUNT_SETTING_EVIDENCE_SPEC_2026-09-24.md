# Genesis Frontier Account-Setting Evidence Spec — Phase 21B.4.19

**SPECIFICATION ONLY. No account setting was inspected, changed, or
activated in this phase. No provider account was accessed.**

Some blockers can only be resolved by a provider account setting
(Mistral's "Anonymous improvement data" toggle; DeepSeek's opt-out if
proven API-applicable; future ZDR / no-retention / no-training
controls). A setting only ever counts as evidence after a separately
owner-authorized action has been executed AND the record below has been
captured and validated by
`orca.eval.frontier_provider_resolution.validate_account_setting_evidence()`.
A checklist, a plan, or an intention to change a setting changes no
reference state.

## Required record

| Field | Requirement |
|---|---|
| `provider` | registry organization value |
| `reference_name` | exact locked reference name |
| `account_identifier_category` | one of `ORG_ID_REDACTED`, `PROJECT_ID_REDACTED`, `NONE` — a **category only**. Never store a real account number, org id, project id, API key, token, or password. Records containing `account_identifier`, `account_number`, `api_key`, `token`, `password` or `secret` keys are rejected. |
| `setting_name` | exact provider UI/documentation label |
| `old_state` / `new_state` | must differ; an unchanged setting is not evidence of a change |
| `effective_scope` | account-wide / project-wide / product-specific, as the provider describes it |
| `effective_timestamp_utc` | when it became effective |
| `screenshot_evidence_reference` | path under the evidence root to the redacted screenshot |
| `sha256` | SHA-256 of the screenshot bytes (recomputed at validation) |
| `provider_documentation_reference` | current provider documentation supporting the setting's meaning |
| `prospective` | must be `true` — applies to future traffic |
| `retroactive` | recorded (may be `false`; retroactivity is not required) |
| `api_specific` | must be `true` — applies to API/Open Platform traffic, not only a consumer app |
| `verification_result` | must be `VERIFIED_ACTIVE` |
| `reviewer` | named reviewer |

## Capture procedure (for the owner, per authorized action)

1. Screenshot the setting BEFORE any change (old state), identifiers redacted.
2. Make only the single authorized change.
3. Screenshot the setting AFTER (new state), identifiers redacted.
4. Reload/re-open the page and screenshot again to prove persistence.
5. Save the provider documentation page describing the setting (URL + saved copy + SHA-256).
6. Confirm scope (API vs consumer, account vs project) from the provider's own wording.
7. Forward the raw files; the reviewer builds the record and the validator hashes the bytes.

## What an account-setting record can and cannot do

- It can support removing `PROVIDER_ACCOUNT_SETTING_REQUIRED` and, together
  with a VERIFIED provider response, `REVIEW_REQUIRED -> PERMITTED` for
  `private_holdout_status`.
- It can never set `access_preflight_status`. Promotion to a counting
  access status happens only through `promote_access_status()` →
  `validate_full_protocol_access_readiness()`.
- It goes stale: re-verify immediately before any future evaluation
  traffic (30-day maximum).

## Per-setting notes (not exercised this phase)

- **Mistral** — Admin panel → Privacy → "Anonymous improvement data" (API/Studio). The Vibe toggle is separate and out of scope. ZDR is a separate control (eligible paid plan/approval).
- **DeepSeek** — inspect first (DSK-02, read-only). Enable only if DSK-01/DSK-02 prove an API-applicable, prospective setting (DSK-03).
- **GLM** — only if GLM-01 verifies an applicable no-training/no-retention control.
- **Kimi / MiniMax / Qwen** — no account-setting route is currently identified; Kimi's route is a written enterprise agreement, not a setting.
