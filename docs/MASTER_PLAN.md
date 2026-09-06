<!--
CEO-level synthesis of everything built and learned across this project:
model tiers (Genesis/Novus/Aeternum), the multi-backend/frontier-passthrough
layer, production hardening, and the two standing strategy docs
(FRONTIER_ROADMAP.md, STARTUP_PLAN.md). This is the sequencing plan that
ties them together — what to do first, second, third, and why.
-->

# Orca Master Plan

## Where we actually stand today (facts, not aspiration)

**Built and verified:**
- Three-tier model architecture (Genesis/nano, Novus/core, Aeternum/ultra)
  with two self-hosted fine-tunes actually trained, evaluated, and
  red-teamed (nano v4, core v2) — real numbers, not claims.
- A real governance stack: hash-chained audit log, signed model cards with
  automatic capability-claim gating, RBAC, 2FA, Stripe billing, enterprise
  team management.
- A jailbreak-detection fix at the moderation layer that blocks 9/10 real
  adversarial probes — found and fixed after two separate model
  fine-tuning attempts failed to teach the model itself to refuse.
- Production monitoring, a real load test that found and fixed two
  serious bugs (a model-resolution bug that broke 100% of chat requests,
  a memory-storage bug that crashed every request after generation), and
  an incident runbook.
- A multi-backend layer (`orca/brain/backends.py`,
  `orca/serve/registry.py`) letting any tier route to self-hosted Ollama
  OR a frontier API (OpenAI/Anthropic), with a code-enforced
  data-sovereignty lock — live-tested end-to-end with a real (now revoked)
  OpenAI key. The pipeline works; the account just needed billing enabled
  to get a live generation through, which is expected and fine.

**Honestly not solved:**
- Nano and core both still show 0% raw jailbreak resistance at the model
  level (mitigated by moderation, not the model itself).
- Neither self-hosted tier has ever beaten its own zero-shot baseline on
  its own eval — four separate fine-tuning attempts on nano all landed
  below it.
- Ultra doesn't exist yet — zero distillation, zero fine-tuning, and it
  needs a paid GPU tier to ever start (see FRONTIER_ROADMAP.md Phase 2).
- No real customer has ever used this. Zero revenue. Zero validated
  vertical.

**The two standing strategic documents this plan sequences:**
- `docs/FRONTIER_ROADMAP.md` — what it actually costs (compute, data,
  team, time) to reach genuine frontier-class capability, phased.
- `docs/STARTUP_PLAN.md` — the revenue-first path, built on the real
  precedent that AI application companies (Harvey, Abridge, Glean) reach
  large valuations on vertical trust/workflow depth, not on training a
  frontier model.

## The sequencing plan

### Phase 0 — Now through 2 weeks: STOP building blind, START validating
This is the single highest-leverage thing outstanding, and it is not an
engineering task:

1. **Pick one vertical.** This is a decision only you can make — it
   depends on your network, industry knowledge, and where you can
   actually get a first conversation. My recommendation stands: legal or
   financial services, both have acute data-sovereignty pain and real
   budget, and both map directly onto the compliance/audit infrastructure
   already built. But the choice has to be yours.
2. **Get 5-10 real conversations with real potential customers in that
   vertical THIS WEEK** — before the product is "done." The question to
   validate: does "self-hosted AI with a real audit trail, or frontier
   capability with our compliance wrapper around it" solve a problem they
   actually have budget for? I cannot have these conversations for you.
3. **Stop spending engineering time chasing model-quality gains on free-tier
   GPUs.** Weeks were spent this project trying to beat nano's own
   baseline via fine-tuning, with no version yet beating it. That
   engineering time is better spent on Phase 1 below, in parallel with
   step 1-2, not sequentially after.

### Phase 1 — Weeks 2-8: make the demo honest and complete
Runs in parallel with Phase 0's customer conversations, not after them.

4. **Extend the frontier-passthrough path to real tool-use for OpenAI
   specifically** (lowest-risk provider to start with — native function-
   calling maps cleanly). Right now frontier passthrough is single-turn
   only, honestly scoped that way — closing this gap makes the "bring
   your own frontier model" demo feature-complete, not just architecturally
   sound.
5. **Surface the audit trail / model card / moderation verdict in the UI**,
   not just the API. A compliance buyer needs to *see* "this response
   never left your infrastructure" or "this was routed to OpenAI, here's
   the log," not be told it happens.
6. **Start SOC 2 Type I now.** It takes months and is very often the actual
   gate to a first enterprise contract — starting it in parallel with
   sales conversations, not after signing the first customer, saves real
   calendar time later.
7. **Define real pricing/packaging**: self-hosted-only tier, hybrid tier,
   usage-based frontier-passthrough add-on (the token/cost tracking
   already built in `orca/serve/metrics.py` and `orca/brain/backends.py`
   feeds directly into this).

### Phase 2 — Months 2-6: first revenue
8. Convert Phase 0's conversations into 3-10 real paying pilots.
   `docs/STARTUP_PLAN.md` Stage 1's target: $10-100K MRR.
9. Let real customer feedback drive priorities from here — most likely
   that means deepening vertical workflow integration, not chasing more
   model-quality percentage points. The startup plan's core thesis (trust
   and workflow depth over raw IQ) is what actually gets tested here.
10. Continue model-quality work only opportunistically, bounded, in the
    background — not as the main engineering focus. If a clean win shows
    up (e.g., a properly-scoped DPO retry with a gentler config), take it;
    don't restructure the roadmap around chasing it.

### Phase 3 — Months 6-18: fundability and Novus's real capability jump
11. With initial revenue and a proven vertical, raise seed/Series A
    ($3-15M) — `docs/STARTUP_PLAN.md` Stage 2. Investors fund traction at
    this stage, not model benchmarks.
12. Use part of that capital for `docs/FRONTIER_ROADMAP.md` Phase 1:
    continued pretraining of Novus on a real 70B-class open base
    ($50K-$500K compute, a small dedicated team, 2-4 months). This is the
    point where "beats its own baseline" becomes a realistically solvable
    problem — QLoRA-on-free-GPU was never going to reliably clear that bar,
    and four attempts already confirmed it.
13. Expand compliance certs (SOC 2 Type II, HIPAA/finserv-specific as the
    vertical demands).

### Phase 4 — 18+ months: scale
14. Series B territory with Stage 2 traction, funding
    `docs/FRONTIER_ROADMAP.md` Phase 2 for Aeternum if the business
    metrics support it.
15. Multi-vertical expansion or a broader platform position. A real,
    non-guaranteed shot at the outcomes `docs/STARTUP_PLAN.md` describes —
    grounded in an executed path, not a hope that more training runs
    would have gotten there faster.

## Decisions that are yours, not mine, right now

- **The vertical.** I can help you think it through, but the choice and
  the first outreach have to come from you.
- **Whether to fund OpenAI billing** to complete a live successful
  frontier-passthrough generation test, versus treating the already-proven
  pipeline (real key, real request, real error correctly surfaced) as
  sufficient validation for now.
- **How much further engineering time goes into nano/core model-quality
  chasing** versus fully redirecting to Phase 1 (demo completeness) and
  Phase 0 (customer conversations) above. My recommendation is: redirect
  fully, now — the marginal return on more free-tier fine-tuning attempts
  has been at or below zero for weeks.
