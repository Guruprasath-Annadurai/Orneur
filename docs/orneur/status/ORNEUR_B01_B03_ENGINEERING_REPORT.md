# ORNEUR — B01/B02/B03 Conversation Shell: Engineering Report

**Directive**: CTO Product Engineering Directive — build ORNEUR's first genuinely functional conversation experience (Authentication → New Conversation → Active Conversation → Answer Reading → Conversation Persistence → Recovery) using the founder-approved B01/B02/B03 designs.
**Branch**: `claude/b01-b03-conversation-shell-2026-10-22`, based on `origin/main`. PR #78, #79, #80 untouched.

---

## 1. Inspection, done first

- **Design archive**: `ORNEUR_UIUX_FINAL_CTO_REVIEW_HANDOFF(2).zip` confirmed present at `/Users/ag/Downloads/`, already extracted and SHA-256-verified in a prior phase (274/274 files matching `SHA256_MANIFEST.txt`). No `APPROVED_REFERENCE_MISSING` condition. The B02 and B03 archives additionally contain real HTML/CSS source (`ORNEUR_B03_Combined_Dark.html`/`_Light.html`), not only PNG references — their checksums were independently re-verified against the manifest before use.
- **Existing frontend**: `orca/serve/web/index.html` (4,310 lines, served at `/app`) is a real, already-functional chat client — a DIFFERENT, unapproved visual design ("Intelligence, Without End" / `#000000`/`#080808` palette, no B01 greeting, a multi-agent "pod panel"), but with genuinely working auth, SSE streaming, session persistence, and markdown rendering logic. Per the directive's own instruction ("reuse existing architecture... do not add duplicate authentication and persistence systems"), this phase's own JS **reuses that exact, working logic** (same endpoints, same SSE event protocol, same `localStorage` token convention, the same `mdToHtml`/`esc` functions) rather than reinventing it — only the markup/CSS is new.
- **Existing backend**: `orca/serve/api.py` already has mature, real endpoints this phase builds directly on: `POST /api/auth/signup|login`, `GET /api/auth/me`, `POST /api/stream` (SSE), `GET /api/sessions`, `GET /api/session/{id}/messages`, `GET /api/models` (real lifecycle/disclosure/fallback honesty fields). None of these were modified.
- **`/app` is left completely unmodified** — the new work lives at a new route, `GET /conversation`, serving a new file, `orca/serve/web/conversation.html`. Verified by test (`test_existing_app_route_is_unmodified`).

---

## 2. What was built

**New files**: `orca/serve/web/conversation.html` (the B01/B02/B03 shell), `orca/serve/web/b01_approved_assets/orneur_logo_horizontal.png` (the exact, SHA-256-verified logo from the approved archive — `b52c2f3...d55768c`, re-verified against the archive's own manifest before and after copying), `tests/test_conversation_shell.py`.
**Modified**: `orca/serve/api.py` (+13 lines: one new route, no other change).

### B01 — New Conversation
- Official logo (byte-identical to the approved archive's own copy), exact greeting `Hello chief, what's the plan today.`, centered composer with model selector inside it, starter-suggestion row (`Research with sources · Work with a file · Write or code`), left sidebar (new conversation / recent conversations / account).
- Both approved themes implemented from the locked CSS tokens: **Obsidian Dark** (`#080808` canvas) and **Meridian Light** (`#F6F3EE` canvas, dark sidebar retained per the design lock's own instruction). Toggle persists via `localStorage`.
- Authentic signed-in/signed-out behavior: a real sign-in/sign-up overlay (calling the real `/api/auth/*` endpoints) gates the experience; "Continue without an account" is also offered, matching `/api/stream`'s own support for anonymous use.

### B02 — Active Conversation
- Real, authenticated conversation creation and durable persistence through the existing session/transcript infrastructure — no new storage layer, no duplicate auth.
- Conversation history retrieval (`GET /api/sessions`) populates the sidebar; selecting one loads its real transcript (`GET /api/session/{id}/messages`) and renders it.
- Real API integration via `POST /api/stream` (Server-Sent Events) — no hard-coded responses. User/assistant messages render distinctly; a "Thinking" indicator appears while the model generates, matching the real `thinking`/`chunk`/`done` SSE event types the backend already emits.
- Accurate loading/error/recovery states: a failed load shows an honest "could not load" message, not a blank or fabricated state; a non-200 `/api/stream` response or a network failure shows a genuine error line, not a silently-swallowed failure.
- Cross-user/cross-organization access protection: entirely enforced by the existing, unmodified `_owned_session_or_404`/`claim_session` machinery — re-verified by this phase's own new tests (see §4), not reimplemented.
- No artificial progress indicators: the "Thinking" state is driven by real SSE events, not a timer.

### B03 — Answer Reading
- Readable, B03-faithful message typography (15px/1.68 line-height, structured paragraphs/lists/code blocks via the ported `mdToHtml`), correct user/assistant ordering, responsive layout.
- Working copy interaction (Clipboard API) on each assistant answer.
- Real response-content rendering: nothing in the reading region is sample/placeholder text once a real conversation exists.
- No source/citation UI is implemented in this increment (none of B03's own illustrative content references real source records, and this codebase currently has no citation-backed answer path to render honestly — correctly omitted rather than fabricated).

### Critical model-availability rule — honored, and a real bug caught and fixed

The first implementation of the model selector read only `info.publicly_served` and labeled every available tier **"Available now."** Testing against the real `/api/models` response revealed this was a genuine overclaim: **all three tiers are `lifecycle: EXPERIMENTAL`, `disclosure: "Experimental model -- not qualified."`**, and **Novus/Aeternum are `fallback_active: true`**, silently served by Genesis's own model underneath. This directly contradicted the directive's explicit "Do not pretend a mock response is ORNEUR native inference... do not silently substitute another provider." **Fixed before this phase's own commit**: the selector now surfaces the real `lifecycle`, `disclosure`, and fallback status for every tier, both in the dropdown and as a persistent disclosure line under the composer once a tier is selected (not just inside a dropdown that closes). No paid infrastructure or API credits were purchased; no provider substitution occurs — Genesis/Novus/Aeternum all route through the existing local Ollama-backed registry exactly as `/api/models`/`resolve_tier_backend` already define.

---

## 3. Live, interactive browser verification (this session)

Performed against a real local server (`uvicorn orca.serve.api:app`, real Ollama backend already running locally) via the Claude Code built-in browser:

1. **B01 empty state**, Obsidian Dark and Meridian Light — screenshotted, matches the locked references' layout/hierarchy.
2. **Theme toggle** — Dark ↔ Light, persisted across reload.
3. **Model selector** — opened, showed the corrected, honest disclosure text for all three tiers; selected Genesis.
4. **Real end-to-end message send** — typed "What is 2+2?", sent via Enter, watched the real "Thinking" state, then a real streamed response from the local Genesis (nano) model rendered with correct Markdown (numbered list), "Copy" action present.
5. **Sign-up** — created a real test account (`b01b03-tester@example.test`) through the real `/api/auth/signup` endpoint; account avatar/name updated correctly after fixing a real response-shape bug (see §4).
6. **Conversation persistence + recovery** — sent "Say hello in one short sentence." under the new account, received a real streamed reply, saw the conversation appear in "Recent Conversations," **reloaded the page from scratch**, confirmed the session was auto-restored (token persisted) and the conversation was still listed; clicked it and confirmed the full prior exchange (`user: ...` / `ORNEUR: Hello.`) loaded correctly from the real transcript endpoint.
7. **Cross-user denial** — signed up a second account via a direct API call and confirmed it received 404 attempting to read the first account's session.
8. **Mobile responsive** (375×812) — confirmed no horizontal scroll, composer/greeting readable; **found and fixed a real completeness gap**: the sidebar had no way to be opened on mobile at all (no navigation affordance), leaving "Recent Conversations" and "Sign out" completely unreachable on a phone. Added a hamburger menu button + slide-in drawer + veil, re-verified working (new conversation, recent conversations, and sign-out all reachable).

No browser screenshot files are attached to this report as separate artifacts (the interactive session itself is the evidence); the descriptions above are accurate accounts of what was actually observed, not assumed.

---

## 4. Real bugs found and fixed during this phase's own testing

1. **Model availability overclaim** (described in §2) — the single most important correctness fix, directly matching the directive's explicit prohibition.
2. **`/api/auth/me` response-shape bug**: `tryRestoreSession()` initially treated the endpoint's response as the user object directly; the real endpoint wraps it as `{"user": {...}, "limits": {...}, "usage": {...}}`. Found via live testing (account avatar showed "?" after reload), fixed, re-verified, and now covered by `test_auth_me_response_is_wrapped_in_a_user_key`.
3. **No mobile navigation affordance** (described in §3, item 8) — fixed with a real hamburger-menu drawer, not a cosmetic patch.
4. **A local dev-environment discovery, not a bug in this phase's own code**: this worktree's `.claude/launch.json` points `orca-web` at `/Users/ag/orca/.venv`, an **unrelated, stale sibling checkout** (`/Users/ag/orca/orca/`, last modified Oct 15) with its own editable install — meaning the preview tool's dev server was silently serving a completely different, outdated copy of `orca`, not this worktree's own code. This was diagnosed by comparing file hashes and import paths, confirmed by running a manually-launched server with an environment pointed unambiguously at this worktree. `launch.json` itself was **reverted to its original value** (not committed as part of this change — repo-shared dev tooling config is outside this phase's scope to alter unilaterally); this finding is recorded here for whoever owns that config next.

---

## 5. Automated tests

`tests/test_conversation_shell.py` (8 tests, all passing): the route serves the real shell (greeting, key structural IDs present), the approved logo asset is served and SHA-256-matches the verified archive copy exactly, `/app` is provably unmodified, `/api/models` keeps exposing the honesty fields the frontend depends on, the `/api/auth/me` wrapping bug is regression-guarded, and cross-user session access is denied (via a real `claim_session()` call, not a reimplemented check) while the genuine owner succeeds.

**Honest scope limitation**: this repo has no existing Playwright/Selenium (or any browser-automation) test infrastructure, and none is introduced in this increment — adding a new, heavyweight automated-browser toolchain was judged out of this phase's reasonable scope. The browser-level B01→B02→B03 navigation, streaming, persistence, cross-user-denial, and mobile-drawer behaviors described in §3 were verified **live, interactively**, with real screenshots inspected during this session, but are not captured in a repeatable, CI-executable browser test suite. This is reported honestly rather than claimed as automated coverage it is not.

Regression: `tests/test_conversation_shell.py` + a broad `tests/test_api_*.py` sweep — see commit's own CI evidence for exact counts (recorded once available; not assumed here).

---

## 6. Deliverables

1. **Branch**: `claude/b01-b03-conversation-shell-2026-10-22`.
2. **Exact commit SHA / PR URL**: recorded once pushed (see commit history / draft PR).
3. **Real features implemented**: see §2.
4. **Screenshots**: observed live during this session (§3); not saved as separate repository artifacts.
5. **Browser-test results**: live, interactive verification only (§3); no automated browser suite exists (§5).
6. **Backend integration evidence**: real `/api/stream` SSE round-trip, real `/api/sessions`/`/api/session/{id}/messages`, real `/api/auth/*`, real `/api/models` — all against the existing, unmodified backend.
7. **Features blocked by unavailable inference/infrastructure**: none — local Ollama inference was genuinely available and used for live testing; the model-availability UI honestly reflects that every tier is still `EXPERIMENTAL`/not qualified regardless.
8. **Failures / skipped tests / unresolved risks**: no automated browser suite (§5); B03's optional section-outline/citation features deliberately not implemented (no real backend support to render honestly); B04–B16 deliberately out of scope per the directive's own instruction.
9. **Honest completion status**:
   - **B01**: Implemented and live-verified (both themes, auth states).
   - **B02**: Implemented and live-verified (creation, persistence, recovery, real streaming, cross-user denial).
   - **B03**: Implemented and live-verified (reading typography, copy action, real content rendering); outline/citation sub-features not built (no real data to back them).
10. **Single next recommended engineering milestone**: wire the B02 "Variant B" contextual file/source panel and B03's optional answer-outline (both already fully speced and, in B03's case, have real reusable source HTML/CSS in the approved archive) — or, per the CTO's own prior directive sequencing, continue the C02 mission-execution backend's remaining gaps (SSE streaming, execution-time screens) before expanding B04+.

No merge, no tag, no training, no GPU/paid infrastructure provisioning, no founder-approved-design modification (the approved references were followed, not altered) occurred in this phase.
