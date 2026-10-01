# GENESIS V2 — Owner Decisions Required Before Provisioning

Status: **No decision below has been made on the owner's behalf.** Each is a gate. Nothing in this infrastructure package provisions anything until these are answered.

## Decision 1 — Infrastructure strategy

- **A: Sovereign Local** — two owner-controlled machines, $0 recurring. Security: best key custody, weakest availability. Recommendation: **start here**.
- **B: High-Assurance Cloud** — separate cloud accounts per domain. Security: best availability/audit, requires real IAM discipline to realize. Cost: see Tier 1/2.
- **C: Hybrid Sovereign** — owner key always local/hardware, ciphertext in cloud object storage, compute separated by account. Recommendation: **graduate here once Tier 0 is exercised and the owner wants real availability.**

## Decision 2 — Local vs. cloud vs. hybrid, by component

| Component | Recommended Tier 0 | Recommended Tier 1+ |
|---|---|---|
| Owner signing key | macOS Keychain | Hardware token (YubiKey) → optionally HSM/KMS at Tier 2 |
| Generator (Forge) | Local process/user | Ephemeral cloud compute, dedicated account |
| Verifier (Witness) | Separate local process/user (or second machine) | Separate cloud account/machine from Forge |
| Vault | Local encrypted directory | Object storage + Object Lock, dedicated account |
| Reliquary | External encrypted drive | Second cloud account/provider |
| Evidence | Git-committed snapshots | Dedicated immutable log/object prefix |

## Decision 3 — Secret manager

- **A**: macOS Keychain (Tier 0 default, $0, single-machine).
- **B**: GitHub Environments (precedent already exists in Phase 14B's `phase14b-staging` environment) — viable for CI-adjacent secrets, **not recommended** for Genesis V2's vault/owner keys given the public-repo/shared-runner caveats already documented.
- **C**: Dedicated secrets manager (cloud-native, or a standalone product such as 1Password/Doppler/Vault) — recommended once Tier 1 is adopted.
- **Technical recommendation**: A now, C at Tier 1, never B for anything in the Secret Custody Plan's inventory.

## Decision 4 — Owner signing mechanism

- **A**: Software-only (Keychain), $0.
- **B**: Hardware security key (YubiKey or equivalent), ~$25–55 one-time. **Recommended** — cheap enough that cost is not a real objection, and it is the single highest-leverage security upgrade available at Tier 0→1.
- **C**: HSM/cloud-KMS-backed, Tier 2 only, cost varies.

## Decision 5 — Storage backend

See `GENESIS_V2_VAULT_STORAGE_DESIGN.md` §5 for the full card. Recommendation: local filesystem now, S3-compatible object storage with Object Lock at Tier 1.

## Decision 6 — Backup provider

- **A**: Owner-held external encrypted drive (Tier 0, recommended now).
- **B**: Second cloud account/provider, distinct from the Vault's provider (Tier 1+).

## Decision 7 — Estimated monthly budget

Owner must set an explicit ceiling before Tier 1 provisioning begins. This package's own estimate: Tier 1 ≈ $17–100/month; Tier 2 ≈ $41–340+/month (see `GENESIS_V2_COST_MODEL.md`). No recommendation is made on the ceiling itself — that is a business decision, not a technical one.

## Decision 8 — Physical machine purchases, if any

Only relevant if Decision 1 = A/C and the owner's existing hardware is judged insufficient for genuine Forge/Witness separation (e.g. only one machine currently exists). If so: a second low-cost machine (even a cheap mini-PC) is sufficient — Genesis V2's generator/verifier workloads are not compute-intensive. Estimated one-time cost: $150–500 depending on choice. No purchase has been made or recommended as a default; this is a yes/no + budget decision for the owner.

## How to answer these

Each decision above links to the full reasoning in its referenced document. The owner may answer them individually, in any order, and partially (e.g. "Decision 1 = A, defer 2–8 until Tier 1 is actually being planned") — none of these block the other, and none are required to be answered before this phase can be reviewed and audited.
