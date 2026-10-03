# Genesis V2 — Tier0-A (two physical machines) readiness and minimal machine requirements

**Phase status: `TIER0_A_READINESS_AND_DEPLOYMENT_PLANNING_ONLY`.** Verdict: **`TIER0_A_BLOCKED_SECOND_MACHINE_REQUIRED`.**
Owner Decision 1 (Strategy A / Tier 0) stands. Single-host Docker Desktop is rejected for real Genesis secrets (`GENESIS_V2_TIER0_HOST_HARDENING_FINDINGS.md`). Nothing here creates a secret, activates a vault, authorizes generation, runs qualification, selects a model, or spends anything.

## 1. Second-machine discovery — `SECOND_MACHINE_NOT_CONFIGURED`
Sources inspected (only already-present, local, read-only; no LAN scan, no device probing): repository docs/config/scripts/IaC, the local SSH client configuration, known-host and agent state, and locally installed remote-access tooling.

| Source | Sanitized finding |
|---|---|
| Repo docs / config / scripts / IaC | A second owner machine appears **only as an option** in decision/design documents; no document, script, or IaC names or configures one. |
| SSH client configuration | None present. |
| Loaded SSH identities | None. |
| Known-hosts references | Git-hosting entries only. |
| `~/.ssh` contents | Only an unrelated product's release-signing key pair; not inspected, not used, not touched. |
| Remote-access / mesh tooling | Standard `ssh`/`scp`/`rsync` clients only; no remote-desktop or mesh-VPN product installed. |

No safe evidence of a second owner-controlled machine exists. Tier0-A is therefore **not deployable and not claimed**, and no cross-machine test was run. No identifiers (hostnames, usernames, addresses, keys, serials) were collected.

## 2. Minimal Tier0-A machine requirement (generic; no hardware is chosen or recommended)
The second machine ("Machine B") only needs:
1. **Owner-controlled physical custody** — in the owner's possession, not shared, not rented/hosted.
2. A **supported OS** with current security updates.
3. **Full-disk encryption enabled.**
4. Ability to run the **Witness workload** as a **non-root** container (or equivalent) with **its own runtime**, i.e. **no shared Docker daemon, socket, or orchestration plane with Machine A**.
5. Enough RAM/disk for the minimal Witness image (order of a few hundred MB image; low single-digit GB total headroom is ample).
6. **No public listener**; able to run with **networking disabled** during verification.
7. A **controlled ciphertext-transfer capability**: removable media or an explicitly reviewed one-shot restricted link.
8. **No GPU, no cloud, no high-end compute** requirement.
9. Separate administrator credentials from Machine A (no shared admin token / account / secret-manager credential).

Machine A (Forge) is the existing owner machine **only if** it is acceptable for it to hold Forge-only material; the owner signing key stays off both (Section 7).

## 3. Role assignment (security-driven)
| | Machine A — Forge | Machine B — Witness |
|---|---|---|
| Future allowed secrets | X25519 **public** key; corpus-generation secret; Generator identity/authorization | X25519 **private** key; Verifier identity |
| Must never hold | X25519 private key; owner Ed25519 private key; Qualification secrets; any Witness credential | corpus-generation secret; owner Ed25519 private key; any Forge credential; Qualification authority |
| Network | default-deny egress, no listener | default-deny egress, no listener |
| Runtime | its own container runtime/user | its own container runtime/user |

## 4. No shared control plane — classification: **not evaluable (no second machine)**
Criteria that must all hold before `INDEPENDENT_CONTROL_PLANES_CONFIRMED` may be recorded (any failure = `SHARED_CONTROL_PLANE_FOUND`, and Tier0-A is not proven):
- separate container daemons/sockets; neither machine can reach the other's runtime API;
- no shared orchestrator, cloud account/project, MDM/remote-management console, or shared admin/root credential;
- no network-mounted or synced secret path (no shared drive, cloud-synced folder, or shared Keychain/secret-manager credential);
- no shared filesystem;
- an adversarial check from each machine that it **cannot** exec/mount/inspect on the other.
Until then the correct label is "not evaluated", **not** `PARTIAL`, and certainly not confirmed. (Note: a remote-management or sync feature that links both machines to one account is a shared control plane and must be disabled or excluded.)

## 5. Forge → Witness transfer boundary (design)
Preferred order: **(1)** owner-mediated removable encrypted storage; **(2)** one-shot mutually authenticated transfer over a dedicated restricted link; **(3)** another reviewed ciphertext-only mechanism. Mechanism (1) needs no network on either machine during real generation/verification.

Allowed payload: `SCREEN.enc`, `QUALIFICATION_HOLDOUT.enc`, `SEAL.enc`, and `MANIFEST.json` (relative path → SHA-256). Forbidden: plaintext corpus, corpus-generation secret, X25519 private key, owner key, anything else.

**Implemented and tested now (machine-independent): `scripts/genesis_v2_tier0a_transfer_bundle.py`** — keyless `seal` (Forge side, write-once manifest), `validate` and `validate_and_stage` (Witness ingress, before import: a read-once, read-only validated copy). It reuses the in-repo courier's rules (expected names, encrypted-artifact magic prefix, write-once) and adds: header-metadata allowlist, header↔path consistency, exactly-three-files-per-corpus, no symlinks/hardlinks/extra files/secret-shaped names, strict duplicate-key-rejecting manifest parsing, and a manifest digest check; the keyless commands never read a key or print content. **Claim level: `EXPECTED_ENCRYPTED_ARTIFACT_FORMAT_VALIDATED` — a shape check, not proof of encryption** (a valid header followed by plaintext passes it, by test). The real keyed proof is the Witness-side library function `cryptographic_verify` (AES-256-GCM tag verification in memory with a caller-supplied key and the expected corpus digest; plaintext is discarded). 27 synthetic tests (`tests/test_genesis_v2_tier0a_transfer_bundle.py`). Neither level is authenticity proof (the signed generation receipt provides that) and neither is evidence of any second machine.

## 6. Network model
Both machines: no public listener; default-deny egress; no model/API access; **no package installs during real generation/verification** — images and dependencies are built and pinned (digest + hash-pinned wheels, as in `infra/tier0-local/`) and transferred before any secret exists. Prefer fully offline execution.

## 7. Owner / Crown plane (plan only; no key created)
The owner Ed25519 private key stays **owner-controlled and non-cloud-resident, and off both machines** (macOS Keychain, owner-controlled hardware token, or physically owner-controlled local HSM — mechanism is still an owner decision). Future flow: Owner/Crown signs the authorization → Forge verifies the authorization (public key only) → generation → Witness verifies output/evidence. No machine ever receives the raw owner private key; signing happens on the Crown plane and only signatures and public keys move.

## 8. Cross-machine synthetic validation plan (NOT run — no second machine)
The 20 required checks are specified as a runbook to execute once Machine B exists: Forge only on A / Witness only on B (recorded as actual evidence, e.g. owner-attested serial-free physical distinction plus differing runtime IDs, not inferred); no Witness private-key path on A; no corpus-secret path on B; no shared daemon; ciphertext-only transfer (validator above); Witness decrypts; wrong key fails; Forge cannot decrypt; no owner key on either; network restrictions hold on both; no Qualification modules on either (the Tier-0 role images already omit them); cleanup scoped; no protected benchmark touched; no plaintext in transfer/backup paths; evidence contains only approved metadata/digests; adversarial cross-admin attempts; physical distinction recorded. Existing single-host synthetic suites (`tests/test_genesis_v2_tier0_local.py`) demonstrate the per-role properties and are reusable per machine.

## 9. Acceptance status (20 items)
**Unchanged** from `GENESIS_V2_TIER0_ACCEPTANCE_STATUS.md`: no second machine means no new evidence, so no item gains status; items 3, 15, 16, 20 stay `PARTIAL`, item 8 stays `OWNER_ACTION_REQUIRED`, nothing is `PROVEN_REAL`. (Even with two machines, synthetic-only evidence could not mark an item `PROVEN_REAL`; item 20 needs separately authorized owner provenance confirmation.)

## 10. Decisions 2–8 — technical recommendation vs owner decision
| Decision | Technical recommendation (non-binding) | Still owner-required |
|---|---|---|
| 2 local/cloud/hybrid per component | Forge and Witness on separate owner-controlled physical machines (Tier0-A); no cloud for either | **Yes** — whether to obtain Machine B |
| 3 secret manager | Per-machine local secret facility; never a shared credential across A/B | **Yes** |
| 4 owner signing mechanism | Owner-controlled hardware token preferred; macOS Keychain acceptable at Tier 0; never cloud KMS | **Yes** |
| 5 real Vault placement | Ciphertext on the Witness machine's encrypted disk, plus the controlled transfer path | **Yes** |
| 6 real Reliquary | Offline encrypted external drive, ciphertext only | **Yes** |
| 7 budget | No spend is required by this design beyond the owner's own choice of Machine B | **Yes** |
| 8 hardware | Generic spec in Section 2 only; no model, brand, or purchase is recommended | **Yes** |

## 11. Blockers before real-secret activation
Second owner-controlled machine (Machine B) and its independence confirmation; cross-machine synthetic run and adversarial admin-boundary check; owner decisions 2–8; owner key creation ceremony (separately authorized); real Reliquary drive; item 20 provenance confirmation; the owner-only acceptance items; separate explicit authorization for any real secret or Corpus Generation Authorization.

## 12. Exact next safest action
Owner decides whether to provide an independent second machine meeting Section 2. No technical step should precede that decision.
