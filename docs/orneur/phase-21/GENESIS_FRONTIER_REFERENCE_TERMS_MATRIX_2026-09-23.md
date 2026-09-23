# Genesis Frontier Reference Terms Matrix — Phase 21B.4.17

**PRIMARY-SOURCE LICENSE/TERMS RESEARCH ONLY. No GPU, no frontier
inference, no paid API call, no benchmark.**

Reference-evaluation admission and teacher/distillation admission are
**independent decisions** (§10) — a reference may be
`REFERENCE_EVALUATION_ADMITTED` while `TEACHER_USE_BLOCKED` or
`TEACHER_USE_STATUS=NOT_EVALUATED`. Neither status is inferred from the
other anywhere in this matrix.

## License/terms and evaluation admission

| Reference | License/terms | Status | Evaluation admission | Basis |
|---|---|---|---|---|
| DeepSeek V4.1-Flash | Plain MIT (weight license) + DeepSeek Open Platform ToS (API) | **CLEAR** | **ADMITTED** | MIT unrestricted; ToS §4.2 broadly permissive |
| GLM-5.3 (flagship) | Z.ai custom license | **REVIEW_REQUIRED** | REVIEW_REQUIRED | Evaluation use, output retention, teacher/distillation all unaddressed by the license text |
| Mistral Large 3 | Apache-2.0 | **CLEAR** | **ADMITTED** | No field-of-use restriction; confirmed via 3 independent first-party sources |
| MiniMax M3 | MiniMax Community License | **CLEAR** (for non-commercial internal eval specifically) | **ADMITTED** | Explicit non-commercial free grant covers ORNEUR's internal evaluation use |
| Qwen3.8-Max | Alibaba Cloud Product ToS | **REVIEW_REQUIRED** | REVIEW_REQUIRED | Unverified holdout-relevant clause, unconfirmed automated-benchmarking permission |
| Kimi K3 | Kimi K3 License (Modified-MIT + MaaS threshold) | **CLEAR** (for internal, non-third-party-exposing use, §4 carve-out) | **ADMITTED** | Internal ORNEUR evaluation is not MaaS/third-party exposure |

## Teacher / distillation admission (SEPARATE from evaluation admission)

| Reference | Teacher/distillation status | Evidence |
|---|---|---|
| DeepSeek V4.1-Flash | **ADMITTED** | DeepSeek Open Platform ToS §4.2 explicitly names "training other models (such as model distillation)" as a permitted use case — the single strongest, most direct permission found this phase |
| GLM-5.3 (flagship) | NOT_EVALUATED | License silent on distillation; evaluation admission itself is also unresolved |
| Mistral Large 3 | **ADMITTED** | Apache-2.0's unrestricted derivative-works + sublicensing grant, no field-of-use limitation — an affirmative broad grant, not inferred from mere evaluation-use silence |
| MiniMax M3 | NOT_EVALUATED | License addresses commercial deployment of fine-tuned/distilled derivatives but not pure non-commercial teacher use |
| Qwen3.8-Max | **BLOCKED** | Alibaba's anti-competing-product ToS clause creates a genuine, material risk given Genesis's own purpose of training a competing frontier foundation model |
| Kimi K3 | NOT_EVALUATED | License silent on distillation/synthetic-data teacher use |

Note the asymmetry: DeepSeek and Mistral Large 3 are the only references
with **explicit, affirmative** teacher/distillation permission evidence
(a named ToS clause and an unrestricted OSS license respectively) — every
other reference's teacher status is either genuinely blocked by a real
conflict-of-interest clause (Qwen3.8-Max) or simply unaddressed by its
license (GLM-5.3, MiniMax M3, Kimi K3), which is recorded as
`NOT_EVALUATED`, never silently upgraded to `ADMITTED`.

## Evidence retention and holdout compatibility

| Reference | Evidence retention | Private holdout compatibility |
|---|---|---|
| DeepSeek V4.1-Flash | PERMITTED (ToS §4.2 output-rights assignment) | PERMITTED_IN_PRINCIPLE |
| GLM-5.3 (flagship) | REVIEW_REQUIRED | REVIEW_REQUIRED |
| Mistral Large 3 | PERMITTED | PERMITTED_IN_PRINCIPLE |
| MiniMax M3 | PERMITTED | PERMITTED_IN_PRINCIPLE |
| Qwen3.8-Max | REVIEW_REQUIRED | FAVORABLE_BUT_UNVERIFIED (opt-in-only training-on-content default is structurally favorable, but an unverified free-trial-content clause could restrict holdout use) |
| Kimi K3 | PERMITTED | **PATH_DEPENDENT** — self-host PERMITTED_IN_PRINCIPLE; hosted-API path trains on submitted content by default (ToS §4) unless an enterprise opt-out is negotiated, a real confidentiality incompatibility for that specific path |

No holdout prompts are authored this phase. No confidentiality claim is
made beyond what each provider's actual terms support.

## Commercial vs. internal evaluation use

Several references distinguish internal (non-commercial, non-third-party-
exposing) evaluation from commercial product evaluation, with different
terms for each:

- **MiniMax M3**: internal eval CLEAR; commercial evaluation
  SEPARATE_PERMISSION_REQUIRED ($20M/yr revenue threshold)
- **Kimi K3**: internal eval CLEAR under §4's carve-out; MaaS-threshold
  ($20M/12mo) and attribution (>100M MAU or >$20M/mo) conditions apply
  only if ORNEUR's use profile changes
- **GLM-5.3**: commercial use permitted below a $10B/12mo aggregate MaaS
  revenue threshold, but this is orthogonal to the still-unresolved
  evaluation-use gap
- **DeepSeek V4.1-Flash, Mistral Large 3**: MIT/Apache-2.0 place no
  distinction between internal and commercial use — both CLEAR
  unconditionally

## No post-hoc substitution

The six references remain exactly as locked in Phase 21B section 3 of the
21B.4.17 spec: DeepSeek V4.1-Flash, GLM-5.3 (flagship), Mistral Large 3,
MiniMax M3, Qwen3.8-Max, Kimi K3. No model was added, dropped, or silently
replaced this phase, regardless of any individual reference's admission
outcome.
