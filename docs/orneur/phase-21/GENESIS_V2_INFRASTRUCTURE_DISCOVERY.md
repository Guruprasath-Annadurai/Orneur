# Genesis Capability Eval V2 — Infrastructure Discovery (read-only audit)

This document is a factual inventory of ORNEUR's ACTUAL, EXISTING deployment surfaces, produced by inspecting the
committed repository — not by assuming another project's cloud architecture. Every claim below cites a real file.
Nothing in this document activates, provisions, or configures anything. Where a component genuinely does not exist,
it is marked **NOT CONFIGURED** rather than described as if it were ready.

## 1. What ORNEUR actually runs today

| Surface | Evidence | Purpose | Suitable for the Genesis V2 vault? |
|---|---|---|---|
| Fly.io (`fly.toml`, `Dockerfile.fly`) | `app = "orca-demo"`, a persistent volume `atheris_data` mounted at `/data` | Public-facing demo web app (chat UI, auth DB, session history) | **No.** A Fly volume backs a live, internet-reachable service process — the opposite of the isolated, owner-controlled, offline-capable machine the vault design assumes. |
| Kubernetes manifests (`k8s/deployment.yaml`, `service.yaml`, `configmap.yaml`) | `replicas: 1`, single uvicorn process (see `docs/orneur/phase-14/CURRENT_DEPLOYMENT_ARCHITECTURE.md`) | Alternative deployment target for the same public app | **No,** same reasoning as Fly — this is the serving layer, not a private storage boundary. |
| Northflank (`orneur-api-a` service) + Supabase (Postgres) + Cloudflare (edge/WAF/tunnel) | `.github/workflows/phase14b-distributed-qualification.yml` — real staging infrastructure, `NORTHFLANK_PROJECT: orneur-phase14b-staging`, `ORNEUR_DATABASE_URL`/`ORNEUR_GODMODE_DATABASE_URL` etc. read from a GitHub Actions **environment** named `phase14b-staging` | Distributed Godmode/authority/auth-store qualification testing (Phase 14B) — an entirely different subsystem | **No.** This is a live, shared, internet-reachable staging environment for a DIFFERENT security boundary (Godmode authority distribution). Reusing it for genesis_v2 secrets would put corpus material behind the wrong access-control policy and mix unrelated blast radii. It IS, however, the only REAL PRECEDENT in this repository for "a secret-scoped GitHub Environment with per-environment secrets" — see §3. |
| Docker Compose (`docker-compose.yml`) | Named local volumes, plain `environment:` blocks, no `secrets:` stanza | Local multi-service dev stack | **No** — no secret-manager integration exists here either; it is a local dev convenience only. |
| macOS Keychain probe (`orca/eval/genesis_v2/secret_manager.py`) | `keychain_entry_present()`, `probe_secret_manager()` — presence-only, via `/usr/bin/security` | The ONLY secret-manager mechanism this program has ever concretely implemented for Genesis V2 | **Yes, for a single-machine setup** — but it is inherently local/single-user: it has no remote distribution mechanism, so using it for two SEPARATE environments (generator, verifier) means two separate machines each with their own local Keychain, not a shared cloud secret store. |

**Bottom line:** ORNEUR's default architecture is single-machine (`orca/config.py`'s `ORCA_HOME`, documented exhaustively in `docs/orneur/phase-14/CURRENT_DEPLOYMENT_ARCHITECTURE.md`). The one place real multi-host, secret-bearing infrastructure exists (Northflank/Supabase/Cloudflare, Phase 14B) is narrowly scoped to a different subsystem and is not a drop-in fit. **No infrastructure exists today that is purpose-built or currently suitable for the Genesis V2 private vault.** This is not a gap introduced by this phase — it is the honest state of the repository, consistent with `private_storage_genuinely_configured: false` in `GENESIS_CAPABILITY_EVAL_V2_STATUS.json`.

## 2. What the existing Genesis V2 design already assumes

Every document written for this vault since it was first designed (`GENESIS_CAPABILITY_EVAL_V2_STORAGE_POLICY.md`, `GENESIS_CAPABILITY_EVAL_V2_OWNER_VAULT_PROCEDURE.md`) already assumes a **trusted, owner-controlled local machine** — not a cloud service. This is consistent with, not a departure from, everything above: it is the one path that requires zero new infrastructure decisions and zero new cost, because it is what the code (`store.EncryptedVaultWriter`/`EncryptedVaultReader`, `vault_verify.py`) was built and tested against.

## 3. Decisions genuinely missing — returned to the owner, not decided here

Per this phase's explicit instruction, these are presented as alternatives rather than chosen unilaterally.

### Decision A — Execution model: local machines vs. cloud/CI-driven

| Option | What it requires | New cost | New integration work needed |
|---|---|---|---|
| **A1. Two trusted local machines** (or two OS user accounts on machines the owner controls) — matches the CURRENT design exactly | Nothing new; `EncryptedVaultWriter`/`Reader` + macOS Keychain probe already implemented and tested | **$0** | **None** — ready today |
| **A2. Cloud/CI-driven generation** (e.g. a GitHub Actions workflow actually runs the generator) | A real secret manager reachable from CI, plus a real generator implementation (does not exist yet — see `CODE_PATHS` limitation in `operational_boundary.py`) | Depends on §Decision B | Writing the generator, wiring CI to call `protected_generate_write_handle()`, and extending `corpus_generation_authorization.CODE_PATHS` to cover it (already flagged as a residual limitation) |

**Recommendation, not a decision**: A1 requires no new work and is what the codebase already assumes; A2 is a strictly larger undertaking that should only be chosen if there is a specific reason CI-driven generation is needed (e.g. reproducibility requirements beyond what a documented manual procedure provides).

### Decision B — Secret-manager mechanism (only matters if A2 is chosen, or if the owner wants something more robust than local Keychain even for A1)

| Option | Real precedent in this repo? | Indicative cost | Notes |
|---|---|---|---|
| **B1. macOS/OS-native Keychain** (already probed, presence-only) | Yes — `secret_manager.py` | $0 | Single-machine only; no remote distribution; the owner manually places each half on its own machine |
| **B2. GitHub Actions Environments** (per-environment secrets + optional required-reviewer protection rules) | **Yes — `phase14b-staging` already does exactly this for a different subsystem** | $0 on any GitHub plan for basic environment secrets; required-reviewer protection rules may need a paid plan tier (confirm current GitHub pricing before relying on this) | Would need two NEW environments (e.g. `genesis-v2-generator`, `genesis-v2-verifier`) created in repository settings — not yet created; only usable if A2 is chosen, since it implies CI holds the secrets |
| **B3. A dedicated secret-manager service** (e.g. AWS Secrets Manager, HashiCorp Vault, 1Password, Doppler) | No — not integrated anywhere in this codebase | Varies by provider (illustrative, NOT confirmed current pricing): AWS Secrets Manager ~$0.40/secret/month + API costs; 1Password Business ~$8/user/month; HashiCorp Vault Cloud has its own tiered pricing | Would require writing new integration code (this program has never called any cloud secret-manager SDK) |

**No option above is chosen or configured.** `store.owner_setup_preflight()`/`generator_setup_preflight()`/`verifier_setup_preflight()` only check environment-variable PRESENCE — they are mechanism-agnostic by design and work with whichever option the owner ultimately picks.

### Decision C — Whether to formalize separate GitHub Environments now, even under the A1 (local) model

Even under A1, the owner MAY want `genesis-v2-generator`/`genesis-v2-verifier` GitHub Environments created now, purely as a documentation/governance anchor (e.g. to record which humans are permitted to touch which role), without using them to hold real secrets yet. This is optional and has no cost implication either way.

## 4. What this phase does NOT do

Consistent with the absolute restrictions of this phase: no X25519 keys were generated, no storage was activated, no generator was registered as `AUTHORIZED`, no owner signature was requested, no corpus was generated, no model was invoked, no GPU was used, nothing was frozen, and no money was spent. This document is discovery and decision-framing only.
