<!--
The concrete, engineering-ordered phase-by-phase build roadmap for Orca as
an answer-engine-category product (Genesis + Novus + Lens) — same category
as Perplexity (search-grounded AI answers), explicitly not a clone: the
differentiation is cost transparency, code-enforced citation discipline,
self-hosted/frontier hybrid routing, and vertical trust, not a copy of
their UI or feature list. Documentation and certification are placed last,
deliberately — they formalize what's already built and proven, they don't
lead it. Builds on and sequences the technical work already scoped in
docs/PERPLEXITY_DIFFERENTIATION_PLAN.md and docs/LAUNCH_PLAN.md.
-->

# Orca Development Roadmap — Phase by Phase

**Category, stated honestly**: an AI answer engine, the same category as
Perplexity — not a clone of it. The differentiation is architectural, not
cosmetic: cost-aware hybrid routing (self-hosted models by default,
frontier passthrough only when needed), citations enforced in code rather
than asserted, and a real audit trail — not a different color scheme on
the same product.

---

## Phase 1 — Core model foundation (in progress)

The two self-hosted tiers that anchor everything else.

1. Finish cross-tier regression + blind A/B testing between nano v4 and
   core v2 (task already underway).
2. Generate and sign real model cards for both, gated by the existing
   persona-claim mechanism (`orca/governance/model_cards.py`) — no
   capability claim ships that the numbers don't support.
3. Deploy both tiers to a stable production Ollama backend (not local dev)
   — this is the prerequisite every later phase's testing depends on.

**Exit**: nano and core running in a real production environment, with
signed model cards reflecting their actual, current, tested capability.

## Phase 2 — Live web-search grounding (the core Perplexity-category capability)

This is the single biggest capability gap between "chatbot" and "answer
engine," and doesn't exist yet.

1. Integrate a real-time search API (Brave/Bing/Serper-class provider).
2. Extend the existing document-citation discipline
   (`orca/docs/citation_check.py`) to live search results — same enforced
   inline-citation pattern, new source type.
3. Build the search-content sanitization pass (a new attack surface —
   indirect prompt injection via scraped web content — has to be handled
   here, not bolted on later).
4. Ship the citation UI (numbered inline references, source popovers) from
   the Stitch design set (`docs/STITCH_DESIGN_PROMPT.md`, Screen 9).

**Exit**: a chat answer can cite live web sources with enforced,
verifiable citation discipline — the actual mechanism behind "no
hallucination," not a training claim.

## Phase 3 — Cost-aware multi-backend routing

The real, measurable cost-differentiation mechanism — without this, Orca
is exactly as expensive as any frontier-API-per-query competitor.

1. Build the query-routing classifier (self-hosted vs. frontier
   passthrough, by query complexity/type).
2. Wire routing into `orca/serve/registry.py`'s existing
   `resolve_tier_backend()` path.
3. Add semantic response caching for repeated/overlapping queries.
4. Extend per-request cost/backend metrics so the cost-advantage claim is
   measured in production, not estimated.

**Exit**: most queries answered by near-zero-marginal-cost self-hosted
models, frontier passthrough reserved for queries that need it, and the
cost delta actually measured and provable.

## Phase 4 — Trust & transparency UI

Makes Phases 1-3's backend guarantees visible, not just true.

1. Ship the per-answer trust panel (model/backend identity, cost, whether
   data left the user's infrastructure) — Stitch Screen 7/8.
2. Surface the audit trail, model cards, and moderation verdicts in a real
   UI, not API-only (Stitch Screen 14 — the admin/governance dashboard).
3. Ship 2FA setup/challenge, knowledge graph explorer, vision-attach UI —
   the remaining backend-exists/no-frontend gaps already identified.

**Exit**: every trust claim the product makes is something a user or
buyer can actually see, not just read about.

## Phase 5 — Orca Lens integration

Media generation, brought in under its own stricter gate given its
distinct legal/moderation risk profile.

1. Content moderation pipeline for generated media (CSAM, deepfake/likeness,
   copyright-flagged content detection).
2. Watermarking/content-provenance metadata on all generated output.
3. Ship the Lens studio/result/gallery UI (Stitch Screens 16-20).
4. Dedicated legal review of Lens's ToS/AUP sections — separate from the
   general product's review, given the distinct exposure.

**Exit**: Lens launches with moderation and provenance built in from day
one, not retrofitted after an incident.

## Phase 6 — Real agentic capability (Novus "deep work")

The honest current gap: Novus's frontier passthrough is single-turn only.
This is a genuine multi-month build, scoped realistically, not
compressed into a marketing timeline.

1. Finish tool-use/function-calling parity for the frontier-passthrough
   path (OpenAI first — cleanest native support).
2. Build a real, bounded agent loop for self-hosted Novus: planning,
   tool use, sandboxed code execution — start with 2-3 reliable template
   tasks, not open-ended autonomy.
3. Gate any further agent-loop investment on Phase 2/3's revenue —
   sandboxed execution has real per-session cost that needs to be funded
   by actual usage, not built speculatively.

**Exit**: Novus can reliably complete a small, well-defined set of
multi-step tasks end-to-end — proven, not promised.

## Phase 7 — Memory & personalization

A real stickiness feature, sequenced after there's a working core product
and real usage data worth remembering — not before.

1. Persistent user context across sessions (building on the existing
   `orca/brain/memory.py` long-term memory engine).
2. Opt-in, disclosed, and deletable — ties directly into the existing
   right-to-delete flow and the Data & Privacy settings screen.

**Exit**: returning users get answers that improve from real prior context,
with full user control over what's remembered.

## Phase 8 — Enterprise features

Ties into the vertical GTM strategy — SSO, team workspaces, admin
controls, and data-residency options, built on the RBAC/audit
infrastructure already shipped.

**Exit**: first enterprise pilot(s) can actually onboard a team, not just
an individual user.

## Phase 9 — Closed beta

Real, unscripted usage testing per `docs/LAUNCH_PLAN.md` Phase 1 — 100-500
invited users, weekly triage, no new features added during this phase,
only fixes to what real usage surfaces.

## Phase 10 — Public launch

Open signups, freemium pricing, honest marketing built only on claims the
beta actually verified, real support/on-call in place.

---

## Phase 11 (last, deliberately) — Documentation & Certification

Documentation and certification come last because they formalize and
prove what's already built and tested — they don't substitute for it.
Certifying or documenting a capability before Phases 1-10 prove it real
would be the exact overclaiming this whole project has worked to avoid.

1. Finalize public API documentation and developer docs.
2. Complete SOC 2 Type I (started earlier, in parallel with sales
   conversations per `docs/FINAL_PLAN.md`, but the certificate itself
   lands here, once the controls it attests to are actually in production).
3. Publish public model cards, the AI policy, and the transparency/trust
   documentation as user-facing pages, not just internal governance
   artifacts.
4. Expand certifications as verticals demand (SOC 2 Type II, HIPAA/finserv
   specific) once there are real enterprise customers requiring them.

**Exit**: every certification and every public document reflects a
capability that Phases 1-10 already built, tested, and proved — nothing
certified ahead of the work.
