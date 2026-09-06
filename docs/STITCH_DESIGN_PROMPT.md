<!--
A complete, screen-by-screen design prompt formatted for Google Stitch
(https://stitch.withgoogle.com). Builds directly on docs/DESIGN_BRIEF.md
and docs/CLAUDE_DESIGN_PROMPTS.md — same design system, same honesty
constraints (every data field referenced is real, pulled from the actual
API) — reformatted and extended for Stitch's screen-generation workflow,
and extended to cover Orca Lens, which the earlier two docs didn't include.

How to use this in Stitch: paste the "Design System Prompt" first as your
initial project prompt to establish the visual language, then generate each
numbered screen below as its own screen within the same Stitch project so
they inherit the same system. Stitch works best with one focused prompt per
screen rather than one giant combined prompt — that's why this is split up.
-->

# Orca — Google Stitch Design Prompt Set

## How to run this in Stitch

1. Create a new Stitch project. Paste the **Design System Prompt** below as
   your first generation — this establishes the palette, type, and
   component language every later screen must match.
2. Generate each screen in the numbered order below, one Stitch prompt per
   screen, in the same project so Stitch keeps design-system continuity.
3. Screens 1-11 cover Genesis + Novus (the core chat product). Screens
   12-16 cover Orca Lens (media generation) — treat these as a visually
   related but functionally distinct surface, per the launch plan's
   stricter review gate for Lens.
4. Every specific number, label, or field named below (chunk counts, retry
   times, eval scores, etc.) is a real value the backend actually returns —
   design the UI to display real data shapes, not placeholder Lorem Ipsum.

---

## Design System Prompt (run first, establishes the whole project)

```
Design system for "Orca," an enterprise AI platform (Genesis, Novus, and
Orca Lens) built by Atheris. This is a precision engineering tool for
serious work, not a bubbly consumer chat toy — the visual language should
make a technical buyer trust it with real data on first look.

COLOR
- Background: true black, #000000 primary surface, #080808 for slightly
  raised panels (cards, sidebars).
- Text: off-white #e8e8e8 for primary text, pure white #ffffff for
  emphasis/headings, muted gray tiers #999999 down to #4a4a4a for
  secondary/tertiary/disabled text.
- Signal colors: one desaturated green (~#4a9d6e, not neon) for
  success/active/online states, one desaturated red (~#c14f4f, not neon)
  for errors/destructive actions. One desaturated amber (~#c9a54a) for
  "not yet verified / caution" states. No other accent colors anywhere —
  no blue, no purple, no bright brand color.

TYPOGRAPHY
- Monospace family (JetBrains Mono or similar) for ALL technical/data
  chrome: session IDs, model names, timestamps, metrics, hashes, code,
  file sizes.
- Sans-serif family (Inter or similar) for conversational content, body
  copy, and marketing text. Never render a full paragraph of assistant
  chat response in monospace — that reads as a terminal, not an assistant.

LOGO
- Primary mark: a single-continuous-stroke line-art orca in side profile,
  white on transparent (or pure black) background — the dorsal ridge line
  is constructed as a subtle waveform/sonar-return rhythm, not a smooth
  arc, so the mark reads "orca" at a glance and reveals the sonar/
  verification concept on closer inspection. Used at full detail in
  headers, splash/marketing surfaces, and favicon — must read clearly at
  24px. See docs/LOGO_DESIGN_PROMPT.md for full construction spec.
- No secondary color or gradient mark exists — the identity is strictly
  monochrome everywhere, product chrome and marketing alike. Only the
  stroke-weight optimization differs between small-size (nav bar, favicon)
  and full-detail (marketing hero, splash) renderings — never a color or
  tone difference.

MOTION
- Subtle and purposeful only. "Thinking"/loading states use a soft pulse or
  faint particle-glitch texture that echoes the geometric logo mark — not
  a generic spinner.

LAYOUT DENSITY
- Auth, marketing, and onboarding surfaces: generous whitespace, centered
  compositions, room to breathe.
- Admin, governance, and data surfaces (audit logs, model cards, metrics):
  deliberately denser information layout — this audience wants data
  density over polish.

OVERALL FEEL
A confident, quiet, technical precision instrument — think a professional
engineering console, not a friendly consumer assistant.
```

---

## Screen 1 — Onboarding: welcome

```
A centered welcome screen, black background. The line-art orca mark
centered, roughly 25% of viewport height above center. Below it, one line
of body text: "The AI platform that shows its work." Below that, a single
full-width-capped primary button, white background black text: "Get
Started." A small muted-gray footer row of links: "Terms · Privacy · AI
Policy."
```

## Screen 2 — Onboarding: model selection

```
Three cards in a horizontal row (stack vertically on mobile), same width,
dark panel background (#080808) with a thin 1px muted border. Card 1
header "Genesis," subtext "Everyday assistant — fast, honest, direct."
Card 2 header "Novus," subtext "Deep reasoning partner for complex work."
Card 3 header "Aeternum," subtext "Flagship cross-domain synthesis." Each
card has a "Select" button at the bottom. On any card whose model hasn't
cleared its internal quality/safety verification threshold, show a small
amber pill badge top-right of that card reading "Not yet verified" — this
must be visually present whenever the real backend signal says so, never
hidden or softened into generic "Beta" text.
```

## Screen 3 — Onboarding: first message

```
A centered composition. A single input field, larger than a normal chat
input, placeholder text "Ask Orca anything." Below it, a 2x2 grid of
four example-prompt chips (rounded rectangle, muted border, sans-serif
text), e.g. "Find investors for my startup," "Write a cover letter,"
"Explain a concept simply," "Debug this code." Clicking a chip fills the
input with that text.
```

## Screen 4 — Auth: sign in / sign up

```
A centered card, max-width ~420px, thin corner-bracket decorative frame
(small white L-shaped brackets at each corner, not a full border box).
Header: line-art orca mark, wordmark "ORCA" below it, small muted-gray
tagline "Enterprise AI · Powered by Atheris."

Below the header, a two-tab pill switcher: "Sign In" / "Sign Up" — active
tab white background with black text, inactive tab transparent with muted
gray text.

Sign In form: email field, password field (dark input, thin border, light
placeholder text), full-width primary white button "Sign In." Below the
button: "No account? Sign up free" as a link, and a smaller separate
"Forgot password?" link.

Footer below the card: three small muted links — "Terms of Service ·
Privacy Policy · AI Policy."
```

## Screen 5 — Auth: 2FA setup

```
Same card/frame style as the auth screen. Header: "Set Up Two-Factor
Authentication," one sentence of plain-language context beneath it.

Center: a QR code image generated from a real otpauth:// URI. Below the QR
code, a toggle link "Can't scan? Enter this code manually" which reveals a
monospace secret string in a small dark box with a copy-icon button.

Below that: a single label "Enter the code from your authenticator app,"
then a row of 6 individual digit input boxes (large, monospace, evenly
spaced), then a primary button "Verify & Enable."

Error state variant: a red-tinted inline text directly below the digit
boxes reading "Invalid code — check your app and try again."
```

## Screen 6 — Auth: 2FA challenge (mid-login)

```
Same card style as Screen 5, shown mid-login instead of at setup. Header:
"Two-Factor Verification," subtext "Enter the 6-digit code from your
authenticator app." Center: the same 6-digit box row, auto-focused on
first box. Primary button "Verify." Below: small muted text "Trouble
accessing your authenticator? Contact support" as the only fallback —
do not show a fake "Resend code" option, since TOTP codes are generated
locally and never sent.
```

## Screen 7 — Main chat interface (Genesis / Novus)

```
Full desktop layout. Left sidebar, ~260px wide, background slightly
lighter than main black (#080808): a search input at top, a "+ New
Session" button below it, then a scrollable list of session rows — each
row shows an auto-generated session title (truncated) and a tiny colored
dot + label indicating model variant (nano/core/ultra).

Top header bar spanning the main content area: line-art orca logo on the
far left, a connection-status indicator just right of it (green dot
"Online" or red dot "Offline"), three pill-shaped model-variant buttons
centered (NANO / CORE / ULTRA — active one has a white background, others
transparent with border; any unavailable variant is visually dimmed with a
small info-icon that reveals on hover/tap WHY it's unavailable — model not
running vs. not yet verified are different reasons and must read
differently). User avatar and menu on the far right.

Main message thread: clear visual distinction between user messages and
Orca's responses (choose alignment/background contrast, but make the
distinction unmistakable at a glance). Orca's responses in sans-serif with
generous line-height. Directly above any response that used a tool, show
small pill tags reading the tool name, e.g. "web_search," "run_code."
Within a response, numbered citation markers like [D1] [D2] render as
small clickable chip-styled tokens, not raw bracket text. Below the final
message in a thread, show a small outline-style "Explain" button with a
magnifying-glass icon.

Bottom composer: a multi-line auto-growing textarea, with icon buttons to
its left/right for attach-document, attach-image, and voice-input, and a
send button (arrow icon) at the far right. Directly below the composer, a
thin row of quick-command hint text ("/web · /run · /remember") in muted
small type.
```

## Screen 8 — Explain / trust panel (modal)

```
A modal overlay, centered, dark panel background, opened from the
"Explain" button on a chat response. Header: "How this answer was
generated." Below it, a vertical sequence of labeled steps (e.g.
"Retrieved 3 documents — 120ms," "Checked 2 citations against source
text — 40ms," "Generated response — 850ms") each as a row with a small
timing value in monospace on the right. Below the steps, a confidence bar
(horizontal, filled proportionally, labeled with a percentage). If any
contradiction or citation-compliance issue was detected, show a distinct
amber warning row below the confidence bar with plain-language text (not
a raw backend error code). This modal must read as authoritative and
calm — a trust surface, not a debug console dump.
```

## Screen 9 — Document upload & citations

```
Design the document-attachment flow within the chat composer area. A
horizontal row of small pill-shaped "doc chips" appears above the
composer once files are attached — each chip shows a small document icon,
truncated filename, a chunk-count badge (e.g. "12 chunks"), and a small ×
to remove it.

Upload-in-progress state: a determinate progress bar with real, specific
stage text cycling through: "Extracting text…" then "Redacting sensitive
data…" then "Chunking…" then "Embedding…" — these must be the real
pipeline stage names, not generic "Uploading…" filler.

Post-upload system note, rendered inline in the chat thread (not a toast
popup): "resume.pdf uploaded — 12 chunks indexed. 3 items redacted (2
emails, 1 phone number) before storage." This redaction disclosure must be
plainly visible, not hidden in a settings page.

Citation popover: clicking a [D1]-style chip in a response opens a small
popover showing the source filename, the specific chunk number, and a
short excerpt of the actual source text used.
```

## Screen 10 — Code interpreter

```
A code block embedded within a chat message. Slightly darker background
than the page, syntax-highlighted Python. A thin header bar directly above
the code showing the language label on the left and an outline "▶ Run"
button on the right.

After running, an output panel appears directly below with no visual gap
(reads as one connected block): stdout text in default off-white,
stderr text in the muted red signal color, and a small monospace footer
line reading e.g. "exit 0 · 340ms."

Blocked-execution variant: if the sandbox rejects the code, the output
panel shows a plain-language explanation instead of a raw traceback, e.g.
"`os` isn't available in the sandbox — this keeps code execution safe."
```

## Screen 11 — Vision / image input

```
An image-attachment flow parallel to but visually distinct from document
attachment — use a photo/image icon, not a document icon. On attach, show
a small thumbnail preview chip (an actual small image preview, not just a
filename) above the composer, with an × to remove.

Pre-send capability warning: if the currently active model variant isn't
vision-capable, show an inline amber warning directly beneath the
thumbnail BEFORE the user can send: "The current model doesn't support
images. Switch to a vision-capable model or continue with text only." This
must appear before sending, never as a failure message after the fact.
```

## Screen 12 — Knowledge graph explorer

```
A panel opened via a "Knowledge" tab/icon within a session view. Left
column: a simple list of entity names extracted from the current session,
each with a small type badge (person / organization / technology / place
/ concept) and a mention-count number.

Main area: selecting an entity shows a minimal node-and-edge diagram —
the selected entity as a center node, its one-hop related entities as
surrounding nodes, thin white connecting lines labeled with the actual
relationship predicate (e.g. "founded," "develops"). Keep this
understated: thin lines on black, small monospace labels, not a colorful
force-directed cluster.

A persistent small badge at the top of this panel, always visible when the
panel is open: "Extracted automatically from this conversation — not
independently verified."
```

## Screen 13 — Settings (tabbed)

```
A settings screen with a left-hand vertical tab list: Profile, Billing,
Security, API Keys, Data & Privacy.

Billing tab: current plan name and price at top, then a 3-column plan
comparison table (Free / Pro / Enterprise) listing real feature
differences (message limits, model access, priority support), one
"Upgrade" button per paid column.

Security tab: a 2FA status row (Enabled/Disabled) with a button leading to
the Screen 5 setup flow, and a separate password-change form below it.

API Keys tab: a table with columns — key name, created date, last-used
date, a masked key preview (e.g. "sk-••••1a3f"), and a revoke button per
row. A "Create New Key" button at the top; clicking it shows the full raw
key exactly once in a copyable monospace box with a clear warning: "This
key won't be shown again."

Data & Privacy tab: a red-outlined (not alarmist, just clearly marked)
"Delete My Account" section. Clicking it opens a confirmation modal that
states real specifics before allowing deletion: "This will delete 3
sessions, 7 documents, and your account. Historical audit log entries are
retained per our data policy." A password-confirmation input, then a final
red "Delete Account" button.
```

## Screen 14 — Admin / Governance dashboard

```
A denser, data-forward admin dashboard — this audience wants information
density, not marketing polish. Left nav: Audit Log, Model Cards, Eval
History, Metrics.

Audit Log view: a searchable, filterable table (columns: timestamp,
event, user, detail preview). A prominent button at the top, "Verify
Chain Integrity" — clicking it runs a real check and displays a large
PASS (green) or FAIL (red) result banner; on FAIL, show the exact sequence
number and reason for the broken entry, never a vague "tampering
detected."

Model Cards view: one detail card per variant (Genesis/Novus/Aeternum) —
base model name, version, a truncated signature hash in monospace, a large
"Persona Claim: Approved / Not Yet Verified" status badge with the exact
reason text beneath it, eval scores (accuracy %, style /10, speed tok/s)
as a row of stat blocks, safety scores (jailbreak block rate, bias flag
rate, calibration score) as a second row of stat blocks, and a "Known
Limitations" list rendered exactly as the backend generates it — do not
paraphrase or soften this copy.

Eval History view: a line chart per model showing overall score over
time, with any regression point marked with a distinct small red marker.

Metrics view: a per-endpoint table (request count, error rate, p50/p95/p99
latency), with large summary stat numbers for overall uptime and error
rate at the top of the page.
```

## Screen 15 — Error / empty / loading states

```
A small consistent set of system states.

Offline state: the header connection dot turns red, and a banner appears
above the chat composer: "Ollama is offline — start it locally to
continue," with a muted "Retry" button.

Rate-limited state: an inline message in the chat thread showing the
actual retry-after value from the real API response, e.g. "Rate limit
reached — try again in 47 seconds," never a generic "try again later."

Empty session state: centered composition, the line-art orca mark at low
opacity, text "Start a conversation," with the same example-prompt chips
from Screen 3 reused here.

Empty knowledge graph state: centered text "No entities extracted yet —
they'll appear here as you chat" — styled as a normal expected state, not
an error.
```

---

## Orca Lens screens (media generation — separate surface, stricter trust/legal framing)

Lens carries a distinctly higher legal/trust risk than the chat product
(copyright, deepfake/likeness, content-policy exposure) — every Lens
screen below is designed to make moderation, provenance, and limits
visible, not hidden, consistent with the stricter launch gate Lens has in
`docs/LAUNCH_PLAN.md`.

## Screen 16 — Lens: generation studio (entry point)

```
A distinct visual context from the chat product — same black/white/mono
design system, but the top header reads "Orca Lens" with its own small
line-art orca-plus-camera-aperture composite mark (reuse the same orca
line-art stroke, add a minimal aperture ring around it) instead of the
plain chat logo, to signal "different surface, same brand."

Center: a large prompt input for describing the desired image/video,
a mode toggle above it ("Image" / "Video"), and below the input, a row of
generation-setting controls (aspect ratio, style preset, quantity) shown
as simple dropdown pills. A prominent primary button "Generate."

Directly below the button, in small muted text, a permanent disclosure
line: "All generated media is watermarked and includes content
credentials. Generation is subject to our content policy." This line must
always be visible on this screen, not something the user has to seek out.
```

## Screen 17 — Lens: generation in progress

```
A generation-progress card shown in place of the result, with a
determinate or indeterminate progress indicator (use the same soft
particle-glitch pulse motion language as the chat product's thinking
state) and real stage text if available (e.g. "Queued" → "Rendering" →
"Finalizing"). Show an estimated time remaining if the backend provides
one, and a cancel button.
```

## Screen 18 — Lens: result & provenance panel

```
The generated image/video displayed large, centered. Directly below it, a
persistent small metadata strip (monospace): generation ID, model/version
used, timestamp, and a visible small "Content Credentials" icon-button
that opens a panel showing the embedded provenance metadata (what
generated it, when) — this is the watermark/provenance disclosure from the
launch plan made concrete and visible, not just embedded invisibly in the
file.

Action row below: Download, Share, Regenerate, and Report (a distinct,
clearly-labeled reporting action for flagging problematic output —
required given Lens's higher moderation stakes).
```

## Screen 19 — Lens: content policy block/warning state

```
When a prompt is blocked by the content moderation pipeline, replace the
result area with a calm (not alarming) message: a neutral icon, text "This
request doesn't meet our content policy," and a link "Learn what's
allowed" pointing to the actual content policy — never a vague "something
went wrong," since this is a deliberate policy block, not an error.

A distinct, rarer variant for a flagged-but-under-review case (e.g.
possible likeness/deepfake match): "This request needs a manual review
before it can be generated," with no further detail exposed about the
specific detection logic (avoid revealing exploitable specifics of the
moderation system).
```

## Screen 20 — Lens: gallery / history

```
A grid gallery of the user's past generations, each thumbnail showing a
small persistent watermark corner-mark (consistent with the provenance
disclosure from Screen 18) and, on hover, the generation date and mode
(image/video). A filter row at top (All / Images / Videos). Clicking a
thumbnail opens the Screen 18 result view for that item.
```

---

## Accessibility requirements (apply to every screen above)

- Every icon-only control (attach, mic, send, revoke, remove) needs a real
  accessible label, not just a visual tooltip.
- Verify all muted-gray text tiers against the true-black background meet
  WCAG AA contrast at minimum.
- The full core chat flow (compose, send, switch model, open Explain
  modal) must be operable by keyboard alone.
- Streaming responses need to be structured so assistive technology
  announces new content incrementally, not by re-reading the entire
  thread.

---

## Addendum — new real capabilities built since the screens above (add these, don't replace)

Everything below reflects backend capability that's real, tested, and live as of 2026-07-24, but has zero frontend yet. Generate these as updates to the existing screens/modal, in the same Stitch project, same design system.

## Screen 21 — Updated Explain/Trust modal (extends Screen 8)

```
Extend the existing "How this answer was generated" trust modal (Screen 8)
with two new real sections — add them below the existing confidence bar,
same calm/authoritative visual language, not a developer console dump.

Section A — Grounding check: a labeled row "Fact-check against sources:"
with one of three states, each with a distinct small icon and the
desaturated signal colors already established (green/amber/red):
  - Green "Grounded" — the response's claims were checked against
    retrieved context and found consistent.
  - Amber "Partially supported" with a one-line reason shown beneath
    (e.g. "One claim about founding date wasn't found in the source") —
    real, specific text from the backend, never a generic warning.
  - Grey "Not checked" — shown when no retrieved context existed for this
    turn (nothing to check groundedness against) — a neutral, non-alarming
    state, not styled like a failure.

Section B — Data handling: a small row "Response reviewed for sensitive
content before delivery" with an expandable disclosure — if anything was
found, show it plainly: "1 email address detected (shown as-is — this may
be your own information)" for PII (never hidden, never redacted from
view, matches the real backend rule that PII is flagged not silently
stripped), or "1 item redacted for safety" for an actual secret/credential
pattern (which DOES get removed from what's shown). If nothing was found,
a single quiet line: "No sensitive content detected" — no need to expand.
```

## Screen 22 — Cost-router escalation badge (new, small, on the message itself)

```
Design a small, subtle badge that appears on an individual assistant
message ONLY when that specific response was escalated from the
self-hosted model to a frontier backend by the cost-aware router (a real,
opt-in backend feature — most responses will never show this badge).

Badge: small pill, muted amber-adjacent tone (distinct from the
red/green signal colors already used for errors/success), reading
"Escalated for this query" with a small upward-arrow icon. Clicking or
tapping it opens a one-line popover with the real reason text the backend
provides (e.g. "time-sensitive language detected — routed to a frontier
model for freshness"). Must look like a transparency feature the product
is proud of, not an apology or a warning.
```

## Screen 23 — Persona claim status badge on the model-selector pills (extends Screen 3/7)

```
Update the NANO/CORE/ULTRA model-selector pills from the main chat screen
(Screen 7) to reflect the REAL, live persona-claim gate status returned by
GET /api/models's "persona_claims" field — this already exists as real
API data, just not rendered anywhere yet.

Each pill gets a tiny status dot in its corner: green if that tier's
persona claims are "approved" (all thresholds cleared), amber if "not yet
verified." Hovering/tapping an amber-dotted pill reveals the exact real
reason text the backend provides (e.g. "jailbreak block rate 0% is below
the 90% required for this tier's persona claims") — never hidden, never
paraphrased into something softer. This is the same honesty-first
principle as every other trust surface in this design: a real limitation
shown plainly reads as more trustworthy than a hidden one, not less.
```

---

## Marketing site — landing page and public screens (new)

Everything below is the public, logged-out marketing site (orca.ai or
equivalent) — separate from the product screens above, but same design
system, same monochrome brand mark (see the updated LOGO section and
docs/LOGO_DESIGN_PROMPT.md), and the same non-negotiable honesty
constraint: **no fabricated social proof.** Orca does not yet have named
enterprise customers, published case studies, or a large user base — the
site must not imply otherwise. Where a typical SaaS landing page would put
customer logos or "10,000+ teams trust us," this site substitutes real,
verifiable technical proof instead (the same real eval numbers, the same
real audit artifacts already built this session). This is a deliberate
positioning choice, not a placeholder to fill in later — revisit it only
once real customers exist, not before.

Generate Screens 24-31 as a new Stitch project (or a new page group within
the same project) using the identical Design System Prompt above, with one
addition: marketing surfaces should lean into the "generous whitespace,
centered composition" density rule already defined, more aggressively than
the product screens do — this is a considered site for a technical buyer
doing due diligence, not a scroll-jacking consumer marketing page.

## Screen 24 — Landing page: hero + primary nav

```
Public marketing landing page, hero section, true black background. Top
nav bar: the primary monochrome orca mark + "ORCA" wordmark on the left,
four simple text nav links center-right ("Product," "Trust & Security,"
"Pricing," "Docs"), one filled white button top-right ("Sign in") and one
outlined button next to it ("Get started"). Below the nav, generous
vertical whitespace, then a large centered headline in bold sans-serif,
white text: "The AI platform that shows its work." Below it, one line of
muted-gray subtext: "Every answer traces back to a source. Every
capability claim is measured before it's shown to you." Below that, two
buttons side by side: primary filled white "Start building" and secondary
outlined "See how verification works." Beneath the fold line, a single
static (non-video, non-looping-gimmick) product screenshot-style panel
showing a real chat response with its citation markers and a visible
"Grounded ✓" trust-modal indicator already established in Screen 21 —
this is the one piece of "social proof" the hero uses: showing the actual
mechanism, not a logo wall.
```

## Screen 25 — Landing page: the core differentiator, explained

```
A full-width section directly below the hero, black background, generous
padding. Section eyebrow label in monospace, muted gray, uppercase,
letter-spaced: "WHY ORCA IS DIFFERENT." Large heading below it: "Most AI
answers confidently. Orca checks first." Below the heading, a horizontal
three-panel row (stack vertically on mobile), each panel a thin-bordered
dark card (#080808) with a small monochrome line-icon at top:
  Panel 1 — icon: a magnifying glass over a document. Header "Retrieves
  real sources." Body: "Before answering, Orca pulls from your actual
  documents and data — not just what it was trained on."
  Panel 2 — icon: the waveform/sonar motif from the brand mark itself,
  reused intentionally here as a UI icon to tie the differentiator
  visually to the logo's own concept. Header "Verifies before
  responding." Body: "Every claim is checked against what was retrieved.
  If something isn't supported, you're told — not left to guess."
  Panel 3 — icon: a simple shield outline. Header "Shows the gaps
  honestly." Body: "Capability claims are gated by real, measured
  thresholds — a model tier that hasn't cleared them says so, plainly,
  in the product itself."
Each panel's body text should mirror the real backend behavior already
built (Screens 8, 21) — do not invent capabilities beyond what those
screens describe.
```

## Screen 26 — Landing page: how it works (3-step flow)

```
A full-width section, black background, section eyebrow "HOW IT WORKS."
Heading: "From question to verified answer." A horizontal 3-step flow
(numbered 01/02/03 in monospace, muted gray), connected by a thin
horizontal line with small directional arrows, stacking vertically on
mobile:
  Step 01 — "Ask" — a small mockup of the chat input from Screen 3/7.
  Step 02 — "Orca retrieves & checks" — a small mockup showing the
  citation-marker response mid-stream plus the grounding-check states
  from Screen 21 (Grounded / Partially supported / Not checked) shown as
  a compact legend, not full modal.
  Step 03 — "You get an answer you can verify" — a small mockup of the
  Explain/Trust modal (Screen 8/21) already expanded, showing a real
  example confidence bar and grounding result.
This section functions as a condensed, marketing-friendly version of the
real trust modal already designed — reuse its visual language exactly,
don't redesign the mechanism just for marketing.
```

## Screen 27 — Landing page: model tiers & pricing

```
A full-width pricing section, black background, section eyebrow
"MODEL TIERS." Heading: "Three tiers, honestly labeled." Three pricing
cards side by side (Genesis / Novus / Aeternum, matching Screen 2's model
names and one-line descriptions exactly), each card showing: tier name,
one-line description, a price or "Contact us" (use whichever is actually
decided — do not invent a specific number here if pricing isn't finalized;
placeholder should read "Pricing on request" rather than a fabricated
figure), a short feature list in monospace-style bullet rows, and — for
any tier whose persona-claim gate is not yet fully approved — the SAME
amber "Not yet verified for [specific claim]" disclosure used in Screens
2/23, rendered here at marketing-card scale rather than hidden. A pricing
page is a trust surface too; the same honesty rule applies here as
everywhere else in the product.
```

## Screen 28 — Landing page: trust & security

```
A dedicated "/trust" page, denser layout (per the admin/data density rule
in the design system, since this audience is doing technical diligence).
Heading: "Trust & Security." A grid of small labeled fact-cards, each
showing one real, currently-true statement with a status icon (checkmark
for done, amber dot for in-progress, grey dot for "not yet started" — no
card should ever claim something that isn't real):
  - "SOC 2" — status: in progress / not yet certified (show whichever is
    actually true; never show a checkmark for a certification that
    doesn't exist yet).
  - "Data retention controls" — real, describe actual behavior.
  - "PII handling" — "Flagged, not silently altered" (matches the real
    DLP behavior from Screen 21).
  - "Secrets & credentials" — "Automatically redacted from responses"
    (matches the real DLP behavior).
  - "Dependency security" — "Automated vulnerability scanning on every
    release" (matches the real CI pip-audit gate).
  - "Sandboxed code execution" — "Code and file tools run in a restricted
    sandbox" (matches the real run_python/run_shell/file sandbox work).
Below the grid, a plain-text link to a security disclosure / responsible
disclosure contact. This entire page must only ever contain claims that
are actually true at time of publish — treat it as a legal-adjacent
document, not a marketing copy exercise.
```

## Screen 29 — Landing page: proof section (NOT a customer-logo wall)

```
A full-width section, black background, section eyebrow "PROOF, NOT
PROMISES." Heading: "We publish our own scorecard." Instead of customer
logos or testimonials (deliberately omitted — see brief), show a compact,
real metrics panel styled like a technical scorecard: 3-4 stat tiles in a
row, each with a large monospace number and a small muted-gray label
underneath, e.g. "Judge-scored accuracy," "Grounding check pass rate,"
"Jailbreak block rate" — pull the actual current numbers from the real
eval reports rather than inventing round marketing figures. Beneath the
tiles, one small muted-gray line: "Numbers updated from our own internal
evals — methodology published in our docs." Link out to a real
methodology/docs page. This section should read as refreshingly
un-marketing-like — a company confident enough to show its actual,
unglamorous numbers instead of a wall of fake logos.
```

## Screen 30 — Landing page: FAQ

```
A full-width FAQ section, black background, section eyebrow
"QUESTIONS." A single-column accordion list, each row a question in white
text with a chevron icon, expanding to muted-gray answer text below. Real
question set to include (answers should reflect actual current product
state, not aspirational claims):
  "How is Orca different from other AI assistants?"
  "What happens when Orca isn't confident in an answer?"
  "Is my data used to train your models?"
  "What model tiers are actually available today vs. coming soon?"
  "How do you handle sensitive or personal information in responses?"
  "Is Orca SOC 2 compliant?" — answer here must match whatever the real
  Screen 28 status is, worded plainly (e.g. "Not yet — SOC 2 is on our
  roadmap as we grow; here's our current security posture in the
  meantime" with a link to /trust), never implying certification that
  doesn't exist.
```

## Screen 31 — Landing page: final CTA + footer

```
A full-width closing section, black background, generous padding,
centered composition. Large heading: "See what a verified answer looks
like." One primary filled white button: "Start building." Below it, the
global footer: left side, the small monochrome mark + "ORCA" wordmark and
one muted-gray line of copyright text; center/right, link columns
("Product": Genesis, Novus, Aeternum, Lens — "Company": Trust & Security,
Docs — "Legal": Terms, Privacy, AI Policy). No social-media icon row
unless real, active accounts exist — an empty or placeholder social row
reads worse than no social row at all.
```

