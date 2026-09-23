# Qwen3.8-Flash-Next License Analysis — Phase 21B.4.14

**Purpose:** determine the truth of whether `Qwen/Qwen3.8-Flash-Next` can
be admitted as an ORNEUR Genesis deployable foundation candidate. This
is a license/terms/identity/documentation-only phase — no GPU, no
weight download, no inference, no benchmark.

## 1. Identity re-verification

- Repository: `Qwen/Qwen3.8-Flash-Next`
- Live HF API `sha` (current `main`): `de4b8e4d43b917e7706784d8bb445c9af86a3540`
- Registry's pinned `exact_immutable_revision`: `de4b8e4d43b917e7706784d8bb445c9af86a3540`
- **Main has NOT moved past the pinned revision — they are identical.**
- `lastModified`: `2026-08-27T05:03:36.000Z` (matches registry's `revision_timestamp` exactly)
- `config.architectures`: `["Qwen4ExpForConditionalGeneration"]` (matches registry)
- `safetensors.total`: `179999981459` (matches registry's `total_parameters` exactly)
- `safetensors.parameters`: `{"BF16": 179999981424, "I64": 35}` (matches registry's `parameters_by_dtype` exactly)

All material identity facts re-confirmed live against the primary source
(Hugging Face Hub API), with zero drift from the registry's existing record.

## 2. Primary license source

- File: `LICENSE` at repository root
- Fetched from: `https://huggingface.co/Qwen/Qwen3.8-Flash-Next/raw/main/LICENSE`
  AND `https://huggingface.co/Qwen/Qwen3.8-Flash-Next/raw/de4b8e4d43b917e7706784d8bb445c9af86a3540/LICENSE`
- Retrieval timestamp: 2026-09-23 (this phase)
- Content SHA-256 (both `main` and pinned revision): `a0dc422560841fd68e06d974907f8b4c709bca44a67daad2b528437bdf676c08`
- **Pinned and current-main license text are byte-identical.** See §13.
- Full text persisted verbatim at:
  `docs/orneur/phase-21/evidence/QWEN3_8_FLASH_NEXT_LICENSE_PRIMARY_SOURCE_2026-09-23.txt`
- README/model-card declaration (`main/README.md` front matter):
  `license: other`, `license_name: qwen-community-1.0`, `license_link: LICENSE`
  — consistent with the license file's own self-identification as
  "Qwen Community License 1.0".
- License name: **Qwen Community License 1.0**
- Official licensing contact (stated in the license text itself):
  `model-business@notice.qwencloud.com`

This analysis is built entirely from the actual retrieved LICENSE file
text above — not from Hugging Face metadata tags, summaries, blog posts,
or secondary articles.

## 3. Full license structure (verbatim, as retrieved)

The license consists of:
1. A copyright notice (`Copyright (c) 2026 Qwen`).
2. A broad MIT-style grant clause naming the exact rights granted and
   defining "Use"/"Using".
3. **Condition 1** — an attribution/display obligation, conditioned on
   scale (MAU or revenue threshold).
4. **Condition 2** — a separate-license requirement for two named
   business categories ("Model as a Service" and "AI Work Assistant"),
   with defined terms for both and one carve-out for pure internal use.
5. A standard "AS IS" disclaimer of warranty and limitation of liability,
   plus a compliance-with-law / no-third-party-IP-infringement clause.
6. A licensing-questions contact address.

No other numbered conditions exist in the retrieved text. No
termination clause, no governing-law/dispute-forum clause, and no
explicit output-ownership clause are present.

## 4. The grant clause (exact text)

> "Permission is hereby granted, free of charge, to any person obtaining
> a copy of this software, including the model weights, parameters,
> configuration files, inference code and associated documentation
> files (collectively, the "Software"), to deal in the Software without
> restriction, including without limitation the rights to use, copy,
> modify, merge, publish, distribute, sublicense, sell, deploy, host,
> fine-tune, and create derivative works from (collectively, "Use" or
> "Using") copies of the Software; and to permit persons to whom the
> Software is furnished to do so, subject to the following conditions:"

This is a broad, explicit grant naming: use, copy, modify, merge,
publish, distribute, sublicense, sell, deploy, host, fine-tune, and
create derivative works — **all EXPLICITLY_GRANTED**, but every one of
these rights is **subject to** Conditions 1 and 2 below, not
unconditional.

## 5. Condition 1 — commercial-scale attribution (exact text)

> "1. The above copyright notice and this permission notice shall be
> included in all copies or substantial portions of the Software. If
> the Software (or any derivative works thereof) is Used for any of the
> licensee's commercial products or services that have more than
> 100,000,000 monthly active users or US$ 20,000,000 (or equivalent in
> other currencies) monthly revenue, respective model name must be
> prominently displayed on the user interface of such product or
> service; and,"

**Exact thresholds:**
- MAU threshold: **> 100,000,000 monthly active users**
- Revenue threshold: **> US$ 20,000,000/month** (or currency equivalent)
- Trigger: either threshold alone is sufficient ("or")
- Obligation once triggered: model name must be **prominently displayed
  on the user interface** of the qualifying product/service
- Applies explicitly to **derivative works**, not only the unmodified
  Software
- **This condition is NOT a separate-license trigger.** It is an
  attribution/display obligation only. It does not block Use; it adds a
  UI-labeling requirement once the licensee's product crosses either
  threshold.

## 6. Condition 2 — MaaS / AI Work Assistant separate-license gate (exact text)

> "2. If the licensee or any of its affiliates conducts a Model as a
> Service or AI Work Assistant business, the licensee shall obtain a
> separate license from Qwen before Using the Software or its
> derivative works for any commercial purpose. The foregoing
> requirement shall not apply to the licensee's internal Use of the
> Software, provided that such Use does not make the Software, its
> outputs, or its underlying model capabilities available to any third
> party."

**Definitions (exact text):**

> ""Model as a Service" means giving a third party access to language
> model inference or fine-tuning (e.g., via API or a hosted endpoint) in
> a manner that allows such third parties to exercise meaningful control
> over the inputs, parameters, or training data. This does not include
> the mere relaying of requests to models hosted by other third
> parties."

> ""AI Work Assistant" means an independent AI-powered product primarily
> designed for AI-assisted coding or office productivity (e.g., Qoder
> and QwenWork). It does not include: (a) a single-purpose AI tool (such
> as an AI translation tool); (b) an AI assistant primarily designed for
> a domain other than coding or office productivity (such as Taobao AI
> Shopping Assistant or AMap AI Chat); or (c) an AI assistant that is a
> feature of a product whose primary purpose is not AI-assisted coding
> or office productivity."

**Internal-use carve-out:** the separate-license requirement does NOT
apply to internal use that does not expose the Software, its outputs, or
its underlying model capabilities to any third party. ORNEUR's planned
product is explicitly a third-party-facing commercial platform (end
users interacting with ORNEUR models), so **this carve-out does not
apply to ORNEUR's planned use** — ORNEUR cannot rely on "internal use
only" to avoid Condition 2 analysis.

## 7. ORNEUR classification — Model as a Service

See `QWEN3_8_FLASH_NEXT_PRODUCT_CLASSIFICATION_2026-09-23.json` for the
full clause-by-clause table. Summary:

The MaaS definition turns on whether third parties (ORNEUR's end users)
are given access to inference "in a manner that allows such third
parties to exercise meaningful control over the **inputs**, parameters,
or training data" — the three conditions are joined by **"or"**, so
satisfying any ONE of them is sufficient to meet the definition.

This creates a **genuine, material interpretive fork**:

- **Narrow reading:** "meaningful control" modifies all three nouns
  collectively in spirit — i.e., the clause is really aimed at raw
  API/hosted-endpoint access where a third party can manipulate model
  *parameters* (temperature, system prompts, sampling config) or supply
  *training data* (fine-tuning-as-a-service), not merely type a chat
  message. Under this reading, a locked-down consumer chat UI where
  users only provide conversational input, with no parameter control
  and no fine-tuning access, might fall outside MaaS.
- **Broad reading:** the "or" is genuinely disjunctive, and ordinary
  end-user prompt text IS "input" over which the user has "meaningful
  control" — they choose exactly what to type, with no restriction.
  Under this reading, essentially any commercial hosted chat product
  where users type free-form prompts satisfies the "inputs" prong of
  MaaS by itself, regardless of whether parameters or training data are
  ever exposed.

The license text does not resolve which reading is correct. Per this
phase's explicit instruction: **"If ordinary user prompt control appears
sufficient to create a serious MaaS interpretation: flag this as a
MATERIAL LICENSE RISK. Do not convert ambiguity to permission."**

**This is flagged as a MATERIAL LICENSE RISK.** ORNEUR's planned product
— "a commercial AI web application/platform in which end users interact
with ORNEUR models, including Genesis" — plainly gives third parties
(ORNEUR's own end users) access to language model inference. Whether
that access rises to "meaningful control over the inputs" under the
broad reading is not resolved by the text, and the described product
explicitly may add "APIs or hosted access depending on product
evolution" — API-based access would unambiguously satisfy MaaS under
either reading (API access is the license's own explicit example of
MaaS: "e.g., via API or a hosted endpoint").

**Classification: AMBIGUOUS**, with an identified path (API/hosted
programmatic access) that would resolve to a clear MATCH once ORNEUR's
product roadmap firms up.

## 8. ORNEUR classification — AI Work Assistant

The AI Work Assistant definition requires the product be **"primarily
designed for AI-assisted coding or office productivity."** ORNEUR's
stated planned functionality spans "conversational inference, reasoning,
coding, research, tool use, agentic execution, project/work workflows"
— i.e., coding is one of several listed capabilities, not the product's
singular primary design purpose, alongside general conversational/
reasoning/research use that resembles neither "coding" nor "office
productivity" narrowly construed.

- Exclusion (b) — "an AI assistant primarily designed for a domain other
  than coding or office productivity" — is itself ambiguous as applied
  to ORNEUR, since ORNEUR is not "primarily designed for" any single
  named domain either; it is described as general-purpose.
- The named AI Work Assistant examples (Qoder, QwenWork) are
  single-domain-focused coding/office tools, unlike the broader,
  multi-capability platform ORNEUR is described as.

**Classification: AMBIGUOUS, leaning NO MATCH** — the stated ORNEUR
product does not read as "primarily designed for AI-assisted coding or
office productivity" the way Qoder/QwenWork are, but the explicit
inclusion of "coding" and "project/work workflows" among ORNEUR's listed
capabilities means this cannot be called a clean NO MATCH without a
firmer statement of ORNEUR's actual primary design purpose.

## 9. Commercial-threshold exposure (Condition 1)

ORNEUR is a pre-scale product today (nowhere near 100M MAU or
US$20M/month revenue). Per this phase's explicit instruction not to
treat today's small user base as permanent clearance: **if ORNEUR
succeeds and crosses either threshold, Condition 1's UI model-name
attribution obligation activates automatically** and applies to
derivative (fine-tuned) works as well as the unmodified Software. This
is a **compliance obligation to track, not a blocker** — Condition 1 by
itself never requires a separate license; it only requires attribution
once triggered.

**Threshold exposure: FUTURE** (not currently triggered; will trigger
automatically on scale, with no separate-license consequence attached
to Condition 1 alone).

## 10. Fine-tuning / derivative / redistribution / hosted-serving / sublicensing rights

| Right | Status | Clause |
|---|---|---|
| Fine-tuning | EXPLICITLY_GRANTED | Grant clause: "...fine-tune..." |
| LoRA/QLoRA | EXPLICITLY_GRANTED (subsumed under fine-tune/modify) | Grant clause |
| Continued pretraining | EXPLICITLY_GRANTED (subsumed under "modify"/"create derivative works") | Grant clause — not a named term, but falls within the broad "modify... create derivative works" grant |
| Preference optimization (DPO/RLHF-style) | EXPLICITLY_GRANTED (subsumed under "modify"/"fine-tune") | Grant clause |
| RL-based post-training | EXPLICITLY_GRANTED (subsumed under "modify"/"fine-tune") | Grant clause |
| Derivative checkpoints | EXPLICITLY_GRANTED | Grant clause: "...create derivative works from..." |
| Redistribution | EXPLICITLY_GRANTED | Grant clause: "...distribute..." |
| Hosted serving | EXPLICITLY_GRANTED, but SUBJECT TO Condition 2 if the hosting constitutes MaaS | Grant clause: "...deploy, host..."; Condition 2 |
| Sublicensing | EXPLICITLY_GRANTED | Grant clause: "...sublicense..." |

All of these are explicitly named in the single broad grant clause —
none are left to silence or inference. However, **every one of them is
qualified by "subject to the following conditions"** — i.e., the grant
is not unconditional; Conditions 1 and 2 constrain how these rights may
be exercised commercially, per §5–§6 above. None of the later clauses
narrow or contradict the specific named rights themselves (fine-tune,
distribute, etc. are not re-restricted anywhere else in the text) — only
Condition 2's MaaS/AI-Work-Assistant gate conditions *commercial* use of
those rights on obtaining a separate license, if the licensee's business
falls in either category.

## 11. Distillation / teacher / synthetic-data use

The license does not use the words "distillation," "synthetic data," or
"training a separate model from outputs" anywhere. The grant clause's
"create derivative works from... copies of the Software" plausibly
covers fine-tuning THIS model on its own outputs, but does not clearly
extend to training a **wholly separate, differently-architected student
model** using this model's outputs as training data — that is a
different act than modifying or deriving from "the Software" itself.

The "AS IS" clause disclaims warranty for "any output and results
therefrom," which acknowledges outputs exist as a category but does not
grant or restrict rights over them.

**Per this phase's explicit instruction, recorded as:
`DISTILLATION_RIGHTS_UNRESOLVED`.** No permission is invented from
silence.

## 12. Output rights

No clause grants Qwen ownership of outputs, and no clause explicitly
restricts downstream use of outputs beyond the general "AS IS" warranty
disclaimer and the general "must comply with applicable laws... must not
infringe the intellectual property rights of any third party" clause
(which is a general compliance obligation applicable to any use, not an
output-specific restriction).

**Output rights: no explicit restriction found; not explicitly granted
as a separate right either — outputs are mentioned only in the
disclaimer clause.**

## 13. Termination / compliance / notice obligations

- **Attribution obligation:** copyright notice + permission notice must
  be included in all copies/substantial portions (unconditional, from
  the moment of first use).
- **Model-name display obligation:** conditional on Condition 1's
  MAU/revenue thresholds (see §5/§9).
- **Copyright notice requirement:** yes — "shall be included in all
  copies or substantial portions."
- **License-copy requirement:** implied by "this permission notice shall
  be included," consistent with standard MIT-style license practice.
- **Separate-license trigger:** Condition 2, MaaS/AI Work Assistant
  business (see §6).
- **Compliance obligation:** "The use of the Software must comply with
  applicable laws and regulations, and must not infringe the
  intellectual property rights of any third party."
- **Termination provision:** **NONE FOUND** in the retrieved text — no
  explicit revocation-on-breach or termination-for-cause clause exists.
- **Governing law / dispute terms:** **NONE FOUND** — no explicit
  governing-law or forum-selection clause exists.
- **Licensing-contact mechanism:** `model-business@notice.qwencloud.com`
  (stated verbatim in the license text).

## 14. Pinned-revision license integrity

- `pinned_license_sha256`: `a0dc422560841fd68e06d974907f8b4c709bca44a67daad2b528437bdf676c08`
- `current_license_sha256` (as of 2026-09-23): `a0dc422560841fd68e06d974907f8b4c709bca44a67daad2b528437bdf676c08`
- **Identical: YES.** No semantic diff required — the retrieved bytes
  for `main` and the pinned revision are byte-for-byte identical, and
  the pinned revision IS the current `main` HEAD (see §1). ORNEUR's
  candidate admission analysis is based on the exact license governing
  the exact artifact that would be evaluated.

## 15. Admission determination

Per the decision logic (phase spec §15):

- Outcome A (`LICENSE_CLEAR_FOR_ORNEUR_COMMERCIAL_GENESIS_USE`) requires
  the primary-source text to **clearly establish** that ORNEUR's
  intended commercial deployment does NOT trigger Condition 2's
  separate-license requirement. It does not — the MaaS "inputs" prong is
  genuinely disjunctive and unresolved as applied to a third-party-facing
  chat/API product, and the AI Work Assistant classification is
  ambiguous given ORNEUR's mixed coding/general-purpose description.
  **Outcome A is NOT available.**
- Outcome B (`LICENSE_REQUIRES_SEPARATE_QWEN_PERMISSION`) requires the
  text to **clearly place** planned ORNEUR use within a separate-license
  category. The text does not clearly do this either — it is genuinely
  ambiguous which reading of "meaningful control over the inputs"
  applies to a locked-down chat UI, and ORNEUR's future API plans are
  explicitly not yet fixed ("depending on product evolution").
  **Outcome B is not clearly established either**, though it is the
  MORE LIKELY outcome once ORNEUR's product roadmap (especially any API
  exposure) firms up.
- Outcome C (`LICENSE_UNRESOLVED`) applies when classification depends
  on ambiguous wording or missing business facts. **This is the correct
  outcome.** Missing business facts, each marked
  `BUSINESS_FACT_REQUIRED` in the classification table:
  - Will ORNEUR expose a public/partner API giving third parties
    programmatic access with parameter control (temperature, system
    prompts, etc.)? (Would resolve MaaS to a clear MATCH.)
  - Will ORNEUR ever allow users/partners to fine-tune or otherwise
    influence training data via the platform?
  - Is ORNEUR's stated PRIMARY design purpose going to be
    coding/office-productivity-centric, or general-purpose multi-domain
    AI? (Resolves AI Work Assistant classification.)
  - Will there be a B2B/enterprise hosted-inference offering distinct
    from the consumer-facing chat product?

**DETERMINATION: `LICENSE_UNRESOLVED`.**

This is NOT a capability rejection. `Qwen/Qwen3.8-Flash-Next` remains a
registered, non-eliminated Genesis deployable candidate. Its runtime
smoke eligibility remains `BLOCKED` pending resolution of the business
facts identified above (or, alternatively, pending written clearance
from Qwen — see the draft clearance request:
`QWEN3_8_FLASH_NEXT_QWEN_CLEARANCE_REQUEST_DRAFT_2026-09-23.md`).

## 16. No "best available" pressure

This determination was reached by testing ORNEUR's planned product
facts against the license's exact defined terms, not by looking for
wording that would let a technically attractive candidate through.
Genesis doctrine holds that intelligence does not override hard license
gates — a potentially excellent candidate remains blocked exactly as
the evidence requires, no more and no less permissively.
