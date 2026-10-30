# L02-B3 — API-key creation requires fresh verification

Evidence state: **VERIFIED_ENGINEERING** (engineering-owned; not independently qualified). Baseline: PR #139 head `38e0d311991875366f2bc88a39690c7b2b6ea3ee` (unmodified). Branch `claude/l02-b3-apikey-reauth`.

## Finding and reproduction
`POST /api/auth/apikeys` minted a long-lived `athr_` credential for any caller holding a valid session token. A hijacked or stolen session could therefore create a key that survives logout (sessions are revoked, keys are not) and keeps working until the owner notices. Reproduced before any change: `evidence/b3_baseline_red_38e0d31.txt` — **16 of the 21 new tests fail on the baseline** (the 5 that pass assert behaviour that was already correct).

## Design (minimal)
Verification is checked **inside the creation request**; nothing is issued, stored or reusable.
| Requirement | Mechanism |
|---|---|
| Fresh, server-verified | request body must carry the current `password`; it is verified against the stored hash for the user the bearer session resolves to |
| MFA preserved | if the account has 2FA enabled, `totp_code` is also required; a password alone is refused (`reauth_failed`, same answer as a wrong password, so the response does not reveal which factor failed) |
| Short-lived / single-use / replay-safe | there is no step-up token. Each creation re-verifies. An authenticator **time step is recorded once** (`auth_stepup_totp_used`, atomic insert), so one code cannot authorise two creations, on any worker |
| Bound to user and session | the password must belong to the same user as the presented session JWT; another account's password is refused |
| Session class | the credential must be a session token: an API key (`athr_`) is refused with `403 reauth_requires_session`; 2FA-pending, reset, verification tokens, revoked and expired sessions are already refused by the auth dependency (401) |
| Rate limited, fail closed | per-IP limiter (`AUTH_LOGIN`, 10/5 min) and a per-account failure ledger (8 failures / 15 min → `429 too_many_attempts`, shared across workers). A subject prefix keeps step-up failures separate from login failures, so a login attempt cannot lock step-up (or vice versa). Missing, blank, wrong or malformed verification never creates a key. A successful verification clears the count |
| Audit | `api_key_created` (key id, whether MFA was used) and `api_key_reauth_failed` (reason code only: `password`, `totp_invalid`, `totp_replayed`, `locked`, `missing_password`, `api_key_credential`). Tests assert that the password, the code, the TOTP secret and the raw key never appear in the audit trail |
| Unchanged | listing, revocation, the password-reset flow that revokes keys, login, 2FA enable/disable |

Code: `orca/auth/routes.py` (`create_api_key`), `orca/auth/account_security.py` (`stepup_*`, `claim_totp_step`), `orca/auth/totp.py` (`matching_step`), `orca/auth/db.py` (table in both the SQLite and Postgres schema), `orca/serve/web/index.html` (password and 2FA fields in the existing API Keys settings panel only), `docs/API_REFERENCE.md`.

## Tests
* `tests/test_l02_b3_apikey_reauth.py` — 21 tests (16 red on baseline, 21 green now): session-only, wrong password, blank/malformed, 2FA password-only, wrong code, replay, other account's password, API key as credential, revoked session, 2FA-pending token, lockout, per-IP limit, count reset, listing/revocation, audit hygiene.
* `tests/journey/test_l02_b3_apikey_reauth_live.py` — two real `orca serve` workers on one auth database: session-only refused; password creates; an API key cannot create a key; 2FA password-only refused; a code works once and its replay on the **other worker** is refused; failures on A lock creation on B. Evidence `evidence/b3_apikey_reauth_live_two_workers.json`.
* `tests/test_a_postgres_integration.py::test_apikey_stepup_ledgers_work_on_real_postgres` — the new ledgers on real PostgreSQL.
* One existing assertion changed with its reason: `tests/test_l02_account_security.py` creates its key with the now-required `password`.

## Residual risks (not hidden)
* A holder of the **password** plus a hijacked session can still create a key when 2FA is off — that is the intended bar; accounts that want more must enable 2FA.
* A TOTP code already used at **login** (not at step-up) can be reused once for a step-up inside its ~90 s window if the attacker also knows the password. The replay guard covers step-up only; login's own replay behaviour is unchanged (out of scope).
* Key **revocation and listing** still need only a session (revoking is a safe direction; listing does not disclose the secret). Existing keys already issued are not affected by this change.
* Failure responses for password vs code are identical, but the 2FA-enabled state is observable to a caller who already holds the session (`/api/auth/me` reports `totp_enabled`).
* The lockout is per account: an attacker holding the session can lock the owner out of *creating* keys for 15 minutes (never out of login or of existing keys).
* Browser UI was changed minimally (two inputs); no browser journey was re-run for this change.

## Not changed
Chroma process isolation (separately gated), any unrelated authentication behaviour, branding/design flows, PR #139/#136/#140.
