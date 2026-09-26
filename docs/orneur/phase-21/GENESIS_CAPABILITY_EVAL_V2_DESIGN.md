# Genesis Capability Eval V2 — Private Holdout Security Correction

`GENESIS_CAPABILITY_EVAL_V2_FROZEN = false`. Private storage is **not configured**; **no private corpus has been generated or committed**.

## 1. Why V2 exists

V1 (`genesis-capability-eval/1.0.0`) committed `eval_private/genesis_capability_eval_v1/holdout.jsonl` — prompts, inputs, ground truth and scoring data — to a **public** repository, next to the seeded generators that can rebuild it. `.dockerignore` is not a confidentiality control, deleting the files would not restore secrecy (git history is permanent), and history was not rewritten. See `GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json` (V1: `FROZEN=false`, `PRIVATE_HOLDOUT_VALID=false`, reason `PUBLIC_REPOSITORY_EXPOSURE`; public/development benchmark only, never a basis for a private qualification decision). V1 hashes were not modified.

## 2. Public / private boundary

| Public repository MAY contain | Public repository MUST NEVER contain |
|---|---|
| harness, scorers, schemas, design, category definitions | private qualification prompts / inputs |
| aggregate counts, distributions, cluster counts | private answers, ground truth, reference solutions |
| opaque item ids, **salted commitments**, aggregate hash | exact generator seeds, reversible generation state, the corpus secret or store keys |
| public DEV examples, public regression fixtures (synthetic, in tests) | private images/documents, private Stage-1 (SCREEN) items |

## 3. Splits

`DEV` (public), `PILOT_TRAIN` (public, training-allowed), `SCREEN` (private, **Stage 1 only**), `QUALIFICATION_HOLDOUT` (private, **Stage 2 / final only**). No item may appear in SCREEN and QUALIFICATION_HOLDOUT (checked on ids, exact content commitments and normalized-text fingerprints; shared template clusters are reported). No V1 prompt, answer, seed or instance may be reused (`check_no_v1_reuse`). `planned_counts` in the public manifest are design targets only.

## 4. Secret generation

Per-item seeds, ids and commitment salts are `HMAC-SHA256(secret, domain | eval_version | category | split | index)`. The secret is ≥32 cryptographically random bytes supplied by the owner from a secret manager (`ORNEUR_GENESIS_V2_CORPUS_SECRET`); it is validated (length, byte diversity, not a repeated block/sequence, not derivable from public strings, hashes or small integers). Index, version, commit SHA and constants are HMAC *inputs*, never the key. **Nothing is invented**: with no secret present, loading raises. Public generator code is acceptable only because it cannot run without the secret.

## 5. Commitments and the public manifest

Commitment = `SHA256("genesis-v2/commitment" | salt | canonical item)` where `salt = HMAC(secret, item_id)` — hiding as well as binding, because a bare hash of a templated item is dictionary-attackable. Item ids are opaque HMAC outputs (`gce2-<24 hex>`), not content- or index-derived. The public manifest is validated by a whitelist: only counts, category/difficulty/cluster aggregates, `{id, commitment}` rows and hashes; any content-bearing key at any depth is a violation.

## 6. Storage boundary

`PrivateCorpusStore` protocol; default `NoStore` raises on every read/write. The **one operational backend** is `EncryptedFileStore` — an authenticated encrypted artifact outside the repository (AES-256-GCM, header bound as associated data, SEAL-last atomic write-once publication, 0700/0400 permissions, fail-closed integrity errors, ciphertext-only backups; full policy in `GENESIS_CAPABILITY_EVAL_V2_STORAGE_POLICY.md`). `PRIVATE_GITHUB_REPO` and `PRIVATE_OBJECT_STORE` remain validated **descriptors only** (no transport). The encrypted store is qualified by tests; `private_storage_genuinely_configured` remains false because no real vault/key exists. Its `cryptography` dependency is declared in the `qualification` extra and the mandatory CI job *Genesis V2 Security* runs the encryption tests with zero skips. `scripts/genesis_v2_preflight.py` reports exactly what is missing.

## 7. Qualification contract (write-once)

- Holdout lifecycle: `SEALED → OPENED → RETIRED`. Ground truth may be disclosed only after formal retirement (`POST_RETIREMENT_DISCLOSURE`).
- A qualification run is **write-once per candidate lineage**: no re-run, no retry, no inspection of private answers to debug or tune the same candidate, no `TUNING`/`ERROR_ANALYSIS`/`ANSWER_INSPECTION`/training/few-shot/router-tuning purposes.
- Any tuning or adaptation after a holdout was opened (candidate derived from an opened lineage) **requires a fresh holdout version** before final qualification (`FRESH_HOLDOUT_VERSION_REQUIRED`).
- SCREEN is used by Stage 1 only; the holdout stays unopened until the pre-registered final stage. Neither is accessible until V2 is frozen (`EVAL_NOT_FROZEN`).
- V1 run records are refused as V2 evidence (`V1_EVIDENCE_REFUSED`).

## 8. Access audit

Each access writes an immutable record — who/component, purpose, eval version, timestamp, corpus digest, run id, candidate revision (+ lineage, process code hash). The ledger is **SQLite** (`BEGIN IMMEDIATE`, `synchronous=FULL`): the decision and the append happen in one transaction, so concurrent processes are serialized — one contiguous sequence number per record, a run id granted once, a qualification lineage granted once per eval version (unique indexes as well as checks), records immutable (triggers), a crash before COMMIT leaves nothing and a retry is denied (`RUN_ALREADY_GRANTED`). Records are hash-chained; `verify_chain` detects edits, gaps, reordering and removed guards, and `head_anchor()` published externally detects truncation. Only pre-registered processes (id + code sha256 + allowed purposes/splits) are admitted. Results are bound write-once and idempotently by run id.

## 9. CI privacy invariant

`tests/test_genesis_v2_privacy.py` scans tracked files, untracked files and generated-artifact directories when release mode is PUBLIC (default; missing/invalid/unknown mode ⇒ PUBLIC; a file claiming PRIVATE is ignored without out-of-band attestation): private-corpus paths, private-holdout flags, ground truth / prompts / reference solutions under alternate field names in private-split or `gce2-` records, secret-seed and generation-state keys, store secrets and AES-key assignments, `.env`/secret-manager export files, archives (zip/tar/gz/bz2/xz, two levels; unscannable formats are violations), base64-embedded corpora, manifest-shaped documents that carry content, unclassified files under `notebooks/data`, and plaintext siblings of `.enc` artifacts. Errors are violations. Only the 71 hash-pinned V1 files are tolerated. Every rule has an adversarial mutation test and a clean twin.

## 9a. Contamination controls

`orca.eval.genesis_v2.contamination` (fail-closed; PASS/FAIL/NOT_CONFIGURED/CONTAMINATION_DATASET_UNAVAILABLE/INCOMPLETE): exact reuse against V1 (prompt, normalized prompt, item id, canonical content, generator instance material, hidden answers, reference-solution strings, scoring key) — high-entropy answer equality is a finding, low-entropy equality only together with a similar prompt; near-duplicate text (word 5-gram Jaccard ≥ 0.60, MinHash/LSH candidates verified exactly); structural/template clones (function-word skeleton Jaccard ≥ 0.75, robust to renamed entities, changed numbers, wording and sentence order). Thresholds are calibrated on the public V1 corpus (cross-category maximum 0.414 surface / 0.565 structure). Prompts under 14 tokens cannot be fingerprinted structurally: reported INCOMPLETE, private manual/semantic review required before freeze. Training/adaptation corpora: an interface plus fail-closed contract — a missing corpus is `CONTAMINATION_DATASET_UNAVAILABLE`, an undeclared corpus list is INCOMPLETE. Semantic overlap: `NOT_CONFIGURED` (no authorized local/private embedding mechanism; never faked, never provider inference). `contamination_controls_pass` requires every mandatory check PASS, so it is currently false.

## 9b. SCREEN vs QUALIFICATION_HOLDOUT separation policy

Gates (any violation FAILS, nothing is only reported): item-id overlap = 0, canonical content commitment overlap = 0, normalized-text overlap = 0, hidden answer/reference overlap (high-entropy answers and any long reference string, under any field name), near-duplicate text, structural clones, shared generation clusters, items without cluster labels. Category table (`isolation.SEPARATION_POLICY`), identical for every non-protocol category: risk HIGH, shared-cluster policy FAIL, near-duplicate FAIL, answer overlap HIGH_ENTROPY_ONLY; a category can only be relaxed with a written independence justification (≥ 40 chars) — none is. Structural fingerprint RELIABLE for: coding, counterfactual_reasoning, cross_domain_transfer, discovery_quality, evidence_use, hypothesis_testing, information_gain_reasoning, instruction_following, research, structured_outputs, tool_use; LIMITED (manual/semantic review required before freeze; separation cannot pass without it) for: long_context, mathematics, multilingual, multimodal_where_applicable, reasoning, strict_contracts, verification. Protocol categories (latency, cost, trainability) have no items.

## 9c. Public SFT datasets are not qualification evidence

`notebooks/data/*.jsonl` (including the legacy-named `orneur_genesis_v2_{train,eval}.jsonl`) are **PUBLIC_SFT** training data classified by `PUBLIC_SFT_DATASET_CLASSIFICATION.json` (hash-pinned; `may_be_qualification_evidence=false`; `is_genesis_capability_eval_v2=false`). They were not renamed because the V1 training-exclusion manifest references those paths; the builder now writes `genesis_sft_v2_public_{train,eval}.jsonl`. The scanner rejects unclassified or modified files there.

## 10. Freeze (not done)

V2 stays `FROZEN=false` until: private storage genuinely configured · new secret corpus generated · privacy audit pass · SCREEN/HOLDOUT separation pass · contamination controls pass · hashes/prereg frozen · sandbox ready · exact-SHA CI green · independent ChatGPT audit approval.

## 11. Preserved

Eternal Architecture 1.1 and Core Protocol 1.1 freezes, Contract Engine qualification, historical evidence, Stage-2 family-order and completeness/fail-closed corrections, funnel doctrine, no-selection state and all authorization=false states are untouched. No GPU, provider inference, training, spending or foundation selection.
