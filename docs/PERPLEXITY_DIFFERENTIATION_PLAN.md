<!--
Founding-team plan for a real, honest differentiation strategy against
Perplexity — written from each functional role's perspective, synthesized
by the CEO. The core insight this plan is built on: Orca cannot currently
out-intelligence Perplexity's underlying frontier models, but it CAN
genuinely win on cost (near-zero marginal cost self-hosted inference vs.
per-token frontier API costs), verifiable grounding (citations + audit
trail as a real, code-enforced feature, not a marketing claim), and
specialization (coding, business). The single biggest missing piece to
make any of that real is live web-search grounding — Orca currently has
citation discipline for UPLOADED documents only, nothing for live chat.
-->

# Orca vs. Perplexity — Founding Team Differentiation Plan

## CEO framing, up front, honestly

Before any role's plan below: **we cannot claim Orca is "smarter" than
Perplexity today, and we will not market it that way.** Perplexity's
answers are backed by frontier models (GPT-4/Claude-class) with a mature
search index. Genesis and Novus are 7-8B self-hosted fine-tunes that
haven't yet beaten their own zero-shot baselines. Claiming raw superiority
would be false, and it would be discovered the first time a user runs a
hard query through both products.

**What we can honestly claim, and what this plan builds toward:**
1. **Cost** — Perplexity pays a real per-token frontier-API cost on every
   query. Orca can route most queries through near-zero-marginal-cost
   self-hosted models, reserving frontier-API cost only for queries that
   genuinely need it. This is a real, measurable, defensible cost
   advantage — if we build the routing layer to make it true.
2. **Verifiable grounding** — "no hallucination" is not a training claim,
   it's a retrieval-and-citation-discipline claim. Orca has zero live
   web-search grounding today (only document-upload RAG). This is the
   single most important gap this plan closes.
3. **Transparency as a feature** — the audit trail, model card, and
   moderation verdict already built can be surfaced per-answer as a trust
   feature Perplexity doesn't offer: "here's exactly which model answered,
   what it cost, and whether your data left our infrastructure."
4. **Specialization** — coding and business-domain expertise, not
   generalist search supremacy.

**The honest risk to name out loud**: consumer AI search is an extremely
capital-intensive, crowded category. Perplexity itself has raised very
large venture rounds and is still establishing durable profitability.
Going head-to-head there as Orca's PRIMARY bet, without comparable capital,
is risky. This plan treats the consumer product as a brand-awareness and
data-flywheel play that feeds the enterprise vertical strategy
(`docs/STARTUP_PLAN.md`), not as a replacement for it.

---

## Founding AI/ML Engineer

**Priority 1 — cost-aware query routing.** Build a lightweight classifier
(can start as a cheap heuristic: query length, question type, presence of
"today/current/latest/price/score" time-sensitive keywords) that decides,
per query: does this need live web grounding + possibly frontier-model
reasoning, or can self-hosted Genesis/Novus answer directly? This is the
actual mechanism behind the "cheaper than Perplexity" claim — without it,
we're just as expensive as they are.

**Priority 2 — retrieval-grounded generation for live chat**, extending
`orca/docs/citation_check.py`'s existing citation-discipline pattern
(currently only wired for uploaded documents) to live web search results.
Same inline `[D1]`/`[S1]`-style citation enforcement, new source: search
results instead of uploaded docs.

**Priority 3 (secondary, opportunistic)** — a genuinely scoped attempt at
improving coding-domain fine-tuning specifically, since nano's existing
eval scores are already relatively strong there (0.6-1.0 range) — a real,
narrower, more winnable differentiation than generalist capability.

**Explicitly deprioritized**: more broad attempts to beat nano/core's
overall eval baseline via free-tier fine-tuning. Four attempts already
established a real ceiling; further attempts belong in Phase 3 of
`docs/FRONTIER_ROADMAP.md`, funded properly, not squeezed in here.

## Founding Backend/Infrastructure Engineer

Builds on the multi-backend layer already shipped
(`orca/brain/backends.py`, `orca/serve/registry.py`). Next:

- The actual routing decision logic from AI/ML Engineer's Priority 1 needs
  a home in the serving layer — likely a new lightweight decision function
  called before `_resolve_backend_for_chat`, not a model-level change.
- **Semantic response caching** for repeated/similar queries — a large,
  underrated cost lever for a search-style product where many users ask
  overlapping questions. Real engineering: embedding-based cache lookup
  before hitting any backend at all.
- Finish tool-use parity for the OpenAI frontier-passthrough path (current
  gap, documented honestly in `orca/serve/api.py`'s
  `_generate_via_frontier_backend`) — needed before web-search grounding
  can route through a frontier backend with tool-calling.
- Per-query cost/backend metrics (`orca/serve/metrics.py` already tracks
  backend identity and cost — extend to a per-request-type breakdown) so
  the "we're cheaper" claim can be measured and proven, not asserted.

## Founding Frontend/UX Engineer

- Real-time citation display: inline numbered references linking to
  actual source snippets, Perplexity-style — this is table stakes for the
  grounding claim to feel real to a user, not a backend implementation
  detail.
- A visible, per-answer trust panel: which model answered (self-hosted
  Genesis/Novus, or frontier passthrough), estimated cost, whether data
  left the user's infrastructure — making the differentiators from the
  CEO framing literally visible on every response, not buried in an API
  field only developers see.
- Fast, clean, mobile-responsive chat UI as the baseline — no native app
  work until Mobile Engineer's gate below is cleared.

## Product Designer

- The consumer onboarding narrative must be radically simpler than the
  enterprise governance-heavy story in `docs/STARTUP_PLAN.md` — these are
  different products for different audiences, and mixing the pitches
  weakens both. Consumer framing: "grounded answers, real citations, a
  private option, at a fraction of the cost" — not compliance jargon.
- Design the "why trust this answer" expandable panel so the audit
  trail/model card data (already built on the backend) is legible to a
  non-technical consumer, not just an enterprise compliance officer.
- First-run onboarding should demonstrate the differentiation immediately
  — e.g., a side-by-side of the same query's cost/latency/citation
  quality, not an explainer wall of text.

## Search & Crawling Engineer

**Realistic scope, stated honestly**: building an original web crawler and
search index from scratch is a multi-year, capital-intensive
infrastructure project — not something to attempt at this stage. The
right move is **integrating an existing real-time search API** (Brave
Search API, Bing Search API, or Serper/You.com-style providers) for live
results, then building Orca's own retrieval-synthesis-citation layer on
top of those results. This is genuinely buildable now.

**Honest cost note for the "cheaper than Perplexity" claim**: search APIs
have their own real per-query cost too — smaller than a frontier-LLM call,
but not zero. The actual cost advantage comes from replacing
*frontier-LLM-per-query* with *self-hosted-LLM + cheap-search-API-per-query*
for the majority of traffic, not from search being free.

## Data Engineer

- Build the real-usage feedback loop (once there are real users, with
  proper consent): identify query categories where self-hosted models
  underperform against frontier passthrough, feed those into future
  distillation batches. This is a genuine long-term data moat that
  free-tier synthetic distillation alone can't produce — but it only
  starts working once there's real traffic, which depends on Phase 0 of
  `docs/MASTER_PLAN.md` actually landing customers/users first.
- Own the search-result caching store design (feeds Backend Engineer's
  semantic caching work) and the citation-corpus data model.

## DevOps/Platform Engineer

- Current hosting (local Mac + Ollama) is fine for validation, not for
  real consumer traffic. Real cloud GPU hosting for self-hosted inference
  is a genuine spend decision — sequence this AFTER there's real usage
  data justifying it, not before.
- Stand up a real CI/CD pipeline and staging environment now, cheaply,
  regardless of hosting decision timing.
- Build the cost-per-query dashboard that makes the "cheaper than
  Perplexity" claim measurable in production, not just estimated.

## AI Safety & Alignment Researcher

- The existing moderation-layer jailbreak mitigation (9/10 real probes
  blocked, see `orca/serve/moderation.py`) stays the honest interim answer
  for raw-model jailbreak resistance (still 0% at the model level after
  two fine-tuning attempts).
- **New, genuinely important risk this plan introduces**: live web-search
  grounding creates a new attack surface — indirect prompt injection via
  malicious web page content that gets pulled into context. This needs its
  own moderation/sanitization pass on retrieved search content BEFORE it
  reaches the model, not an afterthought once search grounding ships.

## Mobile Engineer

- No native app work until the web product has validated real usage and
  retention. Sequencing native development before product-market fit is a
  common, avoidable waste of scarce engineering time. Mobile-responsive
  web first; native only once justified by real data.

## QA Engineer

- Extend the existing test discipline (201 tests, real load-testing that
  found 2 production bugs this session) to the new surfaces: a
  hallucination/citation-accuracy eval harness specifically for the
  search-grounding feature (checking that citations actually support the
  claims made, not just that citations are present), and adversarial
  testing for the new indirect-prompt-injection surface the Safety
  Researcher flagged.
- Regression suite must run on every model swap AND every search-provider
  API change (a Bing/Brave API update changing result formats is a real
  risk to the citation pipeline).

## Growth/Marketing Lead

- **Honest positioning, not hype**: "as good for everyday use, meaningfully
  cheaper, with a fully private self-hosted option, transparent about
  sources and limits" — not "smarter than Perplexity," which isn't true
  yet and would be disproven on first hard use.
- The consumer product (Genesis, free/cheap tier) is a brand-awareness and
  data-flywheel play, not the primary revenue bet — the enterprise
  vertical GTM in `docs/STARTUP_PLAN.md` remains the primary path to
  revenue, because competing head-on in capital-intensive consumer AI
  search against a well-funded incumbent is a real risk without comparable
  capital.

## Legal Counsel

- Web search grounding introduces real copyright/fair-use exposure around
  how search results and content snippets are retrieved, cached, and
  displayed — needs review before shipping, same category of concern
  already flagged for Orca Lens's Seedance/MPA precedent.
- Search API providers (Bing/Brave/etc.) typically have their own terms of
  service restricting caching/redistribution of results — review before
  Backend Engineer's semantic caching work ships, not after.
- Logging real user queries for the Data Engineer's feedback loop needs an
  updated privacy policy and explicit consent flow — `legal/PRIVACY_POLICY.md`
  needs a real update here, not a silent scope change to what's already
  disclosed.

---

## CEO synthesis and the actual next move

Bringing all of the above together, the real differentiation thesis is:
**live web-search grounding with enforced citations + cost-aware routing
between self-hosted and frontier backends + radically honest positioning**
— not a claim of superior intelligence. The single most important
currently-missing technical piece is the search-grounding pipeline; the
single most important currently-missing business piece (per
`docs/MASTER_PLAN.md`, still true) is real customer/user validation before
more building.

**Concrete next 4-6 week sprint, if we proceed:**
1. Search & Crawling Engineer + AI/ML Engineer pair on the live-search
   retrieval + citation pipeline — the core missing differentiator.
2. Backend Engineer builds the cost-aware routing layer in parallel.
3. Frontend/Product Designer build the visible trust UI (citations, cost,
   backend-identity panel) in parallel.
4. Safety Researcher builds the search-content sanitization pass before
   any of the above ships to real users.
5. Growth Lead drafts the honest positioning; Legal reviews search-API ToS
   and updates the privacy policy for query logging, before launch, not
   after.

This does not replace `docs/MASTER_PLAN.md`'s Phase 0 (pick a vertical, get
real conversations) — it runs alongside it. The consumer differentiation
work above is what makes Genesis a credible, demoable product; the
enterprise vertical work is what actually pays the bills while Novus and
Aeternum's real capability jumps get funded properly.

---

## Honest status update (real, verified — not aspirational)

Since this plan was written, most of items 1-4 above have actually shipped.
Verified by reading the real code and running the real test suite, not
assumed from memory:

- ✅ **Live web-search grounding + citations** —
  `orca/tools/search_grounding.py` is real, built, and covered by 9 real
  passing tests (`tests/test_search_grounding.py`). It extends the
  existing DuckDuckGo `web_search` tool with `[S#]`-style citation
  enforcement and a real indirect-prompt-injection sanitization pass
  (flags injection-shaped scraped content and excludes it entirely,
  rather than trying to regex-edit it).
  **Honest gap remaining**: this module is not yet called from
  `orca/serve/api.py` or the agent loop — it exists as a real, tested,
  standalone capability that still needs to be wired into the live chat
  path before a user actually benefits from it. That wiring is the
  single highest-leverage remaining task from this whole plan.
- ✅ **Cost-aware routing** — `orca/serve/routing.py` is real, live code:
  opt-in escalation from a self-hosted tier to a frontier backend, gated
  by a data-sovereignty lock, a daily spend cap, and a query-complexity
  heuristic. This is what makes the "cheaper than Perplexity" claim a
  fact rather than marketing copy, per this module's own docstring.
- ✅ **Visible trust UI** — the marketing landing page (`orca/serve/web/landing.html`)
  and a dedicated `/trust` page (`orca/serve/web/trust.html`) both ship
  real, honest trust signals: a grounding-check indicator, a real
  judge-scored accuracy figure pulled from an actual eval report (not
  invented), and a security posture page that marks SOC 2 as
  "in progress" rather than claiming compliance that doesn't exist yet.
- ✅ **Privacy/consent compliance groundwork** — `orca/auth/privacy.py`
  adds real consent tracking, data-export requests (GDPR Art. 20), and a
  structured security-breach log, with DB-level append-only/immutability
  enforcement verified by real tests (not just application-layer trust).
- 🔄 **Safety fix in progress** — the AI Safety & Alignment Researcher's
  role above calls for a real fix to jailbreak resistance before any of
  this ships to real users. That work is live right now: a
  probe-grounded DPO pass for Novus (core), trained and verified on
  Kaggle's free GPU tier tonight, with a live before/after block-rate
  comparison running as this update is being written. Genesis (nano)
  needs the same pass next — its probe-grounded DPO data was too thin
  (1 usable pair) on the last attempt and needs regenerating with more
  trials before a real training run is worth it.
- ❌ **Still genuinely not started**: the Growth Lead's honest positioning
  copy, Legal's search-API ToS review, and `docs/MASTER_PLAN.md`'s Phase 0
  (real customer conversations) — these remain the actual bottleneck, and
  no amount of further engineering substitutes for them.

**The honest updated next move**: wire `search_grounding.py` into the real
chat path (the missing link between "we built the differentiator" and "a
user can experience it"), finish the safety fix already in progress, then
stop building and go have the real customer conversations this plan's own
CEO framing already flagged as the actual gate.
