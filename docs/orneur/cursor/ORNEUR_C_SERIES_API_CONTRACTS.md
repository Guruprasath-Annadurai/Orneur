# C-series API contracts

Engineering candidate. Independent requalification pending. This document does not add routes, does not merge a protected branch, and does not declare security qualification.

No file under `orca/serve/web/` is edited. Screens for Library, Connectors, Schedules, and Notifications stay disabled. Designer Chat visual specifications are still required before those screens are built. This contract does not describe layout, color, or copy.

C01–C11 stay blocked on a missing authentic design source. Projects, onboarding completion, library, plugins, connectors, scheduled tasks, notifications, and skills are the areas named by that block. This repository does not contain an approved matrix that assigns those names to C01–C11, so this contract does not invent that numbering.

C12–C14 stay blocked on backend or authority. No enterprise tenant, billing extension, or third-party connector is added to fill them. Existing `POST /api/billing/checkout` and `POST /webhook/stripe` are older routes. This contract does not extend them and does not call them qualified.

## Approved workspace

There is no `/api/workspaces` resource. A folder is an owner label. A run is a correlation id for generations the same account already owns. Neither one is a workspace tab, and neither one grants access to another account's conversation.

The approved workspace is the signed-in account's own conversation.

| Call | Contract |
|---|---|
| `GET /api/sessions` | The caller's sessions. Each row has `id`, `title`, `updated_at`, and `pinned`. An active temporary chat is absent. |
| `GET /api/session/{id}/messages` | Owner only. Another account, including a share grantee, receives HTTP 404. |
| `POST /api/session/{id}/messages/{message_id}/edits` and `POST .../regenerate` | Immutable versions. The JSONL line is not rewritten. |
| `GET /api/generations/{id}` and `POST /api/generations/{id}/cancel` | Stored state is `running`, `completed`, `cancelled`, or `failed`. Cancel returns `running` until the worker stores `cancelled`. A stale heartbeat is reported as `interrupted_unknown` and is not written back. |
| `POST /api/sessions/temporary` and `POST /api/session/{id}/temporary/close` | Hidden from list, search, export, and long-term memory. Close and expiry delete the transcript before the record says `closed` or `expired`. |
| `POST /api/runs` and `GET /api/runs/{id}` | The owner can attach streams with `X-Run-Id`. Another account receives HTTP 404. |
| `POST /api/session/{id}/pin`, `DELETE /api/session/{id}/pin`, `GET /api/folders`, `POST /api/folders` | Owner metadata. A pin is not an ACL. |
| `POST /api/session/{id}/shares`, `GET /api/shares/{id}/messages`, `POST /api/shares/{id}/revoke` | One grantee, a TTL, and revocation. The grant JSON and the shared transcript omit the session id. |

`POST /api/docs/upload` and `GET /api/docs/list` remain conversation document routes. They are not a Library. `GET /docs` remains the product documentation page. It is not a Library either.

`orca/connectors` is an internal module. Its provider in this tree is the fake provider. It has no product HTTP route and is not an approved external integration.

## Proposed Library

Not mounted. `GET /api/library` and `POST /api/library/items` return HTTP 404.

A later library, after an authentic design is approved, would be a list of items owned by the signed-in account and distinct from a conversation upload. A stored item would carry `item_id`, `owner_id`, `title`, `content_sha256`, and `created_at`. It would not store a remote URL, and the server would not fetch one. Another account would receive HTTP 404. Until that design exists, no item id is allocated and no body field is accepted.

## Proposed Connectors

Not mounted. `GET /api/connectors` and `POST /api/connectors` return HTTP 404.

A later connector record would be `{connector_id, owner_id, state}` with `state` of `unavailable` only. This contract does not name a third-party kind, an OAuth redirect, a credential, or a sync call. The internal connector dataclasses are not that record. No credential is accepted on an HTTP route by this contract.

## Proposed Schedules

Not mounted. `GET /api/schedules` and `POST /api/schedules` return HTTP 404.

A later schedule would name an account-owned session and a single `run_at` instant, with `state` of `scheduled` or `cancelled`. It would not execute a model call, and it would not be a cron. Execution stays blocked until an explicit authority grant exists. This contract does not define that grant.

## Proposed Notifications

Not mounted. `GET /api/notifications` and `POST /api/notifications` return HTTP 404.

A later notification would be an in-app row for the signed-in account: `notification_id`, `user_id`, `created_at`, and `read_at`. It would not send email, push, or a webhook. No external delivery provider is assumed.

## What a client must do now

Call only the approved workspace routes above. Treat Library, Connectors, Schedules, Notifications, projects, plugins, and skills as absent. A 404 on those paths is the contract, not a temporary outage.
