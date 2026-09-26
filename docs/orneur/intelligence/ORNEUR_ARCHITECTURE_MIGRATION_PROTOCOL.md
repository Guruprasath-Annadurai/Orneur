# ORNEUR Architecture Migration Protocol

Status: design and contract (`ArchitectureMigrationManifest` in `orca/intelligence/protocol.py`). No migration is performed by this document.

## 1. Why this is critical

The 15–20 year goal is not "pick the right model." It is "be able to change the model, and the whole neural architecture, without losing what ORNEUR knows, has proven, or has promised." That property is only real if migration is a **specified, validated contract**, exercised regularly, rather than a heroic effort each time. No current neural architecture may become permanent.

## 2. What must migrate (the eleven asset classes)

| Asset class | What moves | Typical mechanisms |
|---|---|---|
| `datasets` | training, preference and eval-candidate data | replay, re-tokenization, re-indexing |
| `eval_suites` | frozen, adversarial and regression suites | **run unchanged** against the new architecture; never edited to fit it |
| `experts` | adapters, specialized checkpoints, experts | adapter conversion, distillation, continued training |
| `memory_schemas` | knowledge/memory representations | representation conversion, re-indexing |
| `world_models` | `WorldState` versions and deltas | replay of deltas onto new representations |
| `discovery_history` | `Discovery` revisions and outcomes | immutable carry-over with digest chain preserved |
| `outcome_history` | `Outcome` records | carry-over; used as evaluation and training signal |
| `failure_genome` | `FailureGenomeEntry` records | carry-over; drives targeted evals for the new generation |
| `cognitive_primitives` | qualified strategies | re-qualification on the new architecture |
| `router_behavior` | routing decisions and policies | shadow comparison, distillation of the router |
| `authority_evidence_contracts` | Authority Runtime, Contract Engine, evidence rules | **unchanged semantics**; re-run their qualification |

A manifest that omits any of these is invalid (`ArchitectureMigrationManifest.problems()` reports each uncovered class).

## 3. Mechanisms

`distillation`, `continued_training`, `representation_conversion`, `adapter_conversion`, `reindexing`, `replay`, `shadow_comparison`, `dual_running`, `eval_preserving_cutover`, and `no_change_required` (an explicit, reviewable statement that an asset needs nothing). Each asset declares at least one mechanism.

- **Distillation:** the old generation (and any licensed teachers) supervise the new. Preferred for behavior that lives in weights.
- **Continued training:** carry learned capability forward when the base changes but representations are compatible.
- **Representation / adapter conversion:** deterministic transforms of stored state (embeddings, adapters) where a mapping exists.
- **Re-indexing:** rebuild retrieval structures under new encoders from the *source documents*, which are the durable asset.
- **Replay:** re-apply recorded `WorldDelta` sequences, re-run recorded requests and outcomes.
- **Shadow comparison:** new architecture receives real traffic and its outputs are compared, but not released.
- **Dual-running:** old and new both serve during a bounded window with automatic fallback.
- **Eval-preserving cutover:** cutover only if the frozen eval suites (unchanged) show no regression on capabilities that matter, per pre-registered thresholds.

## 4. `ArchitectureMigrationManifest`

```
manifest_id
source:  ArchitectureDescriptor { architecture_id, generation, family_label }   # family_label is informational; no logic may branch on it
target:  ArchitectureDescriptor
assets:  [AssetMigration { asset, mechanisms[], preservation_eval_refs[] }]
shadow_comparison_ref
rollback_plan_ref
obsolescence_review_ref
cutover_approved            # default False
protocol_version
```

Validation rules (all machine-checked):

1. `source.architecture_id != target.architecture_id`.
2. All eleven asset classes are covered, each with at least one mechanism.
3. `cutover_approved = True` additionally requires `shadow_comparison_ref`, `rollback_plan_ref` and `obsolescence_review_ref`, and `preservation_eval_refs` for `eval_suites` and `authority_evidence_contracts`.
4. Manifests are architecture-neutral: nothing in the manifest requires the source or target to be a Transformer, an MoE, a retrieval-augmented system, or any other named design.

## 5. Procedure

1. **Freeze** the current generation's eval results and the eval suites (digest recorded).
2. **Author** the manifest; review by a human owner.
3. **Build** the target's assets by the declared mechanisms.
4. **Verify preservation**: run the unchanged frozen, adversarial and regression suites; re-qualify the Contract Engine and Authority Runtime against the target; replay recorded world deltas and outcomes.
5. **Shadow** on real traffic; compare against the source; collect divergences into the Failure Genome.
6. **Dual-run** with fallback; watch predefined guard metrics.
7. **Cutover** only with `cutover_approved` and every reference present; the decision is a `PromotionDecision` by someone other than the builder.
8. **Obsolescence review** (Self-Obsolescence Rule): list what in the old architecture is now unnecessary or inferior; retire what a proven replacement supersedes; keep a dated record of what was retired and why.
9. **Rollback readiness** is maintained for a defined window.

## 6. Self-Obsolescence Rule (canonical)

Every major ORNEUR generation must evaluate: *"What part of the current architecture is now unnecessary or inferior?"* If a better replacement is proven, the old mechanism must be allowed to retire. Nothing is sacred merely because ORNEUR previously built it. This includes mechanisms on the "permanent" list: what is permanent is the contract and the accumulated state, not any implementation of it.

## 7. Invariants a migration must never break

- Historical results, evidence and outcomes are carried over **byte-identically**; a migration never rewrites history (it adds new-architecture results alongside).
- Eval suites are never modified to make a target pass.
- Tenant boundaries and privacy scopes are preserved.
- Authority and contract semantics keep their guarantees.
- No self-generated component promotes itself.

## 8. Not claimed

This protocol does not claim ORNEUR will survive any particular number of years or that any migration is cheap. It makes migration *specified, testable and reviewable*, which is the prerequisite for the claim being possible.
