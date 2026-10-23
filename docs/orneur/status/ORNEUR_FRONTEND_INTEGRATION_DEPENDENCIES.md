# ORNEUR Frontend Integration Dependencies and Truthful-State Register

**Branch:** `claude/ui-implementation-programme-2026-10-23`
**Date:** 2026-10-23

Per Assignment G's required distinctions, this register states what the frontend **actually has real server state for today**, and what it does not.

| Required distinction | Real backend support exists? | Frontend honors it? |
|---|---|---|
| Model available vs. unavailable | Yes — `/api/models`' `publicly_served` field | Yes — gates send ability, `renderModelOptions()` |
| Response streaming vs. completed | Yes — SSE `chunk`/`done`/`error` events | Yes — explicit `terminalState` tracking (A-P1-01/P1-01, this session); a closed connection is never presented as a successful completion |
| Connection closed vs. server-confirmed completion | Yes — `reader.read()` EOF vs. a genuine `done` event are distinguished | Yes — EOF-without-`done` renders an "interrupted" state, not success |
| User-selected file vs. uploaded/processed file | **No backend support exists.** No file-upload endpoint is wired into `conversation.html` at all. | N/A — the distinction can't be fabricated without the capability existing; B16 (Context & Attachments) is `NOT STARTED` |
| Mission requested vs. authorized | Yes — PR #79's `operation_store` (`REQUESTED`→`AUTHORIZED` are real, distinct, persisted states) | **No frontend exists that surfaces this** — C02 has no UI; the distinction is real on the backend but invisible to any user today |
| Operation running vs. terminated | Yes — PR #79's mission state machine, plus this session's B-P0-02 cancellation-episode-revision fix | Same as above — no frontend surface |
| Relay connected vs. disconnected | **Partial.** The topbar shows a static `"Relay · Not connected"` pill — confirmed via live browser this session to always read "Not connected" regardless of actual backend state, because the pill's text in `conversation.html` is a hardcoded string, not wired to any real connectivity check. **This is a real, confirmed truthfulness gap, not previously documented at this precision**: the UI currently can't actually distinguish connected from disconnected — it only ever shows one static, unconditional string. |
| Authentication failure vs. successful authentication | Yes | Yes — real `/api/auth/login`/`/api/auth/signup` responses drive `errEl.textContent`, `onAuthSuccess()` |
| Subscription unavailable vs. active entitlement | **No backend support exists.** No billing/entitlement endpoint exists anywhere in `orca/serve/api.py`. | N/A — C13 is correctly `BLOCKED — BACKEND OR AUTHORITY DEPENDENCY`, not faked |

## New finding this session: the "Relay" status pill is not truthful

Grep-confirmed: `<span class="relay" id="relay-badge">Relay · Not connected</span>` is static markup. The CSS even already defines a `.relay.connected:before{background:#3DA35D}` (green-dot) rule — so a truthful connected/disconnected toggle was clearly *intended* — but no JS anywhere in the file ever adds the `.connected` class, changes `#relay-badge`'s text, or reads any real connectivity signal. Every screenshot captured in this session's own browser testing (today and in prior phases) shows this exact unconditional text, in every state — signed in, signed out, mid-stream, after a successful response. **This is a genuine instance of the Assignment G anti-pattern ("Relay connected versus disconnected") the directive explicitly calls out**, and it predates this session (found in the existing PR #81 implementation, not introduced here). Not fixed in this pass — flagged for the audit handoff, since fixing it correctly requires deciding what "Relay" actually refers to (a real backend concept this session did not have time to trace) rather than guessing and wiring a cosmetic fix that could itself become a new false-truth claim.

## GENESIS/NOVUS/AETERNUM honesty (already verified, reconfirmed)

`/api/models` honestly reports `lifecycle: "EXPERIMENTAL"` and `disclosure: "Experimental model -- not qualified."` for all three tiers, and `fallback_active`/`resolved_model` when Novus/Aeternum are silently served by Genesis underneath. The frontend surfaces all of this persistently (not just inside a dropdown that closes), confirmed live this session. No tier is presented as trained and publicly served when it is not; no provider substitution happens under a native ORNEUR model name.
