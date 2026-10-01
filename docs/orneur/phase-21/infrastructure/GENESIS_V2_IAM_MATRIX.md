# GENESIS V2 — IAM / Least-Privilege Access Matrix

Status: **DESIGN ONLY — NOT PROVISIONED.** No identity below has been created. This matrix governs whatever Tier is eventually approved; at Tier 0 "account" may mean "OS user" rather than a cloud IAM principal, but the privilege boundaries are identical.

## Identities

| Identity | Maps to code concept | Human or service? |
|---|---|---|
| ORNEUR Owner/Admin | `authority_registry.py` role `OWNER` | Human (the owner) |
| Deployment Automation | n/a today (future CI/IaC apply identity) | Service |
| Generator Runtime | `generator_registry.py` entry | Service (ephemeral/disposable) |
| Verifier Runtime | `runner_registry.py` entry, `allowed_purposes ⊇ {PURPOSE_CREATION_VERIFICATION}`, `∌ PURPOSE_QUALIFICATION` | Service |
| Backup Writer | n/a today (new, Reliquary-scoped) | Service |
| Backup Reader / Restore Operator | n/a today (new, Reliquary-scoped) | Human-initiated, service-executed |
| Evidence Writer | the process appending to the Evidence Ledger (Witness, post-verification) | Service |
| Evidence Auditor | read-only reviewer of the Evidence Ledger | Human (owner, or future delegated auditor) |
| Qualification Runner | `runner_registry.py` entry, `allowed_purposes ⊇ {PURPOSE_QUALIFICATION}` | Service — **not provisioned, design only** |
| Training Runner | future identity, not yet defined in code | Service — **far future, not provisioned** |

## Least-privilege matrix

`✓` = granted, `—` = never granted, `cond.` = conditional/time-boxed only.

| Identity | Vault Write | Vault Read | Owner Sign | Evidence Write | Evidence Read | Network | Training |
|---|---:|---:|---:|---:|---:|---|---:|
| Owner/Admin | — | — | **✓** | — | **✓** | outbound only, no listener | — |
| Deployment Automation | — | — | — | cond. (deploy-identity record only) | **✓** | CI runner default egress, scoped | — |
| Generator Runtime | **✓** (write-only handle) | — | — | — | — | `DENY ALL` default; narrow allowlist only if unavoidable | — |
| Verifier Runtime | — | **✓** (decrypt capability) | — | **✓** (digest-only records) | cond. (own records) | `DENY ALL` default; vault-transfer + ledger only | — |
| Backup Writer | — | — | — | — | — | outbound to Reliquary only | — |
| Backup Reader / Restore Operator | — | cond. (ciphertext only, restore drills) | — | — | cond. | outbound to Reliquary only, owner-triggered | — |
| Evidence Writer | — | — | — | **✓** | — | ledger/evidence store only | — |
| Evidence Auditor | — | — | — | — | **✓** | read-only, no write path at all | — |
| Qualification Runner (future) | — | cond. (holdout, post-freeze, single-use per lineage) | — | cond. | — | `DENY ALL` default | — |
| Training Runner (future) | — | — | — | — | — | not yet defined | **not authorized today** |

## Hard rules

1. **No identity is both Generator and Verifier.** The code already refuses this at the registry-validation layer (`generator_registry.validate()` flags an id registered as both); IAM must mirror that refusal at the infrastructure layer too (no shared service account, no shared role).
2. **No identity holds both X25519 key halves.** Owner (Crown Plane) may *generate* a keypair once, hand the public half to Generator and the private half to Verifier, and then must not retain an operational copy of either half outside its own secure backup of the *keypair-generation event* (see `GENESIS_V2_SECRET_CUSTODY_PLAN.md`).
3. **No broad wildcard permissions anywhere.** Every cloud-tier IAM policy (Strategy B/C cloud half) must name specific resource ARNs/paths, never `*` on an action or resource.
4. **No shared admin token.** The owner's own signing key and any cloud "break glass" admin credential are different materials with different custody (see `GENESIS_V2_INCIDENT_AND_REVOCATION_RUNBOOK.md`).
5. **Deployment Automation never gets Owner Sign.** CI can verify, build, and run acceptance tests; it can never produce a CGA signature, a generation-receipt signature, or a manifest signature on the owner's behalf. This mirrors the already-enforced code rule that the generator process must never receive the owner's private signing key.
6. **Qualification Runner is provisioned with zero standing privilege today.** Its row above is entirely aspirational/design — no credential exists, matching `QUALIFICATION_RUNNER_REGISTRY.json`'s current `REGISTERED_NOT_AUTHORIZED` state.
