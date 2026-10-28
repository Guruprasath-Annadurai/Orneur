# PR #126 Privacy Remediation — Antigravity Handoff

**Corrective branch:** `cursor/pr126-privacy-remediation-e8f0`  
**Starting SHA (PR #126 tip including ownership gate):** `a686e5fa6a456e68c54cb38e648cdfaab40801b6`  
**Remediation commit:** `d1e98fd86709d227e2242103e28bb2df73b56515`  
**Finishing SHA (exact head):** `a106f37d56fc769c28081a554f61ff58fe6cf673`  
(User-cited frozen parent `ada5e135…` is preserved; `a686e5f` already closed the kernel-before-ownership gap and is the verified candidate this branch extends.)

Does **not** rewrite PR #125 / #126 audited SHAs. No merge to production.

## Fixes

### B1 — Authorization before history retrieval
- Ownership gate before kernel on `/api/chat` and `/api/stream` (from `a686e5f`)
- `assemble_messages` refuses foreign transcripts before load
- Frontier path now passes `user_id` into `assemble_messages`
- Inference history assembly passes authenticated `user_id`
- Journey D1 asserts Alice’s secret never appears in recorded Ollama request bodies (not just HTTP 403/404)

### B2 — Temporary-chat lifecycle
- `is_hidden` covers any temp record (active/expired/closed/failed)
- LTM / continuum omitted for any temp record (`_omit_long_term`)
- Late stream publish refused after temp finish (`_stream_may_publish`)
- Message versions deleted on cascade; lock files unlinked after confirmed deletion

### B3 — Canonical frontend (Claude `f7c004f`)
- Server-side logout with live-token revoke, retry, honest outcome, cross-tab `storage`
- Per-turn `bindServerMessageId` (no last-DOM heuristic)
- Sidebar refresh on persistence-confirming `done`, not `session`; temp chats excluded
- Node tests: logout revocation, same-turn bind, view-ownership epochs

## Tests
- `tests/test_session_ownership_isolation.py`
- `tests/test_conversation_context.py`
- `tests/test_temporary_chat_privacy.py`
- `tests/journey/test_journey_api_live.py::test_D1_*` (opt-in live + tap)
- `tests/frontend/test_logout_revocation.mjs`, `test_b11_inline_edit.mjs`, `test_view_ownership_epoch.mjs`

## Remaining limitations
- Journey live + Ollama tap proofs require the opt-in harness (`-m journey_live`)
- Temporary tombstone JSON is retained intentionally as a terminal record
- WAVE A DLP/quota/transcript fixes are on a separate branch; do not assume they are present here

## Qualification request
Independently qualify this tip for B1–B3. Preserve frozen SHAs. Do not merge.
