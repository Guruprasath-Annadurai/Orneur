# P1-E — Conversation Persistence and Management

Existing database/session authority used; no second storage model was introduced.

| Requirement | Evidence | Result |
|---|---|---|
| Create, list, open, resume | manage M1, M5 (real server, real browser) | VERIFIED |
| Rename persists across reload; server holds the new title | M2 | VERIFIED |
| Search by content over the caller's own data only | M3 (alice finds it; bob, who has his own conversation, gets "No matching conversations") | VERIFIED |
| Cross-user access refused (read/export/rename/delete/stream) | M4 | VERIFIED |
| Close browser, log in again, exact transcript restored | M5 compares server transcripts before and after | VERIFIED |
| Delete needs a second click; removes from UI, API and after reload | M6 | VERIFIED |
| Survives application restart | B01 R1/R2; real-model C2; perf run | VERIFIED |
| Two tabs / two workers / Redis interruption | B01 J9, `test_E3_edit_on_server_B…` (real Redis, two servers), L02 recovery suite | VERIFIED (existing, re-run) |
| Interrupted stream leaves no completed turn | Q4, N1 | VERIFIED |
| Deletion ledger / privacy protections | L02 deletion suite re-run green (25-test group) | VERIFIED (existing) |
| Temporary conversations hidden, unshareable, deleted on close | existing F1, B01 J11 | VERIFIED (existing) |
| Export (MD/JSON) | menu present and wired; the route is covered by existing tests; no new export test | IMPLEMENTED, not newly verified |

Not newly tested here: simultaneous rename vs delete races, search during update, delete during generation (these rely on the existing cancel-race and deletion suites; no new race harness was built).
