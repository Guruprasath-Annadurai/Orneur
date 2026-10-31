# P1 — Handoff for Independent Qualification (Antigravity)

Candidate: branch `claude/landmark-04-phase1-real-app`, draft PR (see the master report for the final SHAs). Base: `main` `0a4c518`. Please verify the SHA you test; documentation commits follow the code commit.

## Environment you need
Python venv with repo dependencies; Redis 7 on `localhost:6379`; Node 22 (frontend unit tests); Playwright 1.49 + Chromium via `ORNEUR_JOURNEY_TOOLS`; for real-inference tests a local Ollama with `llama3.2:1b` (journey tests also expect the aliases `orneur-journey`, `orca-nano`, `orca-core`, `orca-ultra`, or run with `ORNEUR_JOURNEY_MODEL=llama3.2:1b`). Never run two Redis-using suites at once. `unset PYTHONDONTWRITEBYTECODE` for the full suite.

## Reproduce failing-before / passing-after
Create a clean checkout of `main` (`0a4c518`), copy the new test files from the candidate, run them: they must fail. Then run on the candidate: they must pass.
```bash
pytest tests/test_p1_mfa_login.py tests/test_p1_sensitive_ops.py tests/test_p1_ui_security_headers.py tests/test_p1_ui_asset_references.py tests/test_p1_background_extraction_bound.py -p no:cacheprovider
```
Expected on `main`: 12 failures from the first three files (see `evidence/red_on_baseline_0a4c518.txt`), asset-reference tests red for `conversation.html`, extraction-bound red. Expected on the candidate: all green.

## Browser and live suites (real Chromium, real server)
```bash
pytest tests/journey/test_p1_browser_security.py tests/journey/test_p1_browser_accounts.py tests/journey/test_p1_browser_account.py \
       tests/journey/test_p1_browser_manage.py tests/journey/test_p1_browser_csp.py tests/journey/test_p1_quota_live.py -p no:cacheprovider -v
```
Real inference: `ORNEUR_JOURNEY_MODEL=llama3.2:1b python docs/orneur/landmarks/landmark-04/phase-1/evidence/p1_real_inference_identity.py out.json` and `…/p1_perf.py out.json`.
Pre-existing suites to re-run (listed in `.github/workflows/test.yml`, Journeys job).

## Where to attack first
1. `orca/auth/routes.py`: `_fresh_auth`, `verify_login_2fa`, `disable_2fa`, `change_password`, `delete_account_endpoint` — try bypassing lockout (account/IP rotation), replay across the ±1-step window edge, racing two verify-login calls with one code (the single-use claim should be atomic).
2. `orca/serve/web/conversation.html`: `mdToHtml`, `_sanitizeLinkHref`, the account dialog, reset-token handling at boot. Find an `innerHTML` interpolation I did not cover (e.g. model labels, error text from the server, document names).
3. CSP in `orca/serve/api.py` (`_UI_CSP`): anything the page does that needs a looser policy; anything the policy lets through.
4. Quota reservation under multi-worker load; the unmetered extraction call (P1-X-04).
5. Reset/verify links: token handling, referrer leakage, replay across workers.

## What was NOT tested (do not assume)
Real inbox delivery; MFA recovery (does not exist); screen readers, contrast, zoom; Firefox/Safari/real phones; external providers; context-window overflow with the real model; disk-pressure and DB-unavailable fixtures beyond the existing suites; session fixation; dependency audit beyond the CI jobs; any scale beyond one workstation.

## Known test-tool compromise
Existing and new journey drivers run Chromium with `bypass_csp=True` because Playwright's string waits use `eval`. The real policy is verified only by `test_p1_browser_csp.py`. Please run a full journey with the CSP enforced if you can.

## Claims I am NOT making
No `INDEPENDENTLY_QUALIFIED`, no staging readiness, no public-launch authorisation, no capacity claim, no native-model claim.
