# B16 — Context & Attachments: Real Implementation (Not Disabled-State)

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Source:** `APPROVED_SOURCE_ARCHIVES/ORNEUR_B16_FINAL_LOCK_AND_HANDOFF.zip` (SHA-256 `a38850996edf55496565ef9b783fc79263e05077855e42ad88e4feace4040f96`) — verified against the archive's own flat `SHA256_PACKAGE_MANIFEST.json`: 30/30 files passing, before any code was written.

## Why this differs from B13/B11's pattern

Going in, B16 was expected to follow B13's and B11's precedent — grep the backend, find nothing, ship an honest disabled state. That is not what happened. Grepping `orca/serve/api.py` for `attachment\|UploadFile\|multipart\|def.*upload` found a real, working document pipeline:

- `POST /api/docs/upload` — extracts text, redacts PII, chunks, and embeds a real uploaded file
- `GET /api/docs/list?session_id=` — lists persisted documents for a session
- `DELETE /api/docs/{doc_id}?session_id=` — deletes a document server-side

`orca/docs/extractor.py` confirmed the real constraints: a specific 21-extension `SUPPORTED_EXTENSIONS` set and `MAX_FILE_SIZE = 50MB`. This pipeline already existed and was *already silently feeding B15's citation work* this same session (`kind: "uploaded_document"` citations) — it simply had zero frontend UI before this phase. So B16 is a real, substantial implementation, not a disabled affordance.

One more real backend fact mattered for the design: `_get_session(session_id=None, ...)` always means "create a new session." Uploading a document to a brand-new conversation (no `sessionId` yet) is therefore a legitimate, server-confirmed way to start one — the same mechanism a first real chat message uses via the SSE `session` event.

## What was implemented

- **`#attach-btn`** (paperclip icon) in the composer toolbar, opening a hidden real `<input type="file">` (`#attach-file-input`) with the backend's real `accept` list as a UX hint only (the server is still the authority on what's actually accepted).
- **`#attach-chips`**: a per-conversation row of chips above the composer, one per attached document.
- **`loadAttachmentsForSession()`**: re-fetches `GET /api/docs/list` fresh every time — never cached across conversations, the same discipline already applied to B14's drafts and B15's citations. A null `sessionId` (new conversation) clears the list rather than showing a stale one.
- **`uploadAttachment(file)`**: immediately renders an "uploading" chip, then `POST`s real `multipart/form-data` to `/api/docs/upload` (deliberately NOT using `_authHeaders()`, which sets `Content-Type: application/json` and would break the multipart boundary). Captures the account token and conversation id before the request and re-checks both after — an account switch or conversation switch mid-upload discards the response rather than attaching it to the wrong place. A `401` routes through the real `_handleSessionExpired()`. A non-ok response shows the server's own real error text verbatim (never a fabricated one). A successful upload to a brand-new conversation adopts the real `session_id` the server returns.
- **`removeAttachment(chip, doc)`**: a chip that never finished uploading (no `doc_id`) is removed locally only — nothing exists server-side yet. A finished upload calls the real `DELETE` endpoint; a failed delete leaves the chip in place rather than silently claiming removal.

## A real bug found and fixed via live verification

Testing the honest failure path with an unsupported file (`test.exe`) surfaced the real, full server error message: *"Unsupported file type. Supported: .c, .cpp, .csv, .docx, .go, .ini, .java, .js, .json, .log, .md, .pdf, .py, .rb, .rs, .rst, .sh, .toml, .ts, .txt, .yaml, .yml"*. A Meridian-light-theme screenshot showed this text overflowing the chip's right edge instead of wrapping — `.chip-state` had `flex-shrink:0` and no `white-space` handling, so a single long line forced horizontal overflow past the composer. Fixed by removing `flex-shrink:0` from `.chip-state`, adding `white-space:normal;max-width:260px;line-height:1.35`, and giving `.attach-chip` itself `align-items:flex-start` so a wrapped multi-line state label doesn't misalign against the single-line filename. Re-verified live in both themes: the full message now wraps cleanly within the chip.

## Verified live, in a real browser, both themes

- A real `.txt` upload succeeded end-to-end, returning a genuine `doc_id` — independently confirmed via `GET /api/docs/list` showing the real persisted record.
- Switched to a new conversation and confirmed the chip list correctly cleared; reopened the original conversation and confirmed the same chip correctly reappeared — per-conversation isolation.
- Clicked the remove (×) button on a real chip and confirmed both the DOM chip and the server-side record were genuinely deleted (`GET /api/docs/list` afterward returned `"docs": []"`).
- Tested the failure path with a real unsupported file (`.exe`) and confirmed the chip showed the `.failed` state with the real server error message, in both Obsidian dark and Meridian light themes, after the CSS fix.

## What was honestly omitted

- Malware/virus scanning — no such capability exists in the backend.
- Async scan states ("scanning…") — there is no scan step to represent.
- Context-capacity / remaining-token display — the backend does not expose per-session token budget or remaining capacity for attached documents.

None of these were fabricated or stubbed with fake progress; they are simply not built, because nothing in the backend supports them.

## Tests

```
node --test tests/frontend/test_b16_context_attachments.mjs   # 9 tests, new
node --test tests/frontend/*.mjs                                  # 142/142 passing (was 133)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

Structural guards: the upload request never sets a manual `Content-Type` (would break the multipart boundary); account/conversation identity is re-checked after every await; a `401` routes through the real session-expiry handler; failure text always comes from the real server response; the attachment list is always re-fetched fresh, never cached across conversations; a failed delete leaves the chip in place; the `.chip-state` CSS bug class can't silently regress. Two behavioral tests exercise the real `renderAttachChip()` against a minimal fake DOM (ready state, failed state).

## Honest verdict

**`ENGINEERING COMPLETE`** for B16 — unlike B13 and B11, this screen has a real, working backend pipeline, and the implementation here is a full, live-verified integration against it: upload, list, per-conversation isolation, delete, and honest failure handling, including a real CSS bug caught and fixed through live verification rather than unit tests alone. The only gaps (malware scanning, async scan states, capacity display) are genuine backend absences, not scope cut for convenience.
