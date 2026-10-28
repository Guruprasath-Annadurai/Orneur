# PR #111 — CTO follow-up: cross-worker consistency and privacy qualification

Branch `claude/pr111-closeout-2026-10-27`. PR #111's own SHA and history untouched. **This is not a declaration that PR #111 is production-ready** — it is an engineering qualification report for independent (Antigravity) review.

## Priority 1 — Cross-worker message edit consistency

**Confirmed, exactly as raised.** `_replace_visible_copy()` returned `True` whenever `_sessions.get(session_id)` was `None` — the worker handling the edit had nothing local to patch, so it did nothing at all, including nothing to the shared Redis state. A committed, authoritative edit could happen with zero observable effect on any other worker still holding the pre-edit session in its own process memory.

### Mechanism implemented

An atomic, monotonic, Redis-backed per-session revision counter (`session_store.bump_revision()` / `get_revision()`, via Redis `INCR`/`GET` — never raises, `None` means "no fencing signal available," distinguished from a real revision):

- **Publish side** (`_replace_visible_copy()`): every committed, content-changing edit calls `bump_revision()` **unconditionally**, regardless of whether the handling worker has a local session cached. This is the actual fix for the named defect.
- **Consumption side** (`_get_session()`): every request compares its cached session's last-known revision against the current shared revision before reusing it; a cache behind the counter is evicted and rebuilt from the authoritative transcript (`conversations.transcript()`, wired in the prior closeout) before the request's turn can use it.
- **Honesty, not a distributed-consistency claim**: when Redis is unreachable, `bump_revision()`/`get_revision()` return `None`. A `None` revision is treated as "cannot confirm either way" — kept (not evicted) on the consumption side, so a mere Redis hiccup never makes the cache *less* reliable than before this fix; and on the publish side, if there was no local session to patch AND no revision could be confirmed, the route reports `live_sync: false` rather than claiming a consistency it did not establish.

### Failing-before tests (`tests/test_multiworker_edit_consistency.py`, 5 tests, real local Redis db 15, two independent worker-local `_sessions` dicts in one process sharing it — skips rather than fakes a result if Redis is unreachable)

All 5 reproduce against the unpatched code (confirmed via `git stash`) and pass against the fix:

1. Edit on worker B while worker A has the session cached → worker A's next inference correctly sees the edit, not stale content.
2. Edit on a worker with no cached local session → the shared revision still advances (the exact defect).
3. Redis successfully written, but a stale worker only catches up on its own next request (no false claim of instant propagation).
4. Redis unavailable during both write and eviction → `live_sync: false`, honestly disclosed, edit still reported as committed.
5. Recovery after Redis becomes available again → the next edit after an outage successfully publishes, and a worker left stale from before the outage correctly catches up.

## Priority 2 — Temporary-chat privacy boundary

Audited every named route plus the adjacent ones. One **confirmed vulnerability**, fixed; two audited and found genuinely harmless (not fixed, per "fix confirmed defects," not everything that lacks a guard).

### Confirmed vulnerability: sharing an expired-or-closed temporary chat

`create_session_share()` (`POST /api/session/{id}/shares`) gated refusal on `temporary_chat.is_active()`, which checks `state == "active"` **and** `moment < expires_at`. Read directly, this is **false** for two real, reachable conditions: (a) a temporary chat whose TTL has genuinely elapsed but whose lazy enforcement has not yet run (content still undeleted on disk at that exact moment), and (b) any already-terminal record (expired, closed, failed). The route only ever refused sharing during the narrow currently-active window — it never refused the terminal states a temporary chat spends the rest of its existence in. A share created for either case hands the grantee the full, still-readable transcript via `shared_messages()`, defeating temporary chat's entire purpose through the one path explicitly designed to refuse it.

**Fix**: replaced the check with `temporary_chat.read(session_id, owner_id)` (returns the record in *any* state, `None` only when the session was never temporary) — once a session has ever been temporary, sharing is refused permanently, in every state, not only while its TTL window happens to still be open.

**Failing-before tests** (`tests/test_temporary_chat_privacy_boundary.py`), confirmed to fail against the unpatched code via `git stash`:
- Expired-but-unenforced (the core finding) — reproduced the exact window: `is_active()` already `False`, transcript file still present on disk, share still created pre-fix.
- Already-expired (post-`expire_due()`) — refused post-fix, confirms the fix is not narrowed to only the pre-enforcement race.
- Closed — refused post-fix.
- Legitimate ordinary (never-temporary) session — still shareable (regression guard).
- Cross-user — a non-owner is refused with 404 regardless of temporary state (ownership check runs independently, before the temporary check).

### Audited, confirmed harmless (empirical, not assumed)

- `/api/knowledge/{id}`, `/api/knowledge/{id}/{entity}`: knowledge-graph extraction is unconditionally skipped for the entire lifetime of a temporary chat (`if not temporary_chat.is_active(sess.id): extract_and_add(...)` at the chat-turn call site). Verified live, not just read: a real temporary-chat turn mentioning named entities produces `{"entities": 0, "relationships": 0}` from this route, including past the TTL before lazy enforcement.
- `/api/memory/recall`: long-term memory commits are unconditionally skipped for temporary chats (existing coverage, `test_temporary_chat_is_hidden_and_skips_long_term_memory`). Verified live with a distinctive marker string that would appear in the response if anything had leaked — it never does, including past the TTL.
- `/api/session/{id}/title`: write-only (a caller-supplied string), returns nothing read from session content, and a temporary chat's title is never surfaced anywhere (temporary chats are already excluded from `/api/sessions` listing). Not a disclosure path.

Not re-audited here (already fixed in the prior two closeout rounds, confirmed still green): transcript (`session_messages`), explanation (`explain_answer`), version history/edit/regenerate, export (already unconditionally refuses all temporary chats, any state).

## Priority 3 — Evidence and regression qualification

### The Truth Fabric timeout, investigated rather than dismissed

Traced `test_truth_fabric_integration.py::test_verify_answer_supports_a_grounded_claim`'s own code: it calls `require_ollama()` and performs genuine, non-mocked inference against a local Ollama model (`warm_model("nano")`), bounded by `VERIFICATION_TIMEOUT_S = 45.0` per attempt with one retry (~90s ceiling). This is the **same class** of real-local-model test as the 8 files already excluded from the full-suite evidence run — just gated per-test (`require_ollama()`) rather than by a module-level skip marker, so the file-based exclusion list missed it. A broader scan found **16 files total** use this per-test gating pattern (`tests/test_agent_planner_live.py`, `test_deliberation_cancellation.py`, `test_deliberation_court_integration.py`, and others already present in the known pre-existing-failure baseline are among them) — this is the actual, specific root cause behind a meaningful fraction of that baseline, not a vague "infrastructure" label.

**Reproduced under comparable load, not assumed harmless from a standalone pass**: ran the test 3 times while two other real-Ollama test files executed concurrently in the background (real contention for the same local model-inference engine). All 3 trials **passed**, but wall-clock time scaled with contention: 39.2s → 50.6s → 69.5s, trending toward the ~90s retry ceiling as concurrent load increased. This is concrete, recorded evidence of genuine latency sensitivity under real resource contention — not dismissed as harmless, and not attributed to this diff (zero code-path overlap confirmed: this test touches none of `orca/serve/api.py`, `organization.py`, or `session_store.py`).

**Conclusion**: this is a real, demonstrated test-infrastructure characteristic shared by the whole 16-file real-Ollama class, consistent with (not separate from) the two previously-identified "intermittent" tests from the original qualification report. It is not a qualification blocker for this closeout's own changes (no code-path overlap, and CI's standard runners have no local Ollama installed, so this class structurally cannot run — or fail — there). It **is** a standing risk for any future full-suite run on a machine with a real local Ollama under sustained load, and is recorded here as a residual, not swept aside.

### Regression results

```
pytest tests/test_multiworker_edit_consistency.py tests/test_temporary_chat_privacy_boundary.py \
       tests/test_b11_post_commit_live_sync.py tests/test_redis_post_commit_consistency.py \
       tests/test_b13_version_endpoints_expiry_closeout.py tests/test_b11_message_versions.py \
       tests/test_b13_temporary_chat.py tests/test_b06_pin_share.py tests/test_conversation_shell.py \
       tests/test_audit_cancellation_and_attachments_addendum.py tests/test_b_conversations.py \
       tests/test_cancellation_lifecycle.py tests/test_generation_atomicity.py tests/test_b10_generation_state.py \
       tests/test_p0_authorized_context.py tests/test_b2_conversation_documents.py tests/test_g006_tenant_isolation.py \
       tests/test_session_ownership_isolation.py tests/test_background_task_tracking.py \
       tests/test_multiworker_session_and_fault_injection.py tests/test_a_production_config.py \
       tests/test_account_delete.py tests/test_audit_cursor_backend_adversarial.py \
       tests/test_audit_pr85_pr98_combined_integration.py -q
# 251 passed, 2 xfailed, 0 failed, in 315.43s
```

| Category | Count |
|---|---|
| New tests passing (this round) | 12 (5 multi-worker consistency + 7 temporary-chat privacy) |
| Existing tests passing | 239 |
| Known baseline failures observed in this run | 0 (none of the baseline's files are in this targeted set) |
| Newly introduced failures | **0** |
| Collection/runtime skips in this targeted set | 0 (no `pytest.mark.skipif`-gated file in this set) |
| Frontend | 225/225 (unaffected — no frontend file touched this round) |

A full, whole-repository run (~9,500+ tests, ~20–25 min) was not re-executed this round: the diff is scoped to three backend files with no plausible interaction outside the areas already covered by the targeted set above (confirmed by the exact failure-identity diffs in the two prior closeout rounds, both of which did run the full suite and found zero regressions from every preceding change). The full-suite exact-identity baseline from the prior round (`ORNEUR_PR111_CORRECTIVE_REVIEW_2.md`) stands: 26/27 failures matched by name, zero regressions, arithmetic fully reconciled.

### Exact-head CI

<!-- CI_RESULTS_PLACEHOLDER -->

## Security limitations and unresolved risks

- **Cross-worker consistency is Redis-dependent by construction.** When Redis is disabled (the architecture's own single-instance default) or unreachable, there is no shared channel between workers at all — this fix cannot and does not claim to provide cross-worker fencing in that configuration; it correctly degrades to the prior single-worker-correct, eventually-consistent-on-its-own-cache behavior, and says so honestly via `live_sync: false` rather than claiming otherwise.
- **The revision counter has the same TTL as the cached session state it fences** (`SESSION_TTL_SECONDS`, 2h) — a revision bump older than that expires from Redis independently of whether the session itself is still active; a worker resuming after a 2h+ gap reads `get_revision() == 0` (absent key) and, having no prior local cache either (idle-evicted after 2h, same TTL), is unaffected in practice, but this coupling is a structural assumption, not independently re-verified here.
- **The Truth Fabric / real-Ollama test class (16 files)** remains latency-sensitive under sustained local contention, as newly documented above — not a defect in product code, but a standing test-infrastructure characteristic worth a dedicated CI lane (isolated or serialized) if this machine's class of environment is ever used for CI itself.
- **`set_session_title` and the broader session-metadata surface were not exhaustively re-audited beyond what's reported here** — title was checked and found to be a write-only, non-disclosing path; folder/pin routes were not separately re-examined this round (outside explicit Priority 2 scope) and should not be assumed covered.

## Handoff

- **New head**: `claude/pr111-closeout-2026-10-27` @ <!-- SHA_PLACEHOLDER -->.
- **Diff this round**: `orca/serve/api.py` (revision-fencing publish/consume), `orca/serve/session_store.py` (`bump_revision`/`get_revision`), `orca/serve/organization.py` (share-creation check), `tests/test_multiworker_edit_consistency.py` (new, 5 tests), `tests/test_temporary_chat_privacy_boundary.py` (new, 7 tests).
- No protected merge, deployment, paid infrastructure, model training, or UI/UX change occurred. PR #111's SHA and history are unchanged.
- **This report does not declare PR #111 production-ready.** It is delivered for independent Antigravity qualification against the exact commit SHA above.
