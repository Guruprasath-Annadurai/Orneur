# P0 consolidated backend security correction

Engineering evidence for the integrated correction of PR #87, PR #88, and PR #89. This document does not accept any requirement, does not authorize a protected merge, and does not alter `docs/orneur/acceptance/acceptance_ledger.json`.

GENESIS, NOVUS, and AETERNUM remain untrained. `production_neural` stays false on the product path. `tool_grant` stays false. Retrieved text does not authorize tool execution.

## Status

**ENGINEERING PASS — INDEPENDENT SECURITY REQUALIFICATION PENDING**

Combined command, 24 October 2026 (Asia/Calcutta): `bash scripts/ci/run_deterministic_tests.sh`.

- Sentinel process: 13 passed.
- Main process: 9018 passed, 7 failed, 456 skipped, 43 deselected, 6 xfailed. Runtime 12 minutes 21 seconds.

Of those 7 failures:

- `test_07d_revoked_api_key_stops_working_and_keys_are_user_scoped` expected the old guest downgrade (HTTP 404). A revoked API key is now HTTP 401. The assertion was updated and the test passes on re-run.
- `test_no_frozen_or_private_path_differs_from_the_branch_point` already fails at PR #86 `5d9c6f7`. The three differing files are pretraining authorization records this correction does not touch.
- `test_isolated_install_can_import_ocl_and_run_cli` and `test_isolated_install_from_sdist_can_import_integrity_and_run_cli` fail because this machine has no `python3-venv` (`ensurepip is not available`).
- `test_cloud_xl_cannot_register_output_under_a_reserved_native_model_name` and `test_cloud_trainer_fails_before_any_ssh_or_network_call` fail only inside the long process, when `orca.train.cloud` is first imported against an already-deleted `isolated_home` directory. Both pass in isolation, including immediately after the new P0 tests.
- `test_golden_final_state_pins_cross_platform_determinism` fails in isolation on this machine (`d42d6dbd…` vs pinned `5bb79b0f…`). This correction does not change that runner.

Focused re-run after the API-key assertion update: the P0 auth and context tests, the revoked-key test, and the two phase-16 tests — 29 passed. Requalification is not this document.

## Protected baselines

These commits are ancestors of the integration branch. They were not rewritten.

| PR | SHA | Role |
| --- | --- | --- |
| #86 | `5d9c6f747169e3f74c7d100994fc64bef376afb4` | Integration base |
| #87 | `753ac8b0b8f08365c4c70117d8e23b8828a2c24e` | Upstream streaming |
| #88 | `1482a58ad5251da94e756fabc0a74a50123e4069` | Dataset `validate()` binding |
| #89 | `258c9424d1b1db3bb91c1e89a84689a5e931a522` | Authorized product retrieval, including the gate this correction closes |

## Root causes

### A — Document context was not the authorized set

`run_authorized_retrieval()` ran as an admission check. The passages actually placed in the kernel, the agent prompt, and citations still came from the session `DocStore` via `run_deep_rag()`, and `_run_cognitive_kernel()` received that store before the gate. Zero authorized hits and `abstained=True` did not stop legacy retrieval. A live session could be read by the kernel on `/api/chat` after ownership was checked but before any passage was authorized.

An authorized index existing for the user was not the same as each returned passage being authorized for that conversation.

### B — Invalid bearer tokens became guests

`get_current_user_optional()` caught `HTTPException` and returned `None`. `HTTPBearer(auto_error=False)` also returns no credentials for a malformed or unsupported `Authorization` scheme. Both cases took the guest path: empty session lists, anonymous document upload, and anonymous conversation load.

### C — Bindings were process-local and the two stores were not one authority

`SessionAuthority.issue()` minted a new random directory id that was not stored against the product conversation. After restart, retrieve and delete could not open the index that still held the text. Upload admitted to the index and then wrote the legacy store with no rollback. Delete removed the legacy copy even when the index delete had not happened. The user-id directory is only a storage prefix. It does not isolate one conversation from another conversation of the same user.

## Correction

Authenticated planning does not receive the legacy store (`allow_legacy_doc_store` is false, and the kernel defers RETRIEVE/SEARCH/VERIFY instead of running Truth Fabric against an empty or unauthorized store). Prompt passages come from `model_context_from_authorized()`:

- the conversation's binding record names one index directory
- each passage must `replay()` in that index
- the document id must be in this conversation's registry
- a contradiction (`abstained=True`) contributes no passage
- zero verified passages produce an ordinary answer with `grounding: none`

They do not produce a legacy-store fallback. A revoked binding is HTTP 403 `retrieval_unauthorized` and does not generate. A missing binding is ordinary ungrounded chat, and `retrieve_authorized()` itself still fails closed.

Anonymous callers keep the legacy pipeline, and only after ownership is checked.

`get_current_user_optional()` reads the raw `Authorization` header. No header means guest. Any present header that is not a single bearer token, or a bearer token the existing `get_current_user()` rejects, is HTTP 401. The exception is not swallowed.

Restart and a second process adopt the index session id stored in:

`ORCA_HOME/authorized_index/<user_id>/bindings/<product_session_id>.json`

The record is written only after that directory has been opened, under an exclusive lock. Revocation sets `revoked: true` on that record before the in-process session is revoked. Recovery never opens a sibling directory and never mints a broader session to make a missing record succeed.

Upload admits to the index, then the legacy store, and registers the document only after both succeed. A legacy-store failure rolls the index admission back and still returns an error. Delete removes the index first. If that fails, the legacy copy is left in place. If the legacy delete fails after the index delete, the response is an error and the text is not put back. Unregistered index text is not eligible for a prompt.

## API compatibility for the Claude frontend

No file under `orca/serve/web/` was edited.

`origin/claude/b04-b09-implementation-2026-10-23` `conversation.html` already treats HTTP 401 as session expiry in `_handleSessionExpired()` ("Your session has expired. Please sign in again."). It keys off status, not the JSON body. That handler now matches this backend:

| Request | Result |
| --- | --- |
| No `Authorization` header | Guest, only where the route already allowed it |
| Valid session bearer | Authenticated user |
| Expired, revoked, forged, reset, or 2FA-pending bearer | HTTP 401 `Invalid or expired token` |
| Malformed or non-bearer `Authorization` | HTTP 401, not a guest |
| Other user's session id | HTTP 404, unchanged |
| Revoked document binding | HTTP 403 `retrieval_unauthorized` |

403 is not session expiry. The frontend must not send the user through sign-in for `retrieval_unauthorized`.

Chat and stream gain optional `authorized_retrieval` fields `contradictions` and `prompt_passage_count` beside the existing `method`, `hit_count`, `production_neural`, `tool_grant`, and `abstained`. Unknown fields are ignored by the current client. Source cards for authorized passages include `doc_id` and `content_sha256`. `source_summary.retrieval.method` is the authorized method (`sparse` or `authorized-enumeration`), not `deep_rag`, and includes `production_neural: false` and `tool_grant: false`.

A comment in `conversation.html` still says `/api/stream` does not emit 401 for an invalid token. That comment is stale. This correction does not edit that file.

## Binding and recovery contract

- One product conversation, one binding file, one index session directory.
- Same-user directory layout is not an ACL. Isolation is the binding record. This code does not scan sibling directories.
- `absent`: no record. Direct retrieve raises. Chat is ungrounded and does not read `DocStore`.
- `revoked`: 403. Restart does not clear it.
- Crash after the index directory is created and before the binding file exists: orphan directory, not served.
- Crash after index admit and before registry commit: not served, because prompt eligibility requires both replay and registry.
- Index and legacy disagreement: the passage is omitted. Authority is not widened to make the stores match.
- TrustedSession tokens remain per process. The shared secret is the directory id in the binding file, not the token.
- A second worker adopts that id. It does not issue a new one.

## Tests

Adversarial coverage lives in `tests/test_p0_auth_boundary.py` and `tests/test_p0_authorized_context.py`.

Before this correction, a session with an authorized document and a legacy-only poison string still placed the poison in model requests, and an expired bearer token on `/api/sessions` returned HTTP 200 with an empty list. After it:

- poison in the legacy store is absent from kernel `doc_store`, model requests, sources, and the streamed body
- zero authorized hits and contradictions do not inject passages and do not fall through
- a passage that fails `replay()` is not prompt material even when search returned it
- two conversations of one user stay separate across restart and a second process
- revocation survives a process-state drop
- a legacy commit failure does not publish the document
- an index delete failure does not remove the legacy copy
- a legacy delete failure after index delete does not leave the text prompt-visible
- missing header, valid login, expired, revoked, forged, reset, 2FA-pending, and malformed schemes follow the table above
- expired upload and expired conversation load do not write or load
- cross-user access stays 404

PR #87 streaming, PR #88 `validate()` binding, and the previous G9 product tests remain in the combined run.

## Remaining limitations

- Lexical conflict detection is not a neural judge. Full `SUPPORTED` is still unreachable. Contradictions that the extractor cannot see are not claimed as clean.
- No qualified encoder is wired. `production_neural` is false. This is not a model-quality claim.
- Same-OS-user write access to the binding file can retarget that user's own conversation. The server does not do this, and it cannot see another user's directory by doing it.
- If index rollback after a failed legacy commit itself fails, the HTTP result is still failure and the unregistered text is not prompt-eligible, but the orphaned index bytes remain on disk until an operator removes them.
- Authenticated document turns defer Truth Fabric retrieval to this gate. Anonymous turns still use Truth Fabric with their own store.
- A question that names a document, upload, file, or summary and misses lexically enumerates up to five passages from that conversation's own index. It does not read the legacy store. A question with no document reference and no lexical hit stays ungrounded.
- Linux only in this run. PR #86's native macOS qualification is unchanged and independent.
- The draft Cloud Agent environment's saved start command still does not run until that environment is saved. That is unrelated to this correction.

## Antigravity requalification

1. Check out this branch. Do not merge it.
2. Confirm ancestors: `git merge-base --is-ancestor 5d9c6f747169e3f74c7d100994fc64bef376afb4 HEAD` and the same for `753ac8b0b8f08365c4c70117d8e23b8828a2c24e`, `1482a58ad5251da94e756fabc0a74a50123e4069`, and `258c9424d1b1db3bb91c1e89a84689a5e931a522`.
3. Confirm `docs/orneur/acceptance/acceptance_ledger.json` is unchanged from those baselines.
4. Confirm no path under `orca/serve/web/` differs from the integration base.
5. Re-run `tests/test_p0_auth_boundary.py`, `tests/test_p0_authorized_context.py`, `tests/test_serve_authorized_product_index.py`, `tests/test_s2_customer_correctness.py`, `tests/test_b_logout_revocation.py`, and `tests/test_cognitive_kernel_defer_stream.py`.
6. Re-run `bash scripts/ci/run_deterministic_tests.sh` if a full combined result is required. The sentinel file must stay in its own process, as that script already does.
7. Adversarial checks that must stay true: legacy-only text never appears in a signed-in model request; `abstained=True` injects nothing; expired and malformed `Authorization` headers are 401 rather than guest; a revoked binding is 403 after a process restart; two conversations of one user do not share passages; `tool_grant` and `production_neural` are false.
8. Do not treat a green run as acceptance of GENESIS, NOVUS, or AETERNUM, and do not treat the same-user directory prefix as an isolation boundary.
