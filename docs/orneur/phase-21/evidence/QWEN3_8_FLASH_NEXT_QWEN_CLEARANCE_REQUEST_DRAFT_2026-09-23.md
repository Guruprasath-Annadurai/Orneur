# DRAFT — Qwen Licensing Clearance Request (Qwen3.8-Flash-Next)

**STATUS: DRAFT ONLY. NOT SENT. Requires explicit owner authorization
before transmission to Qwen.**

**To:** model-business@notice.qwencloud.com
**Subject:** Qwen Community License 1.0 commercial-use clarification — Qwen3.8-Flash-Next

---

Hello,

We are evaluating `Qwen/Qwen3.8-Flash-Next` (pinned revision
`de4b8e4d43b917e7706784d8bb445c9af86a3540`) as a candidate foundation
model for ORNEUR, a commercial AI platform.

We have reviewed the Qwen Community License 1.0 text published in the
model repository and want to confirm our understanding of Condition 2
(the Model as a Service / AI Work Assistant separate-license
requirement) before proceeding with any commercial deployment.

Our planned use of the model (or a fine-tuned/derivative checkpoint of
it) would include:

1. Commercially hosting Qwen3.8-Flash-Next or a fine-tuned derivative of
   it as part of ORNEUR's platform.
2. Providing interactive inference to end users through a web-based chat
   interface, where users submit free-form text prompts and receive
   generated responses.
3. Providing coding, research, and agentic/tool-use functionality built
   on top of model inference.
4. Fine-tuning and/or otherwise post-training the model (e.g. LoRA,
   preference optimization, or similar techniques) and serving the
   resulting derivative through ORNEUR.
5. Potentially scaling beyond the license's stated 100,000,000
   monthly-active-user or US$20,000,000 monthly-revenue thresholds in
   the future, in which case we intend to comply with the model-name
   display/attribution requirement in Condition 1.
6. Potentially using model outputs for permitted synthetic-data
   generation or distillation workflows as part of a broader model
   training strategy, if and when we pursue that.

Given the definitions in the license:

> "Model as a Service" means giving a third party access to language
> model inference or fine-tuning (e.g., via API or a hosted endpoint) in
> a manner that allows such third parties to exercise meaningful control
> over the inputs, parameters, or training data.

We would appreciate clarification on the following specific questions:

1. **Does an ordinary consumer-facing chat interface** — where end users
   submit free-form text prompts and receive model-generated responses,
   with no access to model parameters, system prompts, or training
   data — constitute "meaningful control over the inputs" under the
   Model as a Service definition, on its own?
2. If we later expose a programmatic API (with request parameters such
   as temperature or system-prompt configuration) for partner/developer
   use, would that specific offering require a separate commercial
   license, while the consumer chat interface alone would not?
3. Does our planned use (items 1–4 above) require us to obtain a
   separate commercial license from Qwen before proceeding, under
   Condition 2?
4. Does our platform, as described, fall within the "AI Work Assistant"
   definition, given that coding and work/project workflows are among
   several capabilities offered alongside general conversational and
   research use (i.e., not a product "primarily designed for" coding or
   office productivity specifically)?
5. Is our planned use of model outputs for permitted synthetic-data
   generation / distillation workflows (training a separate model using
   this model's outputs) addressed by the existing license grant, or
   would that require separate permission?

We want to ensure full compliance with the Qwen Community License 1.0
before any commercial deployment, and would appreciate your guidance on
whether a separate license is required for our planned use as described
above.

Thank you for your time.

---

*This draft was prepared by Claude (ORNEUR's implementation/execution
agent) as part of Phase 21B.4.14's license-resolution work. It has not
been reviewed, edited, or sent by the owner. No communication with Qwen
has occurred. Sending this (or any revised version) requires explicit
owner authorization.*
