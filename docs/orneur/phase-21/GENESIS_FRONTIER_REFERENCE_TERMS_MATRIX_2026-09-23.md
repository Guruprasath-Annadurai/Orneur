# Genesis Frontier Reference Terms Matrix — Phase 21B.4.17 (reconciled in 21B.4.17.1)

**PRIMARY-SOURCE LICENSE/TERMS RESEARCH ONLY. No GPU, no frontier
inference, no paid API call, no benchmark.**

Reference-evaluation admission and teacher/distillation admission are
**independent decisions** (§10) — a reference may be
`REFERENCE_EVALUATION_ADMITTED` while `TEACHER_USE_BLOCKED` or
`TEACHER_USE_STATUS=NOT_EVALUATED`. Neither status is inferred from the
other anywhere in this matrix.

**Phase 21B.4.17.1 corrections** (independent audit found these three
evidence/status inconsistencies in the original 21B.4.17 version of
this matrix):

1. **DeepSeek V4.1-Flash's automated-evaluation status** was
   REVIEW_REQUIRED merely because the literal word "benchmark" was
   absent from the fetched ToS text, while its access preflight was
   already marked ready-pending — an internal contradiction (a future
   Genesis run IS automated evaluation). Re-evaluated against the
   actual clause and corrected to CLEAR.
2. **MiniMax M3's commercial-use classification** rested on an
   unsupported "internal use == non-commercial use" inference. The
   license's actual test is whether use is "primarily intended for
   commercial advantage," not whether the specific run happens
   internally — and ORNEUR's Genesis program is explicitly intended to
   become a commercial product. Corrected to REVIEW_REQUIRED.
3. **Mistral Large 3's teacher/distillation admission** rested solely
   on Apache-2.0's derivative-works grant over the model WEIGHTS, which
   is not the same claim as an affirmative license to generated
   OUTPUTS or an explicit distillation permission. Corrected to
   NOT_EVALUATED.

## License/terms and evaluation admission

| Reference | License/terms | Status | Evaluation admission | Basis |
|---|---|---|---|---|
| DeepSeek V4.1-Flash | Plain MIT (weight license) + DeepSeek Open Platform ToS (API) | **CLEAR** | **ADMITTED** | MIT unrestricted; ToS §4.2 broadly permissive, including automated evaluation (corrected 21B.4.17.1) |
| GLM-5.3 (flagship) | Z.ai custom license | **REVIEW_REQUIRED** | REVIEW_REQUIRED | Evaluation use, output retention, teacher/distillation all unaddressed by the license text |
| Mistral Large 3 | Apache-2.0 | **CLEAR** | **ADMITTED** | No field-of-use restriction on the weight license itself; confirmed via 3 independent first-party sources |
| MiniMax M3 | MiniMax Community License, clause 3 | **REVIEW_REQUIRED** (corrected 21B.4.17.1, was CLEAR) | REVIEW_REQUIRED (corrected, was ADMITTED) | Clause 3's operative test is "primarily intended for commercial advantage or monetary compensation" — genuinely ambiguous for a benchmark used while developing a commercial ORNEUR foundation model, not resolved by "internal" alone |
| Qwen3.8-Max | Alibaba Cloud Product ToS | **REVIEW_REQUIRED** | REVIEW_REQUIRED | Unverified holdout-relevant clause, unconfirmed automated-benchmarking permission |
| Kimi K3 | Kimi K3 License (Modified-MIT + MaaS threshold) | **CLEAR** (for internal, non-third-party-exposing use, §4 carve-out) | **ADMITTED** | Internal ORNEUR evaluation is not MaaS/third-party exposure |

## Teacher / distillation admission (SEPARATE from evaluation admission)

| Reference | Teacher/distillation status | Evidence |
|---|---|---|
| DeepSeek V4.1-Flash | **ADMITTED** | DeepSeek Open Platform ToS §4.2 explicitly names "training other models (such as model distillation)" as a permitted use case — the single strongest, most direct permission found this phase |
| GLM-5.3 (flagship) | NOT_EVALUATED | License silent on distillation; evaluation admission itself is also unresolved |
| Mistral Large 3 | **NOT_EVALUATED** (corrected 21B.4.17.1, was incorrectly ADMITTED) | Apache-2.0 grants rights in the licensed Work and Derivative Works OF the Work (the weights) — it does not itself state that generated OUTPUTS are Apache-licensed or that training on them is a licensed derivative-work activity. No express restriction was found either, but the derivative-work grant is not treated as an affirmative separate output/teacher license. Evaluation-reference admission is unaffected — it rests on the weight license, which remains clear. |
| MiniMax M3 | NOT_EVALUATED | License addresses commercial deployment of fine-tuned/distilled derivatives but not pure non-commercial teacher use; independently unresolved regardless of the evaluation-admission correction above |
| Qwen3.8-Max | **BLOCKED** | Alibaba's anti-competing-product ToS clause creates a genuine, material risk given Genesis's own purpose of training a competing frontier foundation model |
| Kimi K3 | NOT_EVALUATED | License silent on distillation/synthetic-data teacher use |

The only reference with **explicit, affirmative** teacher/distillation
permission evidence is DeepSeek V4.1-Flash (a named ToS clause) — every
other reference's teacher status is either genuinely blocked by a real
conflict-of-interest clause (Qwen3.8-Max) or simply unaddressed by its
license (GLM-5.3, Mistral Large 3, MiniMax M3, Kimi K3), recorded as
`NOT_EVALUATED`, never silently upgraded to `ADMITTED` merely because a
permissive weight license exists.

## Evidence retention and holdout compatibility

| Reference | Evidence retention | Private holdout compatibility |
|---|---|---|
| DeepSeek V4.1-Flash | PERMITTED (ToS §4.2 output-rights assignment) | PERMITTED_IN_PRINCIPLE |
| GLM-5.3 (flagship) | REVIEW_REQUIRED | REVIEW_REQUIRED |
| Mistral Large 3 | PERMITTED | PERMITTED_IN_PRINCIPLE |
| MiniMax M3 | **REVIEW_REQUIRED** (corrected 21B.4.17.1, was PERMITTED) | **REVIEW_REQUIRED** (corrected, was PERMITTED_IN_PRINCIPLE) — inherits the unresolved commercial-use question above |
| Qwen3.8-Max | REVIEW_REQUIRED | FAVORABLE_BUT_UNVERIFIED (opt-in-only training-on-content default is structurally favorable, but an unverified free-trial-content clause could restrict holdout use) |
| Kimi K3 | PERMITTED | **PATH_DEPENDENT** — self-host PERMITTED_IN_PRINCIPLE; hosted-API path trains on submitted content by default (ToS §4) unless an enterprise opt-out is negotiated, a real confidentiality incompatibility for that specific path |

No holdout prompts are authored this phase. No confidentiality claim is
made beyond what each provider's actual terms support.

## Commercial vs. internal evaluation use

- **MiniMax M3**: REVIEW_REQUIRED (corrected 21B.4.17.1) — clause 3's
  "primarily intended for commercial advantage" standard is a genuine
  ambiguity for ORNEUR's use, given Genesis's own commercial intent;
  not resolved by internal execution alone. Attribution requirement and
  one-time notice apply below the $20M/yr revenue threshold; prior
  written authorization is required only above it (corrected wording —
  not all Commercial Use requires prior permission).
- **Kimi K3**: internal eval CLEAR under §4's carve-out; MaaS-threshold
  ($20M/12mo) and attribution (>100M MAU or >$20M/mo) conditions apply
  only if ORNEUR's use profile changes
- **GLM-5.3**: commercial use permitted below a $10B/12mo aggregate MaaS
  revenue threshold, but this is orthogonal to the still-unresolved
  evaluation-use gap
- **DeepSeek V4.1-Flash, Mistral Large 3**: MIT/Apache-2.0 place no
  distinction between internal and commercial use — both CLEAR
  unconditionally for the weight license itself

## No post-hoc substitution

The six references remain exactly as locked in Phase 21B.4.17 §3: DeepSeek
V4.1-Flash, GLM-5.3 (flagship), Mistral Large 3, MiniMax M3, Qwen3.8-Max,
Kimi K3. No model was added, dropped, or silently replaced this phase or
in this reconciliation pass, regardless of any individual reference's
admission outcome. No reference was promoted merely to preserve quorum —
the corrections in this document reduce, not inflate, the quorum-counting
total (see GENESIS_FRONTIER_REFERENCE_PRIMARY_SOURCES_2026-09-23.json's
quorum_summary).
