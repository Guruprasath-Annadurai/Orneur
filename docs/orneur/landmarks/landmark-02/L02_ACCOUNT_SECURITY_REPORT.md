# L02-04 — Account security report

Evidence state: **VERIFIED_ENGINEERING**. Code: `orca/auth/{account_security,email,routes,tokens,store,db}.py`, `orca/serve/config_validation.py`. Tests: `tests/test_l02_account_security.py` (22), `tests/journey/test_l02_account_live.py` (2, two real workers), browser journeys S1/S2/S10.

## Controls
| Control | Implementation | Constants |
|---|---|---|
| Email verification | signed token carrying a `jti`; consumption is one atomic `UPDATE … WHERE used_at IS NULL` (single use, cross-worker) | TTL 24 h |
| Password reset | same mechanism; confirmation page on `GET` (never consumes), consume on `POST` so mail scanners/prefetch cannot spend a link | TTL 1 h |
| Resend throttling | per-account send ledger | ≥60 s apart, ≤5/day |
| Credential-stuffing lockout | per-account failure ledger → `too_many_attempts` (429) | 8 failures / 15 min |
| Constant-time login | unknown and known accounts both run the password hash | measured ratio 0.98 (`evidence/l02_04_login_timing.json`; recorded, not a proof) |
| Enumeration resistance | signup returns the same response for new/existing address **only when verified delivery is configured**; otherwise the old explicit behaviour (config finding raised) | |
| Session revocation | reset and verification keep the existing revocation list; logout revokes the token (browser S10) | |
| Recovery vs 2FA | a reset never disables or bypasses an enrolled second factor | |
| Mail | `ORNEUR_MAIL_SINK_DIR` writes `.eml` files locally; **no real email is sent** by any test or journey | |
| No secrets stored | only jti/hash, timestamps, counters | |

## Baseline defect reproduced
`evidence/l02_04_baseline_enumeration_9cb864c.txt`: on `9cb864c` signup distinguished existing addresses and no verification existed.

## Not claimed
* Delivery to a real mailbox/SMTP provider (no uncontrolled recipient was used; external dependency).
* Account-takeover resistance beyond the ledgers above; API-key creation does not require re-authentication (P2 register item).
* Timing equality is a single-workstation measurement.
