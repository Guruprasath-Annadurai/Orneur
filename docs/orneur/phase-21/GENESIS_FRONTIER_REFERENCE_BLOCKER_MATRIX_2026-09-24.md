# Genesis Frontier Reference Blocker Matrix — Phase 21B.4.18

**PRIMARY-SOURCE RESEARCH + CPU/METADATA ONLY. No GPU, no frontier
inference, no paid API call, no benchmark, no private holdout
execution, no provider account action, no message sent to any
provider.**

This artifact is the Phase 21B.4.18 "quorum-recovery blocker map"
required by phase §17/§19: a machine-readable-adjacent classification
of exactly what non-financial evidence is still missing for each of the
six locked frontier references, in priority order, so future phases
know the shortest legitimate path to the locked minimum quorum
(**4 usable references across 3 independent lineages**) without
lowering the threshold, redefining "ready," or substituting easier
references.

Locked quorum target: **6 references / minimum 4 usable / minimum 3
independent lineages**. Substitutions: **NONE**.

## Blocker taxonomy (§17)

- `TERMS_AMBIGUITY`
- `COMMERCIAL_USE_AMBIGUITY`
- `AUTOMATED_EVALUATION_UNRESOLVED`
- `PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`
- `PROVIDER_TRAINING_ON_INPUTS`
- `EVIDENCE_RETENTION_UNRESOLVED`
- `MODEL_IDENTITY_INSUFFICIENT`
- `ACCESS_PATH_UNVERIFIED`
- `SELF_HOST_COMPUTE_PROHIBITIVE`
- `ZERO_CASH_CHECK_REQUIRED`
- `WRITTEN_PROVIDER_CLARIFICATION_REQUIRED`
- `PROVIDER_ACCOUNT_SETTING_REQUIRED`

## Per-reference blocker map (priority order)

### Priority 1 — Mistral Large 3

- **Evaluation admission:** ADMITTED (Apache-2.0 weight license, unchanged).
- **Full-protocol access:** UNQUALIFIED.
- **Remaining blockers:** `AUTOMATED_EVALUATION_UNRESOLVED` (no explicit
  ToS statement on automated benchmarking/evaluation use found this
  phase — searched docs.mistral.ai, legal.mistral.ai, help.mistral.ai);
  `PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`;
  `PROVIDER_ACCOUNT_SETTING_REQUIRED`.
- **Key finding:** Mistral's own help-center article
  (`help.mistral.ai/en/articles/455207`, primary source, directly
  fetched) frames the API/Studio training-use control as **"customers
  retain full control over this processing and have the right to opt
  out at any time"** via an Admin-panel toggle ("Anonymous improvement
  data") — the SAME framing used for the Vibe consumer product, where
  the companion article (`347617`) explicitly states data is "used by
  default... unless you opt out." No text was found stating paid-API/
  La Plateforme traffic is training-excluded *by default*. This
  contradicts several third-party summaries (which claimed default
  opt-out) — the primary source itself does not support that claim.
  Separately, Zero Data Retention (ZDR) is available as an independent
  control (`help.mistral.ai/en/articles/347612`) — distinct from the
  training opt-out.
- **Retention duration (corrected Phase 21B.4.18.1):** the Privacy
  Policy's own §5 ("How long do we keep your personal data?") states,
  verbatim, that "except for specific APIs, we keep your Input and
  Output for the period necessary to generate the Output and then for
  thirty (30) rolling days to monitor abuse (unless zero data retention
  is activated)." However, that same Privacy Policy's own scope clause
  states: *"This Privacy Policy does not apply if you use our Mistral
  AI Products to process personal data in the context of your business
  activities. In this case, you are the data controller, and Mistral AI
  is the data processor processing on your behalf."* ORNEUR's intended
  use (automated internal evaluation while developing a commercial
  product) is exactly "the context of your business activities," which
  this Privacy Policy explicitly scopes itself OUT of — directing
  instead to a separate Data Processing Addendum
  (`legal.mistral.ai/terms/data-processing-addendum/`), which this
  phase did not locate a specific retention-duration figure within.
  **Canonical retention statement:** RETENTION WITHOUT ZDR: NOT PRECISELY ESTABLISHED IN THIS PHASE
  — the 30-day figure exists in the
  Privacy Policy text but that policy scopes itself out of exactly
  ORNEUR's business-context use case, so it is not safely citable as
  the governing figure. ZDR: AVAILABLE FOR ELIGIBLE SUPPORTED
  STATELESS API CALLS, independent of this open question.
- **What would resolve it:** (a) exercising the Admin-panel training
  opt-out toggle before any evaluation traffic (a provider account
  setting change — not authorized this phase); (b) written confirmation
  from Mistral that automated internal benchmarking is an explicitly
  permitted use case under the General Terms of Use; (c) locating and
  reviewing the Data Processing Addendum's own retention-duration terms
  for business/API customers.
- **Clarification required:** YES (see provider clarifications artifact).

### Priority 2 — Kimi K3

- **Evaluation admission:** ADMITTED (Kimi K3 License §4 internal-use
  carve-out, unchanged).
- **Full-protocol access:** UNQUALIFIED.
- **Remaining blockers (corrected Phase 21B.4.18.1):**
  `PROVIDER_TRAINING_ON_INPUTS` (hosted API path — the ordinary hosted
  API confirmed to train on Customer Content by default; this is a
  CONFIRMED condition, not merely "unresolved" — `PRIVATE_HOLDOUT_
  CONFIDENTIALITY_UNRESOLVED` was the wrong taxonomy entry for this
  reference and has been replaced); `SELF_HOST_COMPUTE_PROHIBITIVE`
  (2.8T params, largest of the six — the self-host path is unaffected
  by the training clause but is not currently a real access path);
  `WRITTEN_PROVIDER_CLARIFICATION_REQUIRED` (the enterprise written-
  agreement route exists per Moonshot's own ToS and remains the one
  identified path to resolution — Moonshot has NOT been characterized
  as lacking any route at all).
- **Key finding:** Live re-fetch of `platform.kimi.ai/docs/agreement/
  modeluse` (Terms of Service for Kimi OpenPlatform, last updated
  2026-07-30) §4 "Content": *"We may use Content to provide, maintain,
  develop, support, and improve the Services... Customer who requires
  restrictions on the use of Customer Content for training or improving
  Moonshot AI models may contact Moonshot AI to discuss available
  enterprise arrangements or separate written agreements. Unless
  otherwise expressly agreed in writing, Customer Content may be used
  for the foregoing purposes."* This is an unambiguous, directly-quoted
  confirmation: the hosted API path trains on submitted content by
  default, with **no self-service opt-out** — only a negotiated,
  written enterprise arrangement. The self-host path is unaffected by
  this clause but remains compute-prohibitive.
- **What would resolve it:** a negotiated written enterprise no-training
  arrangement with Moonshot AI (out of scope this phase — provider
  negotiation, not a self-service setting).
- **Clarification required:** YES.

### Priority 3 — DeepSeek V4.1-Flash

- **Evaluation admission:** ADMITTED. **Teacher use:** ADMITTED (ToS
  §4.2, unchanged).
- **Full-protocol access:** UNQUALIFIED (public-eval access remains
  `PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK`).
- **Remaining blockers:** `PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`;
  `WRITTEN_PROVIDER_CLARIFICATION_REQUIRED`.
- **Key finding:** DeepSeek's Privacy Policy grants only an **opt-out**
  right ("the right to opt-out of using your Personal Data for training
  our models or optimizing our technologies") — an unexercised right,
  not a default no-training posture. No first-party documentation this
  phase confirms that this opt-out mechanism (a) applies to Open
  Platform/API traffic specifically, as opposed to only the consumer
  app, (b) can be exercised account-wide before any API call, or (c)
  creates a genuine prospective no-training condition once exercised.
  Third-party sources disagree with each other on whether paid-API
  traffic is training-excluded by default; none cite a specific,
  checkable primary-source clause for the Open Platform.
- **What would resolve it:** either (a) explicit, checkable API-specific
  confirmation of the opt-out's scope and applicability from DeepSeek
  support/Open Platform documentation, or (b) a separately-authorized
  future phase that verifies the account-level opt-out setting exists
  and applies prospectively to API traffic (a provider account
  inspection, not exercised this phase).
- **Clarification required:** YES.

### Priority 4 — GLM-5.3 (flagship)

- **Evaluation admission:** REVIEW_REQUIRED (unchanged — license/terms
  silent on evaluation use, output retention, teacher/distillation).
- **Full-protocol access:** UNQUALIFIED.
- **Remaining blockers:** `TERMS_AMBIGUITY`;
  `AUTOMATED_EVALUATION_UNRESOLVED`;
  `PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`;
  `PROVIDER_ACCOUNT_SETTING_REQUIRED`.
- **Key finding:** Z.ai's Privacy Policy (`docs.z.ai/legal-agreement/
  privacy-policy`, live-fetched this phase) explicitly states it "only
  applies to individual users and does not apply to content that we
  process on behalf of customers of our business offerings," directing
  API/enterprise customers instead to a separate "Data Processing
  Addendum for API Services" — a document this phase did not locate a
  public, fetchable copy of. Separately, third-party reporting describes
  a September 20, 2026 Zhipu announcement of an opt-in "data content
  no-retention" mechanism on its MaaS platform, available on request for
  enterprise/developer users (explicitly excluding Batch API/File API) —
  this is very recent, was not independently primary-source-confirmed
  this phase, and (even if confirmed) would be a request-based provider
  arrangement, not a self-service default.
- **What would resolve it:** locating and reviewing the actual "Data
  Processing Addendum for API Services," and/or written confirmation of
  the September 2026 no-retention mechanism's exact terms and
  eligibility.
- **Clarification required:** YES.

### Priority 5 — MiniMax M3

- **Evaluation admission:** REVIEW_REQUIRED (unchanged).
- **License/terms status:** REVIEW_REQUIRED (unchanged).
- **Full-protocol access:** UNQUALIFIED.
- **Canonical classification (Phase 21B.4.18.1 reconciliation — OPTION
  A, applicability still ambiguous):** the repository cannot
  conclusively determine, from the license text alone, whether ORNEUR's
  intended use — running MiniMax M3 purely as an internal, non-
  redistributed evaluation/reference benchmark while separately
  developing a commercial ORNEUR product — meets the MiniMax Community
  License's clause 3 "Commercial Use" standard ("any use... primarily
  intended for commercial advantage or monetary compensation," with
  non-exhaustive examples). This is a genuinely open applicability
  question, not a resolved compliance-path question: it remains
  possible ORNEUR's use does NOT trigger Commercial Use at all (a
  purely internal, non-productized benchmark use is a materially
  different fact pattern from the license's own examples, e.g.
  fee-based third-party products, commercial API resale, commercial
  deployment of a fine-tuned derivative).
- **Remaining blockers:** `COMMERCIAL_USE_AMBIGUITY` (applicability, not
  merely compliance-path uncertainty); `ACCESS_PATH_UNVERIFIED` (hosted
  API terms not fetched this phase — `platform.minimaxi.com` redirects
  to a `.cn` domain); `WRITTEN_PROVIDER_CLARIFICATION_REQUIRED`.
- **Key finding:** the MiniMax Community License's compliance path IF
  Commercial Use applies is precisely characterized (re-confirmed live
  in Phase 21B.4.18 from `huggingface.co/MiniMaxAI/MiniMax-M3/raw/main/
  LICENSE`): attribution ("Built with MiniMax M3") plus a one-time
  notice email to `api@minimax.io` (subject "M3 licensing — notice")
  below $20M/yr revenue, prior written authorization only above that
  threshold. This compliance path is conditional on the applicability
  question above being resolved (or ORNEUR conservatively electing to
  treat the use as Commercial Use) — it is not itself proof that
  Commercial Use applies, and the notice is not sent this phase (§3:
  "Claude may PREPARE clarification drafts. Claude must NOT send
  them.").
- **What would resolve it:** either (a) written confirmation from
  MiniMax of whether a purely-internal, non-redistributed evaluation
  benchmark use (while separately developing an unrelated commercial
  product) constitutes Commercial Use under clause 3, or (b) ORNEUR
  conservatively electing to treat the use as Commercial Use and
  completing the notice + attribution compliance path above.
- **Clarification required:** YES (the underlying applicability
  question, not merely the compliance mechanics, remains genuinely
  open).

### Priority 6 — Qwen3.8-Max

- **Evaluation admission:** REVIEW_REQUIRED (unchanged — automated-
  benchmarking permission and free-trial/rate-limit terms remain
  unconfirmed). **Teacher use:** BLOCKED (unchanged — anti-competing-
  product ToS risk, not reopened this phase per §14).
- **Full-protocol access:** UNQUALIFIED.
- **Remaining blockers:** `TERMS_AMBIGUITY`;
  `AUTOMATED_EVALUATION_UNRESOLVED`; `MODEL_IDENTITY_INSUFFICIENT`
  (MUTABLE_REFERENCE_IDENTITY — no provider-exposed immutable version
  identifier, unchanged).
- **Key finding (genuine improvement this phase):** Alibaba Cloud Model
  Studio's own documentation states, directly and specifically:
  **"Customer data policy: Alibaba Cloud Model Studio does not use
  customer business data to develop or improve models without explicit
  consent"** (`alibabacloud.com/help/en/model-studio/qwen-and-wan-
  training-data-disclosure`, Security and Compliance section) and, in
  the Model Studio FAQ, **"Does Alibaba Cloud Model Studio save data
  generated during model calls? Alibaba Cloud strictly protects data
  privacy and never uses your data for model training"**
  (`alibabacloud.com/help/doc-detail/2587658.html`). These are direct,
  specific, declarative statements from official Alibaba Cloud Model
  Studio documentation, not implications — this narrows Qwen3.8-Max's
  private-holdout blocker to `PERMITTED` in the registry. This alone
  does **not** promote the reference: general evaluation/benchmarking
  permission remains unconfirmed and the mutable-identity gap is
  unrelated to holdout confidentiality.
- **What would resolve it:** written confirmation that automated
  internal benchmarking is a permitted use case, plus (separately) a
  provider-exposed stable version identifier for at least one dated
  snapshot (e.g. `qwen3.8-max-0902`) to satisfy model-identity
  attributability.
- **Clarification required:** YES.

## Minimum blocker set to reach 4 references / 3 lineages (§19)

No reference currently satisfies full-protocol readiness. The smallest
currently-known unresolved blocker set, one item per reference, needed
to reach the locked minimum (4 usable references, 3 independent
lineages), assuming the three already-ADMITTED references (DeepSeek,
Mistral Large 3, Kimi K3) plus one REVIEW_REQUIRED reference resolve
their license/terms gap:

- **Mistral (Mistral AI):** exercise or written-confirm the Admin-panel
  API training opt-out + written confirmation of automated-evaluation
  permission.
- **DeepSeek (DeepSeek AI):** written, API-specific confirmation that
  the Privacy Policy opt-out applies prospectively to Open Platform
  traffic.
- **Kimi K3 (Moonshot AI):** a negotiated written enterprise
  no-training arrangement (hosted API), or a viable zero-cash self-host
  path (currently compute-prohibitive).
- **One REVIEW_REQUIRED reference reaching CLEAR terms** (most tractable
  candidate: GLM-5.3 flagship, if the "Data Processing Addendum for API
  Services" is located and confirms evaluation/retention terms) to
  supply a fourth reference and a third independent organization
  (DeepSeek AI, Mistral AI, Moonshot AI are three already-distinct
  lineages if all three resolve — GLM/Zhipu would be a fourth
  organization, not strictly required once the first three resolve,
  since three organizations already satisfies `MINIMUM_INDEPENDENT_
  ORGANIZATIONS=3`; a fourth REFERENCE is still needed to satisfy
  `MINIMUM_USABLE_REFERENCES=4`, and any one of GLM/MiniMax/Qwen
  resolving its own terms ambiguity would supply it).

This is a blocker map, not a recommendation to weaken the protocol —
every item above is a genuine, currently-missing piece of primary-source
or provider-side evidence.

## Program state (unchanged this phase)

- GENESIS FOUNDATION: NOT SELECTED
- GENESIS FRONTIER STATUS: UNPROVEN
- PHASE 21C: NOT AUTHORIZED
- NO FRONTIER EXECUTION AUTHORIZED: YES
