# Official model-training preauthorization decision package

Verdict for this programme: `ENGINEERING PARTIAL — SPECIFIC BLOCKERS`.

This document does not assert `PRETRAINING_READINESS_ACCEPTED`, `FOUNDER_AUTHORIZATION_GRANTED`, or `TRAINING_EXECUTION_ALLOWED`.

## 1. SHA and branch

Implementation parent: `origin/cursor/orneur-pretraining-foundation-p0-4e55` at `fc1eb1dd098377e8506485dbcd82d6ed148b52b3`. The commit that adds this package is the head of `cursor/agent-role-registry-a8b0` after this file is committed. Gap register: `cursor/pretraining-gap-register-a8b0` at `255d25a404e1c74d6feca0fc5931497ec29b0bf9` (PR #100). Readiness gate: `cursor/pretraining-readiness-gate-a8b0` at `eaa3eaceef79c78924f0b1d5b0eaea48a04f7c4d` (PR #101). Draft PR #99 was inspected at `c395dba09c54f10d626156ed57512dc635f1e9b8` and was not modified.

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

12 synthetic handlers. 0 qualified. 0 production authorized. Existing orchestrator tests still pass with the new ones: 18 passed.

## 10. Dataset provenance

The parent branch already admits local records, rejects a symlink leaf, and can require a license string. That string is not a training grant. No protected corpus was generated here. Public-web text was not classified as cleared. A full 20-step custody pipeline with an independent custodian is not qualified.

## 11. Legal blockers

No foundation license was accepted for training. Path A (licensed adaptation) and path B (native training from initialization) stay separate. The 2026-09-26 decision package did not select Qwen, Mistral-Nemo, or Phi-4. Historical control smokes are not capability scores.

## 12. Private evaluation

`GENESIS_CAPABILITY_EVAL_V2_FROZEN` is false in `GENESIS_CAPABILITY_EVAL_V2_STATUS.json`. The agent equation comparison is a synthetic fixture, not that freeze.

## 13. Architecture selection

No model was selected. No weights were downloaded.

## 14. Hardware

Compute is unqualified. No throughput was measured in this pass. Frontier pretraining is not the workstation. Prices that were not looked up are `UNKNOWN`, not zero. No GPU job was started and nothing was purchased.

## 15. Reproducibility

The agent tests are deterministic across five trials on one machine. That does not prove another operating system. The acceptance ledger hash was not changed by the gate tests on `main`.

## 16. Security

Handler denials cover the cases in `ORNEUR_AGENT_ADVERSARIAL_SECURITY_REPORT.md`. Same-process tests are not an external trust boundary. Class K recovery stays deferred. Acceptance C27 stays unmet.

## 17. Future training cost

`UNKNOWN`. No new price source was queried. Promotional credits in older documents are not treated as available.

## 18. Founder-only decisions

Supply the R65 source text or leave the row unmapped. Name a G1 reviewer. Record DEC-K without pretending it completes C27. Enroll real trust anchors outside this repository. Choose a foundation, a corpus grant, a budget, and a training authorization through the existing engine. None of those acts was performed here.

## 19. Independent audit

Not done. The handoff file asks a reviewer to re-run the pytest command on the exact commit. Draft PR #99 remains a separate product-integration candidate.

## 20. Next executable work that does not need new authority

Keep the ledger unchanged. Extend synthetic provenance checks on local fixtures. Add the uncovered adversarial cases that do not need secrets or GPUs. Do not start training.

Closure order: R65 source, G1 review, trust enrollment, DEC-K decision with C27 still open, corpus custody, foundation choice, compute qualification, then FINAL-1 only after every counted row has its own acceptance. FINAL-2 and EXEC-1 stay after that. There is no readiness percentage.
