# What must still happen before any private (V2) evaluation can run

NON_NORMATIVE. Authorizes nothing. Reads the register `docs/orneur/ORNEUR_MASTER_EXECUTION_AND_ACCEPTANCE_REGISTER.md` (checked there 2026-10-09; pre-training denominator 95, numerator 0) and
`GENESIS_V2_OWNER_ACTIVATION_CHECKLIST.md` (cited as C/D rows) as they stand on `cd6af2a`. Row ids below are the register's own. Statuses are the register's published observation column,
which the register itself says is **not** an acceptance bit.

Legend. **Founder act** = only the founder (Guruprasath Annadurai) can do or sign it. **External** = a person or party who is not the implementer, not the author of the thing being checked, and is
presently `UNRESOLVED_EXTERNAL` or an independent reviewer in the register. **Engineering** = work an engineer/agent can do in the repository without any secret.
"NO DEDICATED ROW" means the register has no row whose purpose is that item; the nearest rows are named instead of inventing an id.

## Summary table

| # | Prerequisite | Register row(s) | Register status today | Who must act |
|---|---|---|---|---|
| P1 | G8 corpus-generation grant | **G8** (depends G7; G7 <- G6 hardware chain); checklist C11 | G8 `NOT_AUTHORIZED` | Founder act (signature with the registered OWNER authority key) |
| P2 | Private store (real location, outside every git tree, or a private repo/object store with transport) | NO DEDICATED ROW; gates **DATA-3**; blueprint F3; checklist C0a-C0c, C1-C5, C7, C10 | blueprint F3 `BLOCKED`; `private_storage_state: NOT_CONFIGURED` | Founder act (infrastructure choice, custody); External only if a hosted store/secret manager is chosen |
| P3 | Corpus secret (and vault keypair halves) | NO DEDICATED ROW; gates **DATA-3**; checklist C1, C3, C6 | `secret_available: false` in V2 status JSON | Founder act (generation on a trusted machine, secret-manager custody, two custodians) |
| P4 | Independent reviewer keys | NO DEDICATED ROW; inputs to **DATA-2**; blueprint F6; `REVIEWER_REGISTRY.json` | zero keys; DATA-2 `NOT_STARTED` | External (reviewer generates own key, is not implementer/author) + Founder act (enrolls the public key) |
| P5 | Qualification-runner authorization | **QUAL-1** (depends G10); **G10**; **QUAL-2** (depends QUAL-1, P2-2); **P2-2**; checklist C8, C9 | QUAL-1 `NOT_AUTHORIZED`; G10 `NOT_AUTHORIZED`; QUAL-2, P2-2 `NOT_STARTED`; runner state `REGISTERED_NOT_AUTHORIZED` | Founder act (QUAL-1); Engineering (QUAL-2, P2-2 evidence); External reviewer (G10 design review) |
| P6 | Corpus generation and custody | **DATA-3** (creation record), **DATA-1** (provenance manifest), **DATA-5** (independent custody receipt), **DATA-2** (contamination + separation result) | DATA-3, DATA-5, DATA-2 `NOT_STARTED`; DATA-1 `NOT_ACCEPTED` | DATA-3/1/5: External (`UNRESOLVED_EXTERNAL` owners, custodian must differ from creator); DATA-2: Engineering run + independent review |
| P7 | Independent audit | NO DEDICATED ROW for the V2 audit; freeze prerequisite `independent_chatgpt_audit_approval`; blueprint Q-EVAL and section 11; register FINAL-1 recomputation is a different audit | prerequisite `false` | External (independent auditor, not the implementer); Founder act (commissions it, accepts the result) |
| P8 | Freeze (preregistration + thresholds + flag) | **QUAL-3** (numeric thresholds before any candidate result; depends G10); blueprint F4, F5, F9; the 9 `FREEZE_PREREQUISITES` in `spec.py` | QUAL-3 `NOT_STARTED`; `GENESIS_CAPABILITY_EVAL_V2_FROZEN = False`; all 9 prerequisites false | Founder act (the freeze decision and numbers with Product Management); Engineering (binding the last prereg field, see F1 in `INVENTORY.md`) |

Not part of V2 readiness but required before any *spend or training* that would use the evaluation: **AUTH-1** budget record (`NOT_VERIFIABLE`, founder), **FINAL-1** (independent recomputation worksheet,
needs all 94 other pre-training ids), **FINAL-2** (founder authorization), **EXEC-1** (start record). This branch's `budget.py` can enforce a cap but a non-zero cap needs an AUTH-1-style founder record cited by hash.

## Per-item detail

### P1. G8 grant (register G8; checklist C11)
* Today: `CORPUS_GENERATION_AUTHORIZATION.json` is `NOT_AUTHORIZED`; the register notes the grant "does not create a corpus and does not carry a corpus digest" and that it passes none of DATA-3/1/5/2.
* Needed: the founder reviews the exact generator code tree and signs (Ed25519, registered active OWNER key) a record whose `reviewed_commit_sha` and code-tree hash match the code that will run.
  The register places G8 behind G7 and the hardware chain (G4-G6); those are separate founder/hardware acts this branch does not touch.
* Closing evidence: `corpus_generation_authorization.verify()` returns authorized against the real execution context, plus an acceptance-ledger record signed per the register's acceptance engine (not by editing a status cell).
* This branch: nothing signs or edits that file. `ProtectedEvalGate` only *reads* registries.

### P2. Private store (no dedicated row; gates DATA-3)
* Today: vault procedure exists and was activated with an ephemeral test key only; `PRIVATE_GITHUB_REPO` / `PRIVATE_OBJECT_STORE` are descriptors with no transport; the public repository is public.
* Needed (checklist): C0a execution model (two trusted local machines vs cloud), C0b secret-manager mechanism, C7 a real vault directory outside every git tree that passes `scripts/genesis_v2_vault_verify.py`,
  C10 two-custodian backup of each key half, C10a confirmation that generator and verifier run in genuinely separate processes. Option A2 (cloud) additionally requires a generator implementation that does not exist.
* Closing evidence: a real `describe()` of kind `ENCRYPTED_ARTIFACT` (or a store with real transport) for which `is_private_grade()` is true, and the owner-attested custody facts. `private_storage_genuinely_configured` is the freeze flag.
* This branch: interface conformance tests and a guarded-reader design (`PRIVATE_STORE_INTEGRATION_DESIGN.md`). It cannot create or verify a real store.

### P3. Secret (no dedicated row; gates DATA-3)
* Needed: C1 generate the X25519 keypair on a trusted machine and pipe each half straight into its own secret-manager entry (public half to the generator scope only, private half to the verifier/runner scope only);
  C6 generate the corpus secret (>= 32 random bytes) into the generator scope only; C5 remove the retired symmetric-key variable everywhere.
* Closing evidence: role-scoped `scripts/genesis_v2_preflight.py --role generator|verifier|owner` outputs as listed in the checklist; no value is ever printed or committed.
* This branch: creates no secret or key. Tests use ephemeral in-process keys and placeholder hex strings that are not keys of anything.

### P4. Reviewer keys (no dedicated row; evidence for DATA-2; blueprint F6)
* Today: `REVIEWER_REGISTRY.json` has zero records; the semantic-overlap path is `NOT_CONFIGURED`, so manual review is the only possible route and it has no reviewer.
* Needed: an independent person (not the implementer, not the author of the corpus or generator) generates their own Ed25519 key on their own device and sends only the public half; the founder commits the registry
  record (role `PRIVATE_BENCHMARK_REVIEWER`, scoped domains, `allow_dual_role: false`). The reviewer then signs CLEAR/REJECT dispositions bound to the corpus digest after the corpus exists.
* Closing evidence: `review.validate_manifest()` empty for the real corpus digest with >= the number of distinct reviewers the plan requires (the gate's `min_clear_reviewers`).
* This branch: reviewer logic is exercised with synthetic registries; the human rating/adjudication workflow (`rating.py`) is ready for people but there are none.

### P5. Runner authorization (QUAL-1, G10, QUAL-2, P2-2; checklist C8, C9)
* Today: runner record `REGISTERED_NOT_AUTHORIZED`, `SELF_HOSTED_CPU`, network policy `none`; generator registry empty.
* Needed: G10 chamber-design review naming the design SHA and tests run; P2-2 egress test showing the training identity cannot reach a forbidden path; QUAL-2 failed-read log of the holdout by the training identity;
  C8 register the real generator identity; C9 register DISTINCT creation-time-verifier and qualification-runner rows; then the founder sets the runner state to `AUTHORIZED` (QUAL-1).
* Closing evidence: the register's own exits: reviewer accepts the G10 record, the failed-read log is accepted, the founder changes the runner state.
* This branch: `access.py` already refuses every state other than `AUTHORIZED` and ties code hash/scope; it does not and cannot change the state.

### P6. Corpus generation and custody (DATA-3, DATA-1, DATA-5, DATA-2)
* DATA-3: protected-corpus creation record naming the corpus digest and the creating operator. DATA-1: provenance manifest (source, licence, per-record digest) bound to that creation digest.
  DATA-5: custody and integrity receipt that re-hashes the protected corpus and names a custodian who is **not** the creator (the acceptance engine also forces a distinct reviewer key from DATA-3's).
  DATA-2: contamination and holdout-separation result bound to the creation digest, with no item-level leak.
* Closing evidence: each row's own signed artifact, never the founder grant. Owners for DATA-3/1/5 are `UNRESOLVED_EXTERNAL`: the founder or Product Management must name them.
* This branch: `splits.py`, `leakage.py`, `schema.py` provide checks that can be run *by those parties* on the real corpus (inside the runner, never in CI), and the semantic check still needs a configured engine or a full manual review.

### P7. Independent audit (no V2 row; freeze prerequisite)
* Today: `independent_chatgpt_audit_approval` is false. The blueprint (section 11, Q-EVAL) requires approval by a party who is not the implementer.
* Needed: the founder commissions it against an exact SHA; the auditor must be given the code, the docs and the synthetic evidence, never the private corpus.
* This branch: supplies something auditable: inventory, tests, a reproducible synthetic demo, and an explicit list of limitations. It must not be read as audit evidence.

### P8. Freeze (QUAL-3; blueprint F4/F5/F9)
* Needed, in order: (a) bind the last preregistration field `private_corpus_aggregate_commitment` once the corpus exists (and resolve finding F1 about its status value); (b) choose and freeze the numeric
  thresholds, non-regression margins and primary endpoints (QUAL-3 requires this *before any candidate result*; the founder/Product Management own the numbers; the blueprint's proposal is <= 4 primaries,
  zero tolerance in categories 10/14/15/17, >= 3 replicates, >= 10,000 bootstrap resamples, Holm within a declared family); (c) define the mapping from the V2 corpus categories to the numbered spec categories (finding F3);
  (d) all nine `FREEZE_PREREQUISITES` evidenced; (e) only then may a human change `GENESIS_CAPABILITY_EVAL_V2_FROZEN`.
* This branch: `prereg_check.py` refuses analysis unless the prereg is FROZEN and the plan is declared, unmodified and chained before the first result. It chooses no threshold and flips no flag; the analysis-plan numbers in the demo are synthetic fixtures.

## Suggested order (dependencies as the register draws them)

1. Founder decisions C0a-C0c (execution model, secret manager) and naming of the `UNRESOLVED_EXTERNAL` owners (DATA-1/3/5).
2. Hardware/chamber chain that G8 and G10 depend on (G4-G7, G9) - outside this workstream.
3. P2/P3 store and secrets on a trusted machine; P5 identity registration (C8, C9); G10 review; P2-2 egress test.
4. P1 founder grant (G8). 5. P6 generation, creation record, provenance, custody, separation result. 6. P4 reviewer enrollment and reviews.
7. QUAL-1 runner authorization and QUAL-2 failed-read proof. 8. P8 thresholds/endpoints frozen (QUAL-3), preregistration bound, flag decision. 9. P7 independent audit. 10. Only then any qualification run, one per candidate lineage (write-once ledger).

Nothing in this document changes any of those states.
