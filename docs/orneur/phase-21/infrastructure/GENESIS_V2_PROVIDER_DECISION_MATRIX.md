# GENESIS V2 — Provider Decision Matrix

Status: **DESIGN ONLY — NOT PROVISIONED.** Classification of what already exists, then three candidate strategies, then a recommendation. No provider selection in this document is executed.

## 1. What exists today, classified

| System | What it actually is today | Classification for Genesis V2 | Why |
|---|---|---|---|
| **Fly.io** (`fly.toml`, `Dockerfile.fly`, app `orca-demo`) | Public single-replica web API, persistent volume at `/data` | **UNSUITABLE FOR GENESIS** | Internet-reachable serving layer; one admin account; no role separation; wrong blast radius entirely. Keep for the product API. |
| **Kubernetes** (`k8s/*.yaml`) | Same public web app, alternate deploy target, `replicas: 1` | **UNSUITABLE FOR GENESIS** | Same reasoning as Fly; also materially more operational complexity for zero isolation benefit at ORNEUR's current scale. |
| **Northflank + Supabase + Cloudflare** (Phase 14B staging: `orneur-api-a`, Neon/Postgres branches, `orneur-edge-tunnel`) | Live, internet-reachable staging stack for Godmode/authority-distribution testing | **KEEP FOR NON-GENESIS ONLY** | Already a real, working precedent for "secret-scoped GitHub Environment" (`phase14b-staging`) — useful as a *pattern* reference — but it is a shared, live environment scoped to a different security boundary. Reusing it for Genesis V2 would merge two blast radii the code deliberately keeps apart. |
| **GitHub Actions** (`.github/workflows/test.yml` + others) | The exact-SHA CI substrate; 6 mandatory jobs; public repo; shared/ephemeral runners | **EXTEND (CI verification only); UNSUITABLE for key custody** | Perfect for what it already does (deterministic tests, container boot smoke, dependency scan, Genesis V2 security/sandbox tests). Never appropriate for holding the vault private key or the owner signing key long-term: public repo, shared runner pool, no secret-manager broker today. Extend it to run the synthetic deployment-acceptance suite (`GENESIS_V2_REAL_DEPLOYMENT_ACCEPTANCE.md`) against synthetic fixtures — never real secrets. |
| **Docker** (root `Dockerfile`, `docker-compose.yml`, `docker/genesis_v2_sandbox/Dockerfile`) | Local dev stack + the already-pinned-by-digest Genesis V2 sandbox image | **EXTEND** | The sandbox image pattern (pinned digest, hermetic, no network) is exactly the right pattern for Forge and Witness images. Extend it: build dedicated, minimal `generator` and `verifier` images from this same discipline. |
| **macOS Keychain** (`secret_manager.probe_secret_manager()`) | The one real, already-probed local secret mechanism; owner's current machine | **KEEP (Tier 0 owner-key custody)** | Single-machine, local, no remote distribution — exactly right for Tier 0 Crown Plane key custody, exactly wrong for anything needing multi-machine access. |
| **Terraform / Pulumi / OpenTofu / Ansible / systemd units** | None exist | **N/A — introduce as needed (see §4)** | Nothing to classify; this phase proposes a minimal IaC skeleton (`infra/`) that provisions nothing. |

## 2. Three strategies

### Strategy A — Sovereign Local / Owner-Controlled

Two (eventually three, once Qualification activates) genuinely separate physical machines or hardened local VMs, owned and operated by the owner, never cloud-hosted.

- **Security**: strongest key-custody story at Tier 0 — no third-party ever touches key material; weakest availability/redundancy story without deliberate extra work.
- **Cost**: lowest ongoing cost; one-time hardware cost if dedicated machines are purchased (a cheap mini-PC or a spare machine is sufficient — Forge/Witness do no heavy compute).
- **Operations**: owner is the entire ops team; no IAM console, no cloud audit log — operational discipline must be manual and well-documented (this package's runbooks exist for exactly that reason).
- **Backup**: owner must personally manage an offsite ciphertext copy (e.g. an encrypted external drive stored elsewhere) — the one place this strategy genuinely needs deliberate design (`GENESIS_V2_BACKUP_AND_DR_PLAN.md`).
- **Availability**: lowest — a single owner's machines are a single point of operational failure, though not a single point of *secret* compromise if role separation is maintained.
- **Key custody**: best possible at this tier — macOS Keychain or a YubiKey, never leaves owner's physical possession.
- **Reproducibility**: good, if the generator/verifier are built from pinned Docker images rather than ad hoc local installs (recommended regardless of strategy).

### Strategy B — High-Assurance Cloud

Separate cloud accounts/projects per trust domain (e.g. one account for Forge, one for Witness, one for Vault+Reliquary, one for Evidence), each with its own IAM, its own secret manager, its own audit log, private networking, KMS-backed keys where supported.

- **Security**: strongest *availability* and *audit* story; cloud KMS/HSM is excluded for the owner signing key by the canonical owner-key policy (the owner key stays owner-controlled and non-cloud even under this strategy), but cloud-native audit/immutability applies to ciphertext, evidence and non-owner secrets; strongest blast-radius separation if account boundaries are genuinely separate (not just separate projects in one organization with a shared super-admin).
- **Cost**: meaningfully higher — multiple accounts, KMS key costs, storage, egress, a secrets-manager subscription, and the owner's time to configure IAM correctly (this is also a security cost: misconfigured IAM is the single most common real-world cloud breach vector).
- **Operations**: requires genuine cloud operational discipline (IaC, change review, audit log retention) to realize the security benefit — done poorly, a multi-account cloud setup is *worse* than Strategy A because it creates more attack surface (more accounts, more IAM policies, more things that can drift) without the owner yet having the operational maturity to monitor it.
- **Compute isolation**: real container/VM isolation available natively; still requires the owner to actually configure it correctly (see `GENESIS_V2_REAL_DEPLOYMENT_ACCEPTANCE.md`).
- **Costs**: see `GENESIS_V2_COST_MODEL.md` Tier 1/2 line items.

### Strategy C — Hybrid Sovereign (recommended — see §3)

Owner signing offline or on a hardware token (never cloud); Generator isolated on local or ephemeral ("burn after use") compute; encrypted Vault on cloud object storage with immutability features; Witness on separate compute from Generator (local or cloud, but a genuinely different machine/account); offsite ciphertext backup in a second, independent location/provider; Evidence maintained as an append-only trail (git-committed snapshots at Tier 0, a dedicated immutable log store at Tier 1+).

- Combines Strategy A's key-custody strength (owner key never touches a cloud account) with Strategy B's availability/immutability strength for the data that actually benefits from it (ciphertext, which is safe to replicate widely because it's useless without the separately-custodied private key).

## 3. Recommendation

**Strategy C, staged by tier**, because:

1. The single highest-value asset (the owner Ed25519 signing key) should **never** be cloud-resident regardless of tier — this is the one component whose compromise is catastrophic and irreversible (every past and future authorization becomes suspect). Strategy A's custody model for this one key is strictly better than Strategy B's, at any tier.
2. Ciphertext (the Vault's actual content) is, by the existing crypto design, safe to replicate broadly — X25519 envelope encryption means a stolen ciphertext copy alone is worthless. This is exactly the kind of asset that benefits from Strategy B's availability/immutability story (object-lock, multi-region) without taking on Strategy B's custody risk, because there is no secret in it to leak.
3. Forge and Witness benefit most from genuine separation (separate accounts/machines, not just separate processes) — Strategy B's isolation primitives are valuable here specifically, while Strategy A remains viable at Tier 0 if the owner has two physically separate machines (or is willing to operate carefully on one machine with real separate OS users/containers as an interim, explicitly weaker, step — see the Tier 0 caveat in `GENESIS_V2_REAL_DEPLOYMENT_ACCEPTANCE.md`).

This is not a new invention — it mirrors the "split online/offline authority model" the user's own prompt asked to be evaluated, mapped onto ORNEUR's actual four-identity model (Owner / Generator / Verifier / future-Qualification) rather than a generic template.

## 4. IaC posture

Introduce a minimal `infra/` skeleton now (this phase), not a full Terraform deployment. See the repository's `infra/README.md` for the proposed layout. Use Terraform/OpenTofu only once a cloud strategy (B or C's cloud-facing half) is actually approved and funded; use plain, reviewed shell scripts + Docker for the local/offline half (Strategy A pieces of C), since introducing a cloud IaC tool to manage a local machine's Docker containers would be complexity without benefit. **Kubernetes is explicitly rejected** for Genesis V2 at every tier evaluated here — the workload (two or three low-throughput, security-critical processes) does not justify it, and it would materially increase the audit surface the owner must reason about.

## Canonical owner-key policy

**Canonical owner-key policy (audit closure): the owner Ed25519 signing private key MUST remain owner-controlled and non-cloud-resident at every tier. A local hardware token/HSM physically controlled by the owner is permitted; a cloud KMS/HSM holding the owner signing private key is NOT compatible with this architecture.** Strategy B as written is therefore only compatible with the canonical recommendation for components other than the owner signing key.
