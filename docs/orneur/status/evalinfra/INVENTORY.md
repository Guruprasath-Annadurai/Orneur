# Workstream F: Evaluation-infrastructure inventory and what `orca/evalinfra` adds

NON_NORMATIVE status document. Snapshot: branch `claude/ws-f-evalinfra`, cut from `claude/integration-candidate-1` at `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`.
It authorizes nothing, freezes nothing, flips no flag, and contains no private-corpus material, secret or key. Everything the new package does is synthetic-data-only:
no model training, no GPU, no inference, no provider or network call, no weight download. The V1 holdout is public-exposed and permanently invalid; no V1 prompt, answer,
seed or instance is used anywhere in this work.

Method: every module named in the task was opened and read (`orca/eval/genesis_v2/*`, `orca/eval/genesis_stats.py`, `orca/eval/frontier_stats.py`, `orca/eval/genesis_prereg.py`,
`orca/registry/evaluation_*`, `scripts/genesis_v2_*preflight*.py`, the V2 design/prereg-schema/judge/frontier-scoring/integrity/partition documents, and blueprint section 6). Where an existing
module was the right home, it is *reused by import*, not copied.

Status vocabulary (the repository's own rule: a component is not QUALIFIED/FROZEN until an independent audit says so; nothing below is):
`EXISTS` = already in the repository before this branch. `ADDED` = new in this branch, tested against synthetic fixtures only. `DESIGN_ONLY` = documented, not executable. `GAP` = not present anywhere.

## 1. Existing V2 infrastructure (read, not changed)

| Component | File(s) | What it really does | State per `GENESIS_CAPABILITY_EVAL_V2_STATUS.json` |
|---|---|---|---|
| Constants, splits, freeze gate | `genesis_v2/spec.py` | splits `DEV, PILOT_TRAIN, SCREEN, QUALIFICATION_HOLDOUT`; purposes; `FORBIDDEN_PUBLIC_KEYS`; `freeze_status()` needs all 9 prerequisites (all false) | `GENESIS_CAPABILITY_EVAL_V2_FROZEN = False` |
| Access ledger | `genesis_v2/ledger.py` | SQLite, hash-chained, immutable (triggers), write-once holdout lifecycle, `EVAL_NOT_FROZEN` for qualification, unique run id / lineage | `IMPLEMENTED_TESTED`; deployed as sqlite |
| Private store | `genesis_v2/store.py` | `NoStore` (default, refuses), `EncryptedFileStore` (AES-GCM, legacy), `EncryptedVaultWriter/Reader` (X25519 write-only vs read), role preflights. `PRIVATE_GITHUB_REPO` / `PRIVATE_OBJECT_STORE` are validated descriptors only | `ACTIVATED_VERIFIED_TEST_ONLY` (ephemeral test key); `private_storage_state: NOT_CONFIGURED` |
| Secret + secret manager | `secret.py`, `secret_manager.py` | entropy/derivation rules (HMAC ids/seeds/commitments), per-class custody policy, macOS Keychain presence probe | policy implemented; no real secret exists |
| Authorization gate | `authorization.py`, `authority_registry.py`, `identity_registry.py` | Ed25519-signed, request-exact model-execution authorization; active-key derivation (revoked/expired excluded) | committed record `NOT_AUTHORIZED`; one owner authority key registered |
| Reviewers | `review.py`, `reviewer_registry.py` | signed manual-review dispositions bound to a corpus digest; separation of duties | `REVIEWER_REGISTRY.json`: zero keys; reviewer path not operational |
| Runner / generator identities | `runner_registry.py`, `generator_registry.py`, `operational_boundary.py` | registry-driven identities, composed fail-closed gates for generation and for private-split read | runner `REGISTERED_NOT_AUTHORIZED`; generator registry empty |
| Preregistration | `prereg.py` + `GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_{DRAFT,SCHEMA}.json` | 23 bindings, per-binding status, freeze validator, floors immutability | DRAFT_NOT_FROZEN, 22/23 bound |
| Manifest | `manifest.py` | public manifest = opaque ids + salted commitments only; whitelist validator | schema only (no corpus) |
| Contamination / similarity / isolation | `contamination.py`, `similarity.py`, `semantic*.py`, `isolation.py` | MinHash+LSH, skeleton clones, V1 reference, SCREEN-vs-HOLDOUT policy | `IMPLEMENTED_TESTED`; semantic path `NOT_CONFIGURED` |
| Privacy scan | `privacy_scan.py` | fail-closed repository scanner for private material | `IMPLEMENTED_TESTED` |
| Sandbox | `sandbox*.py`, `eval/sandbox*.py` | hermetic coding sandbox | `sandbox_ready = false` |
| Corpus-generation authorization etc. | `corpus_generation_authorization.py`, `generation_receipt.py`, `corpus_manifest.py`, `candidate_lineage.py`, `closure_manifest.py`, `inventory.py`, `vault_*.py`, `owner_preflight.py` | owner-signed generation grant, receipts, lineage, closure | `IMPLEMENTED_TESTED`, grant `NOT_AUTHORIZED` |
| V1 statistics | `eval/genesis_stats.py` | Wilson intervals, floor power, category aggregates (floor decisions, not arm comparison) | EXISTS |
| Frontier statistics | `eval/frontier_stats.py` | cluster-aware paired bootstrap, unseeded by default, percentile only, resamples >= 1, classification vs references | EXISTS |
| V1 prereg | `eval/genesis_prereg.py` | builds the V1 prereg (V1 is public, invalid) | EXISTS, not reused |
| Registry records | `registry/evaluation_{registry,suite_manifest,result_manifest}.py` | mutable-registry result record for baseline runs, promotion thresholds | EXISTS; not hash-chained, not tied to a prereg |
| Preflight scripts | `scripts/genesis_v2_preflight.py`, `genesis_v2_owner_preflight.py` | presence-only environment checks | EXISTS |

## 2. The thirteen deliverables: before / after

| # | Deliverable | Before this branch | Added (module, all synthetic-tested) | Reused from existing | What is still NOT true |
|---|---|---|---|---|---|
| 1 | Schema + manifest validation | PARTIAL: `manifest.py` validates the V2 *public* manifest; no category/scorer/partition schema | `schema.py`: strict whitelist at every level (items, categories, scorers, partitions); unknown field, duplicate id/commitment, missing commitment, V1 id/version, LLM-judge scorer, content key, hash tamper => `SchemaViolation` | `FORBIDDEN_PUBLIC_KEYS` | Not wired into corpus generation (no generator exists) |
| 2 | Private-storage integration + tests | PARTIAL: `PrivateCorpusStore` protocol, `NoStore`, `EncryptedFileStore`; no backend-agnostic conformance suite | `private_store.py`: `SyntheticMemoryStore`, `SyntheticDirStore` (same protocol), `GuardedReader`, `is_private_grade()`; one conformance suite run against NoStore, EncryptedFileStore (ephemeral key), synthetic backends; `PRIVATE_STORE_INTEGRATION_DESIGN.md` | `store.py` protocol, errors, `corpus_digest_of` | Synthetic backends give **no confidentiality** and are never private-grade. No real private store exists (founder act) |
| 3 | Split separation (SCREEN/HOLDOUT/DEV/TRAIN) | PARTIAL: `isolation.py` covers SCREEN vs HOLDOUT only | `splits.py`: all 6 split pairs; exact id/content/text/answer/leaf; near-duplicate; structural clone; shared cluster; canary | `similarity.py`, `contamination.py` thresholds | Run only on synthetic items; no real corpus to check; semantic (embedding) overlap still `NOT_CONFIGURED` |
| 4 | Result-artifact leakage checks | GAP (privacy scan covers the *repository*, not result artifacts) | `leakage.py`: forbidden keys, canaries, prompt 8-gram windows, answer text; `results.py` refuses leaking results; findings never echo text | `FORBIDDEN_PUBLIC_KEYS`, `similarity.normalize` | Short hidden answers (<24 chars) cannot be text-searched; protection there is the strict result-row whitelist (documented, tested) |
| 5 | Protected-access control tests | PARTIAL: each gate tested separately | `access.py` `ProtectedEvalGate`: composes runner registry, authorization, reviewer manifest, vault preflight, ledger; adds replay protection, revocation list, mandatory ledger anchor, dataset-commitment binding, use-time grant re-verification; 36 denial/permit tests with synthetic registries in temp dirs | all of `authorization`, `*_registry`, `review`, `ledger`, `store` preflight | Real registries are still empty/NOT_AUTHORIZED, so the real gate denies everything (tested read-only) |
| 6 | Paired comparison harness | GAP for six-arm paired design (`frontier_stats` = cluster bootstrap vs references) | `stats_paired.py`: McNemar exact, seeded paired bootstrap (percentile + BCa, >= 10,000), effect sizes, per-category breakdown (no merge function exists), Bonferroni/Holm/BH with explicit families, replicate/seed replication, zero-tolerance counts | - | Binary endpoints only for confirmatory use; continuous metrics are not supported |
| 7 | Power / MDE / sample size | GAP in code (numbers only in blueprint prose) | `stats_power.py`: closed form, MDE by inversion, exact-test power, seeded simulation; reproduces blueprint 6.6 | blueprint 6.6 as oracle | See finding F2 (blueprint rounds three cells to nearest) |
| 8 | Human judge rubric + disagreement process | DESIGN_ONLY (`GENESIS_JUDGE_PROTOCOL_SPEC.md` is an LLM-judge design) | `rating.py`: rubric schema, humans-only raters, blinding, double-rating assignment, Cohen's kappa, Krippendorff's alpha (matches Krippendorff 2011 published values), adjudication state machine with forced third rater | - | No human raters exist; blinding cannot detect arm tells inside response text |
| 9 | Config locking | PARTIAL: `EvaluationResultManifest` records fields but does not lock/compare | `config_lock.py`, enforced in `results.py` | - | Hash binding proves *which* config was declared, not that it was actually what ran |
| 10 | Metric defs + prereg validation | PARTIAL: `prereg.py` validates bindings; no endpoints/thresholds/analysis plan anywhere | `prereg_check.py`: repo-schema validation + analysis-plan schema (<=4 primaries, numeric thresholds, families, margins for every category, zero-tolerance 10/14/15/17, >=3 odd replicates, >=10,000 resamples) + hash-chain gate (unfrozen/modified => refuse) | `prereg.validate_for_freeze`, `record_hash`, schema JSON | The real prereg is a DRAFT; it can never pass this gate today. See finding F1 |
| 11 | Cost accounting + quota refusal | GAP (only `max_spend_usd` inside an authorization record) | `budget.py`: chained ledger, default cap 0 refuses everything, contingency, overrun lock | - | Not connected to any real spend path (none is authorized) |
| 12 | Immutable result manifest + verifier | PARTIAL: ledger (access records only) | `chain.py`, `results.py`, CLI `python -m orca.evalinfra verify` | - | Rollback of whole newest entries is detectable only against an externally published head (documented, tested) |
| 13 | Reproducible reporting | GAP | `report.py` (JSON + Markdown, byte-reproducible) | - | - |

Demo: `scripts/evalinfra_synthetic_demo.py` -> `docs/orneur/status/evalinfra/demo/` (SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY; a test regenerates it byte-for-byte).

## 3. Findings about the existing code and documents (reported, not fixed: those paths are frozen or out of scope)

* **F1. `prereg.validate_binding_status` requires the DEFERRED binding to keep status `DEFERRED` even after it is filled.** `private_corpus_aggregate_commitment` is the only key in `DEFERRED`;
  the validator rejects any other status for it, so a record that binds the commitment (value non-null) and marks it `BOUND` fails `validate_for_freeze`. Either the real freeze
  record must (confusingly) keep `DEFERRED`, or the validator needs a fix before freeze. The synthetic fixtures here keep `DEFERRED` to pass the existing validator unchanged. Needs an owner decision;
  this branch does not edit `orca/eval/genesis_v2/prereg.py` semantics.
* **F2. Blueprint 6.6 rounds three cells of its sample-size table to nearest, not up** (8 pts/p_d .10: 120.25 -> 120, correct 121; 10 pts/.10: 76.09 -> 76, correct 77; 10 pts/.30: 233.09 -> 233, correct 234).
  All other cells, all MDE values (19.2, 13.8, 12.4, 11.3, 6.1, 4.0) and the Bonferroni figure (1,020) reproduce exactly. `required_n(..., rounding="nearest")` reproduces the document; the default is the safe `ceil`.
* **F3. Category numbering.** The zero-tolerance ids 10/14/15/17 belong to the 17-category *capability spec* numbering (`genesis_suite.CATEGORY_NAMES`), whereas the V2 corpus categories in
  `genesis_eval_v1.CATEGORIES` are named strings with a different set. No mapping between the two exists in the repository; evalinfra accepts either id type per manifest and the analysis plan
  names the numeric ids, so the founder/reviewer must define the V2-corpus-to-spec mapping before a real prereg is written.
* **F4. The existing `frontier_stats.paired_bootstrap_ci` does not require a seed or a minimum resample count** and offers percentile intervals only; it is left untouched (frozen contract
  `GENESIS_FRONTIER_SCORING_CONTRACT.md`) and evalinfra does not call it.
* **F5. `genesis_suite` marks categories 2, 6, 8, 13 as `llm_judge`.** evalinfra refuses LLM-judge scorers outright (`LLM_JUDGE_FORBIDDEN`) and offers `human_rubric`; reconciling this with the multi-LLM-judge protocol spec is a design decision for the owner.
* **F6. The ledger had no authorization replay protection and no mandatory external head anchor.** `max_runs` in an authorization record was only compared to the *request*. The new gate adds a chained consumption log and requires an anchored ledger head; the ledger module itself is unchanged.
* **F7. Five pre-existing, environment-dependent test failures** (verified identical on the untouched base commit `cd6af2a` in a detached worktree; all pass-or-skip in the project's normal CI environment per their design): `tests/test_eval_sandbox.py::test_subprocess_spawn_from_within_sandbox_is_blocked_by_resource_limit`, `::test_os_system_spawn_does_not_actually_execute_a_command`
  (sandbox resource limits in this container), `tests/test_genesis_v2_tier0s_phase_gate.py::test_Q6_ownership_is_checked_via_mocked_metadata` and `tests/test_training_provenance.py::test_snapshot_files_and_directory_are_chmod_readonly_after_creation` (the container runs as uid 0),
  `tests/test_truth_fetch_security.py::test_ssrf_risk_not_flagged_for_ordinary_public_url` (no network/DNS). Full suite on this branch: 7897 passed, 449 skipped, 4 xfailed, 5 failed (those five).

## 4. Honest limitations of the new infrastructure

1. Everything is exercised on synthetic data. No statistic here says anything about a model; the planted effects in the demo are typed constants.
2. Cryptography in tests uses ephemeral in-process Ed25519 keys; no key material is committed. The gate's trust in a *real* key rests entirely on the (empty) real registries.
3. The vault preflight inside the gate checks configuration *presence and shape* only (as the existing preflight does); it does not prove the vault is private or that separation of identities holds in a real deployment.
4. The hash chain proves internal consistency and tamper evidence after the fact; it cannot prove that the recorded outcomes came from the declared configuration. Independent re-execution by a second party is still required by the blueprint (section 8).
5. Bootstrap uses `random.Random` (Mersenne Twister) with fixed seeds; BCa is implemented and tested for sanity and degenerate cases but has no external numerical oracle in the standard library (no numpy/scipy in this environment). Exact McNemar and the power module are verified against closed-form hand computations and a seeded simulation.
6. No independent audit, no reviewer, no founder act has taken place. `freeze_prerequisites` remain all false; `spec.GENESIS_CAPABILITY_EVAL_V2_FROZEN` remains `False`.
