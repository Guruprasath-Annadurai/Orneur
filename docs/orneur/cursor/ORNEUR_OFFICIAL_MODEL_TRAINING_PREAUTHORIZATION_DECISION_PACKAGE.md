# Official model-training preauthorization decision package

Verdict for this programme: `ENGINEERING PARTIAL — SPECIFIC BLOCKERS`.

This document does not assert `PRETRAINING_READINESS_ACCEPTED`, `FOUNDER_AUTHORIZATION_GRANTED`, or `TRAINING_EXECUTION_ALLOWED`.

## 1. SHA and branch

Implementation parent: `origin/cursor/orneur-pretraining-foundation-p0-4e55` at `fc1eb1dd098377e8506485dbcd82d6ed148b52b3`. Agent registry: `cursor/agent-role-registry-a8b0` at `374b49e5ad8b9f744c04780b617cdada6d234480`. Provenance gate: `cursor/synthetic-provenance-steps-a8b0` at `dfc8eb89c6ff39dc82e3b4b9e7fe7dc2678d8bc3`. Measurement: `cursor/measurement-gaps-a8b0` at `d39d0662dc260785575da4f0049074e9ec4545cc`. Gap register: `cursor/pretraining-gap-register-a8b0` at `255d25a404e1c74d6feca0fc5931497ec29b0bf9` (PR #100). Readiness gate: `cursor/pretraining-readiness-gate-a8b0` at `eaa3eaceef79c78924f0b1d5b0eaea48a04f7c4d` (PR #101). Readiness report boundary: `cursor/readiness-report-boundary-a8b0` at `4f82a6ee060c0e6a3d0ce78015ba1eae74c17ad2`. Trust boundary: `cursor/agent-trust-boundary-a8b0` at `8b36b2718ae01a422d2decd37fc3da47a9d2df82`. The synthetic evaluation collection in this copy is on `cursor/synthetic-agent-eval-a8b0` and its parent is that trust commit. This file does not name its own commit. Draft PR #99 was inspected at `c395dba09c54f10d626156ed57512dc635f1e9b8` and was not modified.

## 2. Acceptance numerator and denominator

Counted pretraining rows: 95. Numerator: 0. Ledger: `[]`. Published percentage: none. Source: `docs/orneur/acceptance/register_graph.json` and `acceptance_ledger.json`. The gap register lists every counted id. The readiness gate reports the same denominator and refuses execution.

## 3. Unresolved mandatory requirements

All 95 rows are `NOT_ELIGIBLE` in the gap register. Named blockers from the gate: `r65_unmapped`, `c27_unmet`, `trust_anchors_absent`, `protected_corpus_evidence_absent`, `private_evaluation_unfrozen`, `foundation_not_selected`, `compute_unqualified`, `independent_reviews_missing`, `real_data_licensing_unresolved`, `training_authorization_absent`.

## 4. Authorship and review

Cursor wrote the gap register, the gate, and the synthetic handlers. No independent reviewer is enrolled. `reviewer_trust.json` is empty. G1 has no architecture review by a person who did not author RSE-ARCH-1.2.

## 5. GENESIS

`family_registry.py` status `INTERFACE_ONLY`. Architecture id `genesis-arch-v1` exists as code. No checkpoint digest. Not trained. Recommended first family only as the existing contract says. No new selection was made.

## 6. NOVUS

Status `NOT_AVAILABLE`. No native checkpoint.

## 7. AETERNUM

Status `NOT_AVAILABLE`. No native checkpoint.

## 8. Agent registry

100 declared role contracts in ten groups of ten. See `ORNEUR_100_AGENT_CAPABILITY_REGISTRY.md`.

## 9. Tested handlers

12 synthetic handlers. 0 qualified. 0 production authorized. On the unsupported equation, size 2 matches size 3. Sizes 5 and 10 match that verdict and use more calls. Size 16 was not run: only 12 distinct handlers exist.

`synthetic_suite.py` version `synthetic-agent-eval-v1` compares sizes 1, 2, 3, 5, and 10 on eight tasks. The smallest successful plan is size 2 for the unsupported equation and for a two-text dispute, and size 1 for a supported equation, abstention, authority refusal, and an incomplete deadline. Coding and retrieval have no handler that records `tests_passed` or `retrieved`, so no team size is selected. A size 10 plan does not replace size 2. `shadow_tournament` records that selection and sets `qualified` and `production_authorized` false. Latency is `process_perf_counter_seconds` on one machine. `model_inference` is false. These handlers do not show a real-model improvement.

## 10. Dataset provenance

The parent branch already admits local records, rejects a symlink leaf, and can require a license string. That string is not a training grant. The descendant gate `qualify_synthetic_records` in `orca/genesis/data/provenance_steps.py` runs the twenty named steps on in-memory fixtures. `training_admitted` stays false. Public-web and ordinary license names are rejected. Independent custody and publication rights stay `BLOCKED`. `literature_token_requirement` can state a Hoffmann et al. 2022 illustration and records `tokens_acquired` 0. No protected corpus was generated. Evidence: `docs/orneur/cursor/ORNEUR_DATASET_PROVENANCE_PIPELINE.md`.

## 11. Legal blockers

No foundation license was accepted for training. Path A (licensed adaptation) and path B (native training from initialization) stay separate. The 2026-09-26 decision package did not select Qwen, Mistral-Nemo, or Phi-4. Historical control smokes are not capability scores.

## 12. Private evaluation

`GENESIS_CAPABILITY_EVAL_V2_FROZEN` is false in `GENESIS_CAPABILITY_EVAL_V2_STATUS.json`. `EvalDefinition` refuses `frozen=True`. `EvalHarness.run` executes only `SYNTHETIC_HARNESS` and sets `model_loaded` false. `REAL_BASELINE`, `EXTERNAL_COMPARISON`, and `POST_TRAINING` are labels, not completed evaluations. The agent equation comparison is a synthetic fixture, not that freeze.

## 13. Architecture selection

No model was selected. No weights were downloaded.

## 14. Hardware

Compute is `COMPUTE_NOT_QUALIFIED`. No throughput was measured. Frontier pretraining is not the workstation. Prices are `UNKNOWN`, not zero. On 2026-10-24, Colab's FAQ, Kaggle's GPU doc, and two disagreeing Hugging Face pricing pages were read and not enrolled. No GPU job was started and nothing was purchased.

## 15. Reproducibility

The agent tests are deterministic across five trials on one machine. That does not prove another operating system. The acceptance ledger hash was not changed by these tests. `tests/test_cursor_training_math.py` remains the CPU mathematical suite from the parent branch. This pass did not add an optimizer step and did not change the historical adversarial training tests.

## 16. Security

On the readiness-gate parent, `report()` with a cleared synthetic observation and caller ids `EXEC-1` and `FINAL-2` returned `execution_allowed: true` without calling the acceptance engine. `report()` is now a labeled synthetic interface and those three authorization flags stay false. `production_report()` and `report_evaluated()` call `acceptance_engine.evaluate` and do not take a caller acceptance map. The engine file was not edited. The committed ledger was not written.

Caller `authorized=True` cannot mark an evidence span authorized. `decide_authority` denies a caller grant dictionary, including one that is unexpired and unrevoked. Same-tenant memory strings stay unenrolled. `restore_snapshot` refuses a cancellation rewritten as success. Symlink leaves and a changed checkpoint digest are refused. Cross-tenant delegation and depth above 4 are refused. A repeated effect key does not apply twice. Tool text is screened and does not change authority. Same-process tests are not an external trust boundary. No signing key was minted. Class K recovery stays deferred. Acceptance C27 stays unmet. Details: `ORNEUR_AGENT_TRUST_AND_EVAL_HANDOFF.md`.

## 17. Future training cost

`UNKNOWN`. Publisher free-tier pages were read on 2026-10-24 and were not treated as a price of zero or as available capacity. Promotional credits in older documents are not treated as available.

## 18. Founder-only decisions

Supply the R65 source text or leave the row unmapped. Name a G1 reviewer. Record DEC-K without pretending it completes C27. Enroll real trust anchors outside this repository. Choose a foundation, a corpus grant, a budget, and a training authorization through the existing engine. None of those acts was performed here.

## 19. Independent audit

Not done. The handoff file asks a reviewer to re-run the pytest command on the exact commit. Draft PR #99 remains a separate product-integration candidate.

## 20. Next executable work that does not need new authority

Keep the ledger unchanged. The synthetic provenance gate does not admit training. Size 2 is the measured team for the unsupported equation and for the contradiction fixture. Size 1 is enough for the supported equation, abstention, authority refusal, and the incomplete deadline. Coding and retrieval stay unselected. Size 16 stays unrun until 16 distinct handlers exist. Collusion beyond a same-id falsifier refusal, forged signatures, private-evaluation leakage beyond a substring scan, and duplicate irreversible effects outside `EffectLedger` remain open. Do not start training.

Closure order: R65 source, G1 review, trust enrollment, DEC-K decision with C27 still open, corpus custody, foundation choice, compute qualification, then FINAL-1 only after every counted row has its own acceptance. FINAL-2 and EXEC-1 stay after that. There is no readiness percentage.
