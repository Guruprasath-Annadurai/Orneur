# Dataset quality and provenance tooling (Workstream E)

Package: `orca/dataquality/`. CLI: `python -m orca.dataquality <command>`. Deterministic, CPU-only, stdlib plus existing repo modules. No training,
no GPU, no model inference, no network or provider calls, no weight downloads. It never reads `eval_private/`, any vault, or any secret.

Output is canonical JSON (sorted keys, ASCII, 2-space indent). **No timestamp is emitted unless you pass `--now <string>`**, so the same inputs always
give byte-identical output. `--out` and `--now` may be given before or after the command.

Exit codes: `0` = PASS, `1` = at least one FAIL, `3` = no FAIL but something NOT_EVALUATED, `2` = usage/input error.

## What each check does and what it reuses

| # | Check / command | Reuses | Notes |
|---|---|---|---|
| 1 | `schema FILE [--kind auto\|chat\|sft\|dpo] [--strict-keys]` | `orca.dataquality._common` | every violation has a 1-based line number and a stable code; messages never echo content |
| 2 | `provenance FILE --sources REG [--default-provenance P]` | | fail closed: source id, license/terms id, generator kind (human / model+revision / program), creation-code SHA, digest. Missing or unknown = violation |
| 3 | `teacher-register validate\|derive\|seal`, `ingest-gate FILE` | corpus inventory `distillation_data` | versioned register, statuses `PERMITTED_RECORDED / RESTRICTED / UNREVIEWED / PROHIBITED`; gate refuses anything not `PERMITTED_RECORDED` with a cited terms record |
| 4 | `dedup FILE`, `legacy-quick-ratio FILES...` | `genesis_v2.similarity` (MinHash/LSH, shingles, skeletons) | exact raw, exact normalized (NFKC, casefold, zero-width removal, partial Cyrillic/Greek homoglyph fold), number-masked variants, word-shingle Jaccard clusters, structural (skeleton) clones, template-concentration entropy |
| 5 | `diversity FILE` | `genesis_v2.similarity`, `genesis_v2.semantic` contract | distinct-1/2/3, type-token ratio, skeleton entropy; semantic diversity only through an injected local, hash-recorded, semantic-capable embedder, otherwise NOT_EVALUATED |
| 6 | `contamination --train T --eval E [--canaries F] [--fingerprints F]`, `fingerprint --eval E` | `genesis_v2.contamination` thresholds, `genesis_contamination` 8-gram fingerprints | exact, near, canary, fingerprint-set. Output carries counts and **train-side** line numbers only |
| 7 | `privacy FILE` | `orca.serve.dlp`, `orca.docs.pii_redact`, `genesis_v2.privacy_scan` | PII + secret patterns + protected-corpus markers; findings carry line + category + count, never the value |
| 8 | `balance FILE [--field F] [--labels JSON] [--min-share X]` | | categories come only from a record field or a sidecar mapping; never inferred from text |
| 9 | `manifest build\|verify` | `orca.registry.dataset_manifest.DatasetManifest`, `_ids.validate_id` | envelope with per-record digests and a manifest digest; `verify` reports changed/added/removed/reordered records with line numbers |
| 10 | `report --train T [--eval E] ...` | all of the above | one JSON with per-check statuses; see below |
| 12 | `datacard --manifest M --report R [--final ...]` | | DRAFT (watermarked) always; FINAL refused unless DATA-1/2/5-shaped inputs are supplied and consistent |
| | `public-sft --out-dir D` | `PUBLIC_SFT_DATASET_CLASSIFICATION.json` | regenerates the committed reports below; refuses files whose bytes differ from the classified hashes |

### The report never collapses statuses

`report` returns `statuses` (flat list, contamination sub-checks included), `status_counts`, and the full per-check results. There is deliberately
**no overall score and no boolean "ok"** (`aggregate_quality_score` is the literal string `NONE_BY_DESIGN`). A check whose required input was not
supplied is `NOT_EVALUATED`, never `PASS`; the contamination roll-up is PASS only when all four sub-checks are PASS. `diversity` with no minimum
requested is descriptive: its PASS means "computed", and the report states this in `thresholds.note`.

### Teacher-model output-use rights register

File: `orca/dataquality/data/teacher_rights_register.json` (schema `orneur-teacher-rights-register/1`). Seed data is *derived* from the corpus
inventory's `distillation_data` class (`teacher-register derive`; a test fails if the committed seed drifts from the inventory):
`llama3.1:8b` (2 logs, 90 records), `nvidia-nemotron-3-ultra-550b-a55b` (14 logs, 5012 records), and `unattributed-provider-teacher` (the 10 raw
`*_distilled*` files whose per-record teacher is not recorded in the repo; 5162 records). **All are `UNREVIEWED`**, with `terms_source_url`,
`terms_record_id`, `reviewed_by`, `reviewed_at` all `null`. The register asserts no legal conclusion (`legal_conclusions_asserted: false` is enforced).
A teacher can be `PERMITTED_RECORDED` only with a cited terms record, source URL, human reviewer, review date, explicit covered revisions and permitted
uses; the validator rejects anything less, and the gate also checks the record's `model_revision` is covered. `content_sha256` detects accidental or
silent edits; it is a checksum, not a signature. Changing a status is a review decision, not something this tool grants.

### Provenance shapes (tooling-defined)

Record `provenance`: `{source_id, license_id, generator:{kind: human|model|program, model_id+model_revision | program}, creation_code_sha (40/64 hex), digest}`.
Source registry: `{schema_version: "orneur-source-registry/1", licenses:[...], sources:[{source_id, license_id}]}`. When a dataset-level default
provenance is used, the tool computes the digest (the report counts these as `digests_computed_by_tool`); a producer-supplied digest is verified.

## Measured on the public SFT files

Reports and manifests: `docs/orneur/status/dataquality/reports/*.report.json|*.manifest.json` (regenerate with
`python -m orca.dataquality public-sft --root . --out-dir docs/orneur/status/dataquality/reports`; a test requires byte-identical regeneration and
pins the key numbers). Only the files classified `PUBLIC_SFT` were read, and generation refuses any file whose sha256 differs from that classification.

### The documented "29% near-duplicates" figure, reproduced and qualified

`docs/orneur/phase-0/GENESIS_DATASET_BASELINE.md` states 192 of 666 pairs exceed 0.85 similarity. Reproduced **exactly**:

* Population: `orca_nano_combined_train_v1.jsonl` (34) **plus** `orca_nano_combined_eval_v1.jsonl` (3) pooled = 37 records, C(37,2) = **666** pairs. (The train file alone gives 561 pairs, so the documented denominator is the pooled set.)
* Text compared: everything after the first `<|eot_id|>` of the Llama-3 string, i.e. the shared system-prompt block excluded and the special tokens kept (user + assistant turns).
* Measure: `difflib.SequenceMatcher(None, a, b).quick_ratio() > 0.85` -> **192 / 666 = 28.83%**.
* **Qualification (new, measured here):** `quick_ratio()` only compares character *multisets* and is an upper bound; the order-aware `ratio()` on the same pairs gives **0 / 666** above 0.85. Under word-3-gram Jaccard >= 0.80 on the content turns (system block and control tokens excluded) there are **0** near-duplicate pairs in the 34 train records, and 0 structural (skeleton) clones. What *is* real is template concentration: 20 of 34 train records (58.8%) share one opening skeleton (normalized opening-skeleton entropy 0.66), consistent with the baseline's "2 templates x 18 subtopics" explanation. So "29% near-duplicates" overstates *lexical* duplication, while the template repetition it was pointing at is real.

The same legacy measure on the other pooled public pairs (for comparison only; it is not a duplicate rate): core v2 856/2556 (33.5%), genesis v2 113/171 (66.1%), genesis v3 2042/3486 (58.6%), all with `ratio()` > 0.85 counts of 18, 0, 0 respectively.

### Per public pair (train / eval records)

| pair | records | schema | exact-normalized dup groups (redundant records) in train | word-Jaccard near pairs in train | train lines exactly in eval | privacy |
|---|---|---|---|---|---|---|
| orca_nano_combined_v1 | 34 / 3 | PASS | 0 | 0 | 0 | PASS |
| orca_core_combined_v2 | 65 / 7 | PASS | **3 (8)**: lines [3,36,55], [21,54,56,58], [29,32,37,64] are byte-identical | 15 pairs, 11 records | **3** (train lines 3, 36, 55 equal an eval record) | PASS |
| orneur_genesis_v2 | 16 / 3 | PASS | 0 | 0 | 0 | PASS |
| orneur_genesis_v3 | 71 / 13 | PASS | 0 | 0 | 0 | PASS |

`orca_core_combined_v2` therefore has real exact duplication and **train/eval leakage inside the public SFT split** (the dedup and contamination checks FAIL
for it). Its fingerprint-set check (8-gram overlap >= 0.20 against the public eval split) additionally flags train lines 2, 3, 16, 36, 49, 55, 57, 65.
This is a finding about a public SFT validation split, not about any protected holdout.

For all four pairs: `provenance` FAIL and `teacher_rights` FAIL (the public files carry no per-record provenance; fail closed), `semantic_diversity`,
`balance` (no category labels exist), and `contamination.canary` are NOT_EVALUATED. `contamination` rolls up to NOT_EVALUATED for the three pairs with no
FAIL because canary strings were not supplied. Lexical distinct-2 ratios: nano 0.512, core 0.401, genesis v2 0.877, genesis v3 0.788.

## Limitations, honestly

* Pattern scanners (PII/secrets) are a floor, not a ceiling. Homoglyph folding is a partial Cyrillic/Greek table, not full Unicode confusables. Near-duplicate and structural measures are lexical; they do not see paraphrase.
* **Semantic overlap/diversity is NOT_EVALUATED**: no local embedding model directory or hash is authorized in this repository (`genesis_v2.semantic` is NOT_CONFIGURED by design) and nothing is downloaded. The lexical `FeatureHashEmbedder` is rejected as semantic evidence. The injected-embedder code path is tested only with a test double, never with a real model.
* Category balance needs labels; the public SFT files have none, and categories are never guessed.
* `manifest verify` and the teacher-register and card digests are integrity checksums, not signatures. Authority to accept evidence belongs to the acceptance engine, not to this tooling.
* `creation_code_sha` for the public SFT files is `NOT_RECORDED` (not recorded in the repository); their manifests say so.
* Final data-card input shapes (DATA-1/2/5 documents) are tooling-defined stand-ins for the records the future process will produce; a FINAL card from this tool is a prerequisite gate only (see below).

## Tasks that require the future G8 corpus-generation grant and independent custody

Distinctions taken from `docs/orneur/ORNEUR_MASTER_EXECUTION_AND_ACCEPTANCE_REGISTER.md` (that file is not in this branch's tree; read from
`origin/claude/p1-development-register`). This tooling grants and passes **none** of them.

| Row | Meaning | Blocked on | What this tooling provides vs. what is still required |
|---|---|---|---|
| **G8** | Founder corpus-generation grant only; does not imply a corpus exists and passes none of the DATA rows | founder decision | nothing: this work does not request, simulate or substitute for it |
| **DATA-3** | Creation of the protected corpus: a creation record naming the corpus digest and the creating operator | G8 | required, not possible now: no corpus may be generated before the grant; `CORPUS_GENERATION_AUTHORIZATION.json` stays NOT_AUTHORIZED |
| **DATA-1** | Provenance manifest (source, license, per-record digest) bound to DATA-3's creation digest | DATA-3 | tooling exists (provenance check, manifest builder with per-record digests); the manifest for the protected corpus can only be produced after DATA-3 |
| **DATA-5** | Independent custody and integrity receipt that re-hashes the protected corpus, naming a custodian who is not the creator | DATA-3 | tooling can verify digests and the custodian-not-creator shape; the receipt itself requires an independent custodian and a real corpus |
| **DATA-2** | Contamination and holdout-separation result bound to the creation digest and holdout fingerprint set, no item-level leak | DATA-1, DATA-3, DATA-5, QUAL-2 | tooling exists (exact/near/canary/fingerprint, no item-level output); it can only be run against the real corpus and holdout after the rows above |
| DATA-4 | Published data card (non-blocking) | a trained model | draft cards only; FINAL cards need DATA-1/2/5-shaped inputs and, for DATA-4 proper, a model and publication |

Also outside this tooling: the actual review of any teacher's output-use terms (needs a human reviewer and a cited terms record), a pre-registered
local embedding model for semantic overlap, and any real canary/holdout material (private, never touched here).
