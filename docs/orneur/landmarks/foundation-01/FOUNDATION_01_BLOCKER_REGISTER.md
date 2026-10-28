# FOUNDATION_01_BLOCKER_REGISTER

Refreshed at tip `6d53c1ed03ca2d827083a7e7a91ac38ed9afb88c` on `cursor/foundation-landmark-01-backend-closure-1cdf`.

| ID | Severity | File / function | Root cause | Already fixed on | Recommended action | Acceptance test |
|---|---|---|---|---|---|---|
| B01 | P0 | `orca/auth/middleware.py` `get_current_user_optional` | Invalid bearer became anonymous | This branch `7c8f7b0` | Done — present credentials must validate | `tests/test_foundation01_auth_optional.py` |
| B02 | P0 | Competing transcript engines (#130 vs #131) | Two SoT designs | Architecture decision: #130 fencing | Done — single SQLite fencing engine | `AUTHORITATIVE_STORAGE_DECISION.md` + `tests/test_p0_transcript_integrity.py` |
| B03 | P0 | `/api/chat` `/api/stream` quota | `check_quota` → generate → `increment_usage` race | This branch `admit_serving` | Done for chat/stream/ultra/vision | `tests/test_foundation01_quota_admission.py` |
| B04 | P0 | Route security divergence | Separate admission logic per route | `orca/serve/admission.py` | Done — shared boundary; adapters remain | `tests/test_a_serving_authorization.py` |
| B05 | P1 | PR #126 multi-turn context not in #130 ancestry | Stack divergence | Merged #126 onto #130 base | Done | `tests/test_conversation_context.py`, `tests/test_ollama_deployment_id.py` |
| B06 | P1 | Temporary-chat lock unlink races | Lock inode unlinked under concurrency | `_unlink_lock` after flock release | Done on this branch | `tests/test_temporary_chat_privacy.py` (extend with two-process) |
| B07 | P1 | `/api/cognitive/execute` still check-then-increment | Experimental route not on reservation path | Closed on follow-up (admit_serving) | Done | `tests/test_a_serving_authorization.py` AST + admit path |
| B08 | P1 | Real multi-worker Redis outage soak | Evidence mostly unit/fixture | Partially covered by p0 suites | Run two-process harness with real Redis | Document in DISTRIBUTED_CONCURRENCY_REPORT |
| B09 | P1 | Live Ollama `llama3.2:1b` E2E on this SHA | Environment may lack Ollama | Gap if unavailable | Report evidence gap; do not invent pass | REAL_OLLAMA_AND_SERVING_REPORT |
| B10 | P2 | PR #129 frontend/conversation.html conflicts | #129 CONFLICTING vs #126 | Backend privacy ported; no UI redesign | Claude owns frontend integration | Contract doc |
| B11 | P0 | Independent qualification | Engineering self-test ≠ audit | Open | Hand to Antigravity at frozen SHA | G13 |

## Closed by consolidation (do not re-implement)

- PR #125/#127 DLP stream redaction, reservation ownership, catalog entitlement — ancestors of this tip.
- PR #130 SQLite fencing epochs — selected SoT (confirmed vs #131 by storage compare).
- PR #126 colon-safe Ollama deployment IDs and conversation context — merged.
- Explorer BB-AUTH-01 / BB-ADM-01 / BB-QUOTA-01 / BB-OWN-01 / BB-PRIV-01 / BB-DLP product SSE — closed on this tip (invalid bearer 401, admit_serving, ownership-before-kernel, temp-chat, StreamRedactor).

## Still open (from storage/auth explorers)

- Redis configured-but-down fail-soft vs SQLite-only proceed (product policy).
- Live Ollama + two-worker Redis soak (environment gap).
- G13 Antigravity independent qualification.
