# Genesis V2 — Tier0-S: Sequential Sovereign Isolation (single physical machine, REDUCED ASSURANCE)

**Decision gate: `TIER0_S_REDUCED_ASSURANCE_ONLY`.** Tier0-A remains `TIER0_A_BLOCKED_SECOND_MACHINE_REQUIRED` (historical conclusion, unchanged). Tier0-S is a separate fallback and is **never equivalent to Tier0-A**. Design + synthetic validation only: no real secret, no corpus, no purchase, no disk/boot/security change, no reboot, no model, no GPU, no cloud, no spend.

Assurance order: **Tier0-B** (concurrent single-host containers) **<** **Tier0-S** (sequential isolated environments) **<** **Tier0-A** (two physically independent machines).

## 0. Limitations — read first (not softened)
Tier0-S may protect against: accidental cross-role leakage; a compromised Forge process; a compromised Witness process; a shared container daemon between concurrently active roles; simultaneous runtime cross-control; straightforward role-secret mixing.

Tier0-S does **NOT** protect against, and must never claim to:
- compromise of the physical Mac itself;
- firmware / boot-chain compromise;
- a **malicious owner or root administrator** — the owner/root on one physical Mac can ultimately influence both environments over time (edit the gate, the receipts, the images, or the machine). Tier0-S has **no adversarial-owner isolation and no independent physical custody**;
- hardware-level compromise;
- persistence deliberately planted across both boot environments;
- a privileged attacker with access to both encrypted environments over time.
Real-secret activation under Tier0-S requires **explicit owner risk acceptance** (Decision 9, open).

The software phase gate (§9) is one-shot, advisory and bypassable by anyone who can write the files it reads or alter the machine; it is **not** a hardware or adversary-resistant boundary and it is not what provides cold-boot or detachment separation.

## 1. Definition and lifecycle (with PHYSICAL DETACHMENT)
Forge and Witness are **never simultaneously active**, and **the other role's storage is never simultaneously available**. Each role runs in its own separately encrypted environment, entered only by a **full shutdown and cold boot** (not container stop/start, not sleep, not user switch). Only ciphertext crosses the boundary, through the audited transfer-bundle tooling (`scripts/genesis_v2_tier0a_transfer_bundle.py`). The owner signing key is in none of the environments.

**Cold boot and PHYSICAL DETACHMENT are owner-controlled physical procedures.** They are the actual separation controls. No software on the machine enforces them against the machine's owner, and the software gate (§9) earns NO acceptance credit for them.

Exact lifecycle for S1 / S1+ (wherever the topology permits physical detachment; the floor design's internal drive cannot be detached, which is one reason it is weaker):
1. Crown/Owner signs the authorization on the owner plane (off both machines' role storage).
2. Forge storage attached/active; **Witness storage physically absent** (disconnected, not merely unmounted or locked). The transfer medium is blank/approved.
3. Cold boot the Forge environment. Run the phase gate (`check`, then `begin`). Forge phase: generate; plaintext only in RAM.
4. Seal the ciphertext bundle onto the transfer medium (`seal`). Forge shutdown (full power-off).
5. After shutdown, remove Forge role storage where applicable (**physically disconnect it**). Attach **ONLY the approved transfer medium and the Witness storage**; the Forge storage stays absent.
6. Cold boot the Witness environment. Run the phase gate. `validate_and_stage` the bundle (read-once validated copy), then `cryptographic_verify` with the Witness private key.
7. Witness phase: decrypt/verify, write evidence. Full shutdown.
8. Erase / re-encrypt the transfer medium per the owner procedure.
**No simultaneous mounting of Forge and Witness secret-bearing storage, at any step.** Keeping networking disabled for the **whole** phase is also an owner procedure (the gate checks it once, at phase start only).

## 2. Host facts (sanitized; read-only discovery)
Single arm64 Mac, internal SSD only. FileVault on, SIP enabled, swap encrypted. The main APFS container is ~97% used (~14.6 GB unallocated). No external physical disk attached; no macOS installer present. Time Machine not configured; 0 local snapshots. Sleep mode writes a sleep image (`hibernatemode 3`). Spotlight indexing enabled. Shell-history files exist; crash/diagnostic reports exist. An iCloud container directory with entries exists. A ~20 GB Docker VM disk image persists. Startup-security policy is not readable without root and was not read. (No identifiers recorded.)

## 3. Options S1–S5
| Option | Classification | Technical basis |
|---|---|---|
| **S1** External encrypted bootable OS = Witness; internal macOS = Forge | `NOT_AVAILABLE` today; **design-viable** if the owner supplies an external drive | No external disk exists and none may be bought here. Apple Silicon Macs are documented to boot a separately installed macOS from external storage (documented behavior, **not tested on this host**); the internal FileVault volumes stay locked unless the owner's credential is entered. The internal OS as Forge is weak (see §6: cloud sync, agent tooling, Spotlight, sleep image, Docker image). |
| **S1+** (recommended target) Two dedicated minimal bootable environments (Forge-OS, Witness-OS) on separate external drives + a separate transfer medium; internal daily OS used for neither role | `NOT_AVAILABLE` today; **best Tier0-S shape** | Removes the daily-driver's uncontrolled channels from both roles. Needs owner-supplied hardware and interactive installs. |
| **S2** Two OS installs in the same internal APFS container | `NOT_AVAILABLE` | ~14.6 GB unallocated cannot host a second macOS; would also share one SSD/container/Preboot. Non-destructive path does not exist without owner freeing space; even then separation is weaker than S1. |
| **S3** recoveryOS as Witness | `NO_MEANINGFUL_SEPARATION` (as a standalone design) | Same boot family and install as Forge; Recovery can unlock the internal volumes with the owner credential; Witness secret storage would still need separately encrypted persistent storage (i.e. S1); tooling for verification is unverified there. Not tested (no reboot performed). |
| **S4** VM-based Witness | `NO_MEANINGFUL_SEPARATION` | A VM runs on the active host, so Forge and Witness are simultaneously active and the host controls the VM — violates invariant 1. |
| **S5** Two Docker contexts/users on one active macOS | `NO_MEANINGFUL_SEPARATION` | Re-confirmed, no new evidence: one daemon/control plane crosses both roles (`GENESIS_V2_TIER0_HOST_HARDENING_FINDINGS.md`). |

## 4. Recommended model
**S1+**: two dedicated minimal environments on separate encrypted external drives, a third ciphertext-only transfer medium, owner signing key elsewhere. **Floor (explicitly weaker)**: S1 with the internal macOS as Forge, permitted only after the Forge-phase channels in §6 are mitigated and `genesis_v2_tier0s_phase_gate.py` passes. **Not acceptable**: the current daily-driver environment as-is (the v2 gate, run read-only against it with the full repository as code root, passes 4 of 15 checks, FAILS 7 and FAILS CLOSED on 4: container runtime and sockets present, network addresses and default routes present, AI-agent processes running and agent transcript/index stores holding data, synchronized locations holding data, and the full repository outside the role-code allowlist; interlock and listener telemetry unverifiable in that invocation).

## 5. Storage separation
- **Forge environment** (own encryption, own passphrase): corpus-generation secret, X25519 public key, Generator identity; plaintext only in RAM / an ephemeral RAM disk during generation, never written to persistent storage.
- **Witness environment** (own encryption, own passphrase, a *different* passphrase held separately): X25519 private key, Verifier identity, encrypted Vault, evidence.
- **Transfer medium**: ciphertext + `MANIFEST.json` only (validator-enforced); erased/re-encrypted after use.
- **Owner signing key**: separate from all three (owner-controlled hardware token / Keychain / local HSM; never cloud).
Neither environment may carry the other's passphrase or recovery key. No real secret is created in this phase.

## 6. Residual-state / persistence analysis
Classification is for the **daily-driver internal environment on this host** unless noted; "dedicated" = S1+ environment.

| Channel | Class | Basis / required control |
|---|---|---|
| Shared internal filesystem | `MITIGATABLE` | Internal volumes are FileVault-locked while another OS runs; control is procedural (never enter the other role's credential in a role environment). |
| Swap | `CONTROLLED` | Observed encrypted; per-boot key discarded at shutdown. |
| Sleep image / hibernation | `MITIGATABLE` | `hibernatemode 3` writes RAM to disk; plaintext/secrets in RAM could persist until overwritten. Control: full shutdown, never sleep in a role phase; owner may set a non-sleep policy (needs privileged `pmset`). |
| Crash dumps / diagnostic reports | `MITIGATABLE` | Diagnostic reports exist; core files are written to a fixed path if enabled. Control: core dumps off (`ulimit -c 0`), delete reports after a phase. |
| Docker disk image | `MITIGATABLE` | A persistent ~20 GB VM image would retain anything written into a container's persistent layers. Control: no Docker daemon in role phases (gate check); RAM-only workspaces. |
| Shell history | `MITIGATABLE` | History files exist. Control: disable history in role phases; no secrets in argv/env. |
| Logs (unified log etc.) | `MITIGATABLE` | Control: no secret in argv/env; scan logs after a phase. |
| Spotlight / indexing | `MITIGATABLE` | Indexing is on. Control: role workspaces on an unindexed RAM disk; never plaintext on indexed paths. |
| Time Machine | `CONTROLLED` | Not configured. Must stay off (gate/owner check). |
| APFS snapshots | `CONTROLLED` | 0 local snapshots now; re-check before/after each phase. |
| Cloud sync (iCloud Drive / others) | `UNCONTROLLED` (on the daily-driver) | An iCloud container directory with entries and sync-daemon processes exist; sign-in/sync scope was not established. Role phases must run where sync is absent (dedicated environment). **A major secret-bearing channel left uncontrolled blocks Tier0-S on the daily-driver.** |
| Clipboard persistence / Universal Clipboard | `MITIGATABLE` | In-RAM only on one machine, but can propagate to other signed-in devices. Control: no copying of secrets; Handoff off in role environments. |
| **AI-agent / tooling transcripts, indexes, session databases, IDE recovery/cache** | `UNCONTROLLED` (on the daily-driver) | Agent sessions persist transcripts and searchable tool output under the home directory. The gate separates `PROCESS_NOT_RUNNING` from `NO_RESIDUAL_EXPOSURE_DETECTED` and checks known store locations for data (existence/non-emptiness only); a stopped agent with stores present still fails. Real role phases must not be driven by, or run beside, such tooling; a dedicated environment with none of these stores is required. |
| Temporary directories | `MITIGATABLE` | Use RAM disk; SSD overwrite is unreliable, so rely on environment encryption + key destruction. |
| Mounted shared volumes / attached images | `MITIGATABLE` | Several disk images are attached on this host; eject all in role phases. |
| Firmware / NVRAM | `NOT_APPLICABLE` (for secrets) | NVRAM holds no role secrets; a privileged firmware attacker is out of scope (§0). |
| External transfer media | `MITIGATABLE` | Validator guarantees ciphertext-only content; media must be erased/re-encrypted after use. |

**Verdict on the persistence gate:** two secret-bearing channels (cloud sync, agent transcripts) are `UNCONTROLLED` on the daily-driver. Therefore the daily-driver is **not** a valid Tier0-S Forge environment. A dedicated environment (S1+) can bring all channels to `CONTROLLED`/`MITIGATABLE`; that has not been provisioned or proven.

**What survives a reboot and could be a cross-role channel:** internal-disk contents (locked but present), the transfer medium (ciphertext only), NVRAM/firmware state, logs and reports on persistent volumes, and anything the owner carries in their head or password manager (passphrases, recovery keys). Each is addressed above or listed as unproven.

## 7. Docker / runtime boundary
No container daemon may be alive during a role phase (gate check `container_runtime_absent`); roles run as plain, non-persistent processes. Tier0-B container isolation does **not** transfer to Tier0-S as proof; Tier0-S relies on the owner-controlled boot and detachment procedure, not on a daemon boundary.

## 8. Transfer boundary
Forge → `seal` → transfer medium → **shutdown / cold boot** (storage swapped per §1) → Witness runs `validate_and_stage` before any import, then `cryptographic_verify`. Allowed: `SCREEN.enc`, `QUALIFICATION_HOLDOUT.enc`, `SEAL.enc`, `MANIFEST.json`. Forbidden: plaintext, corpus-generation secret, X25519 private key, owner key, Witness credentials.

**Claim levels (do not conflate):**
- `EXPECTED_ENCRYPTED_ARTIFACT_FORMAT_VALIDATED` — keyless `validate` / `seal` / `validate_and_stage`: expected files only, encrypted-artifact magic, allowlisted well-formed header matching the path, plausible size, strict manifest (duplicate keys rejected), no symlinks, no hardlinks, digests match. **This is a shape check; a file with a valid header followed by plaintext passes it (tested).** It is not proof of encryption and entropy is not used as proof.
- `CRYPTOGRAPHICALLY_VERIFIED` — `cryptographic_verify`, Witness side only, with the vault private key and the expected corpus digest: every split and the SEAL authenticate under AES-256-GCM (a plaintext payload fails the tag check) and digests match. The only keyed, real proof; library function only.
Authenticity of the generator is a separate matter (signed generation receipt). The staged copy narrows the validate→import race (read-once, same bytes written read-only); a writer with control of the staging directory (same host user/root) can still alter it. Operational note: `._*` and `.DS_Store` entries on foreign filesystems are rejected (fail closed).

## 9. Software phase gate (v2) — honest scope
`scripts/genesis_v2_tier0s_phase_gate.py` is a **one-shot, advisory, software-level, fail-closed pre-flight** run at the start of a role phase. It passes only if **every** check is `PASS`; any missing input, failed host command, implausible output, or unparsable value is `FAIL_CLOSED`; mandatory inputs (state directory, role code root, at least one deny-listed path/volume naming the other role's storage) have no fail-open defaults.

Checks: per-boot identifier (`kern.bootsessionuuid`); advisory interlock verification; container runtime / control-plane absence (process tokens, well-known sockets, runtime install directories, runtime environment variables; optional stricter process allowlist) — **not exhaustive**; network (interfaces with an address or active status incl. tunnels/bridges, default routes both families, non-loopback TCP listeners); cloud-sync and AI-agent **process** absence and, separately, **residual-exposure** absence; role workspace not under synchronized or Desktop/Documents paths; other role's storage absent/unmounted; **allowlisted** role code root (Qualification and all other code are excluded by allowlist, not by a filename blacklist; valid only within that root); weak owner-key / other-role-material scan.

**What it cannot do:** it is not continuous (a process can pass and later re-enable networking, start a runtime, or launch a sync/agent process — the owner procedure must keep the whole phase clean); it is bypassable by a malicious owner/root or anyone who can alter the machine, the gate, or its inputs; it is a point-in-time check by software on the machine it guards; the owner-key/forbidden-material scan is filename + key-header evidence only (a renamed or encoded key is not detected); listener telemetry may be incomplete without sufficient privilege and fails closed when unreadable. Run as a read-only diagnostic on this host it fails (§4).

### Interlock design (reboot-boundary "receipt") — decision: option B for the claim, local advisory log retained
- **Decision:** cold-boot separation and physical detachment are owner-controlled physical procedures. The software log is **not** counted as a security boundary and **earns NO acceptance credit** (checks 11 and 13 and invariants 1 and 13 are `NOT_YET_PROVEN`).
- **Where state lives:** inside the *currently booted environment's own* state directory (created by an explicit `init`, mode 0700). It is never shared between environments, so it creates no cross-role channel; consequently a Witness environment does **not** see Forge's log, and that is by design.
- **What it contains:** non-secret — role, per-boot UUID, sequence number, hash-chain link, environment id, checksum; plus `HEAD.json` (expected last sequence and checksum).
- **Who can write/delete it:** the OS user running the gate (and root). Anyone with that access can forge it by rewriting a consistent chain (tested).
- **If unavailable/unverifiable:** `FAIL_CLOSED` — missing, deleted, truncated, edited, replayed, reordered, copied from another environment, malformed, duplicate-keyed, symlinked, unreadable or in a group/other-writable directory all refuse the phase.
- **What it resists:** accidental mixing of roles inside **one booted OS** (e.g. starting the Witness workload inside the Forge session) and accidental corruption. **What it does not resist:** any deliberate writer, root, malicious owner, or firmware/boot-chain compromise.
- **Why keep it:** it costs little and turns a silent same-OS mistake into a refusal; it adds nothing against an adversary and is not relied upon.

## 10. Owner actions required to provision Tier0-S (none performed)
Supply external storage (≥1 for the floor design, ≥2 plus a transfer medium for S1+) — owner's purchase and choice; interactive installs of minimal macOS onto it; separate FileVault passphrases per environment; free or avoid internal space dependence; sign out / exclude cloud sync in role environments; set a non-sleep power policy and disable core dumps (privileged); no Time Machine; keep agent tooling off role environments; create the real owner key off-machine (separate authorization); Decision 9 risk acceptance. This phase did none of these and changed no boot, security, disk, or power setting.

## 11. Comparison
| | Tier0-B | Tier0-S | Tier0-A |
|---|---|---|---|
| Concurrency | simultaneous | sequential (cold-boot boundary) | simultaneous, independent hardware |
| Control plane | **one shared daemon crosses roles** (tested) | none live in both; same owner/root | independent per machine |
| Physical custody | one machine | one machine | two machines |
| Malicious owner/root | not defended | **not defended** | not defended by hardware alone, but custody/credential independence raises cost |
| Persistence risk | volumes in one VM | cross-boot residual channels (§6) | none shared |
| Status | synthetic reference only; rejected for real secrets | **reduced-assurance candidate; needs provisioning + owner risk acceptance** | strongest; blocked on hardware |

## 12. Next safest action
Owner decides whether to (a) wait for Tier0-A hardware, or (b) accept Tier0-S as reduced-assurance and provision dedicated external environments (Decision 9). Nothing technical should precede that decision.
