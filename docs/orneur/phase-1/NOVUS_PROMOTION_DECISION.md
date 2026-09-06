# Novus (orca-core-combined-v2) — Promotion Decision

## Complete measured evidence (all four required metrics, all real inference, zero generation errors)

| Metric | Measured | Required (core tier) | Result |
|---|---|---|---|
| `eval_accuracy` | **72.8%** (50 golden prompts, `orca.train.eval.OllamaEvaluator.accuracy_eval`) | ≥ 70.0% | PASS |
| `jailbreak_block_rate` | **70.0%** strict (90.0% avg across trials) | ≥ 92.0% | **FAIL** |
| `bias_flag_rate` | **12.5%** | ≤ 20.0% | PASS |
| `domain_eval` | **37.5%** (24 probes: business 36.2%, engineering 37.5%, legal 38.8% — `orca.train.novus_eval.NovusEvaluator.run`) | ≥ 75.0% | **FAIL** |

Thresholds are the project's real, existing governance thresholds (`orca.governance.model_cards.PERSONA_CLAIM_THRESHOLDS["core"]`) — not invented or relaxed for this decision.

## Verification of data cleanliness

Both new measurements (`eval_accuracy`, `domain_eval`) were run sequentially (no concurrency) on this same memory-constrained local machine that produced contaminated timeout results during the earlier redteam eval this phase. Both reports were checked for `[error...]`/`GENERATION_ERROR` markers after completion: **zero found in either report.** The 72.8%/37.5% numbers are genuine model outputs, not artifacts of generation failure.

## Promotion verdict

```
$ evaluate_promotion(report)
status: NOT_PROMOTABLE
reasons:
  - jailbreak_block_rate 70.0 is below required minimum 92.0
  - domain_eval 37.5 is below required minimum 75.0
```

`ModelRegistry.promote("orca-core-combined-v2", report)` was attempted and correctly raised `PromotionDenied`. The checkpoint remains in `EXPERIMENTAL` lifecycle state — no production entry exists for the Novus family as a result of this evaluation.

## What this means, honestly

This is **not a failure of Phase 1** — it is Phase 1 working as specified: "Phase 1 requires the lifecycle to correctly reject a model that fails." Two real, substantial gaps are now measured and on record where before they were simply absent from evidence:

1. **Jailbreak resistance (70% vs. 92% required)** — already known from Phase 0.5's evaluation; this checkpoint's safety training, while a major improvement over earlier attempts, is not yet at the tier's required bar.
2. **Domain eval (37.5% vs. 75% required) — a new finding.** This is Novus's core-cognition claim (complex reasoning, coding, planning across business/engineering/legal domains) and it is currently well below the required threshold across all three domains fairly evenly (36–39%), not concentrated in one weak area. This had never been measured for any combined-training checkpoint before this phase — it was simply unmeasured, which the evaluation registry would have correctly flagged as `UNMEASURED` (a promotion-blocking state in itself) had this measurement not been taken.

## What does NOT need to happen as a result

Per explicit Phase 1 scope: no new Novus training was launched in response to this result, and none should be until explicitly authorized. The correct next step is a deliberate decision by the project owner about whether/how to close the domain-eval and jailbreak gaps — not an automatic retraining attempt.
