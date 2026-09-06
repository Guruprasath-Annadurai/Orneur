# Phase 10 — Current Authority Architecture Audit

Every existing authorization source in the codebase, classified before
any Godmode code was written.

| Source | File | Classification | Notes |
|---|---|---|---|
| Org/tenant identity | `orca/auth/org_store.py`, `orca/auth/db.py` | CANONICAL | `org_id`/`OrgMember` — the real multi-tenancy substrate, reused unchanged by Connectors (Phase 9) and now by Godmode leases. |
| User RBAC (owner/admin/member/viewer) | `orca/auth/rbac.py` | CANONICAL | API-layer permission gating (`has_permission`/`require_role`). Distinct axis from Agent Capability/Policy — an org "admin" role is NOT an Agent Runtime capability and does not itself authorize any tool/connector action. Godmode must not conflate the two. |
| Commercial/subscription entitlement | `orca/cognitive/entitlement.py`, `orca/auth/store.py` (`model_access_allowed`, `DAILY_LIMITS`) | CANONICAL | Billing/model-tier gating, kept explicitly separate from Cognitive Kernel policy since Phase 3.1. Godmode must never touch this (spec §25). |
| License gating | `orca/license/gate.py`, `orca/license/keys.py` | CANONICAL | Product license/feature gating (HMAC-signed license keys — the established signing pattern Godmode lease integrity reuses). |
| Agent Capability Engine | `orca/agent/capability.py` (`check_capabilities`) | CANONICAL | Pure membership check; capability set fixed for a run's duration (Phase 8 invariant). NOT modified by Phase 10 — Godmode adds a layer ABOVE it that computes an effective set fed into this same unchanged function. |
| Agent Policy Engine | `orca/agent/policy.py` (`evaluate_policy`) | CANONICAL | The only thing that may authorize execution. NOT modified — Godmode wraps it, never replaces or bypasses it (spec §19). |
| Connector Policy Engine | `orca/connectors/policy.py` (`evaluate_connector_policy`) | CANONICAL | Tenant-check-first, deterministic (Phase 9). NOT modified — Godmode's connector elevation wraps it. |
| Connector tenant-scoped registry | `orca/connectors/registry.py` (`get_for_tenant`) | CANONICAL | The only connector lookup path; Godmode leases must resolve through this, never a second lookup path. |
| Connector approval binding | `orca/connectors/security.py` (`ApprovalBinding`) | CANONICAL (pattern reused) | Phase 9's exact-match, argument-hashed approval binding is the direct ancestor of Phase 10's `GodmodeApproval` — same discipline, generalized beyond connectors. |
| HMAC token/signing pattern | `orca/auth/tokens.py`, `orca/license/keys.py`, `orca/license/stripe_hook.py` | CANONICAL (pattern reused) | `hmac.new(secret, data, sha256)` + `hmac.compare_digest` is the established integrity primitive in this codebase. Phase 10's lease integrity signing reuses this exact pattern rather than inventing a new one. |
| Model registry lifecycle | `orca/registry/model_spec.py`, `orca/society/lifecycle.py` (incl. `LEGACY_PRODUCTION_SERVING`) | LEGACY (the pseudo-lifecycle) / CANONICAL (the registry itself) | `LEGACY_PRODUCTION_SERVING` is a disclosed Phase-7 pseudo-lifecycle for Genesis-legacy, distinct from `ModelRegistry`'s formal states. Godmode must never grant a mechanism to change either (spec §26). |
| Gateway deployment wiring | `orca/gateway/wiring.py` | CANONICAL | Where deployments get registered/persisted; irrelevant to Godmode except as a boundary that must remain untouched. |
| Webhook signature dev-bypass | `orca/license/stripe_hook.py` (`ORCA_ALLOW_UNSIGNED_WEBHOOKS`) | DANGEROUS | An explicit, disclosed, opt-in-only local-dev bypass (never default) for Stripe webhook signature verification. Unrelated to Godmode; flagged here because it is the one genuine "environment flag that disables a security check" found in the audit — confirms no OTHER such flag exists for Agent/Connector/Policy authorization. |
| Test isolation fixtures | `tests/conftest.py` (`_isolate_gateway_registry_dirs`, `DEPLOYMENT_DIR` overrides) | TEST_ONLY | Redirects file-backed registries into a temp dir during tests. Never reachable in production code paths; Godmode's own lease store must get the same treatment (a `GODMODE_HOME`-style override for tests, never a bypass of validation logic itself). |
| "Ultra" naming | `orca/auth/rbac.py` (`"ultra"` permission string), `orca/variants/ultra.py`, `orca/cli.py`, `orca/serve/api.py`, gateway/tier naming | COMPATIBILITY | "Ultra" is a commercial/model-tier naming convention (an org permission string + a model variant name), NOT an authority-elevation mechanism. No code path treats "ultra" as an authorization override for Agent Runtime or Connector actions. Godmode must not reuse this name for its own elevated level to avoid confusing two unrelated concepts — Phase 10 introduces its own distinct terminology (see AUTHORITY_LEVELS.md). |
| Agent delegation non-escalation | `orca/agent/delegation.py` | CANONICAL | `child_capabilities ⊆ parent_capabilities`, `child_budget <= parent remaining`. Godmode's lease delegation (spec §53-54) is modeled directly on this existing, tested invariant rather than inventing a separate delegation discipline. |
| Cross-connector exfiltration policy | `orca/connectors/security.py` (`authorize_cross_connector_flow`) | CANONICAL | Destination-only authorization; unaffected by, and not touched by, Godmode. |

## Findings

- **No DUPLICATED or DEAD authorization sources were found.** The
  codebase has exactly one Agent Capability Engine, one Agent Policy
  Engine, one Connector Policy Engine, one tenant-identity substrate, and
  one RBAC layer — each with a single, clear responsibility and no
  competing/shadow implementation.
- **The only genuine "bypass" flag in the entire codebase**
  (`ORCA_ALLOW_UNSIGNED_WEBHOOKS`) is scoped to Stripe webhook signature
  verification, is opt-in-only, is already tested
  (`tests/test_stripe_hook.py`), and has nothing to do with Agent/
  Connector/Policy authorization. No comparable flag exists for the
  systems Godmode will touch.
- **"Ultra" is unambiguously a commercial/model-tier naming convention**,
  not an authority-elevation concept — confirmed by reading every one of
  its ~30 references. Phase 10 therefore introduces new, distinct
  vocabulary (Authority Levels, `CapabilityLease`, `GodmodeSession`)
  rather than overloading "ultra."
- **Every existing Policy/Capability boundary is a pure, deterministic
  function with no admin/role/env-flag override path threaded through
  it.** This means Phase 10's elevation mechanism has no existing
  "shortcut" to plug into — it must be built as a genuinely new,
  additive layer, which is exactly what spec §2's canonical rule
  (`effective_authority = normal_authority + valid_elevated_lease_scope`)
  requires.
