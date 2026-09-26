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

`PrivateCorpusStore` protocol; default `NoStore` raises on every read/write. `EncryptedFileStore` (AES-256-GCM, write-once, key from the environment, path must be outside the repository). Private GitHub repo / object store are accepted only as validated descriptors (must not be the public repo; credential is an env-var *name*). Transport is not implemented here — the owner supplies it. `scripts/genesis_v2_preflight.py` reports exactly what is missing.

## 7. Qualification contract (write-once)

- Holdout lifecycle: `SEALED → OPENED → RETIRED`. Ground truth may be disclosed only after formal retirement (`POST_RETIREMENT_DISCLOSURE`).
- A qualification run is **write-once per candidate lineage**: no re-run, no retry, no inspection of private answers to debug or tune the same candidate, no `TUNING`/`ERROR_ANALYSIS`/`ANSWER_INSPECTION`/training/few-shot/router-tuning purposes.
- Any tuning or adaptation after a holdout was opened (candidate derived from an opened lineage) **requires a fresh holdout version** before final qualification (`FRESH_HOLDOUT_VERSION_REQUIRED`).
- SCREEN is used by Stage 1 only; the holdout stays unopened until the pre-registered final stage. Neither is accessible until V2 is frozen (`EVAL_NOT_FROZEN`).
- V1 run records are refused as V2 evidence (`V1_EVIDENCE_REFUSED`).

## 8. Access audit

Each access writes an immutable record — who/component, purpose, eval version, timestamp, corpus digest, run id, candidate revision (+ lineage, process code hash) — as a create-exclusive read-only file chained by `prev_hash`/`record_hash`; the grant is issued only after the record exists. Only pre-registered processes (id + code sha256 + allowed purposes/splits) are admitted. `verify_chain` detects gaps, edits, reordering. Results are bound write-once by run id.

## 9. CI privacy invariant

`tests/test_genesis_v2_privacy.py` scans tracked files, untracked files and generated-artifact directories when release mode is PUBLIC (the default; missing/invalid/unknown mode ⇒ PUBLIC): private-corpus paths, private-holdout flags, ground truth / prompts in private-split records, secret-seed and generation-state keys, store secrets. Errors are violations. Only the 71 hash-pinned V1 files are tolerated (modified ⇒ violation). Mutation tests prove each rule fires.

## 10. Freeze (not done)

V2 stays `FROZEN=false` until: private storage genuinely configured · new secret corpus generated · privacy audit pass · SCREEN/HOLDOUT separation pass · contamination controls pass · hashes/prereg frozen · sandbox ready · exact-SHA CI green · independent ChatGPT audit approval.

## 11. Preserved

Eternal Architecture 1.1 and Core Protocol 1.1 freezes, Contract Engine qualification, historical evidence, Stage-2 family-order and completeness/fail-closed corrections, funnel doctrine, no-selection state and all authorization=false states are untouched. No GPU, provider inference, training, spending or foundation selection.
