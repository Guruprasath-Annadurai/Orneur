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

## 1. Definition
Forge and Witness are **never simultaneously active**. Each runs in its own separately encrypted environment, entered only by a **full shutdown and cold boot** (not container stop/start, not sleep, not user switch). Only ciphertext crosses the boundary, through the already-audited transfer-bundle validator (`scripts/genesis_v2_tier0a_transfer_bundle.py`). The owner signing key is in none of the environments.

Sequence: Crown/Owner → authorization signature → **BOOT F**: Forge (synthetic generation → ciphertext-only bundle → transfer medium) → **FULL SHUTDOWN** → **BOOT W**: Witness (validate bundle → decrypt/verify → evidence) → **FULL SHUTDOWN**. No persistent daemon bridges the sessions.

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
**S1+**: two dedicated minimal environments on separate encrypted external drives, a third ciphertext-only transfer medium, owner signing key elsewhere. **Floor (explicitly weaker)**: S1 with the internal macOS as Forge, permitted only after the Forge-phase channels in §6 are mitigated and `genesis_v2_tier0s_phase_gate.py` passes. **Not acceptable**: the current daily-driver environment as-is (the gate fails 5 of 8 checks there: container daemon alive, network up, cloud-sync processes, AI-agent tooling, full repo including Qualification code).

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
| **AI-agent / tooling transcripts and indexes** | `UNCONTROLLED` (on the daily-driver) | Agent sessions persist transcripts and searchable tool output under the home directory. Real role phases must not be driven by, or run beside, such tooling (gate check). New channel identified by this phase. |
| Temporary directories | `MITIGATABLE` | Use RAM disk; SSD overwrite is unreliable, so rely on environment encryption + key destruction. |
| Mounted shared volumes / attached images | `MITIGATABLE` | Several disk images are attached on this host; eject all in role phases. |
| Firmware / NVRAM | `NOT_APPLICABLE` (for secrets) | NVRAM holds no role secrets; a privileged firmware attacker is out of scope (§0). |
| External transfer media | `MITIGATABLE` | Validator guarantees ciphertext-only content; media must be erased/re-encrypted after use. |

**Verdict on the persistence gate:** two secret-bearing channels (cloud sync, agent transcripts) are `UNCONTROLLED` on the daily-driver. Therefore the daily-driver is **not** a valid Tier0-S Forge environment. A dedicated environment (S1+) can bring all channels to `CONTROLLED`/`MITIGATABLE`; that has not been provisioned or proven.

**What survives a reboot and could be a cross-role channel:** internal-disk contents (locked but present), the transfer medium (ciphertext only), NVRAM/firmware state, logs and reports on persistent volumes, and anything the owner carries in their head or password manager (passphrases, recovery keys). Each is addressed above or listed as unproven.

## 7. Docker / runtime boundary
No container daemon may be alive during a role phase (gate check `no_container_daemon_alive`); roles run as plain, non-persistent processes. Tier0-B container isolation does **not** transfer to Tier0-S as proof; Tier0-S relies on the boot boundary, not on a daemon boundary.

## 8. Transfer boundary
Forge → validator `seal` → transfer medium → **shutdown / cold boot** → Witness runs validator `validate` before any import. Allowed: `SCREEN.enc`, `QUALIFICATION_HOLDOUT.enc`, `SEAL.enc`, `MANIFEST.json`. Forbidden: plaintext, corpus-generation secret, X25519 private key, owner key, Witness credentials. Auditable via the validator output and the phase receipts.

## 9. Software guard added (honest scope)
`scripts/genesis_v2_tier0s_phase_gate.py` runs at the start of a role phase and checks: no container daemon, network disabled, no cloud-sync processes, no AI-agent tooling, other role's secret store not visible, **the other role has not run in this boot session** (opaque boot-session hash + append-only receipts → forces a full reboot between phases), no owner-key/other-role-secret file names in the role's state directory, Qualification code absent. It is a guard against accidental mixing enforced by software on the machine it guards; a malicious root can bypass it (§0). Run as a read-only diagnostic on this host it **fails** (daemon, network, sync, agent tooling, Qualification code present), which is the correct result for the current daily-driver.

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
