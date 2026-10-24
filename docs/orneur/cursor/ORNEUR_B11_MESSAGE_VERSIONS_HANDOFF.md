# B11 message versions handoff for the Claude frontend

No file under `orca/serve/web/` was edited. The Save control stays disabled until it calls the routes below. Do not label an unsent edit as saved.

## Routes

All three require a signed-in owner. Another account, or a caller with no token, receives HTTP 404. An expired bearer receives HTTP 401 from the existing auth dependency.

| Call | Result |
|---|---|
| `GET /api/session/{session_id}/messages/{message_id}/versions` | `active_version_id`, `active_content`, `version_count`, and `versions` oldest first. Each version has `version_id`, `parent_version_id`, `content`, `kind` (`original`, `edit`, or `regeneration`), `generation_id`, and `committed`. |
| `POST /api/session/{session_id}/messages/{message_id}/edits` with `{"content":"..."}` | Appends an `edit` version and makes it active. The original stays in `versions`. |
| Same edit with the same `Idempotency-Key` and the same content | HTTP 200, `created: false`. No second version. |
| Same key with different content | HTTP 422 `idempotency_mismatch`. |
| Empty content, a key shorter than 8 characters, or content over 200,000 characters | HTTP 400 `message_version_rejected`. |
| `POST /api/session/{session_id}/messages/{message_id}/regenerate` | One model completion. On success the new assistant version is active, `generation_state` is `completed`, and `generation_id` is set. |
| Same regenerate key after success | HTTP 200, `created: false`. No second model call. |
| A second regenerate while the first still holds its live lock | HTTP 409 `regeneration_in_progress`. |
| The model raises, or returns blank text | The new version is not activated. `GET /api/generations/{id}` is `failed` and `retry_eligible`. The transcript still shows the previous text. |

`GET /api/session/{session_id}/messages`, search, and export show the active text and add `message_id`, `version_id`, `version_count`, and `edited`. The JSONL line on disk is still the original text.

## What an edit does not do

- It does not rewrite long-term vector memory. The earlier text can remain there until the conversation is deleted.
- It does not delete prior versions. History is the versions route.
- Regenerate does not re-run authorized document retrieval. The new answer is not a refreshed citation.
- Regenerate is one blocking completion. `POST /api/generations/{id}/cancel` does not stop it.
- A same-OS-user can still rewrite their own version file. The server does not do that.

Message ids are assigned when a signed-in turn is persisted. A line with no `message_id` cannot be edited.
