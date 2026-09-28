# Genesis Capability Eval V2 — Historical Contamination Controls (consolidation, this phase)

This document consolidates, and does not weaken, the contamination controls already established in prior phases for
the 70-entry historical training/adaptation corpus inventory
(`docs/orneur/phase-21/GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json`, owner-signed and verified — see
`GENESIS_V2_CORPUS_INVENTORY_ATTESTATION_PAYLOAD_TO_SIGN.signable` and the commit history). **No claim of
contamination-freedom is made here or anywhere in this repository** — every check below produces evidence, never a
declaration of "clean."

## 1. The 57 unknown training-usage declarations remain unresolved

57 of the 70 inventory entries declare `used_in_training = "UNKNOWN"` (independently confirmed this phase — see the
owner review report). This is a genuine, honest declaration: the inventory does **not** claim these files were or
were not used in training any existing ORNEUR model. `inventory.evaluate()` (full contamination qualification)
treats any `UNKNOWN` tristate flag as an unresolved finding (`unresolved.append(...)`) and never lets it silently
resolve to `False`. No code path in this repository converts `UNKNOWN` to a resolved value without new evidence.

## 2. The Kaggle-derived class remains explicitly unavailable

`external_uploaded_datasets` / `external-kaggle-uploaded-datasets` remains `status: UNAVAILABLE` in the inventory —
names not recorded in the repository, content unverifiable. `inventory.actually_unavailable_classes()` derives this
directly from the inventory's own corpora list (not from the attestation's self-report), and
`evaluate_pre_corpus_attestation()` FAILS if any genuinely-unavailable class is not named in the signed attestation's
`unresolved_classes` — enforced this phase, regression-tested.

## 3. The frozen unavailable-corpus acceptance policy is enforced, not just documented

`GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json` (`frozen: true`) is checked programmatically by
`evaluate_pre_corpus_attestation()`: an unresolved class not covered by `applies_to_unresolved_classes` fails the
pre-corpus attestation gate outright. Its fail-closed rules (unchanged this phase):
- unresolved/unavailable corpus data must not be used for future Genesis training or adaptation,
- a candidate lineage with evidence or credible suspicion of exposure is treated as potentially contaminated,
- uncertain exposure requires exclusion or a fresh, independently-verifiable lineage,
- unresolved corpora stay permanently in the contamination risk register until a new signed attestation says
  otherwise,
- no later discovery may retroactively alter prior qualification evidence — only trigger a forward-dated re-analysis.

## 4. Teacher-generated / distillation data with unresolved licensing

26 `distillation_data` entries and their `local-distilllog-*` counterparts are recorded with provenance
`"provider/teacher model outputs (see distill_logs); teacher-output licensing review pending"` (10 of the
`local-raw-*` entries carry the explicit "licensing review pending" note). This is preserved as-is: no phase has
resolved this licensing review, and none is claimed here. It is tracked the same way as the 57 `UNKNOWN`
training-usage entries — as an open item, not a green light.

## 5. Requirements for semantic overlap, training-corpus comparison, candidate-lineage verification, and
   independent qualification (design targets — see `GENESIS_V2_BENCHMARK_PARTITION_ARCHITECTURE.md` §6–7 for the
   mechanisms)

- **Semantic overlap**: `semantic.SemanticOverlapEngine` must report `configured == True` (currently
  `CONFIGURED_LOCAL_ONLY`, not yet `QUALIFIED`) AND the calibration evidence (`GENESIS_V2_SEMANTIC_ENGINE_RECORD.json`)
  must be reviewed and accepted before semantic review results may gate any freeze decision. A lexical-only embedder
  (`FeatureHashEmbedder`, `semantic_capable=False`) is never accepted as semantic review.
- **Training-corpus comparison**: `contamination.check_training_corpora` must run against every `PRESENT`,
  hash-verified, resolvable corpus in the inventory — never a partial or best-effort subset — and the inventory's
  completeness must be `evaluate() == PASS` (full contamination qualification), which structurally requires the V2
  corpus to exist and every `UNKNOWN`/`PENDING_V2_CORPUS` entry to have since been resolved.
- **Candidate-lineage verification**: a candidate's training lineage must be independently attestable (provider
  disclosure, reproducible training log, or equivalent) before it can be exempted from the "uncertain exposure"
  exclusion rule in §3 above. No such attestation mechanism exists yet in this repository — an unresolved capability.
- **Independent qualification**: no result computed against `SCREEN` or `QUALIFICATION_HOLDOUT` may be treated as
  qualifying evidence without independent (ChatGPT) audit of the exact-SHA CI run that produced it, consistent with
  the standing audit discipline this entire program has followed.

## 6. Explicit non-claims

This document, and no other artifact in this repository, claims that:
- the historical training data is contamination-free,
- the 57 `UNKNOWN` flags have been resolved,
- the Kaggle-derived class has been recovered or found harmless,
- any future SCREEN or QUALIFICATION_HOLDOUT content will be free of overlap with training data,
- semantic review is currently qualified to gate a freeze decision.

Any of the above would require new, specific, independently-reviewable evidence — not a restatement of intent.
