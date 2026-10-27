# B14 correlated runs handoff for the Claude frontend

No file under `orca/serve/web/` was edited. A client-side tab is not a server run.

## Routes

| Call | Result |
|---|---|
| `POST /api/runs` as a signed-in user | `{run_id, created_at, members: [], count: 0}` |
| Same call with no token | HTTP 401 |
| `POST /api/stream` with header `X-Run-Id: <run_id>` | The `generation` event includes that `run_id`. The generation is a member of the run. |
| `GET /api/runs/{run_id}` as the owner | `members` of `{generation_id, session_id, attached_at}` |
| Same call as another account, or a stream that names that run | HTTP 404 `run_not_found`. The member list does not grow. |
| Stream with no `X-Run-Id` | `run_id` is null. Existing clients keep working. |

The caller must own the conversation. The run id is not a share and not a workspace tab. Two conversations of one account can be members of one run. A run holds at most 100 generations; the next attach is HTTP 409 `run_full` and that generation is stored `failed`.

Cancel, retry, and temporary-chat rules are unchanged. The frontier passthrough path still has no generation id and ignores `X-Run-Id`.
