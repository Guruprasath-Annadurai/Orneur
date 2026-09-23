# Genesis Frontier Reference Provider Clarification Drafts — Phase 21B.4.18

**Messages sent: NO.** Every draft below is prepared only, per phase
§3/§15/§26: "Claude may PREPARE clarification drafts. Claude must NOT
send them." No email, support ticket, or account-settings change was
sent or made to any provider this phase. Sending any of these remains a
separately-authorized future action requiring explicit owner/ChatGPT
sign-off.

Each draft: identifies ORNEUR, states the intended use accurately as an
evaluation/reference model (never a claim that permission already
exists), distinguishes evaluation from training/distillation, asks the
minimum precise yes/no question(s) needed, and avoids exposing private
holdout prompts, secrets, or unnecessary product-confidential detail.

---

## 1. Mistral AI

**Model:** Mistral Large 3 (La Plateforme API, model slug
`mistral-large-3-25-12`)

**Exact blocker:** `AUTOMATED_EVALUATION_UNRESOLVED`,
`PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`

**Source reviewed:** `help.mistral.ai/en/articles/455207` (opt-out
mechanism), `help.mistral.ai/en/articles/347617` (training-use
defaults), `help.mistral.ai/en/articles/347612` (Zero Data Retention),
`legal.mistral.ai/terms/privacy-policy` §5 (retention periods).

**Unresolved question:** Does the Admin-panel "Anonymous improvement
data" opt-out toggle, once disabled, create a prospective guarantee that
API inputs/outputs submitted afterward are never used for model
training — and is this independent of, or does it require pairing with,
Zero Data Retention (ZDR) to also satisfy confidentiality for sealed
evaluation prompts?

**Why it matters:** ORNEUR needs to know whether disabling that single
toggle is sufficient, on its own, to treat submitted prompts as
training-exempt, before any confidential evaluation material could ever
be sent.

**Suggested recipient:** Mistral AI support / legal
(`legal.mistral.ai`).

**Draft message:**

> Subject: API training opt-out — scope confirmation for automated
> internal evaluation use
>
> Hello,
>
> We are ORNEUR, and we are evaluating whether Mistral Large 3 is
> suitable for use as a reference/comparison model in an internal,
> automated evaluation pipeline for our own AI system under
> development. We are not currently making any API calls under this
> use case.
>
> We have two precise questions:
>
> 1. May we use the Mistral La Plateforme API solely as an automated
>    internal benchmark/reference — i.e., programmatically submitting
>    prompts and comparing outputs for internal evaluation purposes,
>    without incorporating Mistral Large 3 into any product we
>    distribute?
> 2. If we disable the "Anonymous improvement data" toggle in the Admin
>    panel Privacy menu before making any API calls, does that create a
>    prospective guarantee that our API inputs and outputs will not be
>    used for training or improving Mistral's models — and is Zero Data
>    Retention (ZDR) also required to treat that submitted content as
>    confidential?
>
> We are not asking you to review any confidential material — this is a
> terms-of-use scope question only.
>
> Thank you.

**Required yes/no confirmation:** (1) automated-internal-evaluation use
is permitted; (2) the training opt-out toggle alone is sufficient for a
prospective no-training guarantee (or ZDR is additionally required).

**What registry status could change if confirmed:** `automated_
evaluation_status` → `CLEAR`; `private_holdout_status` → `PERMITTED`
(if the opt-out is exercised and confirmed to apply prospectively).

---

## 2. Moonshot AI (Kimi)

**Model:** Kimi K3 (hosted API, `platform.kimi.ai` / `api.moonshot.ai`)

**Exact blocker:** `PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`
(confirmed BLOCKED for the hosted path), `WRITTEN_PROVIDER_
CLARIFICATION_REQUIRED`

**Source reviewed:** `platform.kimi.ai/docs/agreement/modeluse` §4
"Content" (live-fetched this phase, last updated 2026-07-30).

**Unresolved question:** What are the terms, minimum commitment, and
process for the "enterprise arrangements or separate written
agreements" referenced in §4 that would restrict use of Customer
Content for training or improving Moonshot AI models?

**Why it matters:** §4 confirms hosted-API content trains Moonshot's
models by default with no self-service opt-out; ORNEUR needs to know
whether an enterprise no-training arrangement is realistically
attainable (cost, minimum spend, contract term) before treating this as
a viable path to private-holdout compatibility.

**Suggested recipient:** Moonshot AI enterprise/support contact (via
`platform.kimi.ai` support channel).

**Draft message:**

> Subject: Enterprise no-training arrangement — scope and process
> inquiry
>
> Hello,
>
> We are ORNEUR. Your Kimi OpenPlatform Terms of Service §4 states that
> customers requiring restrictions on the use of Customer Content for
> training or improving Moonshot AI models may contact you to discuss
> enterprise arrangements or separate written agreements.
>
> We would like to understand, before making any API calls: what is the
> process, typical minimum commitment, and scope of such an
> arrangement — specifically, would it cover excluding submitted
> prompts and outputs from any training or model-improvement use, for
> an internal automated evaluation/reference use case (not a customer-
> facing product)?
>
> We are not submitting any confidential material with this inquiry.
>
> Thank you.

**Required yes/no confirmation:** whether a no-training enterprise
arrangement is available to a reference-evaluation (not resale/
production) use case, and its process.

**What registry status could change if confirmed:** `private_holdout_
status` → `PERMITTED` (only if a written no-training agreement is
actually executed — a separate future action, not this clarification
alone).

---

## 3. DeepSeek AI

**Model:** DeepSeek V4.1-Flash (Open Platform API, `api.deepseek.com`)

**Exact blocker:** `PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`

**Source reviewed:** `cdn.deepseek.com/policies/en-US/deepseek-privacy-
policy.html`, `cdn.deepseek.com/policies/en-US/deepseek-open-platform-
terms-of-service.html` (both re-checked in Phase 21B.4.17.2 and not
newly contradicted this phase).

**Unresolved question:** Does the Privacy Policy's training opt-out
right apply to Open Platform/API traffic specifically (as opposed to
only the consumer chat product), and if so, how is it exercised for an
API/developer account, and does it apply prospectively to future API
calls once exercised?

**Why it matters:** this is the single remaining gap standing between
DeepSeek's current `PUBLIC_EVAL_READY` status and full-protocol private-
holdout readiness — DeepSeek already has the strongest teacher-use and
automated-evaluation evidence of all six references.

**Suggested recipient:** DeepSeek Open Platform support.

**Draft message:**

> Subject: Privacy Policy training opt-out — scope for Open Platform
> API traffic
>
> Hello,
>
> We are ORNEUR, evaluating DeepSeek models (via the Open Platform API)
> as a reference/comparison model in an internal automated evaluation
> pipeline. We are not currently making API calls under this use case.
>
> Your Privacy Policy states users have the right to opt out of using
> Personal Data for training your models. We would like to confirm,
> before any use: does this opt-out right apply to Open Platform/API
> account traffic (not only the consumer chat product), how would an
> API/developer account exercise it, and does it apply prospectively to
> API calls made after it is exercised?
>
> We are not submitting any confidential material with this inquiry.
>
> Thank you.

**Required yes/no confirmation:** opt-out applies to API traffic;
process to exercise it for an API account; prospective effect.

**What registry status could change if confirmed:** `private_holdout_
status` → `PERMITTED`; `access_preflight_status` (full-protocol) →
`PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK` (still requiring a
separate future account-setting verification per phase §11).

---

## 4. Z.ai (GLM)

**Model:** GLM-5.3 (flagship) (hosted API, `api.z.ai`)

**Exact blocker:** `TERMS_AMBIGUITY`, `AUTOMATED_EVALUATION_UNRESOLVED`,
`PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`

**Source reviewed:** `docs.z.ai/legal-agreement/privacy-policy` (states
it does not apply to API/business customers, directs to a separate "Data
Processing Addendum for API Services" that this phase could not locate
a public copy of).

**Unresolved question:** Where is the "Data Processing Addendum for API
Services" published, and does it (a) permit automated internal
benchmarking/evaluation use, (b) state whether API inputs/outputs are
used for training by default, and (c) describe the September 2026
"data content no-retention" mechanism's exact eligibility and terms?

**Why it matters:** GLM-5.3 flagship's evaluation admission itself is
still REVIEW_REQUIRED — without locating governing API-specific terms,
none of the downstream holdout/retention questions can be resolved
either.

**Suggested recipient:** Z.ai / Zhipu AI developer support
(`user_feedback@z.ai` per the Privacy Policy's contact, or the
`docs.z.ai` support channel).

**Draft message:**

> Subject: Data Processing Addendum for API Services — request for
> access and evaluation-use clarification
>
> Hello,
>
> We are ORNEUR, evaluating GLM-5.3 as a reference/comparison model in
> an internal automated evaluation pipeline. We are not currently making
> API calls under this use case.
>
> Your Privacy Policy states it does not apply to API/business customer
> content and refers instead to a "Data Processing Addendum for API
> Services." Could you share where this document is published? We would
> also like to confirm: (1) is automated internal benchmarking/
> evaluation a permitted use case under your API terms, and (2) are API
> inputs/outputs used to train or improve your models by default, or is
> there an opt-out/no-retention option available (we understand a "data
> content no-retention" mechanism may have recently become available on
> request)?
>
> We are not submitting any confidential material with this inquiry.
>
> Thank you.

**Required yes/no confirmation:** automated-evaluation permission;
default training-on-input status; no-retention mechanism eligibility.

**What registry status could change if confirmed:** `license_or_
terms_status` → `CLEAR`; `automated_evaluation_status` → `CLEAR`;
`private_holdout_status` → `PERMITTED` (each independently, only if
the specific confirming evidence supports it).

---

## 5. MiniMax

**Model:** MiniMax M3 (weight license; commercial-use compliance path)

**Exact blocker:** `COMMERCIAL_USE_AMBIGUITY` (already substantially
resolved — see below), `ACCESS_PATH_UNVERIFIED` (hosted API)

**Source reviewed:** `huggingface.co/MiniMaxAI/MiniMax-M3/raw/main/
LICENSE` (re-confirmed live this phase).

**Note:** this is not really an open *question* — the license already
specifies the exact compliance path (attribution + a one-time notice
below $20M/yr revenue). What remains is executing that notice, which is
a provider-facing action this phase does not perform. The draft below
is the notice itself, prepared but not sent, for completeness.

**Suggested recipient:** `api@minimax.io`.

**Draft message (a compliance notice, not a question):**

> Subject: M3 licensing — notice
>
> Hello,
>
> Per the MiniMax Community License, we are providing notice that
> ORNEUR intends to use MiniMax M3 as an internal, non-redistributed
> evaluation/reference model while developing our own AI system. Our
> aggregate yearly revenue is below the $20,000,000 threshold requiring
> prior written authorization, so we understand a one-time notice is
> sufficient. We will include the required "Built with MiniMax M3"
> attribution wherever applicable.
>
> Thank you.

**Required confirmation:** none required by the license itself below
the revenue threshold — this is a notice, not a request. Sending it
(and adding attribution) is what would resolve
`COMMERCIAL_USE_AMBIGUITY`.

**What registry status could change if confirmed (i.e. once sent and
attribution added):** `license_or_terms_status` → `CLEAR`;
`reference_evaluation_admission_status` → `ADMITTED` (pending the
still-separate hosted-API access-path terms, which remain unverified
this phase).

---

## 6. Alibaba Cloud (Qwen)

**Model:** Qwen3.8-Max (Alibaba Cloud Model Studio API)

**Exact blocker:** `TERMS_AMBIGUITY`, `AUTOMATED_EVALUATION_UNRESOLVED`,
`MODEL_IDENTITY_INSUFFICIENT`

**Source reviewed:** `alibabacloud.com/help/en/model-studio/qwen-and-
wan-training-data-disclosure`, `alibabacloud.com/help/doc-detail/
2587658.html` (both live-fetched this phase; strong, specific
statements on training-use confirmed, but no statement found on
automated-benchmarking permission or on a stable version identifier for
`qwen3.8-max`).

**Unresolved question:** (a) is automated internal benchmarking/
evaluation an explicitly permitted use case under the Alibaba Cloud
International Website Product Terms of Service as applied to Model
Studio; (b) does a dated snapshot such as `qwen3.8-max-0902` carry a
provider guarantee of being frozen (never silently updated), and is
there any provider-exposed version/build identifier in the API response
metadata that would let ORNEUR attribute two calls to the same
underlying model?

**Why it matters:** private-holdout compatibility is now well-evidenced
(`PERMITTED`), but general evaluation-use permission and model-identity
attributability remain the two open gaps for this reference.

**Suggested recipient:** Alibaba Cloud Model Studio support.

**Draft message:**

> Subject: Automated benchmarking permission and version-stability
> confirmation for qwen3.8-max
>
> Hello,
>
> We are ORNEUR, evaluating Qwen3.8-Max via Alibaba Cloud Model Studio
> as a reference/comparison model in an internal automated evaluation
> pipeline. We are not currently making API calls under this use case.
>
> Two questions: (1) is automated internal benchmarking/evaluation an
> explicitly permitted use case under your Product Terms of Service as
> applied to Model Studio; (2) does a dated snapshot model ID such as
> `qwen3.8-max-0902` carry a guarantee that the underlying model weights
> never change without a new dated ID, and does the API response
> include any version/build identifier we could use to detect a change?
>
> We are not submitting any confidential material with this inquiry.
>
> Thank you.

**Required yes/no confirmation:** automated-benchmarking permission;
dated-snapshot freeze guarantee and/or a version identifier in response
metadata.

**What registry status could change if confirmed:** `license_or_
terms_status` → `CLEAR`; `automated_evaluation_status` → `CLEAR`;
`model_identity_attributable` → `true` (if a genuine freeze guarantee or
verifiable identifier is confirmed).

---

## Summary

| Provider | Drafts created | Messages sent |
|---|---|---|
| Mistral AI | 1 | NO |
| Moonshot AI | 1 | NO |
| DeepSeek AI | 1 | NO |
| Z.ai | 1 | NO |
| MiniMax | 1 (compliance notice) | NO |
| Alibaba Cloud | 1 | NO |

**Total: 6 drafts prepared. 0 sent.** Sending any of these, or making
any provider account-setting change (e.g. Mistral's opt-out toggle),
remains a separately-authorized future action.
