# ORNEUR UI/UX Design Specification (for founder review)

Status: **DESIGN PROPOSAL — NOT IMPLEMENTED.** Nothing here changes the running product. No implementation starts until the founder approves this
document (decision **D-2** in `docs/orneur/status/ORNEUR_DEVELOPMENT_REGISTER.md`). Screens: `docs/orneur/design/preview/index.html` (self-contained,
no scripts, sample content) and the PNGs beside it. Tokens: `docs/orneur/design/tokens.json`, contrast-tested in CI.

This supersedes the visual direction of `docs/DESIGN_BRIEF.md` (black/white orca mark). It keeps that brief's best rule: **show real model status
honestly, don't hide it behind a "beta" badge.**

## 1. Principles

1. **Calm.** One column of conversation, generous space, almost no chrome. No dashboards, glow, neon, gradients-for-decoration or status clutter.
2. **Predictable in trust.** The interface always tells the truth about what answered (model label), what it used (citations you can open) and what
   it is doing (visible progress with an always-available stop).
3. **Capability that surprises** comes from answers and workflows, never from decoration.
4. **Keyboard- and touch-first.** Every action reachable by keyboard; touch targets ≥ 44 px.
5. **Original.** Common chat patterns (sidebar + thread + composer) are conventions, not property. No third-party assets, marks, copy or layouts are
   copied; the emblem and wordmark below are original constructions.

## 2. Locked brand → how it is used

| Brand element | Use | Do not |
|---|---|---|
| Slate Indigo `#3A4B6B` | user message fill, avatar, citation number fill, emblem facets | text/icons on **Dark** (≈2:1) |
| Solar Coral `#FF6B57` | one primary action per view (send, "New conversation", "Try again"), active-item marker, the E in the wordmark, streaming caret | text on **Light** (2.2–2.6:1) — use `accent_text` `#B03626` |
| Pale Stone `#E8E4DE` | Light sidebar; Dark primary text | — |
| Near-black `#0E1116` | Dark page; text on coral | pure `#000` |
| Greeting | "Hello chief, what's the plan today." (exact; first run / empty conversation only) | show it above a populated thread |
| Themes | **Dark and Light only.** | third theme, per-user palettes, theme-per-model |

Emblem: **abstract falcon in a stoop** — three facets and four nodes (head node in Coral). Wordmark: **ORNEUR** in even-pitch geometric capitals with a
**segmented E** (spine plus three floating Coral bars). Both are **concepts for approval**; final marks are the founder's call (open question Q1).

## 3. Tokens and measured accessibility

`tokens.json` holds every colour for both themes. Brand colours are used for fills and accents; **text and boundary colours are derived variants**
chosen so every listed pair meets WCAG 2.2 AA (4.5:1 text, 3:1 non-text). `tests/test_design_tokens_contrast.py` recomputes all of them in CI. The
preview page prints the measured ratios (e.g. Dark: text on page 14.9:1; Light: secondary text on sidebar ≥ 4.5:1; label on Coral button 6.3–6.75:1).

Typography: system UI stack (no web-font download: faster, private, no third-party request); 14 / 15 (body) / 16 / 20 / 28 px, line-height 1.55 body;
monospace stack for code. Spacing: 4 px grid. Radius: 8 / 12 / 16. Elevation: borders, not shadows. Motion: ≤ 200 ms, only to explain state; all of it
disabled under `prefers-reduced-motion`.

## 4. Layout

- **Desktop (≥ 1024):** sidebar 248–280 px (collapsible) · thread column max 760 px · composer pinned. Artifacts / code / source viewer open as a
  right panel **only on demand**.
- **Tablet (640–1023):** sidebar becomes an overlay drawer.
- **Mobile (< 640):** single column; header (menu · emblem · new); composer pinned above the safe-area inset; sources open as a bottom sheet.

## 5. Components and states

Each has default / hover / focus-visible (3 px ring, offset 2, ≥ 3:1) / active / disabled / error where applicable:
conversation list item · search field · primary & secondary button · icon button · composer (auto-growing, attach, send↔stop) · user & assistant
message · **model chip** · citation chip + source card · file chip · code block (copy, wrap) · alert (role="alert", recoverable) · empty state with
starters · settings (theme, data controls) · auth screens · dialogs (focus-trapped, Esc to close) · toasts (role="status", never the only signal).

## 6. Key behaviours (the parts that make it trustworthy)

1. **Model chip, always visible.** Shows the real lifecycle from the backend. Today every ORNEUR model is experimental/unqualified, so the chip says
   so ("Orneur Novus · experimental · not yet qualified"). It changes only when the registry promotes a model — never by copy edit.
2. **Streaming with one-click stop.** The send button becomes Stop. Stop aborts the request client-side immediately and tells the server (see §7).
3. **Citations are first-class.** Numbered chips inline → source cards (file / page / section or URL + retrieval time). An uncited claim is not
   styled as cited.
4. **Recoverable errors.** Plain language, what was saved, one primary action ("Try again"). No stack traces, no raw backend text.
5. **No silent downgrade.** If a request is served by a fallback model, the chip says which.
6. **Honest empty/first-run state.** The greeting, three starters, nothing else.
7. **Privacy by default.** No third-party fonts/analytics/CDNs; theme preference stored locally only.

## 7. Backend contract (what exists, what is missing)

Verified against the 44 routes in `orca/serve/api.py` (route names only; behaviour of each not re-verified in this pass).

| UI element | Existing route | Gap to close before the screen is "complete" |
|---|---|---|
| Send / stream | `POST /api/chat`, `POST /api/stream` (SSE) | server-side cancel on disconnect cannot interrupt an in-flight backend call (`orca/serve/streaming.py` says so); no client `AbortController` today |
| History / resume | `GET /api/sessions`, `POST /api/session/load`, `PATCH /api/session/{id}/title`, `POST /api/session/save`, `GET …/export` | sessions are process-local unless Redis is enabled (G-007) |
| Search conversations | none seen in the route list | new endpoint + tests |
| Regenerate / edit | none seen | new endpoint or client resend semantics |
| Attachments | `POST /api/docs/upload|list`, `DELETE /api/docs/{id}` | uploads populate a per-session retrieval store, not per-message attachments; message↔file binding to be specified |
| Citations | `/api/explain/{session}/{message}`, `/api/knowledge/…`, `orca/truth/*` | a stable citation payload (source, locator, retrieved-at) in the chat response |
| Model chip | `GET /api/models` (now with `serving_policy`) | per-response lifecycle header (G-015) |
| Code blocks / run | `POST /api/code/run` | execution is AST-check + subprocess (G-004): the "Run" affordance stays hidden until the qualified sandbox backs it |
| Auth, 2FA, API keys, org | `/auth/*` | email delivery and 2FA flows not verified live |
| Settings | none dedicated | theme is client-only; data controls map to the privacy routes |

## 8. Accessibility and quality gates (acceptance for every screen)

WCAG 2.2 AA; semantic landmarks (`nav`, `main`, `form`), labelled icon buttons, visible focus, keyboard order = reading order, `aria-live` for
streaming status (polite) and `role="alert"` for errors, 200 % zoom without horizontal scroll, reduced-motion respected, 44 px targets, screen-reader
pass (NVDA/VoiceOver) and automated axe checks in CI, Playwright journeys (sign in → ask → stream → stop → cite → reload → resume) on desktop and a
mobile viewport, a Content-Security-Policy and a sanitising renderer for model/user content (replaces the 76 `innerHTML` sinks, G-005).

## 9. Implementation plan **after approval** (progressive, each step shippable and tested)

| Step | Delivers | Done when |
|---|---|---|
| U1 | Tokens → CSS variables, theme switch, shell, auth screens on the new system | axe clean; contrast tests; screenshots match approved mock |
| U2 | Thread, composer, streaming, **stop**, model chip, error recovery | Playwright journey passes against a deterministic mock model |
| U3 | History, search, rename, export; durable sessions | restart/resume test passes |
| U4 | Citations + sources panel; file upload/attach | cited-answer fixture passes; unsafe-HTML fixtures neutralised |
| U5 | Settings, privacy controls, mobile polish | 200 % zoom + mobile journey pass |

Mocks only; no screen is declared complete until its function works against the real backend contract, and none represents an unqualified
checkpoint as production intelligence.

## 10. Open questions for the founder (decision D-2)

- **Q1** Approve, change or replace the emblem and the segmented-E wordmark concepts?
- **Q2** Exact greeting punctuation: "Hello chief, what's the plan today." (as specified, no question mark) — confirm.
- **Q3** Default theme: follow the system setting, or always start Dark?
- **Q4** Should end users see the Genesis / Novus / Aeternum choice, or one "ORNEUR" with routing explained in the model chip?
- **Q5** Is the persistent "experimental · not yet qualified" chip acceptable wording until a model is promoted?
- **Q6** Priority order of U1–U5 given the 5 November resource deadline (my recommendation: U1 → U2 → U3, then U4).
