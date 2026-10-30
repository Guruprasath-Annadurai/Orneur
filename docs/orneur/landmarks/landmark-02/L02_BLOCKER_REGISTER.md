# LANDMARK-02 — gap / blocker register (final)

Baseline `9cb864c99ad323d11626063498a7d1cef0d7d4b5` (PR #136, unmodified). States: `FIXED` = engineering-verified with evidence listed in the matrix/reports; nothing is independently qualified (only Antigravity can set that).

## A. Defects found and closed
| ID | Sev | Finding | State |
|---|---|---|---|
| L02-01a–d | P1/P2 | partial deletion reported as success; doc delete left keyword text retrievable; no tombstone; retention/account deletion ignored failures | FIXED |
| L02-01e | P2 | temporary-chat closure bypassed the deletion workflow | FIXED (closure + TTL sweep use it; `409` contract kept) |
| L02-01f | P2 | no live failure qualification | FIXED — live D1–D6 (Redis down, two workers, in-flight, restart, vector failure, real embeddings) |
| L02-02a–d | P1 | discarded Kernel answer billed; upload parse before ownership; chunk identity; unregistered chunks / fail-open judge | FIXED |
| L02-02e | P2 | judge/reranker/rewriter prompt steering by passage text | FIXED structurally (70 tests); answering-model obedience not provable |
| L02-02f | P2 | tool calls from model output executed without independent authority | FIXED (`orca/tools/authorization.py`) |
| L02-02g | P3 | no sweep for a half-deleted document | FIXED |
| L02-02h | P1 | unbounded/unsafe PDF/DOCX parsing, zip bombs, quotas | FIXED (isolated extraction; real parsers, workstation) |
| L02-03 | P1 | outcome of a request after a drop was unknowable; stale idempotency row after a killed worker blocked retry (found live) | FIXED |
| L02-04 | P1 | no email verification, enumeration, no lockout, reusable tokens | FIXED (delivery to a real mailbox not exercised) |
| L02-05 | P2 | orphan/corrupt deployment records broke listing and accumulated | FIXED (synthetic fixtures) |
| L02-06 | P1/P2 | 4/24 concurrent streams failed as `backend_error`; Kernel stream path had no admission cap; readiness hung 5 s with Redis frozen; fd leak from duplicate diskcache copies; no drain; no backup/restore | FIXED |
| L02-06b | P2 | the new data-directory CLI group shadowed the documented `orca backup --keep N` | FIXED (`orca data-backup …`; test pins both) |
| L02-08 | P2 | model could claim native identity/abilities; tool reporting not limited to executed tools | FIXED |
| L02-CI1 | P2 | CDP pipe used `select()` (fails for descriptors ≥ 1024 — a busy server process) | FIXED (`poll()`, red-then-green test) |
| L02-CI2 | P2 | Two workers cold-starting on one empty data directory could crash one with `database is locked` at the WAL switch (pre-existing; surfaced by the L02 two-worker live tests) | FIXED (bounded retry; probabilistic regression test) |
| CI | – | three CI failures on `7059629`: stale test assumptions (serving-facts message position, per-account lockout vs per-IP test, backend-dependent wiring test) | FIXED (test-side; reasons in the security matrix) |

## B. Open items
| ID | Sev | Finding | Disposition |
|---|---|---|---|
| **L02-Q** | **P1 (process)** | This head has **no independent qualification** | OPEN — Antigravity (`L02_ANTIGRAVITY_HANDOFF.md`). A process gate, not a known defect |
| L02-B1 | P2 | Real-Ollama journeys (`*_real`, D6, document-real, B-01 real-Ollama) and the real-parser suite (optional `docs` extra) run on the workstation only; CI runs the fixture-provider variants of the live deletion (not D6), recovery, operations, account and customer-journey suites | external: needs CI runner with Ollama (paid/infra decision not taken) |
| L02-B2 | P2 | Prompt injection into the *answering* model is mitigated structurally only; no provable guarantee | accepted, disclosed |
| L02-B3 | P2 | API-key creation does not require re-authentication | open, not changed (scope) |
| L02-06a | P2 | A held Chroma lock can freeze the process (library holds the GIL) — `evidence/l02_chroma_lock_freezes_process.txt` | open; bounded callers elsewhere; needs a vector-store design decision |
| L02-B4 | P2 | ≈3.5 fds per active conversation from per-conversation vector indices; readiness goes false near 90 % of the fd limit | documented; not removed |
| L02-B5 | P3 | disk/fd headroom behaviour shown with simulated thresholds, not a really full disk | accepted |
| L02-B6 | P3 | Backups are unencrypted and on the same host unless the operator moves them; existing backups keep deleted data | disclosed in the deletion response; operator duty |
| L02-B7 | P3 | The C11 Variant B recovery panel is not rendered in `/conversation`; recovery uses existing notice surfaces | accepted; design flow untouched |
| L02-B8 | P3 | `turn_requests` retained 24 h; older keys unknown | accepted |
| L02-B9 | P3 | `/readyz` can lag up to 15 s (model-list cache) after the model backend dies (O5) | accepted |
| L02-B10 | P3 | Truth-Fabric answers and document sessions are delivered whole (B-06, L-01 unchanged) | unchanged |
| L02-B11 | P3 | Only Chromium; no mobile/a11y automation | accepted |
| L02-B12 | P3 | No capacity/SLO claim exists; all numbers are single-workstation measurements | by design |
| L02-B13 | P3 | A real mail provider/SMTP path was not exercised (local sink only, by order) | external |
| Carry-over | P2/P3 | B-05, B-07 … B-11 from LANDMARK-01 unchanged unless named above | unchanged |

## C. Counts
Unresolved **P0: 0**. Unresolved **P1: 1** (L02-Q, independent qualification, a process gate). P2 open: L02-B1, B2, B3, 06a, B4. P3 open: B5–B13. No finding is hidden by a skipped test; CI's 399 skips and 6 xfails are the pre-existing conditional skips (same set as the PR #136 head plus one), none belong to L02 tests.
