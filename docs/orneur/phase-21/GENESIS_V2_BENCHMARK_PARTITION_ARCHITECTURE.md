# Genesis Capability Eval V2 — Benchmark Partition Architecture (PREPARATION ONLY — NOTHING GENERATED)

No PILOT_TRAIN, DEV, SCREEN, or QUALIFICATION_HOLDOUT item exists. This document defines the storage/access boundaries,
reproducible-generation commitments, cryptographic manifest shape, deduplication controls, leakage detection and access
evidence that will apply once generation is separately authorized (`corpus_generation_authorization.py`). It only
describes and cross-references machinery that is already implemented and tested; it does not itself create any content.

## 1. The four splits and their classification

Per `orca/eval/genesis_v2/spec.py` (`SPLITS`, `PUBLIC_SPLITS`, `PRIVATE_SPLITS`, `STAGE_SPLIT`):

| Split | Classification | Storage | Purpose |
|---|---|---|---|
| `PILOT_TRAIN` | **PUBLIC** | repository / public artifact store | small-scale pre-check, published alongside the eval |
| `DEV` | **PUBLIC** | repository / public artifact store | ongoing public development signal |
| `SCREEN` | **PRIVATE** | encrypted vault (`store.EncryptedFileStore`) | Stage 1 candidate screening (`STAGE_1`) |
| `QUALIFICATION_HOLDOUT` | **PRIVATE** | encrypted vault (`store.EncryptedFileStore`) | Stage 2 final qualification (`STAGE_2`) — the sealed item |

`PILOT_TRAIN`/`DEV` being public is an existing, deliberate design choice (V1 followed the same pattern) — they are not
secret and do not need vault storage, but they DO need the same non-reuse and non-contamination guarantees as any
other corpus class recorded in the training-corpus inventory (`inventory.py`), since a public split can still leak
into training data if not tracked.

## 2. Storage and access boundaries

- **`SCREEN` / `QUALIFICATION_HOLDOUT`**: written via `store.EncryptedFileStore.write_corpus()` — AES-256-GCM, a fresh
  `os.urandom(12)` nonce per blob (never reused — verified by `test_nonces_never_repeat_across_many_encryptions`),
  atomic `O_CREAT|O_EXCL` + `link()` publish (`_publish()`; never overwrites), directory `0700` / ciphertext files
  `0400`, vault located **outside every git working tree** (`vault_admin.py`, `vault_verify.verify_vault_isolation`).
  Read access requires `orca.eval.genesis_v2.ledger.AccessLedger` to have a pre-registered process matching the
  requested corpus/split/purpose (`ledger.py`); the qualification-runner registry (`runner_registry.py`) is the only
  source of registrable process identities, and its committed state stays `REGISTERED_NOT_AUTHORIZED` (grants nothing)
  until V2 is frozen.
- **`PILOT_TRAIN` / `DEV`**: ordinary repository / public-store files, hash-recorded in the training-corpus inventory
  like any other corpus, with `used_in_training`/`used_in_adaptation`/`visible_during_screen`/
  `visible_during_qualification_holdout` tristate flags — never silently assumed.

## 3. SCREEN vs QUALIFICATION_HOLDOUT isolation

Already implemented and tested: `orca.eval.genesis_v2.isolation.SEPARATION_POLICY` — every applicable category is
`shared_cluster_policy: FAIL` (a generation cluster/template present in both splits fails), `near_duplicate: FAIL`,
and `answer_overlap: HIGH_ENTROPY_ONLY`. `_LIMITED` categories (reasoning, mathematics, multilingual, verification,
long_context, multimodal_where_applicable, strict_contracts) require private manual/semantic review before freeze —
structural fingerprinting alone is not trusted there. `component_states.split_isolation_policy = IMPLEMENTED_TESTED`.

`QUALIFICATION_HOLDOUT` lifecycle (per `spec.py`): `SEALED → OPENED (once, by one candidate lineage) → RETIRED`. It
must never be visible during development, training, or candidate selection — enforced by the tristate flags above
plus the ledger's purpose/split scoping (`ALLOWED_PURPOSES`).

## 4. Reproducible generation commitments

Generation (when separately authorized) must commit to, and record in the preregistration and/or a per-corpus
manifest:
- exact generator code SHA-256 (`runner_registry.code_sha256_of`, already used for the qualification-runner identity),
- exact seed / procedural-generator parameters used per category,
- exact commit SHA the generation ran at,
- the resulting corpus digest (`store.write_corpus()`'s return value, SHA-256 over both split payloads).

This mirrors the pattern already used for the sandbox qualification-candidate record (`sandbox_qualification.py`):
tested-implementation SHA distinct from evidence-record SHA, never a self-referential or placeholder commit.

## 5. Cryptographic manifest

A per-corpus manifest (proposed shape, not yet implemented as code — see `manifest.py` for the existing V1-era
manifest primitives this would extend):
```json
{
  "corpus_id": "gce2c-<hex>",
  "eval_version": "genesis-capability-eval/2.x.x",
  "generator_code_sha256": "<64 hex>",
  "generated_at_commit_sha": "<40 hex>",
  "screen_digest": "<64 hex>",
  "qualification_holdout_digest": "<64 hex>",
  "per_category_item_counts": {"...": 0},
  "corpus_generation_authorization_id": "cgauth-<hex>"
}
```
Public-safe: digests and counts only, never item content — matching every other evidence artifact in this phase.

## 6. Deduplication controls

Within-split and cross-split: exact-hash dedup (SHA-256 of normalized item text) plus near-duplicate detection via
the existing skeleton/structural fingerprinting used by `isolation.py`'s `near_duplicate: FAIL` policy. Cross-corpus
(against the 70-entry historical inventory): the training-corpus contamination check (`contamination.py`,
`check_training_corpora`) already implements Jaccard-based near-duplicate and structural-clone detection
(`NEAR_DUP_JACCARD = 0.60`, `STRUCT_CLONE_JACCARD = 0.75`) and answer-overlap detection for high-entropy answers.

## 7. Leakage detection

- `privacy_scan.scan_repository()` (already implemented, tested, run every phase) — fails on any `.enc` artifact,
  corpus path, or secret pattern appearing in the repository, tracked or untracked.
- `contamination.check_training_corpora` + `semantic.SemanticOverlapEngine` — cross-checks V2 items against every
  PRESENT/resolvable historical corpus and (once genuinely `QUALIFIED`, not just `CONFIGURED_LOCAL_ONLY`) semantic
  near-duplicates.
- Access evidence: every real SCREEN/QUALIFICATION_HOLDOUT read must appear in `AccessLedger`'s append-only,
  hash-chained log (`ledger.py`) — a mismatch between the ledger head and its anchor is itself defined as a privacy
  incident (see the vault procedure doc, §10).

## 8. What is explicitly NOT built by this document

No generator code for actual item content, no real corpus, no real manifest file, no schema enforcement code for the
manifest shape in §5 (proposed only). These are unresolved/proposed capabilities for a future, explicitly-authorized
phase — see the final report's capability classification.
