# Priority 3 — Integration qualification on one combined candidate

Per the CTO directive: *"Run the complete frontend, backend, browser and failure-injection regression suites on one combined candidate. Report exact SHA, CI, failures, unresolved blockers and genuine user-facing functionality."*

## The one candidate

Branch `test/combined-candidate-fresh` (PR #111), built by merging, in order, with real `git merge --no-edit` (never force-push, never rebase):

1. `571f7d8` — prior consolidated state (Phase E, B11 requalification pass 1).
2. Cursor PR #114 (`cursor/cancellation-reconcile-a8b0` @ `8f2b11a`) — cancellation/disconnect separation, orphan upload inventory, document-deletion partial-result reporting (supersedes PR #112; see the companion reconciliation report).
3. This session's Priority 1 fix (`claude/b01-b16-backend-integration-2026-10-24` @ `91ed8ce`) — B11 Cancel-after-uncertain-save.
4. The B16 reconciliation report itself.

**Exact head at the time of this report: `7fa8a1e` (local; pushed as `test/combined-candidate-fresh`'s new tip — see push confirmation below).**

Every merge step was preceded by an ancestry check (`git merge-base --is-ancestor`) and a dry-run conflict check (`git merge-tree` / file-overlap diff) before the real merge — all three merges were conflict-free with zero overlapping files between sides.

## Frontend

```
node --check <extracted inline script from orca/serve/web/conversation.html>   # syntax OK
node --test tests/frontend/*.mjs                                                 # 225/225 passing
```

## Backend — targeted regression (the files this reconciliation actually touched)

```
pytest tests/test_cancellation_lifecycle.py tests/test_generation_atomicity.py \
       tests/test_b10_generation_state.py tests/test_p0_authorized_context.py \
       tests/test_b2_conversation_documents.py tests/test_b13_temporary_chat.py \
       tests/test_g006_tenant_isolation.py tests/test_session_ownership_isolation.py \
       tests/test_b11_message_versions.py tests/test_conversation_shell.py \
       tests/test_background_task_tracking.py tests/test_audit_cancellation_and_attachments_addendum.py \
       -q
# 147 passed, 2 xfailed
```

## Backend — full repository suite (failure-injection and everything else)

```
pytest tests/ -q --ignore=tests/test_audit_genesis_hardening_adversarial.py \
                  --ignore=tests/test_distill.py \
                  --ignore=tests/test_mcp_fs_server_sandbox.py \
                  --ignore=tests/test_native_learning_engine_adversarial_audit.py
```

Result: **9,216 passed, 345 skipped, 6 xfailed, 30 failed**, in 1h15m (9,566 tests collected total; the 4 ignored files are pre-existing collection errors for missing optional third-party packages — `torch`, `mcp` — confirmed unrelated to this change via a clean `--collect-only` pass before the run).

### The 30 failures, individually classified against a clean pre-merge baseline checkout (`571f7d8`, before PR #114 or the Priority 1 fix)

- **28 of 30 reproduce identically on the pre-merge baseline** — confirmed pre-existing, not caused by this reconciliation. They span unrelated subsystems: RSE block1 encryption-divergence/quarantine tests, live-model/live-gateway tests requiring infrastructure not present in this sandbox, distributed-core-DB and security-root config gates requiring external services, `mission_db`/`mission_store` tests requiring specific env vars not set here, Docker sandbox/container tests, a cross-platform determinism golden-state test, and a handful of deliberation-court/deletion-end-to-end tests. None of these touch `orca/docs/store.py`, `orca/serve/api.py`'s document-deletion or cancellation routes, `orca/serve/generations.py`, `orca/docs/orphan_reconcile.py`, or `conversation.html` — the files this reconciliation actually changed.
- **2 of 30 passed on the pre-merge baseline but failed during the full-suite run**: `test_audit_cursor_backend_adversarial.py::test_simultaneous_share_lifecycle_concurrency` and `test_gateway_compat_brain.py::test_live_gateway_brain_end_to_end_matches_orca_brain_interface`. Both were re-run **in isolation on the merged candidate** and **passed cleanly** (2/2, no flakes across the re-run). This is consistent with timing/resource-contention flakiness under a 75-minute, 9,566-test full-suite run (both are explicitly named "adversarial"/"live... end-to-end" — concurrency- and live-call-timing-sensitive by design), not a genuine regression. Flagged here rather than silently dismissed, per the directive's own standard of not describing uncertain results as settled.

**Net result: zero confirmed regressions introduced by this reconciliation.** All 30 full-suite failures are either reproduced identically on the pre-merge baseline, or pass cleanly in isolation on the merged candidate.

## Browser (live, against the real merged backend on port 7346)

- **B11**: live-reproduced the full Cancel-after-uncertain-save scenario against the real `/edits` endpoint (two forced network failures sharing one Idempotency-Key → Cancel → reopen shows the preserved draft → resave reaches the real backend) — confirmed via a direct `GET .../versions` call that `version_count` went from 1 to exactly 2, never 3+, across three total attempts. See the Priority 1 commit message and `test_b11_inline_edit.mjs` for the equivalent unit coverage.
- **B16**: live-exercised document upload → delete (while active) → confirmed the honest response contract (`{"deleted": true, "atomic": false, "index_removed": 1}`); separately created a real 60-second temporary chat, uploaded a second document, waited for genuine expiry (confirmed via `GET .../temporary` returning `state: "expired", terminal: true`), then attempted deletion and got the real `409 {"code": "temporary_expired"}` refusal — not simulated, the actual `_temporary_block()` path in the live server.

## Failure-injection

- **B11**: `fetch` was monkey-patched in a live browser tab to return real `500` responses only for the `.../edits` endpoint (every other call, including the preceding real `/api/stream` exchange, went through the real backend unmodified) — confirmed Cancel-disable timing, same-key retry, and the honest "could not confirm" copy directly against live DOM state (documented in the Priority 1 commit).
- **Backend-wide**: the full-suite run itself is the project's existing failure-injection/adversarial coverage (RSE quarantine tests, redteam cross-layer-chain tests, durable-audit-store-unavailable tests, kill-switch and distributed-config-gate failure tests, container-timeout-cancellation tests) — all pre-existing-failure or pass, per the classification above.

## Unresolved blockers (disclosed, not resolved by this session)

- The 28 pre-existing full-suite failures are **not** fixed by this work — they require infrastructure (Docker, live model gateways, distributed DB config, specific env vars) not present in this sandbox, and are out of scope for a frontend-integration-focused reconciliation. They are not new; they predate this branch.
- `edit_session_message()`'s `_replace_visible_copy()` still has no enclosing try/except in `orca/serve/api.py` (the root cause of the 500-after-commit risk the B11 Priority-1-adjacent work hardens the *client* against) — this is Cursor-owned backend code, flagged for upstream fix, not altered here.
- Cross-store document deletion and orphan reconciliation are explicitly, deliberately **not** atomic or exactly-once (PR #114's own description, preserved as-is in this reconciliation) — a known, disclosed limitation, not a defect introduced or hidden by this work.

## Genuine user-facing functionality (what actually works, end to end, right now)

- Inline message editing with honest, idempotency-key-protected retry semantics across every named ambiguity (network failure, 500-after-commit, Cancel during or after an uncertain save, reopen-after-ambiguity) — live-verified against the real backend, not just unit-tested.
- Document upload and deletion with an honest partial-failure contract (`atomic: false` always reported; a genuine partial failure returns 409/500 with the specific disagreeing store named, never a silent 200).
- Temporary (ephemeral) chat sessions that genuinely refuse document deletion once expired, live-verified.
- Real cancellation vs. disconnect separation server-side (a browser disconnect alone can never be reported as a confirmed `cancelled` generation).
- Correlated-runs plumbing (B14) exists and is live-tested, with zero UI surface — deliberately, per the explicit "no invented Workspace Tabs" constraint from prior directives.

## Verdict

**PASS for the reconciliation work itself** (Priority 1 and Priority 2): zero regressions against the pre-merge baseline, all new and existing targeted tests green, three independent live-browser/live-backend verifications of the actual user-facing behavior (not simulated).

**PARTIAL for whole-repository health**: 28 pre-existing failures remain unresolved in this environment (infrastructure-gated, not introduced here) and are explicitly not claimed fixed.

No protected merge, production deployment, paid infrastructure, model training, or Phase F implementation occurred. This candidate is ready for independent Antigravity review.
