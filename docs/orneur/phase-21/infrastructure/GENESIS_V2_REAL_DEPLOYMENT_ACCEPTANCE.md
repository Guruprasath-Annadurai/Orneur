# GENESIS V2 — Real Deployment Acceptance Criteria

Status: **DESIGN ONLY. ACCEPTANCE HAS NOT BEEN RUN AGAINST A REAL DEPLOYMENT.** `private_storage_genuinely_configured` must not be flipped to `true` until every item below has genuinely passed against the real deployment the owner is about to use — not merely against the synthetic suite this phase adds.

## Why this exists

Same-process Python unit tests (the existing `tests/test_genesis_v2_*` suite) prove **key-level** isolation: a `GeneratorWriteHandle` structurally cannot read, a `EncryptedVaultReader` structurally cannot write, a manifest without a valid signature is structurally rejected. They do **not** and architecturally cannot prove that two real processes on two real machines are genuinely isolated — that requires observing real OS/process/network facts, which only exist once there is a real deployment to observe.

## The 20 acceptance items

| # | Item | How it's proven | Code-level (testable today, synthetic) | Owner-only (real deployment) |
|---|---|---|---|---|
| 1 | Generator environment exists | Forge host/container/user is provisioned and reachable by the owner's own tooling | — | ✓ |
| 2 | Verifier environment exists | Witness host/container/user is provisioned and reachable | — | ✓ |
| 3 | Roles are different | Generator and Verifier are genuinely separate OS processes/UIDs/containers/machines, not the same process wearing two hats | partial — `test_generator_write_handle_refuses_a_read_capable_backing_store` proves the *object* can't play both roles | ✓ — must observe two distinct PIDs/UIDs/hosts |
| 4 | Generator has public key only | `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY` is absent from the Forge's real environment | `store.generator_setup_preflight()` already checks this (code-level, synthetic env) | ✓ — must inspect the REAL Forge environment, not a test fixture |
| 5 | Verifier has private key only | `ORNEUR_GENESIS_V2_CORPUS_SECRET` / vault public key are absent or irrelevant on Witness | `store.verifier_setup_preflight()` | ✓ real environment |
| 6 | Generator cannot access verifier secret | No credential path from Forge's identity to Witness's secret-manager entry | IAM-matrix design (this phase) | ✓ — must attempt and confirm denial against the real secret manager |
| 7 | Verifier cannot access generator corpus secret | No credential path from Witness's identity to the corpus-secret entry | IAM-matrix design | ✓ |
| 8 | Owner key exists outside both | Crown Plane key material is absent from both Forge and Witness environments entirely | custody-plan design | ✓ — inspect both real environments |
| 9 | Encrypted write succeeds | `EncryptedVaultWriter.write_corpus()` round-trips | **✓ fully covered today** — `tests/test_genesis_v2_storage.py`, `tests/test_genesis_v2_operational_boundary.py` | — |
| 10 | Ciphertext transfer succeeds | `.enc` files move intact between genuinely separate storage locations | **✓ covered with synthetic tmp_path "machines"** — `tests/test_genesis_v2_cross_machine_transfer.py` | ✓ — must repeat over the REAL transfer channel (network, drive, etc.) |
| 11 | Verifier decrypt succeeds | `EncryptedVaultReader.read_split()` on the transferred ciphertext | **✓ covered** (same test file) | ✓ repeat for real |
| 12 | Wrong identity decrypt fails | A reader without the correct private key, or an unregistered process id, is denied | **✓ covered** — multiple adversarial tests across `test_genesis_v2_operational_boundary.py` | ✓ repeat for real |
| 13 | Backup receives ciphertext only | Reliquary write path never sees plaintext | design-level (this phase); testable synthetically by asserting backup payloads are always `.enc` files | ✓ — must inspect the REAL backup payload |
| 14 | Restore succeeds | Backup → staging → integrity-verified → promoted | design-level; synthetic drill possible | ✓ real restore drill |
| 15 | Unexpected network egress is blocked | Forge/Witness cannot reach anything off their allowlist | — | ✓ — requires a real network/firewall to test against |
| 16 | Process isolation verified | Real PID/UID/namespace/container separation, confirmed by inspection | — | ✓ — see `GENESIS_V2_PROCESS_ISOLATION_VERIFICATION_PROCEDURE.md` (existing, prior phase) |
| 17 | OS/file permissions verified | `0700`/`0400` (or cloud-equivalent ACL) actually holds on the real storage | partial — code enforces this when writing locally | ✓ — must inspect the real filesystem/bucket policy |
| 18 | Evidence bundle captured | CGA + manifest + receipt + ledger records exist together for the test corpus | **✓ covered** by the full synthetic E2E test (`test_full_synthetic_generation_event_emission_through_ledger_gated_receipt`) | ✓ repeat for the real deployment's own test corpus |
| 19 | Cleanup/self-test cannot delete unrelated data | The acceptance test's own cleanup is scoped to only what it created | **✓ covered** — `vault_admin.activate_test_vault()`'s exclusive-workspace pattern (prior-phase hardening) already guards against this class of bug | ✓ — confirm the real acceptance run's cleanup touched nothing else |
| 20 | No real corpus content was used | Every item above was exercised with synthetic fixtures only | **partial — NOT code-proven.** The static test proves only that the synthetic acceptance module defines no inventory-path/`INV`/`inventory` reference and imports no inventory module. It cannot establish that every synthetic literal was independently authored and not copied from protected corpus content (that would require reading the protected material, which is forbidden). | ✓ — **required**: owner/provenance confirmation that all fixtures were independently authored, before real-deployment acceptance |

## Synthetic acceptance suite (this phase)

`tests/test_genesis_v2_deployment_acceptance_synthetic.py` (added this phase) composes the already-covered items (9, 10, 11, 12, 18, 19, and partial 3/4/5/13/17/20) into one coherent, clearly-labeled suite so a reviewer can see at a glance which of the 20 items have *any* code-level evidence today, and which are irreducibly owner/real-deployment-only. It uses only synthetic fixtures and ephemeral test keys, exactly like every other test in this program, and changes no production code.

## Gate

`private_storage_genuinely_configured` moves from `false` to `true` only when:
1. all "code-level" column items continue to pass in CI (already true today for 9/10/11/12/18/19; item 20 is partial and requires owner provenance confirmation), **and**
2. every "owner-only" column item has been independently performed and recorded as evidence by the owner against the real deployment, **and**
3. the owner explicitly signs off — this is a human decision gate, not something this program's test suite can set on its own.

This phase does not perform step 2 or 3.
