<!--
Business/GTM strategy for turning Orca into a revenue-generating company
whose growth could eventually fund the frontier-roadmap phases in
docs/FRONTIER_ROADMAP.md. Grounded in how real AI application companies
have actually reached large valuations WITHOUT training their own frontier
models — that's not a compromise, it's the realistic and historically
proven path. Revenue funds capability, not the other way around.
-->

# Orca Startup Plan — Revenue First, Frontier Capability Funded By Growth

## 0. The core strategic insight this plan is built on

**Competing with OpenAI/Anthropic/Google on raw model IQ is not a viable
startup strategy — and it's not what the real billion-dollar AI application
companies did.** Look at the actual precedent:

- **Harvey** (legal AI) — reported ~$3B valuation. Doesn't train frontier
  models. Wins on deep legal-workflow integration and enterprise trust.
- **Abridge** (healthcare clinical documentation AI) — reported ~$2.75B
  valuation. Uses a mix of models, wins on healthcare-workflow depth and
  compliance (HIPAA), not model benchmarks.
- **Glean** (enterprise search/AI) — reported ~$4.6B valuation. Wins on
  enterprise data integration and trust, not a proprietary frontier model.
- **Cursor, Perplexity** and similar — built exceptional product experiences
  on top of existing frontier APIs, winning on UX/workflow, not on owning
  the underlying model.

The pattern: **these companies won on vertical depth, workflow integration,
and enterprise trust — not on training a competitor to GPT-4.** That is
the realistic template for Orca, and it happens to line up closely with
what's already built.

## 1. The asset Orca already has that most AI startups don't

This project already has real, working enterprise-trust infrastructure —
not stubs, tested and verified this session:

- Hash-chained, tamper-evident audit log (`orca/audit.py`)
- Signed model cards with automatic capability-claim gating
  (`orca/governance/model_cards.py`) — a real, differentiated
  "AI you can actually audit" story
- Input moderation with verified real jailbreak-pattern coverage
  (`orca/serve/moderation.py`)
- RBAC, 2FA, enterprise team management, Stripe billing already built
- Multi-tier model routing with graceful fallback (`orca/serve/registry.py`)
- Document Q&A/RAG with PII redaction and citation discipline
- Production monitoring, load-tested, with a real incident runbook

**This is, almost by accident, exactly the infrastructure a regulated-industry
enterprise buyer (legal, healthcare, financial services, government
contractors) actually asks about in a security/compliance review** — before
they ever ask "how smart is your model." Most AI wrapper startups have to
build this from scratch after landing their first enterprise deal and
hitting a procurement wall. Orca has it already.

## 2. The real product thesis

**Orca is not "a chatbot." Orca is the governance, audit, and compliance
layer for enterprise AI use — with the option of fully self-hosted,
data-sovereign models for customers who can't send data to any third-party
API at all.**

This means the product can honestly serve customers at two different
capability tiers, both real:

1. **Self-hosted Orca models (Genesis/Novus)** — for customers whose
   requirement is data sovereignty above all (data never leaves their
   infrastructure) — regulated industries, government, defense-adjacent.
   Sell on trust and control, not raw IQ. This is honest: for a customer
   who legally cannot use any cloud API, "a good, audited, self-hosted 8B
   model" beats "no AI at all" or an out-of-compliance workaround.
2. **Bring-your-own-frontier-model mode** — Orca's governance/audit/
   moderation/RBAC layer sits in front of GPT-4/Claude/Gemini via API for
   customers who want frontier capability but need Orca's compliance
   wrapper (audit trail, moderation, access control) around it. This
   monetizes the infrastructure that's ALREADY built, independent of which
   model answers the question — and doesn't require Orca to ever train a
   frontier model to deliver frontier capability to a customer.

Both modes use the exact same billing, admin, audit, and governance stack.
This is a real, buildable, differentiated SaaS thesis, not aspirational.

## 3. Phased plan — revenue stages mapped to what gets funded when

### Stage 1 (0-6 months): Land one vertical wedge, get to first real revenue
**Goal**: $10K-100K MRR, 3-10 real paying pilot customers in ONE regulated
vertical (recommend: legal or financial services mid-market — both have
acute data-sovereignty pain, real budget, and are underserved by frontier
labs who focus on the largest enterprise logos first).

**What to build/do**:
- Pick the vertical. Don't build for "enterprise AI" generically — pick
  legal OR financial services OR healthcare compliance and go deep.
- Add the "bring-your-own-frontier-model" mode to the serving layer (real
  engineering work, buildable now: an adapter in `orca/brain/providers.py`
  alongside the existing Ollama path, routing to OpenAI/Anthropic/Google
  APIs when a customer configures it, with Orca's moderation/audit/RBAC
  layer wrapping every request regardless of backend).
- Start a real compliance certification process (SOC 2 Type I at minimum)
  — this is often the actual gate that unlocks a first enterprise contract,
  more than model quality.
- Direct outbound sales to the chosen vertical — this stage is not
  self-serve signup growth, it's founder-led sales to 10-20 real
  prospects to find the first 3-10 who'll pay.

**What NOT to do yet**: don't spend this stage's limited time/money on
frontier-roadmap Phase 1 training. Revenue and a real customer base come
first — they're what makes Phase 1 fundable, not the reverse.

### Stage 2 (6-18 months): Vertical depth + fundability
**Goal**: $1-5M ARR, a defensible position in the chosen vertical, a
fundable story.

**What to build/do**:
- Deepen vertical-specific workflow integration (e.g., for legal: contract
  review workflows, matter-specific document search; for financial
  services: regulatory-filing-aware document Q&A) — this is the moat
  competitors can't copy quickly, more than model capability.
- Expand compliance certifications (SOC 2 Type II, HIPAA-readiness if
  healthcare, relevant financial regs if fintech/finserv).
- **This is when raising a real seed/Series A ($3-15M) becomes realistic**
  — because a working product with paying enterprise customers and a clear
  vertical wedge de-risks the pitch. Investors fund traction, not model
  benchmarks, at this stage.
- **This is also when Frontier Roadmap Phase 1 (continued pretraining on a
  70B-class open base for Novus) becomes fundable** — using a mix of
  raised capital and recurring revenue. Position: "the trusted enterprise
  AI platform for [vertical] that also runs a genuinely strong, self-hosted
  model" — trust/compliance moat (slow for competitors to replicate) PLUS
  real model competence (Phase 1 quality bar from the frontier roadmap).

### Stage 3 (18-36 months): Scale
**Goal**: $10-30M+ ARR, expansion into 2-3 verticals or broader mid-market.

- Series B territory ($15-50M) becomes realistic with Stage 2 traction.
- **Frontier Roadmap Phase 2 (100-400B+ model, Aeternum's real target)
  becomes fundable here** — by this point revenue and prior fundraising
  rounds can support the $5-50M compute/team investment Phase 2 actually
  requires.

### Stage 4 (3-5+ years): Real scale outcomes
With $20-100M+ ARR and a defensible multi-vertical or platform position,
a "billion dollar" outcome (continued growth to IPO, or strategic
acquisition by a larger platform/cloud player) becomes genuinely plausible
— not guaranteed (most startups don't reach this, regardless of strategy),
but grounded in a real, executed path rather than a hope that training
harder produces it.

## 4. Honest risks and the one thing not to skip

- **Most startups, in any strategy, don't reach billion-dollar outcomes.**
  This plan describes the path that has actual precedent for AI
  application companies — it doesn't guarantee the outcome.
- **The temptation to skip straight to "train a bigger model" instead of
  landing real customers is the most common failure mode** for
  technically-founded AI startups — building is more comfortable than
  selling, but revenue is what makes every later phase (including the
  frontier-roadmap phases) actually fundable. Sales and vertical depth are
  the unglamorous, necessary Stage 1-2 work.
- **Pick one vertical and go deep before going broad.** Serving "everyone"
  with generic enterprise AI competes directly with well-funded frontier
  labs' own enterprise offerings. Serving one regulated vertical
  exceptionally well, with compliance and workflow depth they haven't
  prioritized, is the actual open lane.

## 5. Concrete next step

The first buildable, revenue-relevant engineering task from this plan —
not more model training — is the **bring-your-own-frontier-model backend**
described in Stage 1: letting `orca/brain/providers.py` route to an
external frontier API (OpenAI/Anthropic/Google) behind the existing
governance/audit/moderation/RBAC layer, so the product can honestly offer
frontier capability to customers who want it today, while self-hosted
Genesis/Novus serve the data-sovereignty segment. This is real, scoped,
buildable work — say the word and I'll start on it.
