# L02-07 — Real customer journeys (real Chromium, approved `/conversation` UI)

Evidence state: **VERIFIED_ENGINEERING**. Harness: `tests/journey/browser_l02_journeys.py` driven by `tests/journey/test_l02_customer_journeys.py` (6 runs = 3 personas × {fixture, real}). Chromium via Playwright 1.49.1, real `orca serve` process(es), real Redis container where the step needs it, local mail sink (no real email). No visual redesign: only reconcile/Stop/verification handlers and model-detail rows were added to `conversation.html`; brand, themes and approved flows are untouched.

**Two labelled classes, never mixed:** `fixture` = FakeOllama provider (deterministic, runs in CI); `real` = real Ollama, literal tag `llama3.2:1b` (third-party weights), **workstation only**. Final run on the final code: `6 passed in 118.5 s`; timestamps 17:11–17:13 on 2026-10-29 in each JSON.

| Persona | Mode | Steps passed | Evidence |
|---|---|---|---|
| Student | fixture | 11 / 11 | `evidence/l02_journey_student_fixture.json` |
| Student | real Ollama | 11 / 11 | `evidence/l02_journey_student_real.json` |
| Solo developer | fixture | 9 / 9 | `evidence/l02_journey_developer_fixture.json` |
| Solo developer | real Ollama | 8 / 8 (D7 provider-failure step is fixture-only: a real model cannot be made to fail on demand) | `evidence/l02_journey_developer_real.json` |
| Business owner | fixture | 9 / 9 | `evidence/l02_journey_business_fixture.json` |
| Business owner | real Ollama | 9 / 9 | `evidence/l02_journey_business_real.json` |

Each JSON lists every step with `ok` and a detail line, plus a `PAGE_ERRORS` check (no uncaught page error).

## What the journeys prove (real Chromium)
* **Student:** sign up in the page → no session until the emailed link is opened → link opened (GET does not spend it) → confirmed → reuse refused; the selector names the model and the panel says "EXPERIMENTAL — not qualified"; streaming is progressive; a follow-up uses earlier context; upload a study document and get a sourced answer; an unanswerable question gets a truthful uncertainty path with no invented source; Stop says what actually happened; after an interruption the conversation is recovered from the server; delete removes the conversation and its stored material; logout kills the token.
* **Developer:** readable multi-line code, no broken markup mid-stream, final text equals saved text, follow-up carries the code, long answer scrolls and is saved once, Stop-then-retry leaves exactly one completed turn, suggested code is not presented as executed; (fixture) provider failure is explained without internals and not charged.
* **Business owner:** multi-turn analysis; confidential document with evidence separated from suggestions; nothing claimed as done; a **TCP-level network cut mid-answer** (`CutProxy`) leaves the page reporting what the server says (not a false failure/conflict); reload restores; document removal then conversation deletion; log out everywhere ends the other device's session.

## Defects the journeys found (fixed, then re-run)
Stale-note race (test side); an emulated-offline mode that did not cut a stream (replaced by a real TCP cut); a **product** UX defect — after a dropped connection the same-key retry produced a visible conflict error instead of reconciling with the server (fixed in `conversation.html`, pinned by `tests/frontend/test_l02_outcome_recovery.mjs`). Screenshots named `*_FAIL.png` under `/tmp/orneur-journey-artifacts/l02` are from those earlier failing runs, not from the final passing run; they are not committed.

## Not shown
Mobile viewports, other browsers (only Chromium), screen readers, load with many users, a real mail provider, the C11 Variant B panel (see register L02-B7). The real model is a 1B third-party model: answer quality is not graded and no accuracy claim is made.
