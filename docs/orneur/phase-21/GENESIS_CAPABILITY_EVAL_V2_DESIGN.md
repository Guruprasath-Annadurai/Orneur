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

## 9d. Model-execution authorization boundary (IMPLEMENTED + TESTED)

Ordinary repository activity can never invoke a model. `eval.yml` (model evaluation) and `seed.yml` (Ollama seeding) are `workflow_dispatch` only and their self-hosted jobs `need` an `authorize` job (GitHub-hosted, no model) that runs `scripts/ci/verify_model_eval_authorization.py`. The gate verifies the committed record `docs/orneur/authorization/MODEL_EVAL_AUTHORIZATION.json` (schema `orneur-model-eval-authorization/1`: authorization id, exact commit SHA, eval version, candidate model + revision, permitted stage/runner class/purpose, max runs and spend, issued/expiry, authorizing authority, GPU and provider-inference permissions, Ed25519 signature) against THIS exact request. The committed state is **NOT_AUTHORIZED** and `TRUSTED_AUTHORITY_KEYS.json` has no key, so nothing can be authorized (an agent cannot forge approval by editing the record). Static CPU data checks live in `eval-static-checks.yml` (GitHub-hosted, no model command). Tests parse every workflow and fail if any auto-triggered job runs a model command or a self-hosted runner.

## 9e. Corpus inventory (IMPLEMENTED, populated, UNATTESTED)

`GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json` lists every known corpus (public SFT sets, V1 pilot/dev/exposed holdout, and the owner's machine-local raw/distilled/formatted/DPO/synthetic/distill-log corpora, by hash and count only) with class, provenance, classification, storage descriptor, hash, usage/visibility flags, lifecycle, contamination-check status, owner and PRESENT/DECLARED_NOT_PRESENT/UNAVAILABLE/RETIRED status. Fail closed: an empty inventory is INCOMPLETE; an unattested inventory, an unattested class (`NONE_KNOWN_UNATTESTED`: reasoning, coding, tool-use, RLHF/RLAIF, few-shot stores, retrieval, router/expert data, future and candidate-specific sets), any UNAVAILABLE or non-resolvable source, any UNKNOWN flag or non-PASS contamination check blocks `contamination_controls_pass`. The Kaggle-uploaded datasets cannot be inspected from the repository and stay UNAVAILABLE.

## 9f. Semantic overlap and manual review (IMPLEMENTED + TESTED, operationally NOT_CONFIGURED)

`semantic.py`: local, CPU-only, provider-free engine (deterministic preprocessing, cosine similarity, per-category thresholds, ambiguity band, IDs-and-scores-only artifact, model hash recorded, no auto-download). The only bundled embedder is a lexical feature-hash proxy that is never accepted as semantic review; a local model requires an explicit directory with a pre-registered content hash. `review.py`: signed manual-review decisions binding item id, eval version, reviewer identity/role/key, purpose, exact corpus digest, similarity-evidence digest, disposition (CLEAR / REJECT_CONTAMINATED / NEEDS_REGENERATION / INCONCLUSIVE), timestamp and schema version; INCONCLUSIVE, missing or stale-evidence reviews never PASS, and `TRUSTED_REVIEWER_KEYS.json` is empty. `combine_semantic_and_manual` passes only with (accepted local engine PASS + flagged items cleared) or a FULL manual review; the split-isolation structure review accepts a manual review as its evidence.

## 9g. Hermetic coding sandbox (IMPLEMENTED + TESTED; `sandbox_ready` = false)

`sandbox.py` extends the hardened Docker primitive: one fresh container per item; `--network none`, read-only root, tmpfs `/work` and `/tmp` (size-capped, noexec), the staged job directory as the only host mount (read-only), uid 65534, all capabilities dropped, no-new-privileges, private PID/IPC, memory/cpu/pids/ulimits, `env -i` allow-list, `--pull never`, host-side wall-clock kill of the named container, streamed output cap, digest-only `ExecutionRecord` (item id, candidate revision, image digest, command, exit status, timeout/limit flags, stdout/stderr/test-result digests, duration, policy version). The pure policy tests and the Docker containment suite (host filesystem, network egress, localhost/metadata, fork bomb, infinite loop, oversized stdout and file, memory bomb, environment secrets, path traversal, symlink escape, Docker socket, persistence) run in the mandatory *Genesis V2 Sandbox* CI job with zero skips. No model-generated code is executed. `sandbox_ready` stays false: it needs the image pinned by digest in the frozen preregistration, the suite executed on the scoring runner class, and independent audit.

## 9h. Preregistration draft and owner procedure (DESIGNED)

`GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json` (+ schema) binds the 23 required fields; unknowns (aggregate commitment, code hashes, runner identity, storage verification digest, spend limits) are null; floors are PROPOSED_NOT_LOCKED; no candidate results may exist; a frozen record needs every binding and LOCKED floors, and floors cannot change after freeze or after the first candidate run. `GENESIS_CAPABILITY_EVAL_V2_OWNER_VAULT_PROCEDURE.md` is the placeholder-only owner procedure; `scripts/genesis_v2_vault_verify.py` proves the vault is outside every git work tree and unreachable from the public repo.

## 9i. Status terminology

DESIGNED < IMPLEMENTED < TESTED < QUALIFIED < FROZEN < PRODUCTION READY. Unit-tested code is TESTED, never "qualified". Nothing in V2 is QUALIFIED, FROZEN or PRODUCTION READY.

## 9j. Pre-corpus owner setup & qualification environment closure (this phase)

- **Vault**: `EncryptedFileStore` was activated at a real, isolated, on-machine directory and round-tripped with an EPHEMERAL TEST key (destroyed afterward, along with the test ciphertext) — `orca.eval.genesis_v2.vault_admin`. The public-safe `GENESIS_V2_VAULT_VERIFICATION.json` records only a one-way path digest, policy PASS/FAIL results and a verifier-code hash; no path, key or plaintext. `private_storage_genuinely_configured` stays false: activation with a test key is not the same as a real corpus secret in a real secret manager.
- **Secret manager**: `orca.eval.genesis_v2.secret_manager` defines the policy (owner, generation method, entropy floor, storage class, access scope, rotation/revocation/backup/incident rules) for every secret class, and probes for macOS Keychain as an available local mechanism — never touching a real secret value.
- **Authority / reviewer registries**: `authority_registry.py` / `reviewer_registry.py` (+ `identity_registry.py`) bind role, public key, activation/expiry, revocation and permitted classes/domains; `AUTHORITY_REGISTRY.json` / `REVIEWER_REGISTRY.json` are committed **empty** — registering an authority is never authorizing a run, and no real signing key was generated on the owner's behalf (a private key that only I could hold would not be safely the owner's). Separation-of-duties is checked (`check_separation_of_duties`).
- **Corpus inventory**: a genuine review reclassified nine corpus classes from placeholder `NONE_KNOWN_UNATTESTED` to reviewed `NONE_EXIST_ATTESTED` (confirmed absent, not guessed). The one real unresolved risk (Kaggle-derived datasets referenced by legacy notebooks) stays `UNAVAILABLE`. A full signed-attestation schema now exists (`inventory.validate_attestation_record`); the committed record is an honest **unsigned draft** (`status=NOT_ATTESTED`) because no OWNER authority key is registered to sign it — `contamination_controls_pass` stays false either way.
- **Sandbox**: `docker/genesis_v2_sandbox/Dockerfile` pins the base image by digest; the built qualification-candidate image (its own content digest) passed the full 18-test containment suite. `GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json` records image/Dockerfile digests, runtime versions and the test-result digest. `sandbox_ready` stays false pending preregistration freeze and independent audit.
- **Qualification runner**: `runner_registry.py` binds runner id, class, code hash, sandbox/storage/ledger digests and a credential scope that excludes training/public-write/unrelated-cloud/developer-token access; state `REGISTERED_NOT_AUTHORIZED` — `to_ledger_registered_processes` grants nothing until state is `AUTHORIZED`.
- **Ledger deployment**: the real SQLite ledger was initialized empty at an isolated location (`ledger_admin.py`); `GENESIS_V2_LEDGER_DEPLOYMENT_RECORD.json` confirms permissions, immutability triggers and zero benchmark content, again with no path disclosed.
- **Preregistration**: 22 of 23 bindings are now honestly filled (runner identity, storage/sandbox/ledger digests, code hashes, resource/spend limits at zero); only `private_corpus_aggregate_commitment` remains null, as it must.
- **Owner preflight**: `scripts/genesis_v2_owner_preflight.py` aggregates every check above into one `READY_FOR_PRIVATE_CORPUS_AUTHORIZATION` / `NOT_READY` verdict. It currently reports `NOT_READY` (inventory attestation unsigned, semantic engine `NOT_CONFIGURED`, sandbox not independently approved) — never generates anything itself.

## 9k. Final pre-corpus closure (this phase)

Continuation of 9j, closing the specific gaps an independent audit flagged in it.

- **Sandbox exact-SHA evidence**: `GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json` no longer contains a `PENDING_COMMIT_WILL_BE_SET_AT_PUSH_TIME` placeholder. It now distinguishes `tested_implementation_sha` (an already-existing, immutable, CI-verified commit whose code was actually exercised) from `evidence_record_commit` (the later commit that adds this exact file, deliberately left `null` in the file and reported separately in the phase report — never self-referenced, to avoid a circular claim).
- **Qualification runner qualification**: `runner_qualification.py` binds the concrete machine facts (OS, arch, CPU count, Docker runtime, memory floor, storage/network class) behind the `SELF_HOSTED_CPU` runner class, and proves — via `same_environment_proof` — that the sandbox containment suite ran on the *same* runner class the registry declares. `QUALIFICATION_RUNNER_REGISTRY.json`'s `os_runtime` no longer says "TBD by owner"; this local owner machine is bound explicitly as the canonical runner (no separate hosted infrastructure exists yet).
- **Owner authority key**: per explicit owner decision, Claude never generates this key. `OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md` documents the exact owner-run keygen/export/verify/rotate/revoke procedure (Ed25519 via `openssl`); `AUTHORITY_REGISTRY.json` stays committed empty until the owner runs it and provides only the resulting public key + key_id. Doctrine: *the human owner holds private authority; ORNEUR only verifies signatures.*
- **Reviewer path**: no independent reviewer identity was fabricated. `REVIEWER_PATH_STATUS.md` documents the reviewer registry staying empty and the manual-review path as not operational, and records that the *semantic* path substitutes for it this phase (see below), including an honest investigation of the calibration set's one false negative (a register-shift paraphrase scoring just under threshold) rather than silently lowering the threshold.
- **Local semantic engine**: `sentence-transformers/all-MiniLM-L6-v2` (pinned revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, Apache-2.0) was downloaded — after documenting model/source/revision/license/size/files to the owner first — into a dedicated pinned local directory, loaded via a `transformers`+`torch`-native mean-pooling encoder (`semantic.py`, no `sentence-transformers` package dependency needed), and proven to load and score with outbound sockets blocked. Calibrated against a 20-pair synthetic fixture set (`semantic_calibration.py`): 0 false positives, 1 false negative at threshold 0.85. State: `semantic_overlap = CONFIGURED_LOCAL_ONLY` — explicitly not `QUALIFIED`.
- **Corpus inventory terminology**: `NONE_EXIST_ATTESTED` is now reserved for *after* a genuine signed `ATTESTED` record exists (enforced in `inventory.validate()`); the nine classes reviewed-but-unsigned this phase use the new `NONE_DECLARED_OWNER_REVIEWED` value instead. `GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json` is a frozen (corpus-independent) governance policy defining when `COMPLETE_WITH_DECLARED_UNAVAILABLE` is acceptable and the fail-closed rules that follow (no training on unresolved data, contamination risk register, mandatory re-analysis on later recovery, no silent retroactive changes).
- **Preregistration binding_status**: a new `binding_status` map (schema `genesis-v2-preregistration/1` unchanged; `binding_status` is a new required top-level field) distinguishes `BOUND` / `OPERATIONALLY_CONFIGURED` / `QUALIFIED` / `DEFERRED` / `NOT_APPLICABLE` per binding, so a filled JSON value is never conflated with an approved one.
- **Owner preflight**: rewritten to also require an authority key registered+valid, the corpus inventory attestation signed+accepted, at least one of the semantic/reviewer paths operational, the qualification runner qualified, and the sandbox runner class matching the qualification runner class. It correctly still returns `NOT_READY`, now narrowed to exactly two genuinely owner-gated blockers: `authority_key_registered_and_valid` and `corpus_inventory_attested_pass`.
- **Pre-corpus closure manifest**: `closure_manifest.py` builds `GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST.json`, a public-safe SHA-256 bundle over every artifact this phase and the previous one touched, plus the current owner-preflight result and an explicit `authorizations` block confirming nothing was generated (corpus, SCREEN, holdout, secret, AES key, model inference, GPU, training, spend, foundation, freeze).

## 9m. Pre-corpus attestation / full contamination qualification stage-boundary fix (this phase)

An independent audit found that `owner_preflight.py`'s `corpus_inventory_attested_pass` check used the full `inventory.evaluate()`
verdict, which requires every source corpus to be resolvable on disk, hash-verified, and `contamination_check_status == PASS` per
corpus. Since the private V2 corpus does not exist yet, `evaluate()` can never legitimately reach `PASS` at this stage — the check
was structurally impossible to satisfy, a stage-boundary defect, not a real safeguard.

Fix: `inventory.evaluate_pre_corpus_attestation()` answers a narrower, genuinely pre-corpus-appropriate question — is the owner's
SIGNED completeness attestation itself valid (real OWNER Ed25519 signature, exact `corpus_inventory_digest` binding, every class
declared, and any unresolved class covered by a frozen `GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json`)? It never resolves a
corpus file or checks `contamination_check_status`. `owner_preflight.corpus_inventory_attested_pass` now uses this function.

`inventory.evaluate()` (full contamination qualification) is **unchanged** and remains fail-closed: it still requires every source
resolvable, hash-matched, and per-corpus `contamination_check_status == PASS`, and correctly still cannot reach `PASS` before a real
V2 corpus exists. `owner_preflight` now also reports `corpus_inventory_full_contamination_qualification_status` informationally
(currently `CONTAMINATION_DATASET_UNAVAILABLE`), but never gates readiness on it pre-corpus.

## 10. Freeze (not done)

V2 stays `FROZEN=false` until: private storage genuinely configured · new secret corpus generated · privacy audit pass · SCREEN/HOLDOUT separation pass · contamination controls pass · hashes/prereg frozen · sandbox ready · exact-SHA CI green · independent ChatGPT audit approval.

## 11. Preserved

Eternal Architecture 1.1 and Core Protocol 1.1 freezes, Contract Engine qualification, historical evidence, Stage-2 family-order and completeness/fail-closed corrections, funnel doctrine, no-selection state and all authorization=false states are untouched. No GPU, provider inference, training, spending or foundation selection.
