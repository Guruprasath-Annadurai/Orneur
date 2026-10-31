# P1 — Gap and Defect Register

Severity: P0 unrecoverable/security-critical · P1 breaks a supported journey or a security control · P2 material weakness · P3 minor.
"Red proof" = the named test fails on baseline `main` `0a4c518` and passes on the branch. Raw output: `evidence/red_on_baseline_0a4c518.txt` and the notes per row.

## Defects found and repaired
| ID | Sev | Defect (reproduced on `main`) | Fix | Red proof |
|---|---|---|---|---|
| P1-D-01 | P1 | `POST /api/auth/2fa/verify-login` accepted the same TOTP code repeatedly | single-use claim, same mechanism as API-key step-up | `tests/test_p1_mfa_login.py::test_a_sign_in_code_cannot_be_used_twice`; browser step A8 |
| P1-D-02 | P1 | No per-account lockout on the second factor (guessing limited by IP rate only) | per-account lockout, 429 + `Retry-After`; applied also to `2fa/disable` | `test_repeated_wrong_codes_lock_the_account_out…`, `test_disabling_mfa_needs_a_fresh_code_each_time` |
| P1-D-03 | P1 | `change-password` and `account/delete` needed only the password: no lockout, no second factor for 2FA accounts (stolen session + guessed password destroyed/took over an account) | shared fresh-auth helper: password, plus a single-use code for 2FA accounts, per-account lockout; change-password returns a fresh session so the caller is not silently signed out | `tests/test_p1_sensitive_ops.py` (4 of 5 red) |
| P1-D-04 | P1 | Approved page: a 2FA account could not sign in at all | in-page MFA challenge (C11 Variant B contextual step) | browser A7 |
| P1-D-05 | P1 | Approved page: no forgot-password, no reset, no verification resend | contextual forgot / reset / resend steps; reset token removed from the URL at load; identical answer for registered and unknown addresses | browser A2, A5, A6 |
| P1-D-06 | P2 | Reset email linked to the older `/app` console, which stores its token under a different key, so recovery did not sign the user into the approved page | reset email and verify page now return to `/conversation` | browser A5 |
| P1-D-07 | P2 | Sidebar account row looked interactive but did nothing (dead control) | now a real button opening the account dialog | browser U1 |
| P1-D-08 | P2 | No account settings, no 2FA setup, no account deletion in the approved page | accessible dialog (focus trap, Esc, focus return): change password, 2FA on/off, delete account with confirmation | browser U1–U6 |
| P1-A-01 | P1 | **Broken logo on `/conversation`** (referenced `/static/b01_approved_assets/orneur_logo_horizontal.png`, never installed on `main`; brand tests covered only three other pages) | uses the installed, SHA-256-verified founder emblem + wordmark exactly as the other pages; no asset was created or redrawn | `tests/test_p1_ui_asset_references.py` (2 red), browser B1 (red on baseline, names the broken file) |
| P1-A-02 | P3 | Markdown bullet lists rendered with large gaps (each item wrapped in its own `<ul>`) | adjacent lists merged | browser X8 |
| P1-S-01 | P2 | No CSP, no `frame-ancestors`/`X-Frame-Options` on UI pages (clickjacking; no limit on where injected script could send data) | CSP + `DENY` on `/conversation`, `/app`, `/`, `/trust`; `connect-src 'self'`, `object-src 'none'`, `base-uri 'none'` | `tests/test_p1_ui_security_headers.py` (4 red); browser C1–C6 with the real policy enforced |
| P1-S-02 | P3 | `/api/auth/*` responses (tokens) had no `Cache-Control` | `no-store` | `test_api_responses_are_not_cached…` |
| P1-F-02 | P2 | Each committed turn spawned an unbounded background model-call task | bounded slot pool (`ORNEUR_KG_EXTRACT_SLOTS`, default 2); overflow skipped, counted | `tests/test_p1_background_extraction_bound.py` |

## Probed, no defect found (kept as regression tests)
| Probe | Result |
|---|---|
| XSS through assistant output, user text, link schemes (`javascript:`, tab-split `java\tscript:`, `data:`, `vbscript:`), attribute break-out, fenced code, citation markers, sidebar titles; live and reopened | inert. Test is **red under mutation**: with `esc()` removed the same test reports 15 injected elements and live script execution |
| Cross-user read / export / rename / delete / stream-into, UI and API | 403/404, and the refused stream never reached the model |
| Quota exhaustion, burst of 10 with 4 remaining | exactly 4 served, 4 user-facing provider calls, refused requests cost nothing |
| Failed provider turn | not charged, not stored as saved |
| Client hang-up mid-stream | provider hung up in 0.5 s, no stored completion, 0 open provider streams |

## Open items (not repaired in this phase)
| ID | Sev | Item | Owner / next step |
|---|---|---|---|
| P1-X-01 | P2 | Email delivery verified only against the local sink | **BLOCKED_EXTERNAL**: needs an authorised mail service and credentials |
| P1-X-02 | P2 | MFA recovery codes do not exist in the backend (lost authenticator = no self-service path) | NOT_IMPLEMENTED; needs a product/security decision on the recovery model |
| P1-X-03 | P2 | CSP keeps `'unsafe-inline'` for script/style (the approved page is built inline); an XSS regression would not be stopped by CSP alone | follow-up: nonce migration |
| P1-X-04 | P2 | The background extraction call is still **not metered** against the user's quota (with a paid external provider it would be hidden spend). Local Ollama today: no spend | needs a founder policy decision (meter, disable, or document); no billing policy was invented |
| P1-X-05 | P3 | Default CORS is `*` outside a public edge (auth is by bearer header, not cookie, so no cookie CSRF); public-edge deployments are already forced to an explicit list | document in the launch checklist |
| P1-X-06 | P3 | A 200,000-character message is accepted and forwarded; no token budget check against the model context window | not tested against model limits |
| P1-X-07 | P3 | Legacy `/app` console keeps its own token key and lacks the new account flows | out of scope; the approved page is the Phase 1 surface |
| P1-X-08 | P2 | Accessibility is verified only for the automated checks listed in the UI matrix. **No screen-reader session, no contrast audit, no 200 % zoom pass** | Antigravity / manual follow-up |
| P1-X-09 | P3 | Playwright's string-based waits need `eval`, so the existing journey drivers run with `bypass_csp=True`; the real policy is exercised by a dedicated driver (`test_p1_browser_csp.py`) | accepted test-tool constraint |
| P1-X-10 | P3 | **Inherited flaky foundation test (not caused by this phase):** `tests/test_l03_vector_service.py::test_an_owner_whose_memory_passes_its_limit_leaves_when_idle_and_the_next_call_starts_a_fresh_one_with_the_data_intact` failed twice on the documentation head `f44547b` push run (`VectorUnavailable: vector service did not start`) and passed on the same code in the pull_request rerun and on `02572dd` (both runs). Cause read from the log: after the owner recycles, `col.count()` gets a ~2 s budget to cold-start chromadb, which a loaded runner can miss. 12/12 local passes on both this branch and pristine `main`. The commit that first failed changed documentation files only | protected foundation test: not edited here; handed to the CTO with this reproducer (give the post-recycle call an explicit start budget) |
