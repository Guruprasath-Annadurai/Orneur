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

## Verified vs not verified

- VERIFIED locally (no Docker daemon available in the build sandbox): the server starts and serves `/livez` as UID 10001 with an owned 0700 data
  directory; it **refuses** to start against a root-owned directory; the entrypoint script re-owns a root-owned directory and drops privileges.
  See the PR for the exact commands and output.
- VERIFIED by CI on the PR head: image build and `/livez` boot smoke (`Production Container Build + Boot Smoke`).
- NOT verified: the Fly image (not built by CI), the k8s manifest against a real cluster, `readOnlyRootFilesystem` (deliberately **not** enabled:
  some dependencies write under `$HOME`/`/tmp`; enabling it needs a tested writable-mount list). Pod Security "restricted" admission would reject the
  root init container; clusters enforcing it should pre-chown the PVC instead.
