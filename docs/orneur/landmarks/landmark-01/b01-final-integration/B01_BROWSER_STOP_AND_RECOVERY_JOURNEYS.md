# B-01 — Browser Stop and recovery journeys (approved `/conversation` page, real Chromium)

Evidence state: **VERIFIED_ENGINEERING**. Driver: `tests/journey/browser_b01_journey.py`, wrapper `tests/journey/test_b01_browser_streaming.py`. Two variants of the same script: **fixture** (controlled 16-piece provider, 0.3 s apart; also exercises provider outage and a real server restart) and **real** (workstation Ollama behind the tap). The page is the unchanged approved UI; the only front-end edits are the `stream` event handler and the Stop wording (no visual change). Missing capability fails; nothing skips.

| # | Directive journey step | Script step | Fixture | Real Ollama |
|---|---|---|---|---|
| 1 | Sign in | J1 | pass | pass |
| 2–4 | New conversation, long prompt, **progressive output** | J2 — MutationObserver records the DOM; ≥3 distinct text lengths, ≥1.5 s (fixture) / ≥0.8 s (real) spread; `stream` event upstream+cancellable; final text == provider text | pass | pass |
| 5–7 | Stop usable → stop midway → **provider cancelled** | J3 — Stop control present while streaming; click; interrupted badge; wording "model connection was closed … not saved"; no `done` event; fixture: `stream_aborts +1`, `streams_open 0`, `chunks_sent` frozen; real: tap `client_aborts ≥ 1`, `open_streams 0` | pass | pass |
| 8 | **No phantom completed turn** | J3 — committed transcript unchanged; billing +1 unit (established policy) | pass | pass |
| 9 | Second prompt succeeds | J4 | pass | pass |
| 10–11 | Full response completes; **saved correctly, once** | J5 — saved == DOM; answer rendered once | pass | pass |
| 12 | Refresh recovers transcript | J6 | pass | pass |
| 13 | Next prompt uses correct history | J7 — provider's request contains committed turns, not the stopped prompt | pass | pass (page-level) |
| 14–15 | Edit an earlier message; context reflects it | J8 — provider's next request has the edited text and not the original | pass | pass (page-level) |
| 16 | Logout / token revocation | J12 — token revoked elsewhere; page returns to sign-in; provider request counter unchanged | pass | pass |
| 17 | Temporary chat | J11 — not listed; transcript gone after close | pass | pass |
| 18 | Two-tab isolation | J9 — two tabs stream two conversations concurrently; no cross-talk; each transcript exactly its own | pass | n/a (needs controlled provider) |
| 19 | Provider outage and recovery | J10 — 503 provider: error note, no chunk/done, no phantom turn, quota unchanged, page not stuck; recovery: next prompt answered and billed once | pass | n/a (cannot make real Ollama fail) |
| 20 | Server restart and persistence | R1/R2 — server process stopped and started on the same `ORNEUR_HOME`; re-login; the conversation is in the sidebar with the same id and message count; a new prompt is streamed and saved | pass | n/a (covered by live C2 on the real model) |

Also asserted: no uncaught page errors (`PAGE_ERRORS` absent) and no provider generation left running at the end.

Results on the final code: `pytest tests/journey/test_b01_browser_streaming.py` → 26 passed (fixture 15, real 11) as part of the 106-test journey run in `evidence/journeys_all_literal_llama3.2-1b_final.txt`.

A test that only checked a CSS animation or a spinner would not prove streaming; these assert on the wire (`window.__sseLog` via a fetch tap), on the DOM over time, on the provider's own counters and on the stores.
