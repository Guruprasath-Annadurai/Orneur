# P1 — Browser User Journeys (work-order matrix of 14)

All browser journeys run real Chromium against a real `orca serve` process. "Fixture" = a controllable provider that fixes timing (it is not intelligence); "Real" = local Ollama `llama3.2:1b`.

| # | Journey | Provider | Evidence | Status |
|---|---|---|---|---|
| 1 | Register → verification → login → conversation | fixture | A1–A3 (sink mail) then M1 | VERIFIED (mail = local sink; real inbox BLOCKED_EXTERNAL) |
| 2 | Login → genuine inference → streamed response → logout | **real** | real-model browser suite (55 passed on baseline) + A4 logout | VERIFIED |
| 3 | Start → Stop mid-stream → correct server outcome | fixture + real | B01 J3, N1 (touch), real `test_S4_S5_S6` | VERIFIED |
| 4 | Follow-up carries authorised context | **real** | identity probe: turn 2 request contained turn 1 | VERIFIED |
| 5 | Create → restart server → reopen exact conversation | fixture + real | B01 R1/R2, `test_C2` | VERIFIED |
| 6 | Rename → search → reopen → delete | fixture | M2, M3, M5, M6 | VERIFIED |
| 7 | Two users → cross-user access → refusal | fixture | M4 | VERIFIED |
| 8 | Invalid/expired token → refusal, no provider dispatch | fixture | B01 J12, A4/U2 old-token 401 | VERIFIED |
| 9 | Provider outage → accurate failure → recovery | fixture | B01 J10, Q1 | VERIFIED |
| 10 | Network interruption → retry/commit correctness | fixture | B01 cancel/outcome suites, Q4 | VERIFIED (existing + new) |
| 11 | Quota exhaustion → refusal without cost | fixture | Q2 | VERIFIED (API-level; no browser quota banner test) |
| 12 | Mobile: open navigation → send → stream → Stop → reopen | fixture | N1, N2, B1 | VERIFIED |
| 13 | MFA and password-recovery flows | fixture (mail sink) | A5–A8, U3–U5 | VERIFIED; **MFA recovery codes NOT_IMPLEMENTED**; real email BLOCKED_EXTERNAL |
| 14 | Concurrent streams → bounded admission → no leaks | **real** + fixture | real run: 4 concurrent streams, 4/4 ok, fds 47 / RSS 91 MB after; existing concurrency journey (in the 39-test group) | VERIFIED at the tested scale |

Run commands are in `P1_ANTIGRAVITY_INDEPENDENT_HANDOFF.md`.
