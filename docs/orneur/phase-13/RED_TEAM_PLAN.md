# Phase 13 — Red-Team Plan

## Approach

Given ~700 pre-existing, passing security tests already covering most of
the spec's named attack categories (Phase 9-12.1's own security work),
this phase's plan was:

1. **Audit, don't duplicate** (spec §79) — inventory which categories
   already have real, behavioral coverage (`orca/security/redteam/campaigns.py`),
   citing exact files.
2. **Prioritize the explicitly-flagged unknown** — spec §23-24 explicitly
   says "do not assume the Ollama fix automatically applies" to
   `orca/gateway/frontier_runtime.py`. This was investigated FIRST, with
   a real timing-based test (not static reading alone).
3. **Add genuinely new cross-layer chains** (spec §62-64, §81) — these by
   nature span multiple existing per-subsystem test files and are
   unlikely to already exist as a single composed test. Built two: a
   3-subsystem chain (Connector → Agent/WorldState → Capability
   enforcement) and a 4-subsystem chain (Connector → Agent/WorldState →
   Court → Godmode issuance boundary).
4. **Disclose scope honestly** — a full, bespoke execution of every one
   of the ~80 sub-attack-vectors listed in spec §9-58 as new tests was
   not completed in this pass; see `FINDINGS.md`'s "Known residual risks
   / scope" section for exactly which campaigns received new work versus
   audit-only confirmation of existing coverage.

## Campaign structure

See `orca/security/redteam/contracts.py` (`SecurityFinding`,
`CampaignCategory`) and `campaigns.py` (`build_catalog()`) for the
machine-readable version of this plan.
