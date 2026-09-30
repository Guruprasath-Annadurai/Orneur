# Genesis Capability Eval V2 — Definitive Owner Activation Checklist

This is the single, authoritative checklist for moving from "everything is implemented and tested against synthetic
fixtures" (today's state) to "a real private corpus may be generated." Every row has a **measurable PASS/FAIL
condition** — an exact command and the exact output that means PASS. Every row is placed in exactly one of four
categories. Nothing in this document performs any of the actions it describes; running the commands below is the
owner's action, not this program's.

As of this checklist's writing: `owner_preflight.run()` reports `READY_FOR_PRIVATE_CORPUS_AUTHORIZATION` — meaning
every item in category A is genuinely done — but `CORPUS_GENERATION_AUTHORIZATION.json` remains `NOT_AUTHORIZED` and
`GENESIS_CAPABILITY_EVAL_V2_FROZEN = False`, meaning categories C and D are the actual gate to real corpus work.
"READY" is a statement about preparation machinery, never a statement that generation is authorized.

---

## A. Implemented and tested (code + CI, no owner action needed)

| # | Item | PASS condition |
|---|---|---|
| A1 | Full deterministic test suite | `bash scripts/ci/run_deterministic_tests.sh` exits 0 |
| A2 | Genesis V2 security suite (zero-skip) | `ORNEUR_REQUIRE_CRYPTOGRAPHY=1 bash scripts/ci/run_genesis_v2_security_tests.sh` exits 0, no test skipped |
| A3 | Genesis V2 sandbox suite (zero-skip, Docker) | `ORNEUR_REQUIRE_DOCKER=1` sandbox CI job green (see `.github/workflows/test.yml`) |
| A4 | Privacy scanner clean on the repo as-is | `python -c "from pathlib import Path; from orca.eval.genesis_v2 import privacy_scan as PS; import json; print(json.dumps(PS.scan_repository(Path('.'))))"` → `"pass": true`, `"violations": []` |
| A5 | Owner preflight computation itself | `python scripts/genesis_v2_owner_preflight.py` → exit 0, `"result": "READY_FOR_PRIVATE_CORPUS_AUTHORIZATION"`, `"outstanding_for_ready": []` |
| A6 | X25519 vault write-only / read capability split | `pytest tests/test_genesis_v2_storage.py -k asym` → all pass; proves `EncryptedVaultWriter` holds no private-key material and defines no decrypt method |
| A7 | Generator write-scope enforcement at the actual write call | `pytest tests/test_genesis_v2_operational_boundary.py -k "write_handle or pilot_train_only"` → all pass |
| A8 | Public/private output-path separation | `pytest tests/test_genesis_v2_storage.py::test_output_paths_document_matches_the_code_it_describes` → pass |
| A9 | Creation-time verifier identity separation (restricted purpose) | `pytest tests/test_genesis_v2_operational_boundary.py -k "digest_only_same_process or verifier_also_authorized"` → all pass |
| A10 | Generator/qualification-runner identity separation (registry cross-check) | `pytest tests/test_genesis_v2_identity_credential_boundaries.py::test_generator_registry_flags_identity_collision_with_either_reader_role` → pass |
| A11 | Corpus-generation authorization gate (signature, code-tree hash, ancestry, freshness) | `pytest tests/test_genesis_v2_operational_boundary.py -k bypass_attempt` → all pass (every bypass attempt denied) |
| A12 | Access ledger (hash-chained, write-once holdout lifecycle) | `pytest tests/test_genesis_v2_ledger.py` → all pass |
| A13 | Owner authority key registered, reviewer registry configured | `python -c "from pathlib import Path; from orca.eval.genesis_v2 import authority_registry as AR; d,p=AR.load(Path('docs/orneur/authorization/AUTHORITY_REGISTRY.json')); print(bool(d and not p))"` → `True` |
| A14 | Owner-signed corpus-inventory attestation | `python scripts/genesis_v2_owner_preflight.py` output's `"checks"."corpus_inventory_attested_pass"` → `true` |
| A15 | Closure manifest freshness | `pytest tests/test_genesis_v2_final_pre_corpus_closure.py -k closure_manifest` → pass |
| A16 | Vault activation NEVER deletes pre-existing vault content, on success, on isolation failure, or on an unexpected exception | `pytest tests/test_genesis_v2_vault_ledger_activation.py -k preserves_pre_existing` → all pass (3 scenarios) |
| A17 | Vault activation's `backup_ciphertext_only` reflects a genuinely executed, byte-for-byte backup check — never hardcoded, and run BEFORE the destructive tamper test | `pytest tests/test_genesis_v2_vault_ledger_activation.py -k backup` → all pass |
| A18 | Role-separated preflight: generator role never requires or accepts the private key without flagging it | `pytest tests/test_genesis_v2_storage.py -k "generator_preflight or verifier_preflight or owner_preflight_pair_matching or owner_preflight_is_the_only_role"` → all pass |
| A19 | Owner-only pair-matching fails closed on missing `cryptography` or invalid key material | `pytest tests/test_genesis_v2_storage.py::test_owner_preflight_pair_matching_fails_closed_when_cryptography_is_unavailable` → pass |
| A20 | Digest-only, same-process manifest verifier is honestly named and carries no training/inference/publishing imports | `pytest tests/test_genesis_v2_operational_boundary.py -k digest_only_same_process_verifier` → all pass |

---

## B. Verified only with synthetic fixtures (real code paths, but every credential/key/registry-id used in testing is fake, ephemeral, or a `tmp_path`)

| # | Item | What was actually verified | What is NOT yet proven |
|---|---|---|---|
| B1 | Vault activation round-trip (`vault_admin.activate_test_vault`) | Real `EncryptedVaultWriter`/`EncryptedVaultReader` classes, ephemeral X25519 test keypair, tamper/truncation/wrong-key detection, permission enforcement, a genuinely executed byte-for-byte backup check run BEFORE the destructive tamper test, and confirmed non-destructive to any pre-existing vault content — all on a `tmp_path` vault, its OWN created artifacts destroyed after | That the OWNER's real secret-manager access-control policy genuinely restricts the private key to the intended identity (software cannot verify another system's IAM policy) |
| B2 | Three-identity credential boundary (`test_genesis_v2_identity_credential_boundaries.py`) | Synthetic env dicts prove no role's env contains another role's secret; registry cross-checks prove id-collision detection works | That the REAL deployment's secret manager / CI runner configuration actually assigns credentials this way — this is a code-level capability demonstration, not a deployment audit |
| B3 | Digest-only, same-process manifest verification (`verify_manifest_digest_only_same_process` — renamed from an earlier, overstated `verify_manifest_in_restricted_process`) | The function's return value never contains plaintext, proven by direct inspection across pass/tamper/ledger-evidence scenarios; its own module dependencies scanned and confirmed to contain no training/inference/publishing-capable imports | Real OS-level process isolation (this function runs in the SAME Python process/thread as its caller — its own docstring says so explicitly; a compromised process on the same host could in principle reach its stack frame via a debugger). If genuine process isolation is later required, it means literally running this call in a separate OS process and is not something this function provides today |
| B4 | Full adversarial end-to-end flow (`test_full_adversarial_end_to_end_flow_owner_authorization_through_lineage_eligibility`) | Owner-signed authorization (ephemeral Ed25519 test key) → generator write → creation-time verification → manifest binding → lineage eligibility, wired together and adversarially denied at each stage | A REAL owner signature, a REAL vault, a REAL candidate model, or REAL generated content — all fixtures |
| B5 | Code-tree hash binding scope | `test_code_tree_hash_does_not_cover_dependencies_outside_code_paths` demonstrates the EXACT boundary of what's covered | That `CODE_PATHS` is sufficient for whatever a REAL generator implementation eventually depends on — it does not exist yet, so this cannot be checked until it does (see item D5 below) |

---

## C. Requires real owner-side setup (no code change; owner action on a trusted machine, outside this repository)

| # | Item | Measurable PASS condition once done |
|---|---|---|
| C1 | Generate a real X25519 vault keypair | `python -c "from orca.eval.genesis_v2.store import generate_vault_keypair as g; import sys; priv,pub=g(); print(len(priv), len(pub))"` on the trusted machine → `32 32`; then IMMEDIATELY pipe each half to its own secret-manager entry (never print/store to a file) |
| C2 | Configure `ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY` in the generator's deployment scope ONLY | `python scripts/genesis_v2_preflight.py --role generator` run FROM the generator's own deployment environment → exit 0, `status: GENERATOR_CONFIGURED_UNVERIFIED`, `violations: []`. A non-empty `violations` list here means the PRIVATE key is visible to this environment — a security finding to fix before proceeding, not a normal missing-config item |
| C3 | Configure `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY` in the verifier/qualification-runner deployment scope ONLY | `python scripts/genesis_v2_preflight.py --role verifier` run FROM that (separate) deployment environment → exit 0, `status: VERIFIER_CONFIGURED_UNVERIFIED`; AND confirm (by reading the generator deployment's OWN secret-manager grant list) that `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY` is NOT among what the generator identity can read |
| C4 | Confirm the two key-manager entries pass cross-validation | `python scripts/genesis_v2_preflight.py --role owner` (run ONLY in a context where you, the owner, legitimately see both halves at once — never as a real generator's or verifier's own deployment check) → neither `VAULT_PUBLIC_KEY_ENV` nor `VAULT_PRIVATE_KEY_ENV` appears in `missing` with a `"does not match"` or `"could not verify"` reason. The latter reason means `cryptography` was unavailable or the key material was invalid despite matching hex shape — this preflight fails closed rather than silently accepting an unverifiable pair |
| C5 | Remove any leftover `ORNEUR_GENESIS_V2_ENCRYPTION_KEY` (legacy symmetric var) from any environment, script, or secret-manager entry | Run `python scripts/genesis_v2_preflight.py --role generator`, `--role verifier`, AND `--role owner` (the legacy-var check applies to whichever role's environment you're inspecting) — every role's `warnings` list is empty of any entry naming `ORNEUR_GENESIS_V2_ENCRYPTION_KEY` |
| C6 | Generate the real corpus secret | `ORNEUR_GENESIS_V2_CORPUS_SECRET` set in the generator's (and, if using a non-`ENCRYPTED_ARTIFACT` remote store, the owner's) environment; `python scripts/genesis_v2_preflight.py --role generator` reports no `SECRET_ENV` entry in `missing` |
| C7 | Choose and create the real vault directory, outside every git tree | `python scripts/genesis_v2_vault_verify.py --vault <REAL_VAULT_DIR>` → exit 0, `"VAULT ISOLATION PASS"` |
| C8 | Register the real generator identity | `CORPUS_GENERATOR_REGISTRY.json` has a record with `state: AUTHORIZED`, `code_sha256` matching the ACTUAL generator code at review time, `allowed_artifact_classes` scoped to exactly what that generator should produce, `credential_scope.vault_read: false` |
| C9 | Register the real qualification-runner AND creation-time-verifier identities as DISTINCT rows | `QUALIFICATION_RUNNER_REGISTRY.json` has two records with different `runner_id`s: one with `allowed_purposes` containing ONLY `CREATION_TIME_VERIFICATION`, one with `allowed_purposes` containing `QUALIFICATION_RUN` (and optionally `POST_RETIREMENT_DISCLOSURE`) — never the same row for both |
| C10 | Two-custodian backup policy in place for BOTH key halves, separately | Owner-internal confirmation; no software check can verify this — it is a real-world custodianship fact |
| C11 | Owner reviews and signs a real `CORPUS_GENERATION_AUTHORIZATION` record | A real Ed25519 signature from a registered, active, non-revoked OWNER authority key over a record whose `reviewed_commit_sha`/`authorized_code_tree_sha256` matches the ACTUAL reviewed code; `CGA.verify()` returns `authorized: True` against the real execution context |

---

## D. Remains unauthorized (explicitly, by design — no checklist item in this document authorizes any of these; they require a SEPARATE, later phase and a SEPARATE owner decision)

| # | Item | Current state | What would change it (not part of this checklist) |
|---|---|---|---|
| D1 | Real private corpus generation | `CORPUS_GENERATION_AUTHORIZATION.json` status `NOT_AUTHORIZED` | A real, reviewed, signed authorization record (C11) — a human decision, never automated |
| D2 | V2 freeze | `spec.GENESIS_CAPABILITY_EVAL_V2_FROZEN = False` | All 9 `FREEZE_PREREQUISITES` in `spec.py` independently `True`, including `independent_chatgpt_audit_approval` — a human decision |
| D3 | Real qualification runs against the holdout | Ledger denies `PURPOSE_QUALIFICATION` while `EVAL_NOT_FROZEN` | V2 frozen (D2) AND a real, `AUTHORIZED` qualification-runner identity (C9) |
| D4 | Model inference, GPU use, training, spend | No code path in this program performs any of these | Entirely out of scope for this program; would require separate, explicit authorization elsewhere |
| D5 | Extending `CODE_PATHS` for a real generator implementation | `CODE_PATHS = ("orca/eval/genesis_v2",)` only | Writing the real generator, determining what it actually imports, and extending `CODE_PATHS` (and re-signing the authorization against the new hash) BEFORE that generator is ever authorized to run — see B5 |
| D6 | V1 Genesis Capability Eval rehabilitation | Permanently invalid, by standing program constraint | Never — this is a standing, non-negotiable constraint of this entire program, not a checklist item that can be completed |

---

## How to use this checklist

1. Confirm every row in **A** passes (it should, right now, on the committed repository — these require no owner
   action).
2. Read **B** to understand exactly what "tested" does and does not mean for the credential-boundary and
   process-isolation claims — do not treat a synthetic-fixture PASS as equivalent to a real-deployment PASS.
3. Work through **C** in order on a trusted machine. Each row's PASS condition is a command whose exact output you
   can check against what is printed here — none of them require trusting a chat transcript or a summary.
4. Do **not** attempt any row in **D**. They are listed so it is unambiguous that finishing A–C does not authorize
   them. Each requires its own, later, explicitly-scoped phase and an explicit owner decision recorded in the
   `CORPUS_GENERATION_AUTHORIZATION` record or the freeze-prerequisite evidence — never a side effect of completing
   this checklist.
