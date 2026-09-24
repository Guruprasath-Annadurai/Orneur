# Genesis Frontier Provider Clarification Packets — Phase 21B.4.19

**MESSAGES SENT: 0. SUPPORT TICKETS SUBMITTED: 0. ACCOUNT SETTINGS
CHANGED: 0. COMMERCIAL NOTICES SENT: 0.**

These packets are PREPARED ONLY. They refine (and do not replace) the
Phase 21B.4.18 drafts in
`GENESIS_FRONTIER_REFERENCE_PROVIDER_CLARIFICATIONS_2026-09-24.md`. Each
external action (see the action queue) needs its own explicit owner
authorization — one authorization covers exactly one action id. No packet,
draft, or checklist changes any reference's registry state; only verified
evidence (Tier A/B/C) processed through the evidence gates can.

Every draft: identifies ORNEUR; states the use accurately as an
evaluation/reference model; distinguishes evaluation from training or
distillation; claims no existing permission; and contains no private
holdout prompt, secret, or unnecessary product-confidential detail.
Every question has an id so a reply can be mapped to
`question_ids_answered` and answerable YES/NO or by exact clause.

Suggested owner attachments to any send: none. Sender should be an ORNEUR
business address; forward the raw reply (with full headers) for intake.

---

## Mistral Large 3

**Action:** MIS-01 (email, P0). Follow-ups: MIS-02 (setting), MIS-03 (ZDR, conditional).
**Blockers targeted:** `AUTOMATED_EVALUATION_UNRESOLVED`, `PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`.
**Model identifier in scope:** `mistral-large-3-25-12`.

| ID | Question |
|---|---|
| MIS-Q1 | Is automated internal benchmarking/evaluation of `mistral-large-3-25-12` permitted under the current API terms? |
| MIS-Q2 | Does disabling **Anonymous improvement data** prevent Mistral from using API prompts/outputs for model improvement? |
| MIS-Q3 | Does that setting apply prospectively to all future Studio/API traffic? |
| MIS-Q4 | Does it apply to the specific API account/project we would use? |
| MIS-Q5 | Is Zero Data Retention separate from the training opt-out? |
| MIS-Q6 | Is ZDR required for confidential benchmark prompts? |
| MIS-Q7 | What retention applies to ordinary business API traffic when ZDR is off (we understand the Privacy Policy scopes out business use, so which document governs)? |
| MIS-Q8 | May ORNEUR retain prompts, outputs and API metadata for internal audit? |

**Draft (not sent):**

> Subject: Mistral Large 3 API — internal evaluation use, training opt-out scope and retention
>
> Hello,
>
> We are ORNEUR. We would like to use `mistral-large-3-25-12` via the
> Mistral API solely as a reference/comparison model in an internal,
> automated evaluation pipeline for our own AI system under development.
> We are not using it for training or distillation, and we have not made
> API calls for this use. Please answer each question yes/no or with the
> exact clause:
>
> 1. Is automated internal benchmarking/evaluation of this model permitted under the current API terms?
> 2. Does disabling "Anonymous improvement data" prevent Mistral from using API prompts/outputs for model improvement?
> 3. Does it apply prospectively to all future Studio/API traffic?
> 4. Does it apply to the specific API account/project?
> 5. Is Zero Data Retention separate from the training opt-out?
> 6. Is ZDR required for confidential benchmark prompts?
> 7. What retention applies to ordinary business API traffic when ZDR is off, and which document governs it?
> 8. May we retain our own prompts, outputs and API metadata for internal audit?
>
> No confidential material is included. Thank you.

**Expected evidence:** Tier B reply, or Tier A DPA/terms text.
**Possible transitions (only if verified):** `automated_evaluation_status` REVIEW_REQUIRED → CLEAR; with MIS-02 evidence, `private_holdout_status` REVIEW_REQUIRED → PERMITTED.

### Mistral account-setting checklist

*(Owner-authorized only, action MIS-02; nothing here has been done.)*

- [ ] MIS-01 answered and Q2–Q4 confirm the toggle's scope.
- [ ] Owner separately authorizes MIS-02 by action id.
- [ ] Screenshot **before**: Admin panel → Privacy → "Anonymous improvement data" (enabled), identifiers redacted.
- [ ] Disable only that toggle. Do **not** touch the separate Vibe toggle.
- [ ] Screenshot **after**, then reload and screenshot again.
- [ ] Save the current Mistral documentation page describing the toggle (URL + copy + SHA-256).
- [ ] Record per the account-setting evidence spec (prospective, API-specific).
- [ ] If MIS-Q6 = ZDR required: separately authorize MIS-03 (eligible plan/approval).
- [ ] Re-verify the setting is still active immediately before any future evaluation traffic.

---

## DeepSeek V4.1-Flash

**Action:** DSK-01 (email, P0); DSK-02 (read-only inspection); DSK-03 (conditional).
**Blockers targeted:** `PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`, `WRITTEN_PROVIDER_CLARIFICATION_REQUIRED`.

| ID | Question |
|---|---|
| DSK-Q1 | Does DeepSeek's model-training opt-out apply to Open Platform API traffic? |
| DSK-Q2 | Can it be enabled prospectively before any API request? |
| DSK-Q3 | Is it account-wide, project-wide or product-specific? |
| DSK-Q4 | Once enabled, are API inputs excluded from (a) model training, (b) model improvement, (c) optimization datasets? |
| DSK-Q5 | Does DeepSeek retain Open Platform API prompts? |
| DSK-Q6 | What retention period applies? |
| DSK-Q7 | Can confidential evaluation prompts be submitted under this setting? |
| DSK-Q8 | May ORNEUR retain responses/metadata for internal benchmark audit? |

**Draft (not sent):**

> Subject: Open Platform API — training opt-out applicability and retention
>
> Hello,
>
> We are ORNEUR. We plan to use DeepSeek V4.1-Flash through the Open
> Platform API solely as a reference/comparison model in an internal
> automated evaluation pipeline (not for training or distillation). We
> have not made API calls for this use. Please answer yes/no or with the
> exact clause:
>
> 1. Does the training opt-out in your Privacy Policy apply to Open Platform API traffic?
> 2. Can it be enabled prospectively before any API request?
> 3. Is it account-wide, project-wide or product-specific?
> 4. Once enabled, are API inputs excluded from model training, model improvement and optimization datasets?
> 5. Does DeepSeek retain Open Platform API prompts, and for how long?
> 6. May confidential evaluation prompts be submitted under this setting?
> 7. May we retain responses and metadata for internal benchmark audit?
>
> No confidential material is included. Thank you.

**Expected evidence:** Tier B reply or Tier A documentation; Tier C setting evidence for DSK-03.
**Interim note only:** if the mechanism is documented and can be applied before execution, record `HOLDOUT_PATH_RESOLVABLE_BY_PRE_EXECUTION_PROVIDER_SETTING` — this is **not** `PERMITTED`.

### DeepSeek account-setting inspection checklist

*(Owner-authorized only. DSK-02 is READ-ONLY; DSK-03 is conditional.)*

- [ ] DSK-02 authorized by action id. Log in and **look only** — save nothing.
- [ ] Screenshot every privacy/data-use/training page reachable from the Open Platform account (identifiers redacted); record "no such setting found" if none exists.
- [ ] Record the documentation URL for each setting found.
- [ ] Do **not** toggle any setting under DSK-02.
- [ ] DSK-03 only after DSK-01/DSK-02 evidence is verified AND the owner authorizes DSK-03 separately: capture before/after/reload screenshots and the evidence record.

---

## Kimi K3

**Action:** KMI-01 (email, P1); KMI-02 (accept enterprise term, conditional, P2).
**Blockers targeted:** `PROVIDER_TRAINING_ON_INPUTS`, `WRITTEN_PROVIDER_CLARIFICATION_REQUIRED`.

Ordinary hosted terms are already confirmed unsuitable for the private
holdout (Moonshot ToS §4 permits use of Customer Content to improve the
Services and requires a separate written agreement to restrict it). Do
**not** ask whether the ordinary terms are safe; ask what the enterprise
route can provide.

| ID | Question |
|---|---|
| KMI-Q1 | Can Moonshot provide a written API arrangement under which Customer Content is NOT used for model training or model improvement? |
| KMI-Q2 | Under it, do confidential evaluation prompts remain confidential? |
| KMI-Q3 | Is retention defined (what period)? |
| KMI-Q4 | May ORNEUR retain its own prompts, outputs and metadata? |
| KMI-Q5 | Is automated evaluation permitted? |
| KMI-Q6 | Is Kimi K3 model identity sufficiently attributable (stable identifier/version metadata)? |
| KMI-Q7 | Does the arrangement require an enterprise plan? |
| KMI-Q8 | Is there a minimum spend? |
| KMI-Q9 | Does it require a contract? |
| KMI-Q10 | Can it apply to Kimi K3 specifically? |
| KMI-Q11 | Does it change the endpoint or model identity? |
| KMI-Q12 | Is it available without committed paid spend? |

**Draft (not sent):**

> Subject: Enterprise written arrangement — no-training terms for Kimi K3 API
>
> Hello,
>
> We are ORNEUR. Your OpenPlatform Terms §4 states that customers
> requiring restrictions on the use of Customer Content for training or
> improving Moonshot AI models may discuss enterprise arrangements or
> separate written agreements. We would use Kimi K3 solely as an internal
> automated evaluation/reference model and have made no API calls. Could
> you tell us, yes/no or by exact clause, whether such an arrangement can
> provide: (1) no use of Customer Content for training or model
> improvement; (2) confidentiality of evaluation prompts; (3) a defined
> retention period; (4) our right to retain our own prompts/outputs/
> metadata; (5) permission for automated evaluation; (6) an attributable
> Kimi K3 model identifier/version? And: (7) does it need an enterprise
> plan, (8) a minimum spend, (9) a contract; (10) can it apply to Kimi
> K3; (11) does it change the endpoint or model identity; (12) is it
> available without committed paid spend?
>
> We are not negotiating or accepting terms with this message and include
> no confidential material. Thank you.

**Expected evidence:** Tier B reply. **A reply describing an arrangement is not an executed agreement** — `private_holdout_status` BLOCKED → PERMITTED requires an executed written agreement (KMI-02), separately authorized by the owner, with terms stored and hashed.

---

## GLM-5.3 flagship

**Action:** GLM-01 (email, P1); GLM-02 (no-training/no-retention enablement, conditional, P2).
**Blockers targeted:** `TERMS_AMBIGUITY`, `AUTOMATED_EVALUATION_UNRESOLVED`, `PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED`, `PROVIDER_ACCOUNT_SETTING_REQUIRED`.
GLM-5.3-Flash evidence must never substitute for this reference.

| ID | Question |
|---|---|
| GLM-Q1 | Please provide the current API Data Processing Addendum. |
| GLM-Q2 | May GLM-5.3 be used for automated internal evaluation? |
| GLM-Q3 | May raw prompts/outputs/metadata be retained for benchmark audit? |
| GLM-Q4 | Are API inputs used for training/model improvement? |
| GLM-Q5 | Is no-retention available? |
| GLM-Q6 | Is no-training available? |
| GLM-Q7 | Do those controls apply to GLM-5.3? |
| GLM-Q8 | Can private benchmark prompts remain confidential? |
| GLM-Q9 | What stable model identifier/version metadata does the API return? |
| GLM-Q10 | What account settings are required? |

**Draft (not sent):**

> Subject: GLM-5.3 API — Data Processing Addendum request and evaluation-use questions
>
> Hello,
>
> We are ORNEUR. We plan to use GLM-5.3 solely as a reference/comparison
> model in an internal automated evaluation pipeline (not for training
> or distillation) and have made no API calls. Your Privacy Policy
> refers API customers to a Data Processing Addendum for API Services.
> (1) Please provide the current version. Please also answer yes/no or
> by clause: (2) may GLM-5.3 be used for automated internal evaluation;
> (3) may we retain raw prompts/outputs/metadata for benchmark audit;
> (4) are API inputs used for training or model improvement; (5) is
> no-retention available; (6) is no-training available; (7) do those
> controls apply to GLM-5.3; (8) can private benchmark prompts remain
> confidential; (9) what stable model identifier/version metadata is
> returned; (10) what account settings are required?
>
> No confidential material is included. Thank you.

**Expected evidence:** Tier A (published DPA) and/or Tier B reply. **Not assumed:** the September 2026 no-retention mechanism was reported only by third parties.

---

## MiniMax M3

**Action:** MNX-01 (applicability clarification — **not** the notice, P1); MNX-02 (conditional notice, P2).
**Blockers targeted:** `COMMERCIAL_USE_AMBIGUITY`, `ACCESS_PATH_UNVERIFIED`, `WRITTEN_PROVIDER_CLARIFICATION_REQUIRED`.
Recipient: `api@minimax.io` (the contact listed in the license).

| ID | Question |
|---|---|
| MNX-Q1 | Does using MiniMax M3 ONLY as an internal evaluation/reference model while developing a commercial ORNEUR product constitute **Commercial Use** under the MiniMax Community License? (Direct YES/NO or exact clause.) |
| MNX-Q2 | (Secondary) Which hosted-API terms govern M3 API access, and do they cover evaluation use, retention, and non-training? |

**Draft 1 — clarification (not sent):**

> Subject: M3 licensing — applicability of Commercial Use to internal-only evaluation
>
> Hello,
>
> We are ORNEUR. We would use MiniMax M3 only as an internal
> evaluation/reference model, with outputs scored internally. No MiniMax
> weights would be incorporated into our product, and the model would not
> be offered to any third party. ORNEUR may eventually be commercial. Does
> this use constitute "Commercial Use" under clause 3 of the MiniMax
> Community License? A direct YES/NO or the exact clause would be ideal.
> Secondarily, which hosted-API terms govern access to M3, and do they
> address evaluation use, data retention and non-training?
>
> We are not sending any notice with this message and include no
> confidential material. Thank you.

**Draft 2 — conditional notice (not sent; only if MNX-Q1 = YES or the owner separately elects the conservative reading):**

> Subject: M3 licensing — notice
>
> Hello,
>
> Per the MiniMax Community License, we give notice that ORNEUR uses
> MiniMax M3 as an internal, non-redistributed evaluation/reference
> model. Our aggregate yearly revenue is below the threshold requiring
> prior written authorization. We will include "Built with MiniMax M3"
> attribution where required.

**Expected evidence:** Tier B reply. If YES, the future compliance path is attribution plus a one-time notice below the revenue threshold. **The notice is not sent in this phase.**

---

## Qwen3.8-Max

**Action:** QWN-01 (email, P0).
**Blockers targeted:** `TERMS_AMBIGUITY`, `AUTOMATED_EVALUATION_UNRESOLVED`, `MODEL_IDENTITY_INSUFFICIENT`.
Private holdout is **PERMITTED** on Alibaba Cloud Model Studio's own customer-data statements and is not reopened absent contradictory evidence. Do not conflate Qwen3.8-Max with the open-weight `Qwen/Qwen3.8-2.4T-A95B`. Do not call the API.

| ID | Question |
|---|---|
| QWN-Q1 | Is automated internal benchmarking/evaluation permitted? |
| QWN-Q2 | May Qwen3.8-Max outputs be scored and retained internally? |
| QWN-Q3 | Does Alibaba expose a stable dated snapshot such as `qwen3.8-max-0902` (or equivalent)? |
| QWN-Q4 | If so, is it immutable? |
| QWN-Q5 | Does response metadata expose the actual serving version? |
| QWN-Q6 | Can the mutable alias `qwen3.8-max` change underneath ORNEUR? |
| QWN-Q7 | Can a dated model identifier be used for the entire future evaluation? |
| QWN-Q8 | What is the exact API model identifier for the dated version? |

**Draft (not sent):**

> Subject: qwen3.8-max — automated benchmarking permission and version stability
>
> Hello,
>
> We are ORNEUR. We plan to use qwen3.8-max via Alibaba Cloud Model
> Studio solely as a reference/comparison model in an internal automated
> evaluation pipeline (not for training or distillation) and have made no
> API calls. Please answer yes/no or by clause: (1) is automated internal
> benchmarking/evaluation permitted; (2) may outputs be scored and
> retained internally; (3) is there a stable dated snapshot such as
> qwen3.8-max-0902, (4) is it immutable, (5) does response metadata expose
> the actual serving version; (6) can the mutable alias qwen3.8-max change
> underneath us; (7) can a dated identifier be used for a whole
> evaluation; (8) what is the exact API model identifier for the dated
> version?
>
> No confidential material is included. Thank you.

**Expected evidence:** Tier A version documentation and/or Tier B reply. `model_identity_attributable` FALSE → TRUE requires `PROVIDER_VERSION_IDENTITY` evidence — a plain "yes it's stable" without a verifiable identifier is insufficient.
