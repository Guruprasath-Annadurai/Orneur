<!--
The single, consolidated final plan — supersedes nothing else (the other
docs remain the detailed backing material) but is THE plan to work from.
Ties together docs/MASTER_PLAN.md, docs/STARTUP_PLAN.md,
docs/FRONTIER_ROADMAP.md, and docs/PERPLEXITY_DIFFERENTIATION_PLAN.md into
one sequence, with one honest current-state statement and one answer to
"what do we work on now."
-->

# Orca — Final Plan

## Honest one-line statement of where we are

Orca is a working three-tier AI platform with real self-hosted fine-tunes
(Genesis/nano, Novus/core), a real multi-backend architecture (self-hosted
+ frontier passthrough), real production hardening, and real governance
infrastructure — but zero paying customers, zero live users, and no model
that has yet beaten its own pre-fine-tune baseline. Calling it an
"enterprise-level LLM" today would be false. Calling it a **startup with a
real, working product and a credible path to enterprise-level trust** is
true, and is what this plan builds toward, honestly, in stages.

There is no shortcut that makes this an "official" enterprise/investor-ready
company without doing three non-engineering things: getting real customer
conversations, proving cost/trust differentiation in production, and
raising capital against real traction. No amount of additional solo
fine-tuning changes that. This plan sequences engineering AROUND those three
things, not instead of them.

---

## What actually makes an LLM company "official" — the four gates

Investors and enterprise buyers judge four things, in this order of what
they check first:

1. **Does it work, reliably, in production?** (uptime, monitoring, incident
   response, no launch-blocking bugs)
2. **Can I trust it with my data and my compliance requirements?** (audit
   trail, data sovereignty, security posture, SOC 2)
3. **Does it solve a real, budgeted problem for a real customer, better or
   cheaper than the alternative?** (not raw model IQ — workflow + trust +
   cost)
4. **Is there a business model and early traction?** (revenue, retention,
   pricing, a fundable narrative)

Gate 1 is done. Gate 2 is partially done (audit trail/model cards/RBAC
exist; SOC 2 hasn't started). Gates 3 and 4 have not started — this is the
real gap, and it's not a coding gap.

---

## The plan — four phases, in order

### Phase 1 (now → 4-6 weeks): make the product demoable and trustworthy, get first real conversations

Run these in parallel, not sequentially:

**Business (the actual bottleneck — starts today, not after engineering):**
- Pick one vertical (legal or financial services recommended — acute
  data-sovereignty pain, real budget, maps directly onto the audit/RBAC
  infrastructure already built). This decision is yours.
- Get 5-10 real conversations with real potential customers in that
  vertical this week, before the product is "finished." Validate: does
  "self-hosted AI with a real audit trail, or frontier capability wrapped
  in our compliance layer" solve a problem they have budget for?
- Start SOC 2 Type I now — it gates enterprise contracts and takes months,
  so starting in parallel with sales conversations saves real calendar
  time later.

**Engineering (in parallel, not before the above):**
- Surface the audit trail / model card / moderation verdict / backend
  identity + cost in the UI — a buyer needs to *see* trust, not be told
  about it in an API field.
- Finish frontier-passthrough tool-use for OpenAI (closes the one honestly
  scoped gap in the multi-backend architecture).
- Define real pricing/packaging: self-hosted-only tier, hybrid tier,
  usage-based frontier-passthrough add-on — the cost/token tracking
  already built feeds this directly.
- Ship the consumer-facing differentiation work from
  `docs/PERPLEXITY_DIFFERENTIATION_PLAN.md`: live web-search grounding with
  enforced citations, cost-aware routing between self-hosted and frontier
  backends, and a visible trust panel. This is what makes Genesis a
  credible, demoable product on its own — not a claim of superior
  intelligence, but a real, provable cost/transparency advantage.
- Deprioritize further broad fine-tuning attempts to beat nano/core's own
  baseline — four attempts already established that free-tier QLoRA isn't
  going to clear that bar. That capital (engineering time) is better spent
  above. (A narrowly-scoped coding-domain fine-tune is the one exception
  worth a bounded, opportunistic attempt, since nano's coding eval scores
  are already its strongest real result.)

**Phase 1 exit criteria**: a demoable product with visible trust features,
defined pricing, SOC 2 in progress, and at least 5 real customer
conversations completed.

### Phase 2 (months 2-6): first revenue

- Convert Phase 1's conversations into 3-10 real paying pilots. Target:
  $10-100K MRR (`docs/STARTUP_PLAN.md` Stage 1).
- Let real customer feedback drive priorities from here — most likely
  deepening vertical workflow integration, not chasing more model-quality
  percentage points.
- Continue model-quality work only opportunistically and boundedly in the
  background.

**Phase 2 exit criteria**: signed paying customers, real usage data, a
retained cohort — the actual proof point investors and future enterprise
buyers both check first.

### Phase 3 (months 6-18): fundability and Novus's real capability jump

- With initial revenue and a proven vertical, raise seed/Series A ($3-15M)
  — investors fund traction at this stage, not model benchmarks.
- Use part of that capital for `docs/FRONTIER_ROADMAP.md` Phase 1:
  continued pretraining of Novus on a real 70B-class open base
  ($50K-$500K compute, small dedicated team, 2-4 months). This is the point
  where "beats its own baseline" becomes realistically solvable —
  QLoRA-on-free-GPU was never going to reliably clear that bar, and four
  attempts already confirmed it.
- Expand compliance certs (SOC 2 Type II, HIPAA/finserv-specific as the
  vertical demands).

**Phase 3 exit criteria**: funded, a real capability jump underway, deeper
compliance posture.

### Phase 4 (18+ months): scale, global reach, monetization at scale

- Series B territory with Stage 2 traction, funding
  `docs/FRONTIER_ROADMAP.md` Phase 2 for Aeternum if the business metrics
  support it.
- Multi-vertical expansion, and — only once there's proven demand and
  capital to match — international/global-market expansion (localization,
  regional data-residency compliance, regional pricing). Going global
  before Phase 2 revenue is proven would repeat the same mistake as
  claiming enterprise-readiness before it's earned: real, but premature.
- This is a real, non-guaranteed shot at the billion-dollar outcomes
  `docs/STARTUP_PLAN.md` describes — grounded in an executed path, not a
  hope that more training runs would have gotten there faster.

---

## What we work on right now, starting today

In order, this week:

1. **You**: pick the vertical, start outreach for 5-10 real conversations.
2. **Engineering**: wire the audit trail/model card/cost/backend-identity
   into the UI (highest-leverage, fastest-to-ship trust feature).
3. **Engineering**: begin the live web-search-grounding + citation pipeline
   (the core product differentiator that's currently missing entirely).
4. **You + Legal**: start the SOC 2 Type I process.
5. **Engineering**: define and implement real pricing tiers using the
   existing cost/metrics infrastructure.

Everything else in this plan follows from what's learned doing those five
things — not from more solo engineering guesses about what investors or
enterprise buyers want.

## The three decisions only you can make, restated

- **The vertical** — the single highest-leverage decision outstanding.
- **How much further engineering time goes into nano/core capability
  chasing** versus fully redirecting to the trust/demo/pricing work above.
  Recommendation: redirect fully, now.
- **When to start spending real money** — cloud GPU hosting, search API
  costs, SOC 2 audit fees — all of which are genuine, justified spends only
  once Phase 1's customer conversations validate demand, not before.

---

## Addendum: reality-checking the "Perplexity attack surface" playbook

A detailed competitive playbook was proposed, built around real, accurate
Perplexity user pain points (stale answers, citation fabrication, no real
agentic execution, no memory, weak multimodal, no proactivity, opacity
about data use). The pain-point map is legitimate and worth keeping. Two
parts of the proposed execution were not: swapping the core model to a
550B-class model (`nemotron-3-ultra-550b-a55b`), and a months-2-to-4
timeline for a fully working autonomous agent that scrapes dozens of sites
and produces finished reports. Both require infra, GPU budget, and
engineering headcount this project doesn't have as a solo, unfunded effort
— that tier of model needs real multi-GPU serving cost, and a reliable
agent loop with sandboxed code execution is a genuine multi-month build
even for a funded team, not a bolt-on to the existing single-turn
frontier-passthrough path.

**Realistically re-scoped, folded into the phases above:**

- **Citation fabrication + staleness (Perplexity's #1 and #2 complaints)**
  — this is exactly Phase 1's web-search-grounding + citation work above.
  No new phase needed; it's already the top engineering priority.
- **"No real agentic execution" (#3)** — real, and the honest gap Novus has
  today (frontier passthrough is single-turn only). Building a genuine
  agent loop (planning, tool use, code execution) is real Phase 2/3 work,
  gated on Phase 1 revenue funding the engineering time and any sandboxed
  code-execution costs (e.g., E2B) — not a pre-revenue solo sprint.
- **Memory/personalization (#4)** — a legitimate stickiness feature once
  there's a working core product and real users generating the data worth
  remembering; belongs after Phase 2 traction, not before it.
- **Multimodal (#5), proactivity (#6), radical transparency (#7)** — the
  transparency piece is already covered (audit trail, model cards, cost
  disclosure); the other two are real feature bets for Phase 2+ once
  there's a user base to build them for.
- **Freemium/Pro pricing, referral program, closed power-user beta launch
  sequence** — realistic and worth adopting as-is for Phase 1/2's go-to-market,
  once Phase 1's customer-conversation validation confirms the vertical
  and pricing.

**The corrected version of the core message**: the pain-point analysis is a
genuinely useful lens for prioritizing what Phase 1's citation/freshness
work and later agent work should target — but the timeline and resourcing
have to match what a pre-revenue, solo-built project can actually execute,
not what a funded team could. Claiming the 550B-model, agent-in-months
version of this plan as achievable now would repeat the exact mistake this
whole project has been careful to avoid: promising capability before it's
built.
