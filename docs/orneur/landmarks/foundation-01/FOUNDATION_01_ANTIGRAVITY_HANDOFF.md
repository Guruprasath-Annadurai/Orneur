# FOUNDATION_01_ANTIGRAVITY_HANDOFF

**For:** Antigravity independent qualification  
**From:** Cursor — FOUNDATION LANDMARK-01 corrective closeout  
**Not a qualification verdict.** Engineering package only. Cursor does **not** self-assign `INDEPENDENTLY_QUALIFIED`.

## Exact candidate

| Field | Value |
|---|---|
| Branch | `cursor/foundation-landmark-01-backend-closure-1cdf` |
| Draft PR | https://github.com/Guruprasath-Annadurai/Orneur/pull/132 |
| Functional CI tip (product + CI recovery) | `2b6b6de8eccb2acbfaa5ece7ba52cebee8c357c8` |
| Authoritative audit SHA | **GitHub PR #132 HEAD** after evidence-freeze docs (must match tip file + PR metadata) |
| Architecture | SQLite fencing SoT (#130); Redis advisory; JSONL derived |

If HEAD advances past the SHA you audited, **qualification restarts**.

## Engineering CI already recorded (functional tip only)

| Run | URL | Result |
|---|---|---|
| Push Test Suite `40733516543` | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40733516543 | 9/9 SUCCESS @ `2b6b6de` |
| PR Test Suite `40733526194` | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40733526194 | 9/9 SUCCESS @ `2b6b6de` |
| Eval Static `40733526200` | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40733526200 | SUCCESS |
| Deterministic | within PR suite | 8941 passed / 372 skipped / 75 deselected / 7 xfailed |

Re-verify mandatory CI on the **document-bearing HEAD** before starting attack work.

## Provenance (frozen parents)

| Ref | SHA | Role |
|---|---|---|
| PR #125 | `9298b157fe22c95c897d7afbcc9f2e21a99d256e` | Inference P0 baseline |
| PR #126 | `7ea44aed3e9dabb6d75e4d99fb0dba82a87c8edc` | Multi-turn + Ollama IDs (merged) |
| PR #127 | `22225086873cba5274d3ad44aab9e7ef5a913230` | DLP/quota/fencing closure |
| PR #130 | `497073d2dfb45f82554fb260db3fe4d87b0b5019` | Selected SQLite fencing SoT |
| PR #131 | `040d694702d9d70bb0dbeb70d643bc19877dfcf4` | Rejected competing SoT |

## Dependencies

```bash
git fetch origin cursor/foundation-landmark-01-backend-closure-1cdf
git checkout <PR_HEAD_SHA>   # exact GitHub head
uv sync --extra dev --extra redis --extra postgres
# Live challenges also need: redis-server, ollama + llama3.2:1b
```

## Required regression commands

```bash
.venv/bin/pytest -q \
  tests/test_foundation01_auth_optional.py \
  tests/test_foundation01_quota_admission.py \
  tests/test_a_serving_authorization.py \
  tests/test_b_logout_revocation.py \
  tests/test_session_ownership_isolation.py \
  tests/test_p0_transcript_integrity.py \
  tests/test_p0_transcript_commit.py \
  tests/test_p0_stream_dlp_closure.py \
  tests/test_p0_reservation_ownership.py \
  tests/test_conversation_context.py \
  tests/test_ollama_deployment_id.py \
  tests/test_temporary_chat_privacy.py \
  tests/test_g006_tenant_isolation.py \
  tests/test_s2_customer_correctness.py \
  -rsx
```

Full deterministic (CI equivalent):

```bash
bash scripts/ci/run_deterministic_tests.sh
```

## Positive / negative security assertions

1. Invalid / expired / revoked bearer on `/api/chat` and `/api/stream` → **401**, never anonymous.
2. Cross-user transcript / edit / export → non-leaking **404/403**; zero model dispatch.
3. Pre-stream gates → HTTP JSON **401/402/400/404/429** (not SSE 200).
4. 49/50 concurrent admits cannot exceed quota; consumed `request_id` → no second provider call.
5. Stale fencing epoch / fence → commit refused; superseded worker cannot publish.
6. StreamRedactor: split-chunk secrets never leave the wire unredacted.
7. Temporary chat close → content not resurrected by late writers.
8. Spoofed GENESIS/NOVUS/AETERNUM identities refused; colon tags preserved in deployment ids.
9. Reload `GET /api/session/{id}/messages` after stream `done`; null `user_message_id` ⇒ unconfirmed SQLite commit.

## Live challenges (must not invent passes)

```bash
# Real Redis two-worker / takeover / outage
redis-server   # or docker redis
# run multiprocess harnesses / p0 workers with ORNEUR Redis URL set

# Real Ollama
ollama pull llama3.2:1b
pytest -q tests/journey/test_journey_api_live.py -m live_ollama_smoke
# Capture provider request payloads (redacted) proving model + tags
```

## Known gaps / blockers for qualification

| Item | Status |
|---|---|
| B08 Real Redis two-worker | Unverified in Cursor env |
| B09 Live Ollama | Unverified in Cursor env |
| B10 Browser FE | Claude integration |
| B11 G13 | **You** |
| B12 Persist best-effort UX | Documented risk |
| G-020 agent tools | Known xfail |

## Audit entrypoints

1. `FOUNDATION_01_CORRECTIVE_CLOSURE_REPORT.md`
2. `FOUNDATION_01_FINAL_ENGINEERING_REPORT.md`
3. `FOUNDATION_01_TIP_SHA.txt`
4. `AUTHORITATIVE_STORAGE_DECISION.md`
5. `BACKEND_SECURITY_QUALIFICATION_MATRIX.md`
6. `BACKEND_FRONTEND_CONTRACT.md`
7. `FOUNDATION_01_BLOCKER_REGISTER.md`
8. `DISTRIBUTED_CONCURRENCY_REPORT.md`
9. `REAL_OLLAMA_AND_SERVING_REPORT.md`
