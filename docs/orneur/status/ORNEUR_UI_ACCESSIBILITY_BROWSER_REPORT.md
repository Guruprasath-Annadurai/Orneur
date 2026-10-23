# ORNEUR UI Accessibility and Responsive Browser Report

**Branch:** `claude/ui-implementation-programme-2026-10-23`
**Date:** 2026-10-23
**Method:** real local server + real browser (not static-source assertions alone). This report picks up exactly where the V3 package's own `07_ACCESSIBILITY_RESPONSIVE_QA/EXECUTION_AND_GAPS.md` honestly says it stopped ("Required on engineering host" — this session has that host).

## Findings this session, specifically investigated per the V3 audit's own flagged risks

### 1. Authentication input labels — investigated, nuanced finding

The V3 audit's concern: "Auth sign-in/sign-up all fields have persistent accessible labels." Checked via the live accessibility tree (`read_page`): the Email and Password fields **do** compute a real accessible name (`"Email"`, `"Password"`) — this satisfies WCAG 2.2 SC 4.1.2 (Name, Role, Value) and SC 3.3.2 (Labels or Instructions), because `placeholder` is a valid source of an accessible name when no other label exists. **This is not a hard WCAG failure.** It is, however, a real best-practice gap the V3 audit's word "persistent" correctly points at: placeholder text disappears the moment a user types, which is a recognized usability regression for users relying on labels to re-orient (e.g., after a validation error, or with cognitive/memory considerations). **Recommendation, not auto-applied this pass:** add visually-hidden `<label for="...">` elements paired with each input, keeping the placeholder text as supplementary hint text. This is a small, visual-geometry-neutral change but was not made in this pass pending confirmation it's in scope (a form-markup change, however small, to the approved auth card).

### 2. Sidebar/topbar account control — investigated, found and fixed

The V3 audit's concern: "Account row accessible by keyboard." Checked directly in source: `#sidebar-avatar`, `#sidebar-account-label`, and `#topavatar` are plain `<span>` elements with **no click handler and no keyboard handler anywhere in the file** (confirmed by grep across the whole script, not just visual inspection). `.topavatar` carried `cursor:pointer` in its CSS despite this — a misleading affordance implying an interaction that doesn't exist. **Fixed this pass**: removed the misleading `cursor:pointer` (see `conversation.html` diff). This is the conservative fix — it removes a false affordance rather than inventing new click/keyboard behavior the approved design doesn't specify. If the account area is *meant* to be interactive (e.g., opening an account menu), that's a design decision requiring the actual menu contents to be approved first — flagged for founder decision in the audit handoff, not invented here.

### 3. Focus visibility on composer, model selector, auth controls — verified

Confirmed via live keyboard interaction (this session's A-P1-01/A-P1-03 verification work, re-confirmed): `.authskip:focus-visible`, `.authtabs button:focus-visible`, `.authcard input:focus-visible`, `.authcard button:focus-visible`, and `.modelopt:focus-visible` all carry an explicit `outline: 2px solid var(--accent)` rule. Live-tested: Shift+Tab from the auth dialog's first element correctly wraps to its last (focus trap working); the model dropdown's first option receives focus automatically on open and Tab/Enter navigate and select correctly (screenshotted this session).

### 4. 320px mobile viewport — verified, no overflow

`document.documentElement.scrollWidth === window.innerWidth === 320` at a real 320×640 viewport — **no horizontal overflow**, confirmed via live JS evaluation, not estimated from CSS.

### 5. Reduced motion does not suppress state truth — verified by design

`prefers-reduced-motion: reduce` (A-P2-02, this session) disables only the decorative pulse/slide animations; the underlying state (the "Thinking"/model-status text, the drawer's final open/closed position) is conveyed through text and layout, not motion — confirmed by reading the actual CSS rules, which touch only `animation`/`transition` properties, never `display`/`visibility`/text content.

### 6. Streaming interruption truthfulness — verified

Re-confirmed this session (A-P1-01 live A/B test): an interrupted or abandoned response is marked with a visible "Response interrupted" badge and never offered a Copy action, which only appears after a genuine `done` event. No invented success state.

## Not executed this pass (honestly disclosed, per the V3 audit's own template)

- Automated axe-core or equivalent WCAG ruleset scan (no such tool is wired into this repo or available in this session).
- Zoom-to-200%/400% reflow testing.
- Screen-reader-specific (VoiceOver/NVDA) spoken-output verification — the accessibility *tree* was inspected (names/roles/states), but no actual screen reader was run.
- Tablet-width (768–900px) and 390px viewport screenshots — only 320px and desktop (1536px) were captured this pass.
- A systematic contrast sweep beyond what `test_contrast_regression.mjs` already covers (A-P1-02, prior phase) — no new color pairs were introduced this pass to check.

## WCAG 2.2 AA compliance status

**NOT FULLY VERIFIED**, consistent with the V3 package's own honest conclusion. This pass closes several of the specific gaps the V3 audit named (items 1–2 above, investigated and one fixed) and adds real keyboard/viewport/motion evidence the V3 package could not capture from its own authoring environment. A full automated+manual WCAG 2.2 AA audit remains outstanding.
