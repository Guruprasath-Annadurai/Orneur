# Closure and edit recovery contract

This is the backend contract for the temporary-chat recovery route and for an edit whose durable version commits while the live cache does not. It does not change the conversation UI.

## `POST /api/session/{session_id}/temporary/closure/retry`

Authentication is required. The caller must be the `user_id` stored on the temporary-chat record. A missing record and another account's record both answer `404` `temporary_not_found`. The route does not choose a new final state. It uses the stored `intended_state`, which must already be `closed` or `expired`.

| Result | HTTP | Body |
| --- | --- | --- |
| Stored state is already `closed` or `expired` | 200 | `retried: false`, `deleted: true`, `remaining: []` |
| Retry clears every checked store | 200 | `state` is the stored intended state, `retried: true`, `deleted: true`, `remaining: []` |
| Intended state was not stored | 409 | `state: failed`, `retried: false`, `deleted: false` |
| A checked store still has data or cannot be read | 409 | `state: failed`, `deleted: false`, `remaining: [{store, detail}, ...]` |
| Caller is anonymous | 401 | `auth_required` |
| Caller does not own the record | 404 | `temporary_not_found` |

`remaining` is the list of stores that were still observable after the cleanup attempt. The check includes the transcript, message-version files, the document registry, a non-empty keyword fallback, episodic memory, generation records for this owner, the live session, the session title, and an authorized retrieval binding. A binding that still exists blocks `closed` and `expired`. Revocation does not prove the index bytes are gone, and this route does not delete those bytes.

Calling the route again after success does not create a second deletion and does not change the stored terminal state. Calling it again after a failed cleanup retries the same intended state.

`POST /api/session/{session_id}/temporary/close` uses the same predicate. It returns 200 only when the resulting state is `closed` or `expired` and `remaining` is empty. Otherwise it returns 409 with `remaining` when data is still present, or 500 when the closure failed without that list.

## `POST /api/session/{session_id}/messages/{message_id}/edits`

The durable version is the authoritative text. The in-memory history and Redis copy are a cache.

A failure before `message_versions.edit` commits still uses the existing 400, 404, 409, and 422 codes. No new version is written.

If the version commits and the cache sync then raises, the response is HTTP 500:

```json
{
  "code": "edit_saved_cache_uncertain",
  "created": true,
  "cache_sync": "failed",
  "authoritative_content": "<committed active text>",
  "active_content": "<same committed text>"
}
```

The same `Idempotency-Key` and the same content are the replay. The replay does not append another version. It returns HTTP 200 with `created: false`, `reconciled: true`, and `authoritative_content` set to the committed text. When the previous version's text is still the live cache, that replay replaces it with the committed text. A different message of the same role is not rewritten.

The client already treats HTTP 500 from this route as ambiguous and retries the same key once. This body tells that retry which text was saved. It is not a new success screen.
