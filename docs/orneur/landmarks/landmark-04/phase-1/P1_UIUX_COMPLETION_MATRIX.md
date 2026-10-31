# P1-A — UI/UX Completion Matrix

Scope rule honoured: no redesign. The approved page, theme tokens, layout, greeting, composer and sidebar are unchanged; the locked logo was **not** redrawn (see P1-A-01). New surfaces reuse the existing auth-card styling and tokens.
Screenshots (real Chromium against the served page): `evidence/screenshots/01…09_*.png` — sign-in, forgot password, empty conversation, answer (dark/light toggle exercised), account dialog, mobile answer, mobile drawer, tablet list.

| Requirement | Baseline | Change | Test | Result | Remaining risk |
|---|---|---|---|---|---|
| Official logo shown, unchanged | broken image on `/conversation` | installed founder emblem + wordmark (files SHA-256-verified against `ASSETS.json`) | `test_p1_ui_asset_references.py`; browser B1 (every `<img>` loads, desktop + mobile) | VERIFIED_ENGINEERING | brand tests elsewhere still cover only the three older pages plus the new reference test |
| No dead controls on the account row | empty handler | real button → account dialog | browser U1 | VERIFIED_ENGINEERING | the other `onclick` handlers on the page were enumerated (login, signup, reset, MFA, resend, logout, theme, skip, temp-chat guard) and all are wired |
| Auth states: default / error / expired / verification / recovery / MFA | sign-in + sign-up only | contextual steps (C11 Variant B) for forgot, reset, MFA challenge, unverified resend; existing session-expired and signed-out-in-another-tab messages preserved | browser A1–A9 | VERIFIED_ENGINEERING | wording is engineering copy, not founder-approved copy |
| Account settings, 2FA setup, deletion | none | accessible dialog (role=dialog, aria-modal, labelled controls, focus trap, Esc, focus return) | browser U1–U7 | VERIFIED_ENGINEERING | no QR code for the authenticator key (key is shown as text) |
| Sidebar reflects persisted state; rename / search / delete | existing | unchanged | browser M1–M6 against real server | VERIFIED_ENGINEERING | — |
| Conversation: progressive answer, Stop, retry, copy, code, markdown | existing | tight lists fix | B01 suites (39 + 15 re-run green) + X8 | VERIFIED_ENGINEERING | markdown renderer is a small hand-written one; only the constructs in the tests are claimed |
| Hostile content cannot execute | not tested in a browser | none needed | browser X1–X8 (14 payloads, live + reopened); mutation-proven | VERIFIED_ENGINEERING | inline-script CSP (P1-X-03) |
| Desktop 1280 / tablet 820 / mobile 390 | desktop only tested | none needed | browser N1, N2, T1, B1 | no horizontal scroll at any width; mobile drawer, send, stream, Stop, reopen all work by touch | other devices/browsers (Firefox, Safari) not run |
| Keyboard, names, focus ring | not tested | none needed | browser H1 (every visible control has an accessible name; Tab shows a focus indicator), U1 (dialog focus handling) | VERIFIED for the automated checks | **no screen-reader testing, no contrast audit, no zoom audit (P1-X-08)** |
| Touch targets | not measured | none needed | browser N2: menu, send, model, input ≥ 24×24 CSS px (WCAG 2.2 AA 2.5.8) | VERIFIED | 44 px (AAA) not asserted |
| Reduced motion | not tested | none needed | browser H2: no looping animation under `prefers-reduced-motion` | VERIFIED | — |
| CSP-compatible | no CSP | CSP added | browser C1–C6 with the real policy | VERIFIED | `'unsafe-inline'` remains |

Honest limits: this is not a visual-regression suite and not an accessibility certification. Light/dark were captured, not diffed pixel by pixel.
