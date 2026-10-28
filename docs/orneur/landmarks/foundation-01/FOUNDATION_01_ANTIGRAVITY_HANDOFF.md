# FOUNDATION_01_ANTIGRAVITY_HANDOFF

**For:** Antigravity independent qualification  
**From:** Cursor — FOUNDATION LANDMARK-01 backend closure  
**Not a qualification verdict.** Engineering package only.

## Exact candidate

| Field | Value |
|---|---|
| Branch | `cursor/foundation-landmark-01-backend-closure-1cdf` |
| Exact SHA | `6d53c1ed03ca2d827083a7e7a91ac38ed9afb88c` |
| Prior engineering SHA | `6d53c1ed03ca2d827083a7e7a91ac38ed9afb88c` (code freeze before docs commit; qualification restarts for tip) |
| Base lineage | PR #130 fencing (`497073d`) + merged PR #126 context + Landmark-01 admission/auth fixes |
| Draft PR | (opened by Cursor; do not merge without founder authorization) |

If this tip advances, **qualification must restart** for the new head. Record the new SHA explicitly.

## Provenance (frozen parents — do not rewrite)

| Ref | SHA | Role |
|---|---|---|
| PR #125 | `9298b157fe22c95c897d7afbcc9f2e21a99d256e` | Inference P0 baseline |
| PR #126 | `7ea44aed3e9dabb6d75e4d99fb0dba82a87c8edc` | Multi-turn + Ollama IDs (merged) |
| PR #127 | `22225086873cba5274d3ad44aab9e7ef5a913230` | DLP/quota/fencing closure |
| PR #130 | `497073d2dfb45f82554fb260db3fe4d87b0b5019` | Selected SQLite fencing SoT |
| PR #131 | `040d694702d9d70bb0dbeb70d643bc19877dfcf4` | Rejected as competing SoT (see storage decision) |

## Audit entrypoints

1. `docs/orneur/landmarks/foundation-01/AUTHORITATIVE_STORAGE_DECISION.md`
2. `docs/orneur/landmarks/foundation-01/BACKEND_SECURITY_QUALIFICATION_MATRIX.md`
3. `docs/orneur/landmarks/foundation-01/BACKEND_FRONTEND_CONTRACT.md`
4. `docs/orneur/landmarks/foundation-01/FOUNDATION_01_BLOCKER_REGISTER.md`
5. `docs/orneur/status/P0_TRANSCRIPT_INTEGRITY_HANDOFF.md` (PR #130)
6. `docs/orneur/status/P0_SECURITY_CLOSURE_ANTIGRAVITY_HANDOFF.md` (PR #127)

## Reproducible commands

```bash
git fetch origin cursor/foundation-landmark-01-backend-closure-1cdf
git checkout 6d53c1ed03ca2d827083a7e7a91ac38ed9afb88c
uv sync --extra dev --extra redis --extra postgres
.venv/bin/pytest -q \
  tests/test_foundation01_auth_optional.py \
  tests/test_foundation01_quota_admission.py \
  tests/test_p0_transcript_integrity.py \
  tests/test_p0_transcript_commit.py \
  tests/test_p0_stream_dlp_closure.py \
  tests/test_p0_reservation_ownership.py \
  tests/test_a_serving_authorization.py \
  tests/test_conversation_context.py \
  tests/test_ollama_deployment_id.py \
  tests/test_b_logout_revocation.py
```

Live Ollama / two-worker Redis / browser journeys: see REAL_OLLAMA and DISTRIBUTED reports for evidence gaps.

## Attack focus (suggested)

1. Invalid bearer on `/api/chat` and `/api/stream` (must 401, never anonymous inference).
2. Cross-user transcript / edit / export.
3. 49/50 concurrent admits; request_id theft; consumed replay.
4. Stale worker commit after epoch bump.
5. Split-chunk PEM DLP on `/api/stream` and inference stream.
6. Temporary-chat resurrection after close.
7. Spoofed native model identities.
