# Training Authorization — Threat Model and Design

Status: **IMPLEMENTED_TESTED, NOT_AUTHORIZED, NOT_INDEPENDENTLY_AUDITED.** Nothing in this document or in the code it describes authorizes any
training. The committed registry has zero keys; the committed record is `NOT_AUTHORIZED`. Training stays NO-GO until the founder provisions a key
(see *Founder provisioning* — a separate, founder-approved action that this work does not perform).

## 1. Problem

`orneur train run|nano|core|ultra`, `orneur train cloud`, `orca.train.finetune.train()` and `_train_impl()` could start real fine-tuning without
checking any authorization. The documented gates (runbook, `NOT_TRAINED` router state, `MODEL_EVAL_AUTHORIZATION.json`) were procedural;
`orca/train` contained no authorization code, so the only things stopping a run were missing GPU/dependencies. Reproduced against PR #23 head
`bd3072c`, with every "allow" switch set in the environment: all four entry paths reached the first real-work boundary
(`scripts/security/training_gate_repro.py`).

## 2. Assets, actors, trust boundary

| Asset | Why it matters |
|---|---|
| Founder authority to start training (spend, GPU, data egress, new checkpoint lineage) | The programme's gate (Phase 21C, pre-training 0/95) |
| Training data (may include protected corpus later) | Egress to a rented host; contamination |
| Checkpoint lineage / audit trail | Evidence the run was approved and what it was |
| Rented-GPU spend | Real money (a prior incident billed $3.52 over a $0 cap) |

Actors: **founder** (holds the private signing key, offline); **operator** (can run commands and edit the working tree); **the training
process** (this code); **a malicious or mistaken contributor** (can open a PR); **an attacker with local non-root access**.
The private key never exists in this repository or in any process this code runs in.

## 3. Threats and mitigations

| # | Threat | Mitigation | Test |
|---|---|---|---|
| T1 | Run training with no grant via CLI | Every CLI training command reaches `train()` / `CloudTrainer.run()`, which call `authorize_training()` first; CLI maps denial to exit 2 | `test_cli_training_commands_exit_nonzero_and_start_nothing` |
| T2 | Bypass by calling a lower-level function directly | `_train_impl()` requires a `TrainingGrant` and re-checks it against the config; grants can only be created inside the gate (module-private seal) | `test_train_impl_cannot_be_called_directly`, `test_grant_cannot_be_minted_through_the_public_api` |
| T3 | New code adds another trainer entry point | AST guard fails the build if any module outside the gated allowlist references a TRL/HF trainer | `test_every_trainer_construction_site_in_the_repo_is_gated` |
| T4 | Missing / expired / malformed / revoked grant | Pure `verify()` returns reasons; any reason denies; unreadable registry, record or revocation list denies (never "nothing revoked") | `DENY_CASES` (31 parametrized), `test_unreadable_or_malformed_trust_files_fail_closed`, `test_revocation_list_revokes_a_grant` |
| T5 | Grant for one thing reused for another | Exact binding: family, base model, **pinned revision**, SHA-256 of the exact train/eval files, dataset manifest ids / bundle, environment class, purpose, epochs, LoRA rank, sequence length, spend, GPU, wall clock | `test_request_side_mismatches_are_denied`, `DENY_CASES` |
| T6 | Data swapped after approval (TOCTOU) | Files re-hashed immediately before **and** after loading (and before upload on the SSH path); config fingerprint re-checked at last mile | `test_data_modified_after_signing_is_denied_and_after_authorizing_is_caught` |
| T7 | Code changed after review | Grant binds a reviewed commit (HEAD must equal or descend from it), a SHA-256 over `orca/train` + `orca/registry`, and a clean working tree | `test_code_changed_after_review_even_if_committed_is_denied`, `test_dirty_working_tree_is_denied`, `test_reviewed_commit_that_is_not_an_ancestor_is_denied` |
| T8 | Training process self-issues permission | The gate has no signing code or key; signatures verify against a registry the process cannot rewrite without a reviewed source change (registry digest is pinned in source) | `test_gate_module_never_reads_the_environment_or_holds_signing_keys`, `test_registry_not_matching_the_source_pin_authorizes_nothing` |
| T9 | Environment variable / flag / "dry run" / CI marker grants authority | The gate never reads the environment (AST-checked); no bypass parameter exists on `train()` or `authorize_training()`; no `--dry-run/--force/--yes` on any train command | `test_environment_variables_cannot_grant_authority`, `test_train_signature_has_no_bypass_parameter`, `test_cli_has_no_dry_run_or_force_flag_for_training` |
| T10 | Reuse of a signature made for another purpose (e.g. model eval) | Domain-separated signing bytes (`orneur-training-authorization/1\n` prefix); separate registry; eval key is not in it | `test_signature_from_another_purpose_domain_is_rejected` |
| T11 | Over-broad authority | Registry record scopes each key by purpose, environment class, family, GPU and spend permission | `test_authority_scope_is_enforced`, `test_spend_requires_spend_permission_on_the_authority` |
| T12 | Replay / unlimited reruns | `max_runs` enforced by atomic `O_EXCL` slot claims (concurrency-tested); ≤14-day validity; revocation list | `test_run_budget_is_enforced…`, `test_concurrent_claims_never_exceed_budget` |
| T13 | Runaway job | Authorized wall-clock cap enforced by a trainer callback; SSH path timeout is `min(7200s, cap)`; spend estimate must be ≤ cap, unknown estimate = unbounded = denied | `test_wall_clock_limit_stops_training`, `test_cloud_trainer_unknown_cost_is_treated_as_unbounded` |
| T14 | No evidence of what ran, or of denied attempts | Every decision appends to a hash-chained `events.jsonl` under the hardened ORNEUR home; if the *grant* record cannot be written the grant is not honoured | `test_valid_grant_is_issued_bound_and_audited`, `test_event_chain_detects_tampering` |
| T15 | Data egress to a rented host before approval | SSH path authorizes before any connection, install, or upload | `test_cloud_trainer_is_denied_before_any_ssh_or_upload` |

## 4. Design

`orca/train/authorization.py`:

- **Record** `docs/orneur/authorization/TRAINING_AUTHORIZATION.json` (`orneur-training-authorization/1`), Ed25519-signed over
  `SIGNING_DOMAIN + canonical JSON`.
- **Registry** `TRAINING_AUTHORITY_REGISTRY.json`, **empty** in this change. Its canonical SHA-256 is **pinned in source**
  (`PINNED_REGISTRY_SHA256`). Adding an authority therefore needs a reviewed edit to both the registry and the pin.
- **Revocations** `TRAINING_AUTHORIZATION_REVOCATIONS.json`: authorization ids that must not verify. (Authority keys can also be revoked in the
  registry.)
- `authorize_training(cfg, environment_class=…, …)` is the only entry: it computes the request from facts the process cannot choose, verifies,
  claims a run slot, writes evidence, and returns a `TrainingGrant`. Every lower-level function re-checks the grant.
- The entry path declares the environment class (`SELF_HOSTED_GPU` for local, `SSH_RENTED_GPU` for `train cloud`); the grant must name it.
- Files live under the repository root the module was loaded from — never an environment variable or caller argument. State (run slots, events)
  lives under `ORNEUR_HOME/training/authorization`, created through the hardened `_mkdir_owner_only` (PR #22/#23).

Not changed: RSE-ARCH-1.2, Manifest V3, the existing eval/corpus authorization gates, their registries or keys, or `orca/eval/genesis_v2`
(its code-tree hashes are untouched).

## 5. Founder provisioning (NOT performed; requires founder approval)

1. Founder generates an Ed25519 key offline (see `OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md`); the private key never enters the repository or CI.
2. Reviewed PR adds a registry record (public key, scoped purposes/environments/families, `gpu_permission`, `spend_permission`) **and** updates
   `PINNED_REGISTRY_SHA256`; independent audit of that PR.
3. For each run, the founder signs a record for the exact commit, code-tree hash, dataset digests, base-model revision and limits, and commits it.
4. Revoke by adding the id to the revocations file or setting `revoked: true` on the key.

## 6. Residual risks (honest)

- **Same-process / same-privilege operator.** Anyone who can edit this source file, patch Python at runtime, or run their own training script
  without importing ORNEUR is outside what code in this repository can stop. The gate controls ORNEUR's entry points and makes a bypass require
  a visible source change (caught by review and by the code-tree hash).
- **Repository-write attacker.** Could change registry + pin + record in one commit. Mitigation is process: independent review of any change to
  `orca/train/authorization.py` or `docs/orneur/authorization/`, and founder-held offline signing (the attacker cannot produce the signature).
- **Environment class is declared by code path, not measured.** `train run` on a rented VM would be labelled `SELF_HOSTED_GPU`.
- **Local slot ledger is deletable** by the local user; the grant's expiry, limits and hash bindings still apply.
- **Spend** on the SSH path is an estimate from the preflight tier table, not metered billing.
- **Remote script.** The uploaded `train.py` runs on a host ORNEUR does not control; the gate prevents *launching* it, not its contents.
- No independent review yet (Antigravity). Treat as unaccepted.

## 7. Verification

`tests/test_training_authorization_gate.py` (synthetic Ed25519 keys, throw-away git repositories, patched pin; no live key, no GPU),
`scripts/security/training_gate_repro.py` (before/after across entry paths).
