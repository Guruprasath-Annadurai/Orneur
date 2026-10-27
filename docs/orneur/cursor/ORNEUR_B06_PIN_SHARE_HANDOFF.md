# B06 / B09 pin and share handoff for the Claude frontend

No file under `orca/serve/web/` was edited. Pin and share controls stay disabled until they call these routes. A session id is not a share.

## Pin and folders

| Call | Result |
|---|---|
| `POST /api/session/{id}/pin` as the owner | `{"session_id", "pinned": true}`. `GET /api/sessions` includes `"pinned": true` on that row. |
| `DELETE /api/session/{id}/pin` | `"pinned": false`. The conversation is not deleted. |
| Another account | HTTP 404. A pin does not change who can read the session. |
| `POST /api/folders` `{"name":"Work"}` | `{folder_id, name, session_ids: []}`. Names are 1 to 80 characters and cannot contain control characters. |
| `POST /api/folders/{folder_id}/sessions` `{"session_id"}` | The session id is appended. The caller must own it. |
| `GET /api/folders` | Only the caller's folders. |

## Shares

| Call | Result |
|---|---|
| `POST /api/session/{id}/shares` `{"grantee_id", "ttl_seconds"}` | An active grant. TTL is 60 seconds to 30 days. The grantee must be an existing account and not the owner. The response does not include the session id. An active temporary chat is HTTP 400 `temporary_not_shareable`. |
| `GET /api/shares/incoming` | Active grants for the caller. Rows do not include the session id. |
| `GET /api/shares/{share_id}/messages` as the grantee or the owner | The transcript, while the grant is active. The body does not include `session_id`. |
| `GET /api/session/{id}/messages` as the grantee | HTTP 404. The session route does not become shared. |
| Another account that is not the grantee | HTTP 404 on the share. |
| `POST /api/shares/{share_id}/revoke` as the owner | `state: "revoked"`. Later reads are HTTP 409 `share_not_active`. |
| The grantee calling revoke | HTTP 404. |
| After `expires_at` | HTTP 409 `share_not_active`. The transcript is not returned. |

A share does not allow edit, regenerate, delete, or pin. It is not a link that anyone with the session id can open.

Deleting the conversation revokes its grants before the transcript file is removed. A later read is HTTP 409 `share_not_active`. A read that already resolved the grant can still return the transcript it opened. Turning an empty session into a temporary chat revokes existing grants before the temporary record is stored as `active`. Deleting the account removes that account's pin file and revokes grants it owns or holds. Pins and folders are not access control.
