<!--
The definitive, detailed, phase-by-phase launch plan for Orca's first
public release: Genesis + Novus + Orca Lens together. Builds on
docs/FINAL_PLAN.md's four-phase business sequencing but goes one level
deeper — this is the operational launch checklist: what has to be true,
function by function, before each phase gate opens.
-->

# Orca Launch Plan — Genesis + Novus + Lens

## Honest framing, before anything else

**"100% ready" and "0 bugs" don't exist for any real software launch** —
no company, including the frontier labs, ships that. What this plan holds
instead is a real, verifiable bar: every launch-blocking risk identified
and closed, every public claim checked against what's actually true, every
legal exposure reviewed by the time each phase gate opens. That is a
higher bar than most startups hit, and it's the one that actually protects
users, the company, and its credibility.

**"Next-generation AI era" — what we can honestly claim and what we
can't.** We cannot claim Genesis/Novus are more capable than frontier
models (nano/core haven't beaten their own pre-fine-tune baselines yet;
see `docs/MASTER_PLAN.md`). We *can* honestly claim a genuinely different
trust, cost, and transparency model: code-enforced citations, a real audit
trail, data-sovereignty guarantees, and a hybrid self-hosted/frontier
architecture nobody else in this exact form has shipped. That is the real
"next-generation" claim, and it's the only one this plan markets.

**Known, unresolved risks that must be disclosed, not hidden, before
launch:**
- Raw model jailbreak resistance is still ~0% at the model level; the
  moderation layer blocks 9/10 real adversarial probes in testing, but
  this is a mitigation, not a fix. This must be in the security/trust
  documentation shown to users, not buried.
- Lens (media generation) carries real, distinct legal exposure —
  copyright/deepfake/likeness risk — already flagged against the
  Seedance/MPA precedent. This needs a dedicated legal review before Lens
  goes anywhere near a public launch, separate from Genesis/Novus's review.

---

## Product scope for this launch

- **Genesis (nano)** — self-hosted answer engine, free/low-cost tier, the
  cost + citation + transparency differentiator from
  `docs/PERPLEXITY_DIFFERENTIATION_PLAN.md`.
- **Novus (core)** — larger self-hosted tier + frontier-passthrough option,
  the "bring your own frontier model" hybrid product.
- **Orca Lens** — media (image/video) generation, launching alongside but
  gated on its own, stricter legal/moderation review given the distinct
  risk profile.

---

## Phase 0 — Launch Readiness Audit (now → 2-3 weeks)

This phase's only job: find every launch-blocking problem before real
users do. Nothing in Phase 1 starts until every item below is closed or
explicitly, knowingly accepted as a disclosed risk.

### Engineering
- [ ] Full regression suite green (201+ existing tests), extended with
  Lens-specific coverage (moderation, rate limiting, content policy).
- [ ] Fresh load test at realistic launch-scale traffic — repeat the
  load-testing exercise that previously found two real production bugs
  (model-resolution exact-match failure, chromadb metadata rejection);
  confirm neither has regressed and no new class of bug has appeared.
- [ ] Fresh redteam run (not reused numbers) confirming the moderation
  layer's 9/10 real-probe block rate still holds; document the residual
  1/10 and any new probes discovered.
- [ ] Data-sovereignty lock re-verified end-to-end: force-configure every
  tier to a frontier backend and confirm the lock still forces Ollama-only
  when set, per `orca/serve/registry.py`'s existing guarantee.
- [ ] Incident runbook (`docs/RUNBOOK.md`) rehearsed as a real dry run —
  pick one scenario (e.g., Ollama down) and actually execute the response,
  not just read it.
- [ ] Backup/restore actually tested — restore a model artifact and a
  user-data backup from cold storage and confirm it works, not just that a
  backup file exists.
- [ ] Billing integration (Stripe, per existing setup) tested with a real
  end-to-end transaction, not a mocked one.

### Lens-specific (separate, stricter gate)
- [ ] Content moderation pipeline for generated media: CSAM detection,
  deepfake/likeness misuse detection, copyright-flagged-content detection
  — reviewed and tested with adversarial prompts, not just the happy path.
- [ ] Watermarking/provenance metadata (e.g., C2PA-style content
  credentials) on all AI-generated media — increasingly a legal
  requirement (EU AI Act, various US state laws) and a trust feature in
  its own right.
- [ ] Rate limiting and abuse controls specific to media generation (higher
  compute cost per request than text, and a higher-stakes abuse surface).
- [ ] Legal sign-off specifically on Lens's ToS/AUP sections — this is the
  single highest legal-risk surface in this launch and gets its own review,
  not a shared paragraph in the general ToS.

### Security
- [ ] Lightweight external security pass: dependency vulnerability scan,
  OWASP Top 10 check on all public endpoints, secrets-handling audit
  (confirm no API keys ever hit git history — the `.env`-only pattern
  already established this session stays enforced).
- [ ] Rate limiting and abuse detection on every public-facing endpoint,
  not just chat.

### Legal/Compliance
- [ ] ToS, Privacy Policy, and Acceptable Use Policy finalized and reviewed
  by real counsel — AI-drafted versions are a starting point, not a
  substitute for actual legal review before launch.
- [ ] Age verification / content policy specifically for Lens.
- [ ] Export control / sanctions screening if serving a global user base —
  a real, often-overlooked requirement for US-based AI companies.
- [ ] Data processing agreement (DPA) template ready for the first
  enterprise conversations from `docs/FINAL_PLAN.md` Phase 1.
- [ ] Public-facing model cards and capability disclaimers (building on
  `orca/governance/model_cards.py`'s existing persona-claim gating)
  extended to cover Lens.

### Product/UX
- [ ] Trust UI shipped: audit trail, cost, backend identity, and the
  known-jailbreak-mitigation disclosure all visible to the user, not
  buried in an API field.
- [ ] Onboarding flow tested with real people (friends/family/early
  network counts) before opening to strangers.
- [ ] Support channel operational — even a single monitored email or
  Discord — before any public signup is possible.

**Phase 0 exit criteria**: every checklist item above is closed or is an
explicitly disclosed, accepted risk written down somewhere real users or
reviewers can see it — not silently skipped.

---

## Phase 1 — Closed Beta (Weeks 3-6)

- Invite-only: 100-500 users, drawn from AI power-user communities
  (per the Perplexity-pain-point targeting in
  `docs/PERPLEXITY_DIFFERENTIATION_PLAN.md`) plus early prospects from the
  chosen vertical (`docs/FINAL_PLAN.md` Phase 1).
- **Goal**: find real bugs under real, unscripted usage — this is what
  synthetic load testing and redteaming cannot substitute for.
- Track, weekly: retention, real error rates, moderation false-positive AND
  false-negative rate in the wild (not just against the known probe set),
  actual realized cost-per-query (validates or corrects the cost-advantage
  claim before it's said publicly).
- **Lens gets the closest monitoring** of any feature — this is the
  highest-risk abuse surface and the one most likely to surface a real
  incident first.
- Weekly triage-and-fix cycle; do not add new features during this phase —
  only fix what beta usage surfaces.

**Phase 1 exit criteria**: no critical/unresolved bug found in the final
full week of beta, retention signal is positive, and qualitative feedback
confirms the trust/cost differentiation actually lands with real users
(not just makes sense on paper).

---

## Phase 2 — Public Launch (Weeks 7-10)

- Open signups. Freemium: Genesis free tier, Novus/Lens paid tiers per the
  pricing work from `docs/FINAL_PLAN.md` Phase 1.
- **Marketing, honestly scoped**: content marketing built on real,
  verifiable comparisons (fact-checking real answers against citation
  accuracy, not fabricated superiority claims), a public launch
  (Product Hunt / Hacker News / relevant communities), a referral program.
  Every public claim gets checked against Phase 0/1's actual measured
  results before it's published — no claim ships that beta didn't verify.
- Support scaling to a real queue/SLA, even if still founder-staffed.
- Monitoring dashboards live with a defined on-call response (even a
  single-person on-call beats none).

**Phase 2 exit criteria**: stable uptime through the first real traffic
spike, no repeat of a previously-fixed incident class, and the payment/
monetization flow proven with real, unprompted paying customers — not just
beta invitees.

---

## Phase 3 — Enterprise & Vertical Push (Months 3-6)

Ties directly into `docs/FINAL_PLAN.md` Phase 2/3 and `docs/STARTUP_PLAN.md`:

- SOC 2 Type I completed (started back in Phase 0/1's legal track).
- Enterprise features: SSO, team workspaces, admin controls, data
  residency options — built on the RBAC/audit infrastructure already shipped.
- Convert the vertical conversations from `docs/FINAL_PLAN.md` into signed
  paying pilots.

**Phase 3 exit criteria**: first signed enterprise pilot(s), SOC 2 Type I
complete, real retained usage data feeding back into product priorities.

---

## Phase 4 — Scale (Months 6+)

Ties into `docs/FRONTIER_ROADMAP.md`'s funded phases and
`docs/FINAL_PLAN.md` Phase 3/4 — seed/Series A raised on real traction,
Novus's real capability jump funded, expanded compliance certs, and only
then, global/multi-vertical expansion.

---

## The standing rule across every phase

No phase gate opens on a checklist that's "probably fine" — it opens when
the item is actually verified, or the risk is written down and knowingly
accepted, in writing, by the person accountable for it. That discipline —
not a marketing claim — is what actually makes this launch credible to
users, enterprise buyers, and investors alike.
