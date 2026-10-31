# P1-D — Authentication and Account Lifecycle

## Journeys verified in real Chromium (`browser_p1_auth.py`, `browser_p1_account.py`; real server; mail = local sink)
| Step | Result |
|---|---|
| A1 sign up when verification is required: no session issued, user told to check email | pass |
| A2 unverified sign-in is explained; **resend** works and is throttled server-side (60 s) with the same acknowledgement | pass |
| A3 confirm link → sign in | pass |
| A4 sign out revokes the token on the server (old token → 401) | pass |
| A5 forgot password: identical message for a registered and an unregistered address (no enumeration); reset link opens the in-page reset step; token is removed from the address bar; new password signs the user in | pass |
| A6 reset link replay refused; old password dead | pass |
| A7 MFA: password alone yields **no session**; wrong code refused; right code signs in | pass |
| A8 a used MFA code cannot be replayed | pass (was red: P1-D-01) |
| A9 no credentials in URLs, no page errors | pass |
| U2 change password: wrong current password refused; success keeps this session on a fresh token and kills the old one | pass |
| U3–U5 2FA on/off in the page (secret not left in the DOM after enabling; disable needs a fresh code) | pass |
| U4/U6 delete account: needs confirmation + password (+ code on 2FA accounts); signs out; deleted account cannot log in | pass |

## API-level controls (deterministic tests)
- Sign-in second factor: single-use + per-account lockout (`test_p1_mfa_login.py`, 3).
- change-password / account-delete fresh authentication (`test_p1_sensitive_ops.py`, 5).
- Existing, re-run green: account lifecycle and single-use links across two workers (`test_l02_account_live.py`), API-key step-up (L02-B3), tenant isolation (G-006), invalid bearer refusal.

## Multi-account adversarial results
Two independent synthetic users (alice, bob): cross-read, export, rename, delete, stream-into and search all fail closed (403/404); the refused stream never reached the model (provider request count unchanged); bob's search never returns alice's conversation; after alice's deletion the transcript returns 404/410.

## Not verified / limits
- **Real email delivery: `BLOCKED_EXTERNAL`.** The local sink proves the application emits the mail and the links work; it proves nothing about inbox delivery, SPF/DKIM, bounce handling or link rewriting by real mail scanners. Missing prerequisite: an authorised mail service + credentials.
- **MFA recovery: `NOT_IMPLEMENTED`** in the backend (no recovery codes).
- Session fixation, token entropy review, secure-cookie settings: tokens are bearer headers (no auth cookies); no dedicated fixation test was written.
- Password hashing parameters were not re-reviewed in this phase.
- Dependency vulnerability scanning is performed by existing CI jobs (see the CI report); no separate audit was run locally.
