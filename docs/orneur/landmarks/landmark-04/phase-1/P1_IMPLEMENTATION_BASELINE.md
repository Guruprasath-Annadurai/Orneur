# P1 — Implementation Baseline (Wave 0)

Status vocabulary: `NOT_IMPLEMENTED · IMPLEMENTED_UNVERIFIED · VERIFIED_ENGINEERING · FAILED · BLOCKED_EXTERNAL · INDEPENDENTLY_QUALIFIED` (the last is assigned only by the independent authority; nothing here carries it).

## Starting point
| Item | Value |
|---|---|
| Protected `main` (fetched and verified, no advance) | `0a4c5180555a3102a4e0d61f56e0f8539975f4ee` |
| Main tree | `106487db24a66672c7ca3e660a1d1e0792281238` |
| Branch | `claude/landmark-04-phase1-real-app` (new; no other agent's branch touched) |
| Workstation | AMD Ryzen 7 9700X (16 threads), 15.2 GB RAM, WSL2 Linux 6.18, real Ollama on `localhost:11434` with `llama3.2:1b` installed, Redis 7 (local container), Chromium via Playwright 1.49 |

Environment note: the local Redis test container (`orneur-redis-test`) no longer existed and was recreated from the local `redis:7-alpine` image. Nothing was provisioned or paid for.

## What the baseline already did correctly (measured on `main`, before any change)
Measured by running the existing suites against an untouched checkout:

| Suite (real processes) | Result on `main` |
|---|---|
| `test_journey_api_live.py` + `test_b01_real_ollama_live.py` — real server, **real Ollama** | 22 passed |
| `test_journey_browser.py` + `test_journey_browser_fixture.py` + `test_b01_browser_streaming.py` — real Chromium | 55 passed |

So real inference, progressive SSE, Stop with provider hang-up, restart persistence, two-user isolation and logout revocation were already `VERIFIED_ENGINEERING` and were **preserved, not rebuilt**.

## Implementation gap matrix (what the audit found)
| Area | Finding on `main` | State at baseline |
|---|---|---|
| Hostile content rendering (XSS) | Probed with 14 payloads in real Chromium, live and reopened. **No defect found.** | VERIFIED (new test) |
| Approved page auth | Only sign-in / sign-up. A 2FA account hit a dead end ("use the main app"); no forgot/reset; no verification resend | NOT_IMPLEMENTED |
| MFA at sign-in | Code replayable; no per-account lockout | FAILED |
| change-password / delete-account | No lockout; no second factor for 2FA accounts | FAILED |
| Account menu | Sidebar "account" row was a clickable element wired to an empty function; no settings, 2FA setup or deletion UI | NOT_IMPLEMENTED (dead control) |
| Logo on `/conversation` | Broken image (file from a superseded asset set, never installed) | FAILED |
| CSP / framing | None | NOT_IMPLEMENTED |
| Quotas, routing, cancellation | Behaved correctly under live tests | VERIFIED (new tests) |
| Post-turn extraction | One unmetered, unbounded background model call per turn | FAILED (bounded; metering is open) |
| Mobile / tablet / accessibility | No browser test existed above 1280 px | IMPLEMENTED_UNVERIFIED → verified for the checks listed in the matrix |
| MFA recovery codes | No backend support | NOT_IMPLEMENTED (unchanged, see register) |
| Real email delivery | Only a local sink exists | BLOCKED_EXTERNAL |

Full defect list: `P1_GAP_AND_DEFECT_REGISTER.md`.
