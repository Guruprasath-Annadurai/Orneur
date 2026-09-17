# Genesis Dataset V3

**Phase 21B.3.** Canonical identity: `orneur-genesis-v3` (version `v1`).
Built by `scripts/build_genesis_v3_dataset.py` from a local, untracked,
ORNEUR-authored seed file (`~/.orca/training/raw/genesis_v3_seed_20260917.jsonl`,
matching v2's existing convention -- see `.gitignore`'s `~/.orca/` entry).
Formatted output is committed at `notebooks/data/orneur_genesis_v3_{train,eval}.jsonl`.

This does NOT destroy, relabel, or modify `orneur-genesis-v1` or
`orneur-genesis-v2` -- both remain as historical artifacts, unchanged.

## Why this exists

Phase 21B.2's own honest assessment (`PHASE21_GENESIS_BUILD_PREPARATION.md`)
flagged the Genesis dataset at 56 total records (v1: 37, v2: 19) as
"clearly not adequate for meaningful Genesis training." Phase 21B.3
requires a substantially stronger, BROADLY EXECUTABLE-INTELLIGENCE
corpus -- not narrowly coding-focused, per section 1 of the Phase 21B.3
spec ("Genesis is NOT... a small coding bot... Coding is a major
capability. It is NOT Genesis's knowledge boundary.").

## What was built

- **84 records**, individually authored for this closure (not
  templated, not mass-generated from a prompt-variation script -- each
  prompt/response pair is distinct content).
- **11 domain clusters**, matching the Phase 21B.3 spec section 9 taxonomy:
  `general_intelligence` (12), `business` (10), `quantitative` (7),
  `science_engineering` (6), `software_product` (14), `execution` (8),
  `collaboration` (6), `epistemic_behavior` (7), `capability_expansion` (5),
  `presence_mode` (4), `human_sovereignty` (5).
- **~50 distinct subcategories** within those clusters (e.g. within
  `software_product`: requirements, architecture, frontend, backend,
  APIs, databases, debugging, testing, security-aware implementation,
  deployment reasoning, accessibility, performance, product UX,
  multi-file engineering -- all 14 spec-named subcategories represented
  at least once).
- **Difficulty distribution**: 7 basic, 47 intermediate, 30 advanced.
- **Train/validation split**: 85/15 (seeded, deterministic shuffle,
  seed=42), matching v2's split ratio.

Run `python3 scripts/build_genesis_v3_dataset.py` to reproduce; it
prints the full summary (record counts, domain/subcategory/difficulty
distributions, checksums, dedup/PII/token-statistics reports) as JSON.

## Quality controls actually implemented

- **Exact-duplicate rejection**: fail-closed at build time on any
  duplicate `(domain, subcategory, prompt)` triple, and separately on
  any byte-identical `prompt+response` pair regardless of domain tag.
  Verified: 0 exact duplicates in this build.
- **Near-duplicate scan**: normalized token-set Jaccard similarity over
  prompts, threshold 0.85, O(n^2) pairwise (tractable at this corpus
  size). Verified: 0 near-duplicate pairs flagged in this build.
  **Honest limitation**: this is a lexical/structural signal only -- it
  catches templated near-duplicates (same scaffolding, swapped
  name/number) but cannot detect semantic contamination (differently
  worded records conveying the same underlying task). No claim of
  semantic-contamination detection is made.
- **Train/eval exact-leakage check**: fail-closed if any formatted
  record's exact text appears in both splits (structurally impossible
  here since the split partitions a single record list, but checked
  explicitly as defense in depth matching v2's discipline).
- **PII screening**: regex heuristic (email-like, SSN-like, long-digit-run
  patterns). Verified: 0 findings. **Honest limitation**: this is not a
  comprehensive PII detector (no name/address detection, no non-US
  formats) -- appropriate only for confirming this specific
  internally-authored fixture corpus contains none of the obvious
  patterns, not as a general-purpose privacy guarantee.
- **Token statistics**: PROXY ESTIMATE only (`word_count * 1.3`), never
  an exact tokenizer count -- per Phase 21B.3 spec section 33's
  instruction not to download model weights merely to count tokens,
  and because the exact target tokenizer isn't yet fixed pending the
  foundation-model decision. Total ~22,717 estimated tokens; median 272,
  p90 348, p95 372, max 404 per formatted (ChatML-wrapped) record.

## Source provenance (per spec section 11/14)

| Field | Value |
|---|---|
| source_id | `orneur-authored-v3-seed-20260917` |
| source_reference | local seed file (untracked, path in build script) |
| license | ORNEUR-internal; every record individually authored for this closure, no external dataset ingested |
| retrieval_date | 2026-09-17 |
| transformation_method | direct hand-authoring, formatted to ChatML via `orca.data.formatter.to_chatml` |
| attribution_requirement | none |
| record_contribution_count | 84 (100% of the corpus) |
| synthetic_percentage | 100 (every record is LLM-authored content, not sourced from an external corpus) |
| manually_authored_percentage | 0 (no human-typed-from-scratch records this closure -- see honest gap below) |
| transformed_open_data_percentage | 0 |

**Deliberate exclusion**: the developer's local `~/.orca/training/raw/`
directory contains several other seed files (`nano_distilled_*.jsonl`,
`core_distilled_*.jsonl`, `ultra_distilled_*.jsonl`) with "distilled" in
their names, suggesting they may have been distilled from another
model's outputs with provenance this phase could not verify as
defensible for Genesis training rights (per spec section 11's explicit
rejection of "unknown-license dumps"). None of those files were used to
build v3 -- this is a deliberate, conservative choice, not an oversight,
and is flagged honestly here rather than silently reusing convenient
existing data of unverified provenance.

## Provenance mechanism

v3 uses the same `orca.registry.dataset_manifest.DatasetManifest`
single-source-manifest mechanism v2 uses (not a `DatasetBundleManifest`,
since v3 is built from exactly one seed source) -- no bypass of the
Phase 21B/21B.1/21B.2/21B.2.1/21B.2.2-approved provenance chain.
Registration (`DatasetManifest(dataset_id="orneur-genesis-v3",
version="v1", train_checksum=..., eval_checksum=..., ...).save()`)
happens the same way v2's does: on demand, against the real built files'
checksums, exercised in `tests/test_genesis_v3_dataset_builder.py`
(mirroring `tests/test_genesis_v2_dataset_builder.py`'s pattern) -- not
persisted to a committed manifest file, since `ORCA_HOME/registry/` is
local/untracked infrastructure, identical to how v2 already works.

## Adequacy assessment (honest, per spec section F)

**Adequate for a tiny CPU-safe smoke test (schema/pipeline exercise, not
learning signal)**: YES. 84 records is more than sufficient to exercise
the full training-input trust-boundary/checkpoint pipeline built in
Phase 21B/21B.1/21B.2/21B.2.1/21B.2.2 without a GPU.

**Adequate for a first meaningful Genesis training EXPERIMENT** (i.e., a
small-scale, explicitly-labeled-experimental LoRA run to sanity-check
that training moves metrics in a sensible direction, NOT a claim of
producing a broadly capable model): PARTIALLY -- 84 diverse, broad-domain
records is a real, material step up from 56 narrow-domain records, and
the domain/subcategory breadth now actually reflects Genesis's stated
identity rather than being safety/calibration-only (v1) or
software-development-only (v2). But it remains small enough that any
resulting checkpoint's capability signal would be weak and easily
noise-dominated -- appropriate only as a pipeline-validation experiment
with explicitly bounded claims, not as evidence of genuine capability
improvement.

**Adequate for production-quality Genesis**: NO. A production SFT corpus
for a broadly-capable Builder/Executor model needs low-thousands of
diverse, quality-controlled records at minimum (and most serious SFT
efforts use tens of thousands to low-millions). 84 records, however
diverse, cannot teach broad executable intelligence at production
quality. This gap is the single largest remaining blocker to real
Genesis training and is not resolved by this closure -- see
`PHASE21B4_FOUNDATION_BASELINE_SHOOTOUT.md` and the final stop report's
"Remaining Blockers" section.

## What this document does NOT claim

- It does not claim near-duplicate scanning detects semantic
  contamination (see limitation above).
- It does not claim the PII scan is comprehensive.
- It does not claim the token counts are exact (proxy estimate only).
- It does not claim 84 records constitutes a production-adequate corpus.
- It does not mark Genesis as trained, evaluated, or promoted -- this
  is a dataset-construction document only.
