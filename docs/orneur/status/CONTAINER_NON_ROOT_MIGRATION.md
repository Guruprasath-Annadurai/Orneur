# Container hardening: running ORNEUR as a non-root user (G-003)

**What changed.** The production images (`Dockerfile`, `Dockerfile.fly`) and `k8s/deployment.yaml` previously ran the server as **root** (no
`USER`, no `securityContext`). They now run as `orneur` (UID/GID **10001**). Pod `securityContext`: `runAsNonRoot`, `runAsUser/Group/fsGroup 10001`,
`seccompProfile: RuntimeDefault`; container: `allowPrivilegeEscalation: false`, all capabilities dropped.

**Data path moved** (Dockerfile / compose / k8s): `/root/.orca` → `/home/orneur/.orca`. Fly keeps `/data`.

## Why existing data needs a one-time re-own

`orca.config._mkdir_owner_only()` (PR #22/#23) **refuses a state directory not owned by the running user**, deliberately. A volume written by the old
root-running image is root-owned, so the new image will fail to start against it until the data is re-owned. That is the security property working,
not a bug.

| Platform | What to do |
|---|---|
| Docker Compose | `docker compose down`, then once: `docker run --rm -u 0 -v <project>_orneur_data:/d <image> sh -c 'chown -R 10001:10001 /d && chmod 0700 /d'`; `docker compose up -d`. (The volume is now mounted at `/home/orneur/.orca`.) |
| Kubernetes | Handled by the `fix-data-ownership` init container in `k8s/deployment.yaml` (runs as root with only CHOWN/FOWNER/DAC_OVERRIDE, only chowns when the top-level owner is wrong). **The PVC mount path changed to `/home/orneur/.orca`** — update any other manifest that mounts the same claim. |
| Fly.io | `docker/entrypoint-nonroot.sh` starts as root, re-owns `/data` if needed, then `runuser`s to `orneur`. No manual step. |

## Verified vs not verified (updated by the container-assurance change)

Behavioural verification is `scripts/container/verify_nonroot.sh` (needs a Docker daemon; synthetic volumes only; run against a locally built image and,
from this change on, against the CI-built image in `Production Container Build + Boot Smoke`). 22 checks:

| Area | Check | Result |
|---|---|---|
| Identity | default user is UID 10001; every process in the running container is 10001 | pass |
| First install | new named volume: starts, state root and subdirs are `10001`/`0700` | pass |
| Existing root-owned data | refused with `UntrustedStoreDirectory` (the security property) | pass |
| One-time migration | `chown -R` as root, then starts; data preserved byte-for-byte | pass |
| Fly | entrypoint starts as root, re-owns `/data`, drops to 10001, app starts; data preserved | pass |
| **Partial migration** | top level already 10001 but a subtree still root-owned (interrupted re-own): **was waved through** by the top-level-only check (Fly entrypoint AND k8s init) — now repaired by a whole-tree `find ! -uid` check | **fixed** (was FAIL) |
| Kubernetes | the init container's exact command (read from `k8s/deployment.yaml`) migrates and repairs under `drop ALL` + `CHOWN,FOWNER,DAC_OVERRIDE` + `no-new-privileges`; without `CHOWN` the same step fails (so the capability is required) | pass |
| Privilege | app runs with **no capabilities**, `no-new-privileges`, cannot write `/app` or become root | pass |
| Read-only root filesystem | `--read-only --tmpfs /tmp` + state volume: the app imports, builds its routes and initialises state | pass (start-up only) |
| Execute-only ancestors (PR #28) | state under `0711` root-owned parents starts | pass |
| Symlink | a symlinked state subdirectory is refused | pass |
| Boot | `orca serve` answers `/livez` | pass |

Local verification used an image with the same base, user/ownership layout and entrypoint as `Dockerfile`/`Dockerfile.fly` **minus the apt-installed
`curl`/`build-essential`** (the verification sandbox has no DNS for apt). CI runs the same script against the real image.

**Not verified:** the Fly image itself (CI does not build `Dockerfile.fly`; its entrypoint is exercised through the verification image); the k8s manifest
against a real cluster (Pod Security "restricted" admission would reject the root init container — pre-chown the PVC there); `readOnlyRootFilesystem`
is **start-up verified only** and is still not enabled in the manifest — chat, document upload and model/embedding caches have not been exercised
under it, so enabling it needs an end-to-end run with the writable-mount list; behaviour under a real volume driver (NFS root-squash, EBS fsGroup
semantics) — root-squashed NFS cannot be re-owned from the client.

## Prerequisites, backup and rollback (do this before the first non-root start of an existing deployment)

1. **Back up the volume first** (root-owned copy that preserves modes): Compose `docker run --rm -v <vol>:/d -v "$PWD":/b <image> sh -c 'cd /d && tar czpf /b/orneur-backup.tgz .'`
   (run with `-u 0`); Kubernetes: a `VolumeSnapshot` of the PVC (or `kubectl exec` + `tar`); Fly: `fly volumes snapshots create <volume>`.
   Confirm the archive lists files before proceeding. Also back up the auth database if it is external.
2. **Stop the old pods/containers** before re-owning (no writer should run during `chown -R`).
3. **Mount path changed** for Compose/k8s: `/root/.orca` → `/home/orneur/.orca`. Point the volume at the new path (the manifests do); Fly keeps `/data`.
4. Set `ORNEUR_AUTH_SECRET` (public deployments fail closed without it) — independent of this change but required before any public start.
5. Roll forward, then check `/livez` and `docker top`/`ps` shows only UID 10001.

**Rollback.** The previous (root) image can read data owned by 10001, so rolling back needs no chown: redeploy the old image at the OLD mount path.
Anything the old image writes afterwards is root-owned, which the next roll-forward repairs automatically (the whole-tree check above). If data was
damaged, restore the backup from step 1 into an empty volume. Do not run both images against the same volume at once.

**Residual risks.** A concurrent writer during `chown -R` (step 2); symlinks planted inside a volume by someone who can already write it (the re-own does
not follow them, and the app refuses symlinked state directories, but this is not a defence against a hostile volume owner); NFS root-squash.
