# L02-B3 — handoff to Antigravity for independent re-test

Status: `VERIFIED_ENGINEERING` — **not** independently qualified. Nothing here pre-empts your verdict. Draft PR #141 (base: PR #139 branch, head `38e0d31`; neither PR #139, #136 nor #140 was modified). Not merged, not deployed.

## Attack matrix to try (all must end with **no key created**)
| Attempt | Expected |
|---|---|
| valid session, no `password` | `401 reauth_required` |
| valid session, wrong password / blank / whitespace / wrong type | `401 reauth_failed` / `reauth_required` / `422` |
| valid session, another user's password | `401 reauth_failed` |
| 2FA account, password only / wrong code / code from a previous creation | `401 reauth_failed` |
| 2FA account, same code on the other worker | `401 reauth_failed` |
| an existing API key as the bearer, with the password | `403 reauth_requires_session` |
| revoked session; 2FA-pending, reset or verification token as bearer | `401` |
| 8 wrong attempts in 15 min, then the right ones | `429 too_many_attempts` (+`Retry-After`), on every worker |
| flood from one IP | `429 rate_limited` |
Things to confirm still work: listing, revocation, login, 2FA enable/disable, password reset revoking keys.
Ideas we did **not** test: timing differences between "wrong password" and "wrong code" paths under load; races creating two keys with one TOTP step on two workers at the same millisecond (the claim is a single atomic `INSERT … ON CONFLICT DO NOTHING`, exercised sequentially on Postgres); reusing a code that was first spent at *login*; browser UI journeys for the new fields; clock skew between workers.

## Reproduce
```
pytest tests/test_l02_b3_apikey_reauth.py -p no:cacheprovider                      # 21 passed (16 fail on 38e0d31: evidence/b3_baseline_red_38e0d31.txt)
pytest tests/journey/test_l02_b3_apikey_reauth_live.py -p no:cacheprovider         # two real workers; evidence/b3_apikey_reauth_live_two_workers.json
pip install -e ".[pgtest]"; pytest tests/test_a_postgres_integration.py            # 14 passed (includes the step-up ledgers on real PostgreSQL)
pytest tests/test_l02_account_security.py tests/test_g006_tenant_isolation.py
```
Review first: `orca/auth/routes.py::create_api_key`, `orca/auth/account_security.py` (`stepup_*`, `claim_totp_step`), `orca/auth/totp.py::matching_step`, the two schema blocks in `orca/auth/db.py`. Residual risks: `B3_APIKEY_REAUTH_REPORT.md`. Please record your verdict against the exact SHA in your own PR.
