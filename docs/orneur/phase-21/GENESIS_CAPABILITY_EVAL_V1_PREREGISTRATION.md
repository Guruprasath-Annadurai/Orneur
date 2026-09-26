# Genesis Capability Eval V1 — Pre-registration

- Eval version: `genesis-capability-eval/1.0.0`; corpus `genesis-corpus/1.0.0`; architecture `orneur.eternal-architecture/1.1.0`; protocol `orneur.core-protocol/1.1.0`
- **Pre-registration SHA-256:** `b8b7e7430c2938c95980618bf9b0ffd2113c5234148fc5e896a910ec8750ad97`
- Harness SHA-256: `01a6b3b0b69bfba23053261b010de11ca91b2529cdc31259c82e777b600ea880`
- Dataset manifest SHA-256: `c8dfba1b3c479f197081fa4d374a2da71d0732c70ef7511f2512b45ccf2dda4d`
- Private holdout manifest SHA-256: `997d87967e804bd462fca25e9c7c4d5151a9451c41d42cc7b4408815770287b5`
- Training-exclusion manifest SHA-256: `7c6b98c326d1c53cce2f1ba33cc27f51b82348304bc88113ccc22a93f3576286`

## Status

`GENESIS_CAPABILITY_EVAL_V1_FROZEN = false`

The earlier design-level `GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY = true` is recorded historically and means only that the funnel *design* was structurally ready. The actual evaluation becomes frozen only when: corpus complete; floors frozen; manifests complete; hashes frozen; pre-registration frozen; harness tests pass; exact-SHA CI passes; independent ChatGPT audit passes. Exact-SHA CI and the independent audit are pending.

No model has been run. `foundation_selected=false`, `gpu_authorized=false`, `training_authorized=false`, `provider_inference_authorized=false`, `phase_21c_authorized=false`, no spending authorized.

## Corpus (private; no answers appear in this document)

Original ORNEUR-authored seeded procedural items; no external benchmark text copied. Corpus files live under `eval_private/genesis_capability_eval_v1/` and are excluded from the container build context. Splits: DEV (eval development), PILOT_TRAIN (Stage-3 pilot only), HOLDOUT (private qualification).

| Category | Role | DEV | PILOT_TRAIN | HOLDOUT |
|---|---|---|---|---|
| `instruction_following` | GATING | 20 | 100 | 200 |
| `strict_contracts` | REPORT_ONLY | 15 | 100 | 150 |
| `structured_outputs` | GATING | 18 | 100 | 180 |
| `reasoning` | GATING | 18 | 0 | 180 |
| `coding` | GATING | 10 | 0 | 100 |
| `mathematics` | GATING | 18 | 0 | 180 |
| `research` | GATING | 12 | 0 | 120 |
| `tool_use` | GATING | 12 | 60 | 120 |
| `long_context` | GATING | 6 | 0 | 170 |
| `multilingual` | GATING | 20 | 0 | 200 |
| `multimodal_where_applicable` | REPORT_ONLY | 6 | 0 | 60 |
| `verification` | GATING | 18 | 0 | 180 |
| `evidence_use` | GATING | 16 | 0 | 165 |
| `counterfactual_reasoning` | GATING | 12 | 0 | 120 |
| `hypothesis_testing` | GATING | 12 | 0 | 120 |
| `discovery_quality` | REPORT_ONLY | 6 | 0 | 60 |
| `cross_domain_transfer` | REPORT_ONLY | 6 | 0 | 60 |
| `information_gain_reasoning` | GATING | 12 | 0 | 120 |
| `latency` | PROTOCOL | 0 | 0 | 0 |
| `cost` | PROTOCOL | 0 | 0 | 0 |
| `trainability` | PROTOCOL | 0 | 0 | 0 |

Totals: {'DEV': 237, 'PILOT_TRAIN': 360, 'HOLDOUT': 2485}. Latency uses 12 protocol probes; cost and trainability are protocol definitions with no Q&A items.

## Frozen floors (gating categories)

Wilson 95% intervals on the mean item score. Adequately powered (n >= 100): FAIL iff the point estimate is below the floor. LOW_POWER (n < 100): may only FAIL, and only when the upper bound is below the floor. INCOMPLETE results fail closed. Stage 1 drops a model only when the upper bound of a 30-item slice is below the floor.

| Category | Floor | n | Chance | Margin | Wilson half-width at floor | Min detectable true rate (80% power, full) | (Stage 1, n=30) | Why |
|---|---|---|---|---|---|---|---|---|
| `instruction_following` | 0.45 | 200 | 0.02 | 0.43 | 0.069 | 0.35 | 0.22 | every item needs 2-4 jointly satisfiable verifiable constraints ALL met (chance is near 0); a competent instruction-tuned model commonly meets multi-constraint prompts on roughly half to most items, so 0.45 rejects models that cannot follow explicit format rules without rejecting borderline ones |
| `structured_outputs` | 0.65 | 180 | 0.0 | 0.65 | 0.066 | 0.545 | 0.405 | extraction from an explicit passage into a stated schema is the easiest gated skill; the Contract Engine can retry once, so the floor is set below the earlier 0.85 no-repair proposal but well above chance (which is near 0 for exact field values) |
| `reasoning` | 0.35 | 180 | 0.1469 | 0.203 | 0.072 | 0.25 | 0.13 | unique-answer logic puzzles with answer spaces of 3-6 (chance about 0.2); 0.35 requires clearly better than guessing while accepting small models |
| `coding` | 0.3 | 100 | 0.0 | 0.3 | 0.096 | 0.18 | 0.1 | small, specified functions with hidden tests; requires the hermetic sandbox (results without it are INCOMPLETE, never guessed) |
| `mathematics` | 0.45 | 180 | 0.0 | 0.45 | 0.073 | 0.345 | 0.22 | exact numeric answers (chance near 0); short multi-step arithmetic/number-theory items, so 0.45 separates models that compute from those that pattern-match |
| `research` | 0.45 | 120 | 0.01 | 0.44 | 0.089 | 0.325 | 0.22 | multi-hop answer AND exact citation set must both be right (chance near 0); 0.45 accepts models that ground answers in supplied documents |
| `tool_use` | 0.55 | 120 | 0.05 | 0.5 | 0.086 | 0.42 | 0.31 | tool name plus exact arguments, including refusal when no tool applies or an argument is missing; explicit specs make this comparatively easy |
| `long_context` | 0.45 | 100 | 0.0 | 0.45 | 0.098 | 0.315 | 0.22 | gated on the 8k slice only (n=100); 16k and 40k are LOW_POWER report-only slices because vendor-supported context differs across models |
| `multilingual` | 0.4 | 200 | 0.1781 | 0.222 | 0.069 | 0.305 | 0.16 | overall over English/Hindi/Tamil/Kannada (50 each); per-language results are LOW_POWER report-only; the floor is lower than monolingual floors because low-resource-script items are harder for small models |
| `verification` | 0.5 | 180 | 0.2466 | 0.253 | 0.072 | 0.39 | 0.25 | strategic; planted-error step identification and claim-vs-evidence labels have chance about 0.2-0.33, so 0.50 requires real checking ability |
| `evidence_use` | 0.5 | 165 | 0.03 | 0.47 | 0.075 | 0.385 | 0.25 | strategic; correct answer AND exact supporting evidence ids or a correct abstention; chance is near 0.05 |
| `counterfactual_reasoning` | 0.35 | 120 | 0.03 | 0.32 | 0.089 | 0.23 | 0.13 | exact set/number answers computed from dependency graphs and formula systems; chance near 0.05; hard for small models so the floor is modest |
| `hypothesis_testing` | 0.5 | 120 | 0.3139 | 0.186 | 0.088 | 0.375 | 0.25 | choose a discriminating experiment or a verdict; chance about 0.25-0.33, so 0.50 is comfortably above guessing |
| `information_gain_reasoning` | 0.35 | 120 | 0.1864 | 0.164 | 0.089 | 0.23 | 0.13 | pick the single question with maximal information gain (ties accepted) or recognise sufficiency; chance about 0.2-0.25 |

Report-only categories (never floors, never ranking): `strict_contracts`, `multimodal_where_applicable`, `discovery_quality`, `cross_domain_transfer`. `strict_contracts` is a report-only recovery-cost signal.

The design-time proposals (e.g. `instruction_following` 0.70, `structured_outputs` 0.85) are superseded; see `floors_supersede_design_proposals` in the JSON.

## Funnel and rules

Stage 0 CPU checks: tokenizer_round_trip_on_fixed_multilingual_probe; chat_template_renders_system_user_tool_and_thinking_modes; config_and_architecture_load_on_cpu_under_pinned_runtime; exact_40_hex_revision_pinned; all_weight_shard_hashes_verified; license_text_archived; context_length_recorded_config_vs_vendor; architecture_supported_by_pinned_runtime_version.

Stage 1: all Stage-0-compatible models; probe = first 30 holdout items per gating category by item hash (420 items); cap 0.25 GPU-h per model. Stage 2: survivors within USD 40.0; a family name carries no priority; incomplete results are rejected. Stage 3: up to 3 finalists chosen from pre-trainability criteria; no selection until every finalist completes the same pilot.

Selection rule: No model is selected in this phase. A future selection must use per-capability results from the frozen Genesis Capability Eval V1 and this pre-registered rule, applied only after every finalist has completed the same trainability pilot: (1) a model must clear every frozen floor on the gating categories; (2) among survivors, drop any model Pareto-dominated on every gating category at equal or lower cost; (3) rank the remainder lexicographically by verification, then evidence_use, then trainability, then cost; (4) ties or irreconcilable trade-offs go to an explicit owner decision. strict_contracts is a report-only recovery-cost signal and is never a floor or a ranking input. Release date, parameter count and popularity are never inputs.

Tie rule: if two or more finalists are identical on verification, evidence_use, trainability and cost, the result is OWNER_DECISION_REQUIRED_TIE; no automatic tie-break by name, size, date or popularity

NO_MODEL_QUALIFIES: if no finalist clears every frozen floor the result is NO_MODEL_QUALIFIES: nothing is selected, floors are never lowered after the fact (that requires Eval V2), and the owner decides the next step

## Contamination policy

The private holdout may be used for QUALIFICATION only; never for SFT, QLORA, PEFT_TRAINING, PROMPT_TUNING, FEW_SHOT_EXAMPLES, ROUTER_TUNING, THRESHOLD_TUNING, MODEL_SELECTION_DEBUGGING, DATA_AUGMENTATION, SYNTHETIC_DATA_SEEDING. Any contamination invalidates this eval version. Checks: exact duplicate; near duplicate (instance text); instance-key uniqueness; 8-gram overlap against training corpora; semantic overlap hook (protocol; not configured); split-boundary check (ids, hashes, private flag).

## Remaining uncertainties

- items are template instances; correlated within template, so nominal intervals overstate power (cluster sizes in the manifest)
- floors are reasoned from chance baselines and task design, not from any model result; they may reject every model or none
- Hindi/Tamil/Kannada items were authored by an AI assistant and have not been reviewed by native speakers
- the coding category cannot be scored until an attested hermetic sandbox exists; until then Stage 2 cannot complete
- semantic-overlap checking is a protocol hook only; no embedding model is configured
- long-context lengths are approximate (fixed words-per-token ratio); tokenizer-specific lengths differ
- the Stage-1 GPU-time cap of 0.25 h per model is a planning assumption, unmeasured
- discovery scoring uses evidence anchors plus keyword diagnostics, which is brittle for paraphrased falsifiers and actions
