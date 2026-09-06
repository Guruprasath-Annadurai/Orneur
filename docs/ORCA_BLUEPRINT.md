# Orca LLM — Enterprise Development Blueprint

Status: **IN EXECUTION** — Phase 1 (Genesis) fine-tune complete, Phase 2
(Novus) distillation running. Founder-approved and actively building, not a
draft awaiting sign-off anymore.
Author: solo dev + AI engineering support.
Scope: three-model Orca LLM (Genesis / Novus / Aeternum), collectively
branded **"Orca Genius"** as the public-facing product family (Section 3b),
built on open-weight base models, fine-tuned with Nvidia Nemotron-3-Ultra as
a distillation teacher, deployed as a user-centric, search-augmented AI
platform positioned against Perplexity (Section 3a).

This document replaces prior "god-mode" drafts. Every item below is either
(a) already real code in this repo, (b) buildable by one developer with the
resources actually available (this Mac, Ollama, one Nemotron API key, free-
tier cloud GPU credits, no GPU cluster, no funding round), or (c) explicitly
marked as requiring a resource decision (budget, timeline, hires) before it
can move from plan to build. Nothing here is included because it sounds
impressive.

---

## 1. Executive Summary

Orca is a three-tier AI platform (Genesis / Novus / Aeternum) positioned as
"the AI that shows its work" — every answer traceable to a source, every
tool call visible, every uncertainty stated honestly instead of masked by
confident hallucination. This is not a marketing slogan bolted onto a
generic chatbot; it is a direct extension of mechanisms already built and
working in this codebase: the persona-claim gate, citation enforcement,
PII-redaction disclosure, and hash-chained audit log. No major competitor
(ChatGPT, Gemini, Claude via consumer surfaces, Perplexity) exposes this
combination to end users as a first-class, verifiable feature.

Target buyer: businesses and professionals who have been burned by
confident-but-wrong AI answers and want a system that tells them when it
doesn't know, shows where an answer came from, and can be audited after the
fact. Not "smarter than GPT-4o" — "more honest and more auditable than
GPT-4o," which is a claim a solo developer can actually make good on.

---

## 2. Current State Assessment (updated — reflects real progress, not the original draft)

Real, working, tested:
- Auth: email/password, TOTP 2FA (+ frontend setup/challenge UI), RBAC,
  session store (SQLite/Postgres dual)
- Rate limiting: IP-aware, proxy-header-safe, per-endpoint rules
- Content moderation: 3-tier action, self-harm never blocked (crisis
  resources injected instead)
- Document Q&A / RAG: 7-stage pipeline, PII redaction on ingest (Luhn-
  validated), citation enforcement, sufficiency checking
- Code interpreter: sandboxed execution, AST safety checks
- Vision input: one-shot, honestly scoped, now has a frontend (attach
  button, capability-mismatch warning before send)
- Knowledge graph: per-session, LLM-extracted, honestly scoped (no
  cross-session resolution), now has an explorer UI
- Context intelligence: budget-aware compression, fixed a real unbounded
  memory-growth bug
- Governance: hash-chained audit log (SHA-256 + HMAC), model cards with a
  runtime persona-claim gate, red-team suite, regression testing — **and
  now a real admin dashboard UI** (model cards, verify-chain-integrity
  button, metrics) closing what was previously the single biggest gap
  between "governance exists" and "governance is demoable to a buyer"
- Enterprise/Team management: seat-limited org invites, role management —
  built this cycle, did not exist before
- Production ops: Prometheus/JSON metrics, SQLite-safe backup/restore,
  Stripe billing (webhook signature verification now fails closed, was
  fail-open), right-to-delete (GDPR-shaped)
- **pytest suite: 86 tests, 0 failing** — covers stripe webhook/signup
  sequencing, PII redaction, rate limiting, account deletion, moderation,
  org/team seat logic, and the distillation retry/backoff logic. The "zero
  test coverage" gap from the original draft is closed.
- **Genesis (nano) fine-tune: complete.** Base Qwen2.5-7B-Instruct zero-shot
  baseline measured at **0.76/1.0** on the 30-question domain eval
  (business/coding/Hindi-business/honesty). QLoRA fine-tune (rank 16, 653
  distilled+curated examples, 3 epochs) trained via Colab free-tier T4 —
  real, observed signal: training loss dropped steadily (0.17→0.09) while
  validation loss rose after step 100 (0.65→0.73), an overfitting flag on
  this small a dataset that must be checked against the post-fine-tune
  eval score before calling this tier "improved," not assumed.
- **Novus (core) distillation: in progress**, split across two providers
  (Nvidia direct + OpenRouter) to avoid a single rate-limit bottleneck —
  targeting engineering/business/legal domains, including a newly-added
  `legal` seed domain (`orca/data/seeds.py`) that didn't exist before.
- Domain eval sets for all three tiers now exist and score per-domain, not
  averaged into one hidden number (`genesis_eval.py`, `novus_eval.py`,
  `aeternum_eval.py`) — matches this blueprint's own Phase 2 requirement.

Real, missing, and flagged honestly:
- **No SSO/SAML.** Still blocks real enterprise sales conversations on the
  first call, every time. Not addressed yet.
- **Aeternum (ultra) not yet distilled, fine-tuned, or eval-baselined.**
  Largest remaining gap in the three-tier plan.
- **No production search/retrieval infrastructure yet** — the Perplexity-
  style positioning (Section 3a) requires real-time web search ranking and
  citation-grounded synthesis at a quality bar beyond the current RAG
  pipeline's document-Q&A scope. Not started; scoped in Section 3a.
- Ultra's fine-tune will very likely require a **paid** cloud GPU (70B-class
  VRAM needs exceed every free tier checked so far) — the free-GPU path
  that worked for Genesis does not extend to Aeternum. Budget decision
  needed before Phase 3, not assumed away.

---

## 3. Product Positioning

**Primary claim:** Orca is the AI platform that shows its work — every
answer cites its source, every tool call is visible, every uncertainty is
stated plainly instead of hidden behind confident phrasing.

**Not the claim:** "First Indian LLM" (false — Sarvam, Krutrim, AI4Bharat,
BharatGen already exist and are well-funded; this claim is publicly
fact-checkable and would damage credibility instantly). Not "beats
GPT-4o/Claude on frontier benchmarks" (untrue for a solo-built, open-weight
fine-tune; do not make claims that collapse under a single benchmark run).

**Real differentiators, ranked by actual buildability:**
1. Persona-claim honesty gate — a tier can't claim "verified" until it
   clears a real accuracy/safety threshold. Already built.
2. Citation enforcement + PII redaction disclosure — already built,
   needs UI surfacing (see Phase 4).
3. Audit-chain integrity verification — already built, partial UI.
4. Multi-step task guidance (e.g., "help this researcher find the exact
   document") — this is an agent-loop/tool-use engineering problem, not a
   bigger-model problem. Real gap, real opportunity, addressed in Phase 2.

---

## 3a. Perplexity-Style Positioning — What It Actually Requires

Perplexity's core differentiator is not a better foundation model — it's
real-time web search + retrieval ranking + citation-grounded synthesis,
running on top of existing/fine-tuned models, not raw pretraining. Orca
already has the bones of this (RAG pipeline, `[D1]`/`[D2]` citation
markers, the `citation_compliance` "unverified against your documents"
flag, and a `web_search` tool already wired into the agent loop) — the gap
is depth and quality of the search/retrieval layer, not model size.

**What "build a public model like Perplexity" honestly requires, in order:**
1. **Real-time web search infra** — current tool-use gives the model a
   `web_search` call; a Perplexity-grade product needs ranked, deduplicated,
   freshness-aware results feeding the synthesis step, not a single API
   call's raw output. This is a search-infrastructure engineering problem.
2. **Citation-grounded answer synthesis** — extend the existing RAG
   citation-enforcement pattern (already built for documents) to live web
   results: every claim in an answer traceable to a specific fetched source,
   same honesty mechanism already shipped, applied to a new source type.
3. **Query understanding / decomposition** — multi-part questions need to
   be broken into sub-searches (this is the "multi-step task guidance"
   differentiator from Section 3, item 4 — same underlying engineering
   work, not a separate initiative).
4. **Freshness and re-ranking** — stale or low-quality sources cited
   confidently is worse than the hallucination problem this whole platform
   is built to avoid. Needs an explicit quality/recency filter before
   synthesis, not "whatever the search API returns first."
5. **Scale/cost reality** — every user query now potentially triggers
   several external search-API calls, not just one model inference. This
   is a real, ongoing per-query cost that needs a budget ceiling (same
   discipline already applied to Nemotron distillation cost in Section 10),
   not an unbounded assumption.

**Sequencing:** do not start this before Genesis and Novus are proven
(matches Section 4's existing "ship and generate real usage data first"
principle) — search infrastructure is expensive to build and maintain, and
should be justified by real user demand for it, not built speculatively
alongside the model fine-tuning work already in flight.

---

## 3b. Public Brand — "Orca Genius"

**Decision:** the three-tier product family is publicly branded **Orca
Genius** (Genius as the platform/family name — chosen over "Mastermind" for
being shorter, cleaner in a product wordmark, and not implying a single
dominant persona when the actual product is three distinct tiers). This is
a naming-layer decision only — it does not rename any internal code:
`orca-nano`/`orca-core`/`orca-ultra` remain the technical model ids,
Genesis/Novus/Aeternum remain the tier names used throughout this
blueprint and the codebase (`genesis_eval.py`, `novus_eval.py`,
`aeternum_eval.py`, `variants.py`). "Genius" wraps the family in
marketing/product surfaces (site, onboarding, pricing page) the same way
"Genesis" already sits above `orca-nano` as a marketing name distinct from
the technical id — this adds one more layer on top, it doesn't replace the
existing one.

**If "Mastermind" is preferred instead:** same structure applies — it's a
one-place branding swap (marketing copy, `index.html` taglines, pricing
page), not a re-architecture. Revisit and confirm before it ships publicly;
treat this as provisional until confirmed, not locked.

---

## 3c. User-Centric Product Principles — Solving Real Problems, Not Chasing Benchmarks

The honesty/trust mechanisms in Section 3 are necessary but not sufficient
— a platform can be perfectly honest about its limitations and still fail
to solve what the user actually came to solve. Concrete mechanisms, not a
mission-statement platitude:

1. **Problem-outcome tracking, not just eval scores.** A high
   `genesis_eval` score proves the model "didn't obviously fail" on a
   fixed probe set (per that module's own honest-scope docstring) — it
   does not prove a real user's actual problem got solved. Add a
   lightweight per-conversation outcome signal (did the user's follow-up
   indicate resolution, frustration, or abandonment?) feeding back into
   what gets prioritized for the next distillation/eval-set expansion —
   not vanity engagement metrics, a resolution signal.
2. **Domain eval sets grow from real usage, not just designer intuition.**
   `novus_eval.py`'s engineering/business/legal domains and
   `aeternum_eval.py`'s six cross-domain pairs were built from a
   reasonable guess at what "deep reasoning" and "cross-domain synthesis"
   buyers need — once real users exist, the eval sets should be revised
   toward the domains and failure modes actual users hit, not left frozen
   at their initial design.
3. **The persona-claim gate and "unverified" disclosures are the user-
   centric mechanism, not a compliance checkbox.** A user who's told
   plainly "this hasn't cleared its verification threshold yet" can decide
   whether to trust a specific answer — that's solving their actual
   problem (knowing when to double-check), not a legal hedge. Don't let
   this get diluted into fine print as the product matures.
4. **Support/feedback loop is a real engineering deliverable, not an
   afterthought.** There is currently no structured channel for "this
   answer didn't help me, here's why" that feeds back into training data
   curation or eval-set expansion. This is a concrete gap to close before
   claiming the platform is user-centric in practice, not just in
   positioning copy.
5. **Free tier (Genesis) is the primary user-feedback instrument, not just
   a funnel.** Section 8's go-to-market already made Genesis free with no
   limit specifically to get real users and real feedback before over-
   building (Section 8) — that decision is the user-centric mechanism
   already in place; the work now is making sure that feedback actually
   gets captured and acted on (item 4), not just generating usage volume.

---

## 4. Technical Architecture (buildable, not aspirational)

```
                          User (web/PWA)
                                │
                        FastAPI backend (existing)
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
   Auth/RBAC/2FA        Model Router (genesis/          Governance
   (existing)            novus/aeternum)                (audit, model
                                │                        cards, redteam)
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
   RAG pipeline           Code interpreter          Vision (v1, one-shot)
   (7-stage, existing)    (sandboxed, existing)      (existing)
        │
   Ollama (local inference, default)
        │
   Fine-tuned models: orca-nano (Genesis), orca-core (Novus),
   orca-ultra (Aeternum) — LoRA adapters on open-weight bases
        │
   Nemotron-3-Ultra (Nvidia API) — DISTILLATION TEACHER ONLY,
   never in the live user request path
```

Explicitly rejected from this architecture (cost/complexity, no proven
need): Neo4j AuraDB, Pinecone, Upstash Kafka, Temporal, dedicated GPU
fleet, multi-provider generative media stack (ElevenLabs/Twelve
Labs/Luma/Suno/HeyGen), edge-compute mesh. Revisit only after Genesis and
Novus are shipped, used, and generating revenue — not before.

---

## 5. Three-Model Development Plan

### Phase 1 — Genesis (DONE — fine-tuned, pending post-tune eval)
1. ~~Distill 2,000-3,000 examples~~ — done at smaller scale (653 curated
   examples after quality filtering; distillation continued past this
   toward the original target in the background).
2. ~~LoRA fine-tune~~ — done via Colab free-tier T4 (rank 16, not the
   original `prosumer`-preset assumption — this Mac has no CUDA GPU at
   all, so the plan's "on this Mac" assumption was wrong and had to route
   through a free cloud GPU instead; real correction, not a footnote).
3. **Next, not yet done:** re-run `genesis_eval.py` against the fine-tuned
   model and compare to the 0.76 baseline — this is the actual proof step
   and has not happened yet. Do not call Genesis "improved" until this
   runs, especially given the overfitting signal noted in Section 2.
4. Redteam + register in Ollama + ship as first revenue surface — pending
   step 3's result.

### Phase 2 — Novus (distillation in progress)
1. Base model decision: Llama-3.1-8B (per `variants.py`), same VRAM
   constraint as Genesis applies — revisit "32B if feasible" only after
   confirming real GPU access beyond the free tiers used so far.
2. ~~Build a real domain eval set~~ — done (`novus_eval.py`, 24 prompts
   across engineering/business/legal, scored per domain).
3. Distillation running now, split across Nvidia-direct and OpenRouter to
   avoid single-provider rate limiting — not yet fine-tuned.
4. Multi-step tool orchestration (the "guide the researcher" differentiator)
   remains unstarted — this is real engineering work, not automated by the
   fine-tune itself.

### Phase 3 — Aeternum (not started)
1. Largest model, largest cost, highest data-quality bar.
2. Persona-claim gate scrutiny is highest here — this is the
   most-marketed tier; it must not claim "verified" without actually
   clearing its threshold.
3. Do not start this phase until Genesis and Novus have proven the
   fine-tune pipeline moves real numbers, not vibes.
4. **Budget reality check, updated:** none of the free-GPU paths that
   worked for Genesis (Colab T4, Lightning free A100 hours) will fit a
   70B-class fine-tune. This phase very likely requires a paid GPU rental
   — confirm budget before starting, do not assume a free path exists.

---

## 6. Enterprise Readiness Track (parallel, ongoing)

1. **pytest suite** — currently zero coverage repo-wide. Priority: the
   modules that already had real bugs found this session (PII redaction,
   rate limiting, account deletion, moderation).
2. **Admin dashboard UI** — model cards, "Verify Chain Integrity" button,
   metrics visualization. Audit log viewer alone exists; this is the
   single biggest gap between "governance exists" and "governance is
   demoable to a buyer."
3. **SSO/SAML** — not code-quick, but the single largest blocker to actual
   enterprise sales conversations. Requires a resource/timeline decision.
4. **Stripe webhook signature verification** — confirm `construct_event`
   (or equivalent) is actually called; unverified webhook = anyone can
   grant themselves a paid plan by POSTing a fake event. Check before
   anything else in this list.

---

## 7. Data & Training Pipeline (already scaffolded in this repo)

- `orca/train/distill.py` — Nemotron-3-Ultra as teacher, generates ShareGPT-
  format training data. Real cloud cost per call; not free, not estimated
  automatically — check Nvidia pricing before running at scale.
- `orca/train/variants.py` — per-tier base model + LoRA config.
- `orca/train/genesis_eval.py` — new this session, 30-question Genesis
  domain eval (business/coding/Hindi/honesty), keyword-scored.
- `orca/train/redteam.py`, `orca/train/regression.py` — run after every
  fine-tune, every tier. A fine-tune that improves domain accuracy but
  degrades safety is a net loss and must be caught before shipping.

---

## 8. Go-To-Market & Revenue Model

**Decided (founder, this session):**
- **Genesis: free**, no limit, at initial launch. Accessible tier, real
  users, real feedback signal before over-building.
- **Novus: free for the first 100 users only.** After the 100th signup,
  new users see Novus as paid; the first 100 keep free access
  (grandfathered) — confirm this grandfather behavior explicitly before
  building, since "first 100 users free forever" and "first 100 signups
  get a free trial window" are different products with different code.
- **Aeternum: paid from day one.** Flagship tier, sold on the honesty/
  audit features (Section 3) — the actual sales pitch, not invented.

**Real engineering implication, not yet built:** the codebase currently
has zero plan/tier-gating logic tying a user account to which model
(genesis/novus/aeternum) they're allowed to call. Confirmed by direct
grep of the auth and serving layers — no `plan` field on the user record,
no model-access middleware. Stripe webhook exists for payment fulfillment
but nothing downstream currently checks a user's plan before routing a
chat request to a model. This needs to be built as part of Phase 1/2, not
assumed to already work:
1. Add a `plan` field to the user record (free / novus_early / paid).
2. **DECIDED**: "first 100" = global signup order (account #1-100 by
   creation timestamp), not first-100-to-try-Novus. Implementation: a
   single atomic counter (Postgres sequence or Redis `INCR`) checked at
   signup time — assign `novus_early` to accounts 1-100, `free` after.
   Must be atomic under concurrent signups (race condition risk if two
   signups at #100/#101 hit a naive read-then-write check) — use
   `INSERT ... RETURNING` sequence value or `INCR`, not a
   count-then-compare pattern.
3. Add model-access middleware in the chat/stream endpoints that checks
   plan before allowing a `model=novus` or `model=aeternum` request —
   currently any authenticated user could call any model in the code as
   it exists today.
4. Aeternum's Stripe paywall must be wired to actually block access
   pre-payment, not just fulfill after payment — confirm this is real
   before launch, not assumed.

**Scale note (founder target: 10K-100K user onboarding):** at this scale,
the codebase's default fallbacks are wrong and must not be used at
launch: in-memory rate limiting, SQLite auth DB, and in-memory session
store are all single-instance, best-effort fallbacks documented
elsewhere in this repo as "accepted tradeoffs for most Orca
deployments" — that assumption breaks at 10K+ concurrent users. Required
before onboarding at this scale: `ORCA_DATABASE_URL` set to real
Postgres, `ORCA_REDIS_URL` set to real Redis, both already supported as
dual-backend in the existing code — this is a deployment/config decision,
not new code, but it must be made deliberately, not left on defaults.
The atomic signup counter in item 2 above depends on this being Postgres/
Redis, not SQLite/in-memory, to be race-condition-safe under concurrent
signups at this volume.

- Enterprise track (SSO, admin UI, compliance docs) targets the buyer
  who needs to justify the purchase to their own security/legal team —
  this audience cares about the audit chain and persona-claim gate more
  than raw benchmark scores.

---

## 9. Risk Register

| Risk | Severity | Status |
|---|---|---|
| Zero test coverage | Resolved | 86 tests, 0 failing, covers auth/billing/PII/rate-limit/org/distill-retry |
| No admin dashboard UI | Resolved | Model cards, verify-chain button, metrics — built |
| No SSO for enterprise buyers | High | Still open — needs resource decision |
| Stripe webhook signature unverified | Resolved | Was fail-open on missing secret, now fails closed (`stripe_hook.py`) |
| Nemotron API cost unbounded at scale | Medium | Needs budget ceiling before Phase 2/3 spend scales up |
| "First Indian LLM" claim | Would be High if used | Killed — do not use |
| Overbuilding infra (Kafka/Neo4j/etc.) before revenue | Medium | Explicitly deferred, see Section 4 |
| Persona-claim gate bypassed for marketing convenience | High if it happens | Must never be bypassed — this is the entire trust product |
| No plan/tier-gating logic exists yet (any user could call any model today) | Resolved | `model_access_allowed()` built, tested, wired into `/api/chat` and `/api/stream` |
| "First 100 Novus users" definition | Resolved | Decided: global signup order, atomic counter |
| SQLite/in-memory defaults at 10K-100K onboarding scale | High | Must set `ORCA_DATABASE_URL`/`ORCA_REDIS_URL` to real Postgres/Redis before launch, not left on defaults |
| Genesis fine-tune overfitting (validation loss rose after step 100) | Medium, unconfirmed | Must be checked against post-fine-tune eval score before declaring Genesis "improved" — not yet run |
| Aeternum has no free-GPU path (unlike Genesis/Novus) | High | Real budget decision needed before Phase 3 starts, not assumed away |
| Perplexity-style search positioning has no built infrastructure yet | Medium | Scoped in Section 3a; sequenced after Genesis/Novus ship, not started |
| No structured user-feedback-to-training-data loop | Medium | Section 3c item 4 — real gap, not yet built |
| "Orca Genius" brand name unconfirmed publicly | Low | Provisional per Section 3b — confirm before it ships on any public surface |

---

## 10. Budget & Resource Decisions Needed Before Phase 1 Spend

1. **Nemotron distillation budget ceiling** — 50-example real test batch
   run against `nvidia/nemotron-3-ultra-550b-a55b` (this session):
   49/50 written (1 empty-response failure, ~2%), **36,759 total tokens**
   (2,784 prompt + 33,975 completion — completion is 93% of cost, this
   is the number that matters). Avg 735 tokens/example.
   Extrapolated: 2,000 examples ≈ 1.47M tokens, 3,000 examples ≈ 2.2M
   tokens. Dollar cost still needs a founder decision — Nvidia NIM
   pricing varies by account/contract; check the actual $/1M-token rate
   on the Nvidia billing dashboard and multiply against the completion-
   token figures above before committing to the full batch. Do not
   proceed to a 2-3K run without confirming this number first.
2. **Timeline commitment** — nights/weekends vs full-time solo changes
   phase sequencing and how aggressively to parallelize Phase 4 against
   Phases 1-3.
3. ~~Revenue model shape~~ — **DECIDED**: Genesis free, Novus free for
   first 100 users then paid, Aeternum paid from day one (Section 8).
   Still needs: exact definition of "first 100" (see Risk Register) and
   the plan-gating engineering work (Section 8) before this is real
   instead of a pricing page that doesn't enforce anything.

---

## 11. What This Blueprint Explicitly Excludes

Distributed event-sourced "Memory Cathedral" graph databases, multi-modal
generative media orchestration (video/music/avatar generation), self-
modifying/self-coding agent loops, planet-scale edge GPU meshes, and
similar items from earlier draft documents. These are not rejected because
they're bad ideas in the abstract — they're rejected because they cost
thousands of dollars a month, require months of solo engineering time each,
and have no proven user demand yet. Revisit after Genesis and Novus ship
and generate real usage data, not before.
