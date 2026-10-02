# GENESIS V2 — Trust Domain Model

Status: **DESIGN ONLY — NOT PROVISIONED.**

Each domain below states: purpose, exact holdings, exact forbidden holdings, network default, and the code-level identity it maps to (where one already exists).

## Domain 0 — ORNEUR Crown Plane (Owner Authority)

**Purpose**: the single highest-trust control point. Signs `CORPUS_GENERATION_AUTHORIZATION` records, generation receipts (`generation_receipt.attest_receipt()`), and manifests where the owner is the signing authority. Performs emergency revocation. Approves infrastructure changes.

**Holds**: the OWNER Ed25519 signing key (`authority_registry.py` role `OWNER`), the owner's own copy of the evidence-snapshot tooling, read access to all evidence.

**Never holds**: X25519 vault private key (that belongs to Witness), generator code execution capability, any public-facing network listener, model-provider credentials, training credentials.

**Staged key custody** (see `GENESIS_V2_SECRET_CUSTODY_PLAN.md` for full detail):
- Tier 0: macOS Keychain on an owner-controlled machine, key never exported as plaintext to an environment variable for any CI job.
- Tier 1: hardware security key (YubiKey or equivalent) performing the Ed25519 signature; signing ceremony is a deliberate, multi-step owner action (`GENESIS_V2_OWNER_SIGNING_CEREMONY.md`), never a single CLI flag.
- Tier 2: owner-controlled local hardware token or physically owner-controlled HSM holding the Ed25519 key (never a cloud KMS/HSM — see canonical owner-key policy), with a documented split-custody or quorum model if the owner later brings on a second signer (`DELEGATED_OWNER` role already exists in `authority_registry.ROLES`).

**Network**: no inbound listener ever. Outbound only to fetch the evidence snapshot it needs to review, and (Tier 1+) to push a signed record back into the repository/registry.

**Code mapping**: `authority_registry.py` (`role: "OWNER"`), `corpus_generation_authorization.py` (`verify_signature`/`verify_referenced`), `corpus_manifest.py` (`verify_manifest_signature`), `generation_receipt.py` (`attest_receipt`).

## Domain 1 — ORNEUR Forge (Generator)

**Purpose**: the only place real Genesis private-corpus generation runs.

**Holds (minimum necessary)**: generator identity (registered in `CORPUS_GENERATOR_REGISTRY.json`, currently **0 records** — nothing registered yet), the corpus-generation secret if the canonical implementation requires one (`ORNEUR_GENESIS_V2_CORPUS_SECRET`), the X25519 vault **public** key (`ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY`), the exact authorized generator code (pinned by `code_sha256` in the generator registry and cross-checked live by `operational_boundary.check_authorization()`), the specific signed CGA it is operating under, and a write-only vault handle (`store.EncryptedVaultWriter` via `operational_boundary.protected_generate_write_handle()`).

**Forbidden**: X25519 **private** key, qualification-runner credentials, owner signing key, model-provider credentials, GPU credentials, training credentials, unrelated cloud credentials, public-repository write credentials, developer personal tokens. This list is not aspirational — it is already enforced structurally: `GeneratorWriteHandle` is built only from a write-only store object and raises `PrivateStorageWriteHandleViolation` if handed anything exposing `read_split`.

**Network default**: `DENY ALL`. The only justified exception (if generation cannot be fully offline) is outbound access to whatever read-only corpus-source material the generator legitimately needs — never inbound, never to the vault's own storage account credentials beyond the write-only capability it was issued.

**Disposability**: the Forge must be rebuildable from the pinned code digest with no persistent state that matters after a successful write + emitted `GenerationWriteResult`. Compromise of the Forge **after** generation completes must not reveal plaintext, because the Forge never held decrypt capability in the first place — this is a structural (cryptographic), not merely procedural, guarantee.

**Code mapping**: `generator_registry.py`, `operational_boundary.protected_generate_write_handle()` / `GeneratorWriteHandle` / `GenerationWriteResult`, `generation_receipt.build_unsigned_payload()`.

## Domain 2 — ORNEUR Witness (Creation-Time Verifier)

**Purpose**: validates generated encrypted artifacts immediately after generation, strictly separate from the Forge.

**Holds**: X25519 vault **private** key, a restricted creation-time-verifier identity (registered in `QUALIFICATION_RUNNER_REGISTRY.json` with `allowed_purposes` containing `PURPOSE_CREATION_VERIFICATION` but explicitly **not** `PURPOSE_QUALIFICATION` — the code already enforces this separation-of-duties in `authorized_manifest_verification_bytes()`), ledger access scoped to the creation-verification purpose, read access to the ciphertext vault.

**Forbidden**: generator write credentials, owner signing key, model execution, training, publishing, public-repository writes, unrelated cloud credentials.

**Output discipline**: the composed entry point (`operational_boundary.verify_manifest_digest_only_same_process()`) already returns **only** a `list[str]` of digest-comparison diagnostics — never plaintext, never the decrypted bytes themselves, by construction (no `return screen_plain` anywhere in that function). Real deployment must preserve this: Witness's own logs/outputs must never include plaintext, consistent with that function's existing contract.

**Network default**: `DENY ALL` outbound except to fetch the ciphertext transfer and (Tier 1+) push digest-only evidence to the Evidence Ledger.

**Real process isolation — mandatory, not optional**: same-process Python tests (the existing `tests/test_genesis_v2_*` suite) prove *key-level* isolation only. They do **not** and cannot prove that a real deployment runs Forge and Witness in separate OS processes, UIDs, containers, or machines. See `GENESIS_V2_REAL_DEPLOYMENT_ACCEPTANCE.md` items 3–8 and 16 for the owner-executed proof this requires, and `GENESIS_V2_PROCESS_ISOLATION_VERIFICATION_PROCEDURE.md` (existing, prior phase) for the underlying procedure this builds on.

**Code mapping**: `runner_registry.py`, `operational_boundary.authorized_manifest_verification_bytes()` / `verify_manifest_digest_only_same_process()`, `store.EncryptedVaultReader`.

## Domain 3 — ORNEUR Qualification Chamber (inactive)

**Purpose**: post-freeze holdout qualification. **Must remain inactive now.** Designed here only so the eventual deployment has a slot to grow into without an emergency redesign.

**Future identity requirement**: must be a **fourth**, distinct identity from Generator, Creation-Time Verifier, Training Runner, and Owner — the code's registry schema already anticipates this (`runner_registry.py`'s `allowed_purposes` vocabulary includes `PURPOSE_QUALIFICATION` as a value distinct from `PURPOSE_CREATION_VERIFICATION`, and a single identity holding both is exactly the separation-of-duties violation `authorized_manifest_verification_bytes()` already refuses).

**Lifecycle**: single-use/lineage-aware holdout semantics are already implemented in `ledger.py` (write-once holdout state machine: `SEALED` → `OPENED` → `RETIRED`, lineage tracking) — the infrastructure for this domain, when it is eventually provisioned, must plug into that existing state machine rather than inventing a parallel one.

**Current state**: no qualification runner is `AUTHORIZED` (`QUALIFICATION_RUNNER_REGISTRY.json`'s one record is `REGISTERED_NOT_AUTHORIZED`). This phase does not change that.

## Domain 4 — ORNEUR Vault (Private storage)

See `GENESIS_V2_VAULT_STORAGE_DESIGN.md` for the full design. Summary of the trust contract: ciphertext at rest only (X25519 envelope encryption via `store.EncryptedVaultWriter`/`EncryptedVaultReader`, unchanged), write-once per `corpus_id` directory, no plaintext ever persisted here under any circumstance, restricted ACLs (`0700` directories / `0400` files already enforced by the existing code and must be preserved by whatever real storage backend is chosen), integrity evidence via the existing SEAL mechanism, and no public exposure under any tier.

## Domain 5 — ORNEUR Evidence Ledger

**Purpose**: durable, append-only record of every fact that proves the generation/verification chain happened honestly, without ever holding the content that chain protects.

**Holds**: generation authorization records, generator identity, exact code hash, git commit, the `GenerationWriteResult`'s digest fields, the emitted-payload digest, the signed generation receipt, the signed manifest, ciphertext digests, `AccessLedger` records (already SQLite-backed, hash-chained), vault verification records, backup verification records, verifier results, revocation events, deployment identity records, machine/container image digests.

**Never holds**: SCREEN plaintext, QUALIFICATION_HOLDOUT plaintext, any secret key, the corpus secret, the owner private key. This is enforced today by construction: every function that touches the ledger or produces a receipt/manifest/evidence-snapshot deals exclusively in digests and booleans (see `scripts/genesis_v2_evidence_snapshot.py`'s own security contract, and `generation_receipt.py`'s schema, which has no plaintext field anywhere in `REQUIRED_FIELDS`).

**Design preference**: append-only / immutable / retention-controlled storage over a mutable application database — e.g. a write-once object store prefix, a signed/hash-chained log (the existing `AccessLedger` already is one), or a git-committed JSON evidence trail (the existing `GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST.json` / `GENESIS_CAPABILITY_EVAL_V2_STATUS.json` pattern already behaves this way via git history). Tier 0 can literally be "git commit the evidence snapshot after each event" — cheap, genuinely append-only given normal git-history discipline, and already the pattern this entire program has used for every phase's evidence.

## Domain 6 — ORNEUR Reliquary (Backup / Disaster Recovery)

See `GENESIS_V2_BACKUP_AND_DR_PLAN.md`. Summary: ciphertext-only, independent credentials from the primary Vault, immutable retention where the backend supports it, regular restore drills, and an explicit rule that **the X25519 private key is never auto-replicated into backup storage** — key custody and ciphertext custody must never share a single compromise path.

## Domain 7 — ORNEUR Sentinel (Observability / Security)

See the monitoring section of `GENESIS_V2_REAL_INFRASTRUCTURE_ARCHITECTURE.md`'s companion threat matrix for the specific alert list. Summary rule: Sentinel may see *that* an event happened, never *what* it contained. No plaintext corpus, private key, corpus secret, or owner signing material may ever reach a log line, metric label, or alert payload.
