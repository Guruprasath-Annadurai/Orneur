# FOUNDATION_01_CORRECTIVE_CLOSURE_REPORT

**Milestone:** FOUNDATION LANDMARK-01 — Corrective CI recovery and evidence freeze  
**Authority:** ORNEUR CTO (engineering acceptance only)  
**Owner:** Cursor  
**Independent qualification:** Antigravity — **not claimed here**  
**Draft PR:** https://github.com/Guruprasath-Annadurai/Orneur/pull/132  
**Branch:** `cursor/foundation-landmark-01-backend-closure-1cdf`  
**Report timezone:** Asia/Calcutta

## 1. Original failing SHA

| Field | Value |
|---|---|
| Failed PR head (CTO review) | `1ffb7b8562de0dd819833c93471599692946f666` |
| Push Test Suite (FAILED) | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40719785862 |
| PR Test Suite (FAILED) | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40719797352 |
| Eval Static Checks (PASSED) | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40719798113 |
| Failed job | Deterministic Unit Tests |

Prior functional product tip under the docs pin: `799a3d32a2b2080695107ebc429f0696b6a399de`.

## 2. Root causes (G006 + S2)

| Failure | Classification | Actual cause |
|---|---|---|
| `tests/test_g006_tenant_isolation.py::test_07d_revoked_api_key_stops_working_and_keys_are_user_scoped` | Test fixture defect vs strengthened product | Revoked API key correctly returns **401**. Test still expected **404** from the pre–FOUNDATION-01 anonymous-downgrade behavior. Product behavior is correct; expectation was obsolete. |
| `tests/test_s2_customer_correctness.py::test_quota_and_plan_gates_carry_codes_on_chat_and_stream` | API contract evolution + test fixture defect | Pre-stream admission refusals for `model_access_denied` return **HTTP JSON 402**, not SSE `error` events on a 200 stream. Test called `_events()` and IndexError’d on empty SSE. |
| `tests/test_s2_customer_correctness.py::test_moderation_refusal_has_its_own_code_and_no_model_call` | Same as above | `content_refused` on `/api/stream` is **HTTP JSON 400** with zero model dispatch; SSE parser path was wrong. |

**Not:** product-code security regression, missing dependency, or environment misconfiguration.

## 3. Exact corrections

Commit `2b6b6de8eccb2acbfaa5ece7ba52cebee8c357c8`:

1. G006 expects **401** for revoked API key (fail-closed auth).
2. S2 asserts stream HTTP JSON status + `code` for plan gate and moderation; asserts `fake.requests == []`.
3. `BACKEND_FRONTEND_CONTRACT.md` documents pre-stream HTTP JSON refusals.

No tests removed, skipped, or weakened. No insecure HTTP acceptance.

## 4. Functional CI tip (product + CI fix)

| Field | Value |
|---|---|
| Functional exact SHA | `2b6b6de8eccb2acbfaa5ece7ba52cebee8c357c8` |
| Push Test Suite | `40733516543` — **SUCCESS** (9/9) — https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40733516543 |
| PR Test Suite | `40733526194` — **SUCCESS** (9/9) — https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40733526194 |
| Eval Static Checks | `40733526200` — **SUCCESS** — https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40733526200 |
| Deterministic Unit Tests (PR run) | **PASS** — `8941 passed, 372 skipped, 75 deselected, 7 xfailed` (~17m 48s) |

## 5. Document-bearing HEAD (this freeze)

This corrective report and related handoff files are committed on top of `2b6b6de…`.  
**Authoritative audit target after push = GitHub PR #132 HEAD** (see `FOUNDATION_01_TIP_SHA.txt`).  
A documentation commit is a new exact head; mandatory CI on that HEAD must be verified separately and recorded in the PR description / tip file. Do not treat `2b6b6de` CI as automatic qualification of a later docs SHA until that HEAD’s checks complete.

## 6. Local foundation regression (Cursor environment)

**SHA under test:** `2b6b6de8eccb2acbfaa5ece7ba52cebee8c357c8`

```bash
.venv/bin/pytest -q \
  tests/test_foundation01_auth_optional.py \
  tests/test_foundation01_quota_admission.py \
  tests/test_a_serving_authorization.py \
  tests/test_b_logout_revocation.py \
  tests/test_session_ownership_isolation.py \
  tests/test_p0_transcript_integrity.py \
  tests/test_p0_stream_dlp_closure.py \
  tests/test_conversation_context.py \
  tests/test_temporary_chat_privacy.py \
  tests/test_g006_tenant_isolation.py \
  tests/test_s2_customer_correctness.py \
  -rsx
```

**Result:** `145 passed, 2 skipped, 2 xfailed`

| Kind | Case | Why |
|---|---|---|
| SKIP | `test_p0_transcript_integrity` (2) | `needs real Redis` — environment limitation |
| XFAIL | `test_11a_agent_shell_cannot_read_outside_the_workspace` | G-020 known open — path confinement explicitly undone |
| XFAIL | `test_11b_agent_file_tools_are_not_shared_between_users` | G-020 known open — server-wide workspace, no user identity |

Developer local green ≠ independent qualification.

## 7. Verified backend controls (engineering)

| Control | Status | Evidence |
|---|---|---|
| Invalid / revoked / expired bearer → 401 | VERIFIED | middleware + foundation01_auth + G006 revoked key |
| Ownership non-leaking refusals | VERIFIED | session_ownership + serving_authorization |
| Atomic quota admission + consume/release/replay | VERIFIED | foundation01_quota + reservation_ownership |
| SQLite fencing epochs authoritative | VERIFIED | p0_transcript_integrity / commit (unit) |
| Redis advisory only | VERIFIED (design + unit) | storage decision; live two-worker soak **unverified** |
| Streaming DLP (StreamRedactor) | VERIFIED | p0_stream_dlp_closure |
| Multi-turn + colon-safe Ollama IDs | VERIFIED | conversation_context + ollama_deployment_id |
| Pre-stream HTTP JSON refusals | VERIFIED | S2 + contract |
| Persistence semantics (delivered ≠ saved) | DOCUMENTED | chat best-effort; stream `user_message_id` only on commit |

## 8. Remaining unverified capabilities

| Gap | Classification |
|---|---|
| Live Ollama `llama3.2:1b` | Environment limitation — not available in this agent VM |
| Real two-worker Redis concurrency / takeover / outage | Environment limitation — no Redis in this VM |
| Crash/restart recovery soak | Awaiting Antigravity on qualified host |
| Browser ↔ backend integration | Claude’s scope; Cursor did not modify frontend branch |
| G-020 agent tool path confinement | Known open (xfail); outside FOUNDATION-01 CI recovery scope |
| Independent G13 qualification | Open — Antigravity only |

## 9. Known security / integration risks

- Chat/stream still deliver model text when SQLite commit fails (best-effort `_persist_turn`); clients must reload messages API — no false `saved: true`, but UX can look “answered” without durable history.
- Redis-down policy is fail-soft advisory; product policy for “configured but down” remains for Antigravity review.
- G-020 agent shell/file tools remain intentionally unconstrained (documented xfail).
- Pre-stream JSON vs SSE requires frontend parser branching (Claude handoff).

## 10. Backend engineering acceptance verdict

**`VERIFIED_ENGINEERING`** for the functional tip `2b6b6de…` under mandatory exact-head CI green (push + PR Test Suite 9/9, Deterministic PASS).

**Not** `INDEPENDENTLY_QUALIFIED`.  
**Not** production-ready. Draft PR only — no merge, deploy, paid infra, or training.

## 11. Claude Code handoff requirements

See `BACKEND_FRONTEND_CONTRACT.md` § “Claude copyable handoff”.  
Do not modify Claude’s frontend branch from this Cursor run. Required FE changes: HTTP status / Content-Type gate before SSE parse; transcript reload after `done`; honor null `user_message_id` as unconfirmed persistence.

## 12. Antigravity qualification requirements

See `FOUNDATION_01_ANTIGRAVITY_HANDOFF.md`. Qualify the **GitHub PR HEAD** after evidence freeze (or restart if HEAD advances). Execute live Ollama + real Redis two-worker challenges; do not accept Cursor self-cert as G13.
