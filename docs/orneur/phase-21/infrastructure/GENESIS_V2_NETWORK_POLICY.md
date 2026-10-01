# GENESIS V2 — Network Policy

Status: **DESIGN ONLY — NOT PROVISIONED.** Default posture for every Genesis V2 component, at every tier: **deny all, allow by explicit exception only.**

## Principles

- No Genesis V2 component (Forge, Witness, Vault, Reliquary, Evidence Ledger) is ever assigned a public IP or an inbound listener reachable from the internet.
- Private subnets (Tier 1+ cloud) or no network at all (Tier 0 local, offline-capable where feasible) by default.
- Outbound-deny by default; every allowed destination is named explicitly below, not inferred.
- No inbound SSH where avoidable — prefer session-manager-style administration (e.g. a cloud provider's native "connect without open port" mechanism) over a listening SSH daemon, at any tier where that's available; at Tier 0 (local machine), physical/local access substitutes for this.
- Service identity over shared network location: a component's right to talk to another component is proven by its credential/identity, not merely by being on the same subnet.
- mTLS for any Tier 1+ network hop that is not already covered by the X25519 envelope encryption at the application layer (the ciphertext itself does not need TLS to stay confidential, but channel integrity/availability still benefits from it).
- Egress auditing everywhere a real network exists (Tier 1+).
- A separate, narrower management path for anything administrative (owner's own access), never reusing the Forge/Witness data path.

## Communication matrix

`Source → Destination → Protocol → Purpose → Allowed?`

| Source | Destination | Protocol | Purpose | Allowed? |
|---|---|---|---|---|
| Owner (Crown Plane) | Authority registry (git repo) | HTTPS/git | push signed CGA / receipt / registry updates | ✓ (owner-initiated only) |
| Owner (Crown Plane) | Generator | — | — | **DENIED** — owner never connects into the Forge; hands off a signed CGA via the evidence/authority channel only |
| Owner (Crown Plane) | Verifier | — | — | **DENIED** by default; `cond.` only for the owner-executed deployment-acceptance procedure (§ below), never routine |
| Generator (Forge) | Vault (write) | application-layer X25519 envelope, over whatever transport the chosen backend uses (local FS, or TLS to object storage at Tier 1+) | write-only corpus upload | ✓ — this is the Forge's one legitimate outbound purpose |
| Generator (Forge) | anything else | any | — | **DENIED** (`DENY ALL` is the real default; a narrow, justified allowlist — e.g. a specific read-only corpus-source — may be added per deployment, documented at provisioning time) |
| Vault | Verifier (Witness, read) | ciphertext-only transfer (see `GENESIS_V2_CROSS_MACHINE_TRANSFER_PROCEDURE.md` for the existing procedure this must satisfy) | creation-time verification | ✓ |
| Verifier (Witness) | Evidence Ledger | digest-only writes | append verification result | ✓ |
| Verifier (Witness) | anything else | any | — | **DENIED** |
| Vault | Reliquary (backup) | ciphertext-only, async | disaster-recovery copy | ✓, backup-writer identity only |
| Reliquary | Vault | — | — | **DENIED** (one-directional; restore is an owner-triggered, explicit, out-of-band operation, never an automatic sync back) |
| CI (GitHub Actions) | Evidence Ledger (git-committed snapshots) | HTTPS/git | run synthetic deployment-acceptance + exact-SHA verification | ✓ — read/verify only, no secret material crosses this path |
| CI (GitHub Actions) | Vault / Forge / Witness | — | — | **DENIED** — CI never touches real key material or the real vault; it only runs against synthetic fixtures |
| Qualification Runner (future, inactive) | Vault (holdout read) | — | — | **DENIED today**; future design: single-use, post-freeze, purpose-scoped only |
| Sentinel (observability) | Forge / Witness / Vault | metrics/log export, metadata only | monitoring | ✓, read-only telemetry channel, never a data-plane channel |
| Anything | Internet (public) | — | — | **DENIED** for all Genesis V2 components other than the owner's own outbound administrative connections and CI's standard package-fetch egress |

## Tier-specific notes

- **Tier 0 (local)**: "network" for Forge/Witness can be `none` in the literal sense (air-gapped generation is explicitly preferred where the corpus source allows it) — the strongest possible instantiation of `DENY ALL`. Ciphertext transfer between Forge and Witness happens via an explicit, manual, owner-mediated copy step (external drive, or a single deliberate `scp`/`rsync` invocation), never an always-on network link.
- **Tier 1+ (cloud)**: private subnets with no NAT gateway for Forge/Witness unless a specific, documented outbound need exists; security-group/firewall rules enumerate exact destination CIDRs or private-endpoint service names, never `0.0.0.0/0` for anything except the owner's own administrative access (and even that should be restricted to the owner's known egress, where practical).
- **Tier 2**: add a dedicated, isolated management VPC/account for administrative access, separate from both the data-plane accounts and the owner's day-to-day machine.
