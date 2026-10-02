# Genesis V2 — Tier-0 host-hardening findings (limited elevated-administration phase)

**Outcome: `TIER0_SINGLE_HOST_REAL_ISOLATION_LIMIT_REACHED`.** No privileged operation was performed: every proposed control was evaluated first and none materially strengthens *this* Docker Desktop topology, so none was implemented. No account was created, no `pf` rule was loaded, no system setting was changed, no password or credential was requested, typed, stored or handled. Real-secret deployment acceptance requires **Tier0-A (two physically distinct owner-controlled machines)**. Owner Decision 1 (Strategy A / Tier 0) stands; this is a statement about what a *single host* can prove, not a retreat from it.

## What the host actually looks like (facts, no identifiers)
- Docker Desktop is **per-user, single-owner**: every Docker Desktop process (backend, VM, CLI proxy) runs as the one local user; the only root component is a network/socket helper. There is exactly **one** Docker daemon, one Linux VM, and one socket.
- The system-wide Docker path is a root-owned symlink that points into that user's home; the socket's mode is `rwxr-xr-x` (owner write only). A Unix-socket `connect` needs write permission, so other local users could not use it. That is a *host-account* fact, not a role boundary: **both Forge and Witness containers live in that one daemon.**
- The home directory is group-traversable by the default `staff` group (`rwxr-x---`): newly created standard accounts would be in `staff` by default and could traverse it.
- Docker Desktop is a GUI application. A second account would need its own interactive login session, its own VM (this machine: 16 GB RAM, ~13 GB free disk, the existing VM already takes ~8 GB) and its own image/volume store.
- `/etc/pf.conf` is stock Apple (only `com.apple/*` anchors); no custom rules exist. Reading live pf state needs root (not used).
- **Empirical originator test** (loopback listener on the host, container connecting to `host.docker.internal`): the connection's peer process is Docker Desktop's backend running **as the owner's uid** — the same uid as every other owner process. All container/VM traffic is originated there.

## Control classification

Scale: `MATERIALLY_STRENGTHENS_ISOLATION` · `DEFENSE_IN_DEPTH_ONLY` · `NO_MEANINGFUL_SECURITY_GAIN` · `UNSAFE_OR_INCOMPATIBLE`. **No control qualified as `MATERIALLY_STRENGTHENS_ISOLATION`.**

| Control | Class | Why |
|---|---|---|
| Two dedicated macOS accounts, each running its **own** Docker Desktop | `UNSAFE_OR_INCOMPATIBLE` | Needs two interactive GUI login sessions (account passwords I must not handle), two ~8 GB VMs on a 16 GB machine, duplicated stores on ~13 GB free disk. Would push toward auto-login or stored passwords — weaker, not stronger. |
| Two dedicated accounts while roles keep running in the **owner's** Docker Desktop | `NO_MEANINGFUL_SECURITY_GAIN` | Roles still run in one daemon controlled by the owner uid. The new accounts could not connect to the socket and would hold nothing. Adversarial test (below): the control-plane holder crosses every role boundary. |
| Roles as plain host processes under non-login service accounts (`sudo -u`) + `pf` `user` rules | `DEFENSE_IN_DEPTH_ONLY` (not implemented) | Real macOS file-permission separation and a genuine per-uid egress rule are possible, but it abandons the container hardening (dropped caps, read-only rootfs, netns), cannot be layered with Docker on this hardware, needs persistent privileged configuration and an architecture change, and still leaves one kernel and one human administrator. Not a substitute for Tier0-A. |
| macOS `pf` rule scoping Genesis traffic | `NO_MEANINGFUL_SECURITY_GAIN` | `pf` cannot distinguish Forge/Witness from any other container: all VM traffic carries the owner's uid via one backend process. Blocking that uid would break the owner's other Docker work and unrelated services. The roles have no network path at all (`--network none`), so there is nothing for `pf` to add. |
| macOS application firewall | `NO_MEANINGFUL_SECURITY_GAIN` | Inbound, per-application only; no egress control. No role publishes or listens on any port (inspected and probed). Enabling it changes a system security setting and triggers per-app dialogs for no Genesis benefit. |
| Keep `--network none` (existing) | *effective boundary* | Verified by probe (no TCP, no DNS, no usable interface) and by `docker inspect` (`NetworkMode none`, no ports). Retained unchanged. |

## Adversarial results on the **actual** topology (synthetic, ephemeral key, booleans/lengths only)
Run by `tests/test_genesis_v2_tier0_local.py` (local, Docker-gated). The holder of the Docker control plane — the single host user — can:
- `exec` into the Witness container as the Witness uid and read its (ephemeral) private key — **crosses**;
- mount the Witness secret volume into a new container and read it — **crosses**;
- mount the owner stand-in volume — **crosses**;
- launch a privileged container — **crosses**;
- enumerate both roles — **crosses**.

Conversely, a compromised Forge or Witness **process** has no docker socket, zero capabilities, no network, and no mount reaching the other role, so it can perform none of these (tested). So the container separation protects against a compromised *role process*, **not** against the control-plane holder, and in this topology the control-plane holder is the owner's host account — the same account that would hold both roles' real secrets.

Not tested, and why: cross-**host-user** file/Docker access (requested tests 1–2) needs a second host user, which was not created because it would add no boundary here; the socket-mode fact above is the only evidence. That is stated as untested, not passed.

## Acceptance items
- **3 Roles are different — stays `PARTIAL`.** No host boundary prevents the control-plane holder from controlling both roles.
- **15 Network egress blocked — stays `PARTIAL`.** Single enforcement layer (container netns). No independent host-level layer exists or is achievable here.
- **16 Process isolation — stays `PARTIAL`.** Namespaces/UIDs/caps are container-level; one VM kernel; one host user.
- **20 — stays `PARTIAL`.** Provenance confirmation was not authorized or performed.
- No other item changes; none is `PROVEN_REAL`.

## Rollback
Nothing privileged was changed, so there is nothing to roll back: no accounts, no `pf` anchor or rules, no firewall setting, no sudoers entry, no launchd item. Docker Desktop was started/stopped as an ordinary user application; unrelated Docker resources were not touched (tests check pre/post state, and teardown only removes resources labeled `orneur.tier0.run=<id>`).

## What would actually change the answer (owner decisions, not performed)
- **Tier0-A:** Forge and Witness on two distinct owner-controlled physical machines, with the owner key held off both (hardware token). This is the minimum for real-secret deployment acceptance.
- Or accept, explicitly and in writing, that single-host Tier-0 protects only against compromised role processes and is **not** acceptable for real secrets.
