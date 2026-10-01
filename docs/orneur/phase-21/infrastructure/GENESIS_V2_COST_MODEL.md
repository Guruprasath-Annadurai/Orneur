# GENESIS V2 — Cost Model

Status: **DESIGN ONLY. NOTHING HAS BEEN PURCHASED OR PROVISIONED.** All figures are approximate, order-of-magnitude estimates to support an owner decision — not quotes, not commitments.

## Tier 0 — Minimum Sovereign Setup

| Item | One-time | Monthly | Mandatory? |
|---|---:|---:|---|
| Owner key custody: macOS Keychain | $0 | $0 | Mandatory |
| Optional hardware security key (YubiKey or equivalent) | ~$25–55 | $0 | Optional (strongly recommended, cheap enough to treat as default) |
| Forge + Witness: existing owner-controlled machine(s), run as separate OS users/processes | $0 (reuses existing hardware) | $0 | Mandatory |
| Vault: local encrypted directory (FileVault or equivalent) | $0 | $0 | Mandatory |
| Reliquary: external encrypted drive | ~$50–150 | $0 | Mandatory (backup is not optional) |
| Evidence: git-committed snapshots (existing repo) | $0 | $0 | Mandatory |
| **Total** | **~$75–205** | **$0** | |

Security improvements over doing nothing: real key-half separation, real write-once ciphertext, real append-only evidence trail, offline owner signing. Mandatory controls: all of the above. Optional: the hardware key (software Keychain is an acceptable Tier 0 floor, but meaningfully weaker against a compromised owner machine).

## Tier 1 — Production Hardened

| Item | One-time | Monthly | Mandatory? |
|---|---:|---:|---|
| Hardware security key for owner signing | ~$25–55 | $0 | Mandatory at this tier |
| Dedicated cloud account/project for Vault storage (object storage + Object Lock) | $0 setup | ~$5–25 (small data volumes at Genesis V2 scale) | Mandatory |
| Separate cloud account/project for Forge compute (ephemeral VM/container, used only during generation) | $0 setup | ~$0–20 (pay-per-use, likely near-zero if genuinely ephemeral) | Mandatory |
| Separate cloud account/project for Witness compute | $0 setup | ~$5–20 (small always-off-except-during-verification instance, or also ephemeral) | Mandatory |
| Secrets manager (cloud-native, scoped per identity) | $0 setup | ~$1–10 (typically priced per secret per month) | Mandatory |
| Reliquary: second cloud account/provider, object storage + Object Lock | $0 setup | ~$5–15 | Mandatory |
| Evidence store: dedicated immutable log/object prefix | $0 setup | ~$1–5 | Mandatory |
| Basic cloud-native audit logging (CloudTrail-equivalent) | $0 setup | ~$0–10 | Mandatory |
| **Total (new recurring)** | **~$25–55 one-time** | **~$17–100/month** | |

Operational complexity: meaningfully higher than Tier 0 — requires IAM policy authorship, multi-account management, and genuine cloud operational discipline. Security improvement: real multi-machine/multi-account isolation, immutable storage, cloud audit trail, availability beyond a single owner machine.

## Tier 2 — Enterprise / Critical Infrastructure

| Item | One-time | Monthly | Mandatory? |
|---|---:|---:|---|
| HSM-backed or cloud-KMS-backed owner signing key | $0–1,000+ (dedicated HSM appliance, if chosen over cloud KMS) | ~$1–50 (cloud KMS asymmetric key + per-operation cost) or $0 (self-hosted HSM after purchase) | Optional — cloud KMS is a reasonable middle ground before a dedicated HSM appliance |
| Multi-provider, multi-region Vault + Reliquary replication | $0 setup | ~$20–80 | Optional, for genuine multi-provider resilience |
| Dedicated SIEM-grade observability (Sentinel) | $0–varies (platform-dependent) | ~$20–200 (highly variable by log volume and chosen platform) | Optional |
| Formal IaC with policy-as-code review gates (e.g. a Terraform/OpenTofu pipeline with automated policy checks) | owner/engineering time, not a direct line cost | $0 incremental beyond existing CI | Recommended once Tier 1's cloud footprint is real |
| Dedicated management/administrative account separate from data-plane accounts | $0 setup | ~$0–10 | Recommended |
| **Total (new recurring)** | **$0–1,000+** | **~$41–340+/month** | |

At Tier 2, costs become genuinely workload- and vendor-dependent; the figures above are illustrative ranges, not estimates to budget against without a specific provider quote.

## Which controls are mandatory vs. optional, across all tiers

**Always mandatory, regardless of tier or cost**: role separation (Forge ≠ Witness ≠ Owner), ciphertext-only backup, no shared admin credential, write-once vault semantics, append-only evidence, the owner signing ceremony's review steps, network default-deny. None of these are "nice to have" — they are the actual security model, and every tier above implements them at increasing cost for increasing availability/operational convenience, never as a tradeoff against the core model.

**Genuinely optional, tier-dependent**: hardware-backed key custody vs. Keychain-only, cloud multi-account vs. local machines, multi-region replication, SIEM-grade observability vs. basic logging, HSM vs. cloud KMS vs. hardware token.

## Recommendation

Start at Tier 0 — it is free, already matches the current `NOT_CONFIGURED` baseline exactly, and exercises the full trust model end-to-end before any money is spent. Graduate to Tier 1 only when the owner wants real multi-machine availability or is ready to generate a corpus the owner considers valuable enough to justify ~$20–100/month. Tier 2 is appropriate only once ORNEUR has a funding/operational profile that justifies enterprise-grade infrastructure spend — premature Tier 2 adoption adds cost and operational surface without a corresponding security benefit at today's scale.
