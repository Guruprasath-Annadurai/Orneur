# Genesis Capability Eval V2 — Three-Identity Deployment Design

Formalizes the concrete deployment separation for the three identities this program's code already distinguishes
(`generator_registry.py`, `runner_registry.py`, `operational_boundary.py`). Written against Decision A1 (two trusted
local machines — see `GENESIS_V2_INFRASTRUCTURE_DISCOVERY.md`), the ready-today, zero-cost default; the cloud/CI
alternative (A2) is noted where it would differ, but is NOT designed in full here since it remains an undecided,
larger undertaking.

## Identity 1 — Generator

| Property | Value |
|---|---|
| Holds | `ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY` (X25519 public key) and `ORNEUR_GENESIS_V2_CORPUS_SECRET` |
| Never holds | `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY` — checked by `generator_setup_preflight()`, which reports it as a `violations` finding (not a missing-config note) if present |
| Registry | `CORPUS_GENERATOR_REGISTRY.json` — `generator_id`, `code_sha256`, `allowed_artifact_classes`, `credential_scope.vault_read: false` (required and validated) |
| Capability | `operational_boundary.protected_generate_write_handle()` → a `GeneratorWriteHandle` wrapping `store.EncryptedVaultWriter` (write-only; holds no private-key material anywhere in its object state) |
| Deployment (A1) | A trusted local machine (can be the SAME machine as the owner's admin machine, or a separate one) with its own OS user account / Keychain holding only the public key + corpus secret |
| Deployment (A2, if later chosen) | A dedicated CI job / runner whose credential grant is scoped to exactly these two secrets |
| Network policy | `"none"` — required by `generator_registry.validate_record()`; generation is local/deterministic, never fetches from a network |

## Identity 2 — Creation-Time Verifier

| Property | Value |
|---|---|
| Holds | `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY` only |
| Never holds | `ORNEUR_GENESIS_V2_CORPUS_SECRET` (verifying never generates anything) or `ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY` (decryption needs only the private key) |
| Registry | `QUALIFICATION_RUNNER_REGISTRY.json`, a row with `allowed_purposes` containing ONLY `CREATION_TIME_VERIFICATION` — never `QUALIFICATION_RUN` (enforced in code by `authorized_manifest_verification_bytes()`, which denies a dual-purpose identity) |
| Capability | `operational_boundary.verify_manifest_digest_only_same_process()` — real plaintext exists only as local variables in its own stack frame; returns digest-only diagnostics, never plaintext, never trains, infers, or publishes anything (confirmed by a module-dependency-scan test) |
| Isolated from the generator | **Structurally, by key possession** (cannot decrypt without the private key it never gets; the generator cannot decrypt without ever holding the private key). **NOT structurally isolated at the OS/process level by anything in this codebase** — see `GENESIS_V2_PROCESS_ISOLATION_VERIFICATION_PROCEDURE.md`; this remains an owner deployment responsibility, explicitly marked UNVERIFIED until confirmed |
| Deployment (A1) | A SEPARATE trusted local machine (or, at minimum, a separate OS user account with its own Keychain) from the generator's |
| Lifecycle | Pre-freeze only, on a SEALED holdout (`spec.PURPOSE_CREATION_VERIFICATION`, ledger-enforced `STATE_SEALED`-only) |

## Identity 3 — Qualification Runner

| Property | Value |
|---|---|
| Status | **Remains unauthorized until the later, separate qualification gate.** No action in this phase changes this. |
| Registry | `QUALIFICATION_RUNNER_REGISTRY.json`, a DIFFERENT `runner_id` row than the creation-time verifier, with `allowed_purposes` containing `QUALIFICATION_RUN` (and optionally `POST_RETIREMENT_DISCLOSURE`) |
| Holdout access | Denied by the ledger (`EVAL_NOT_FROZEN`) until `spec.GENESIS_CAPABILITY_EVAL_V2_FROZEN = True` — which itself requires all 9 `FREEZE_PREREQUISITES`, including `independent_chatgpt_audit_approval`, a human decision this program never automates |
| No early holdout access | Confirmed by `owner_preflight.py`'s `runner_not_authorized_for_holdout_yet` check (`RN.to_ledger_registered_processes(rn_doc) == {}` — a `REGISTERED_NOT_AUTHORIZED` record grants nothing at the ledger) |
| Relationship to the verifier | May, LATER, reuse the same private key custody chain as the creation-time verifier (both need read access to the same vault), but is ALWAYS a distinct registry row and distinct process identity — never the same row serving both purposes |

## Separation enforcement, already implemented and tested (nothing new added this round)

- `generator_registry.validate(doc, qualification_runner_doc=...)` flags an id shared between the generator registry and EITHER role in the runner registry.
- `authorized_manifest_verification_bytes()` refuses a runner identity whose `allowed_purposes` includes `PURPOSE_QUALIFICATION` when used for creation-time verification.
- `GeneratorWriteHandle`/`protected_generate_write_handle()` refuse to be built from any object exposing `read_split` (structural, not just a registry check).
- `authorized_manifest_verification_bytes()` refuses any object exposing `write_corpus` when used as a reader.

Synthetic, ephemeral-key demonstrations of all of the above are in `tests/test_genesis_v2_identity_credential_boundaries.py`.

## What THIS document adds that did not exist before this phase

Prior rounds implemented and tested the CODE-LEVEL separation above. What was missing — and what this phase supplies — is the explicit mapping from those code-level roles to CONCRETE DEPLOYMENT UNITS (which machine, which OS account, which secret goes where) under the A1 default, so the owner has a literal checklist rather than having to infer it from source code. See `GENESIS_V2_OWNER_ACTIVATION_CHECKLIST.md` categories C for the resulting action items.
