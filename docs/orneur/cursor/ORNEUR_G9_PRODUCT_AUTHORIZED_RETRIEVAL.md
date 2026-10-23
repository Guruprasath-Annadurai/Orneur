# Increment 3 — G9 authenticated product retrieval

Engineering evidence. This document does not accept any requirement and does not alter the acceptance ledger.

## Change

Signed-in `/api/docs/upload` admits extracted text into a session-bound `AuthorizedIndex`. Signed-in `/api/chat` and `/api/stream` call `run_authorized_retrieval` before `run_deep_rag`. Refusal is HTTP 403 `retrieval_unauthorized`. Cross-user session ids remain 404 from existing ownership checks.

Anonymous DocStore traffic is unchanged and is not an authorized index.

## API compatibility

- Existing chat/stream JSON fields are preserved.
- Authenticated document chats add optional `authorized_retrieval` (`method`, `hit_count`, `production_neural`, `tool_grant`, `abstained`). Clients may ignore it.
- No `orca/serve/web/*` edits.

## Security impact

- Authenticated retrieval is fail-closed on revoked or unbound trusted sessions.
- Cross-tenant TrustedSession search remains AccessDenied.
- `tool_grant` stays false. `production_neural` stays false on this sparse path.
- Does not replace DocStore ranking after a successful authorization gate.

## Limitations

- TrustedSession tokens are in-process and not serializable; restart requires a fresh bind.
- Anonymous uploads are not G9-qualified.
- This does not certify a neural encoder or accept G9 in the 95-row ledger.
- Linux tests only. Native macOS qualification of PR #86 is independent.
