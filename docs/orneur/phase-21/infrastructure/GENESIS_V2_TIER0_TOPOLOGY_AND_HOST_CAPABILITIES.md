# Genesis V2 — Tier 0 topology decision and host capabilities

**Owner Decision 1 = APPROVED: Strategy A — Sovereign Local / Tier 0.** Authorizes planning and building the minimum real local boundary needed to prove deployment isolation. It does **not** authorize corpus generation, Corpus Generation Authorization, benchmark creation/regeneration, model execution, qualification, foundation selection, GPU, training, protected-holdout inference, cloud/cloud KMS/paid providers, hardware purchase, spending, V2 freeze, or flipping `private_storage_genuinely_configured`. All remain separately gated and unchanged.

## Host capabilities (facts only; no identifiers)

| Capability | Result |
|---|---|
| OS / arch | macOS 27.0.1, arm64 (single physical machine) |
| CPU / RAM | 10 cores, 16 GB |
| Disk | 460 GB volume, ~17 GB free at discovery (**tight**: keep images/volumes small; teardown after every run) |
| Disk encryption | FileVault **On** (volume-level only; says nothing about vault ciphertext custody) |
| Docker | CLI + Docker Desktop 29.6.2 installed; daemon was **stopped** on arrival and was started for this phase (and quit again at its end) |
| Container runtime facts | Linux VM (aarch64, cgroup v2, 10 vCPU, ~8 GB), seccomp builtin, cgroupns; **daemon is not rootless** (containers run as non-root numeric UIDs *inside* the VM) |
| Non-root containers | Yes (`--user uid:gid`), caps dropped, `no-new-privileges`, read-only rootfs — verified by `docker inspect`, not just requested |
| Network isolation | Enforced per container by `--network none` (no interface with an address, no DNS, no TCP egress — probed). **Host firewall: not available** (macOS application firewall disabled; `pf` needs root) |
| Separate host OS users | **Not creatable by this program**: sudo is password-gated (owner action) |
| Distinct UIDs for Forge/Witness | Yes, inside containers (10001 / 10002 / courier-harness 10003) |
| Removable/external volume | None attached (only a disk image); nothing configured for a real Reliquary drive |
| Secure-secret facility | macOS login Keychain present (not used or touched in this phase) |
| Second owner-controlled machine | **Not represented anywhere** in the repo or deployment docs (only offered as an option in the decision cards) |

## Topology selected: **Tier0-B (container variant), explicitly weaker than Tier0-A**

Forge, Witness, and a key-less courier are separate containers (separate images; separate PID/NET/MNT/IPC namespaces; distinct UIDs; disjoint volume sets) on one machine, `--network none`, with an explicit ciphertext transfer boundary and a ciphertext-only backup/restore path.

**Why:** Tier0-A needs a second owner-controlled machine, which does not exist in the repo/docs and cannot be bought. The Tier0-B ingredients that *can* be genuinely enforced on this host without sudo (distinct identities, mount/secret separation, default-deny networking, a courier boundary) are enforced and verified. This is not Tier0-C: container-level separation is real and testable, and the missing pieces are named below rather than faked.

**What this topology does NOT give you (stated plainly):**
1. **No distinct host OS users.** One host user owns the Docker daemon access and every volume's backing store. A compromise of that user, or of the Docker daemon/VM, defeats all separation.
2. **Shared kernel.** All containers share one Linux VM kernel; a container escape crosses roles.
3. **No host firewall.** Egress denial is per-container network namespace only.
4. **Not physical-machine separation.** Tier0-A (two machines) remains strictly stronger.
5. **Everything here is synthetic.** Ephemeral keys are generated *inside* a root provisioner container and written straight into role volumes; the host process never sees a key byte; volumes are removed at teardown. No real secret exists.

## Strengthening options (updated by the host-hardening phase)
Host OS users and `pf`/application-firewall changes were **evaluated and not implemented**: on single-owner Docker Desktop they add no boundary (see `GENESIS_V2_TIER0_HOST_HARDENING_FINDINGS.md`, verdict `TIER0_SINGLE_HOST_REAL_ISOLATION_LIMIT_REACHED`). What would change the answer: a second owner-controlled machine (Tier0-A) and, for the real Reliquary, an owner-authorized external encrypted drive.

## Reproduce (local, free; needs Docker)
`python scripts/genesis_v2_tier0_local.py discover | build | verify` and `ORNEUR_TIER0_DOCKER=1 pytest tests/test_genesis_v2_tier0_local.py`. Teardown (`teardown <run_id>`) removes only resources labeled `orneur.tier0.run=<id>`; it never prunes. Container tests are **LOCAL evidence only** — CI's deterministic job skips them (no Docker-dependent step was added to any workflow).
