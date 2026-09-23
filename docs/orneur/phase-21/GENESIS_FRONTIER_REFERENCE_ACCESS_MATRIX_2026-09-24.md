# Genesis Frontier Reference Access Matrix — Phase 21B.4.18 update

**PRIMARY-SOURCE RESEARCH + CPU/METADATA ONLY. No GPU, no frontier
inference, no paid API call, no benchmark. Metadata/docs/terms only.**

This is an ADDITIVE Phase 21B.4.18 closure artifact. The Phase
21B.4.17/.1/.2 access matrix
(`docs/orneur/phase-21/GENESIS_FRONTIER_REFERENCE_ACCESS_MATRIX_2026-09-23.md`)
is preserved unmodified as the historical record of that phase's
conclusions; this file records what Phase 21B.4.18's quorum-recovery
research (blocker resolution across all six references, prioritized
Mistral → Kimi → DeepSeek → GLM → MiniMax → Qwen) actually changed, and
— just as importantly — what it did NOT change (§20: no fake progress).

Source evidence:
`docs/orneur/phase-21/GENESIS_FRONTIER_REFERENCE_BLOCKER_MATRIX_2026-09-24.md`,
`docs/orneur/phase-21/evidence/GENESIS_FRONTIER_REFERENCE_PROVIDER_CLARIFICATIONS_2026-09-24.md`,
and the registry's six new Phase 21B.4.18 evidence fields
(`automated_evaluation_status`, `private_holdout_status`,
`access_path_identified`, `model_identity_attributable`,
`non_financial_blocker_status`, `full_protocol_access_validation`).

## What changed this phase

| Reference | Field | Before (21B.4.17.2) | After (21B.4.18) | Why |
|---|---|---|---|---|
| Qwen3.8-Max | `private_holdout_status` | (not tracked as a discrete field) | **PERMITTED** | Direct, specific Alibaba Cloud Model Studio primary-source statements: "does not use customer business data to develop or improve models without explicit consent" and "never uses your data for model training." |
| All six | (new fields added) | n/a | `automated_evaluation_status`, `private_holdout_status`, `access_path_identified`, `model_identity_attributable`, `non_financial_blocker_status`, `full_protocol_access_validation` | Phase 21B.4.18 §7/§8 machine-enforced promotion gate — see `orca/eval/candidate_registry.py` and `orca/eval/frontier_reference_admission_quorum.py` Phase 21B.4.18 docstring addenda. |

## What did NOT change this phase (§20/§28 regression lock)

- No reference's `access_preflight_status` changed — all six remain
  `UNQUALIFIED` for full-protocol purposes.
- No reference's `reference_evaluation_admission_status` changed.
- DeepSeek V4.1-Flash's `private_holdout_status` remains
  `REVIEW_REQUIRED` — no new primary-source evidence this phase proved
  the Privacy Policy opt-out applies to Open Platform/API traffic.
- Mistral Large 3's `private_holdout_status` remains `REVIEW_REQUIRED`
  — the Admin-panel opt-out mechanism exists but was not exercised (no
  provider account action authorized this phase), and no primary source
  states paid-API traffic is training-excluded by default.
- Kimi K3's `private_holdout_status` is now explicitly recorded as
  `BLOCKED` (hosted path) rather than merely unresolved — Moonshot AI's
  own Terms of Service §4 was re-fetched live and directly confirms
  default training-on-content with no self-service opt-out.
- GLM-5.3 flagship, MiniMax M3 remain `REVIEW_REQUIRED` across the
  board — no primary source located this phase resolves their
  respective terms ambiguities.
- Quorum status remains `QUORUM_BLOCKED` (0 full-protocol-counting
  references, 0 independent lineages) — unchanged from Phase 21B.4.17.2.
- `public_eval_access_preflight_status` for DeepSeek remains
  `PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK` (informational only,
  does not count toward full-protocol quorum).

## Machine promotion gate (§7/§22, new this phase)

`compute_admission_quorum()` no longer trusts a reference's
`access_preflight_status` string. Before counting any reference, it
re-derives readiness from that reference's own evidence fields via
`validate_full_protocol_access_readiness()` — the same fail-closed
function `candidate_registry._validate_reference()` invokes at registry
load time whenever a reference claims a counting status. A forged
status string, a `REVIEW_REQUIRED` terms/retention/automated-evaluation/
private-holdout field, an unattributable model identity, a missing
access path, or any unresolved non-financial blocker (`non_financial_
blocker_status != "NONE"`) silently excludes that reference from the
counting set — it can never inflate `quorum_status`. Only an
otherwise-fully-passing reference whose sole remaining gap is the
zero-owner-cash check (`access_preflight_status =
PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK`) is accepted as counting
— proving the state carries its intended, narrow meaning. See
`tests/test_genesis_frontier_reference_admission.py`'s Phase 21B.4.18
tamper tests for the full proof set.

## Program state (unchanged)

- GENESIS FOUNDATION: NOT SELECTED
- GENESIS FRONTIER STATUS: UNPROVEN
- PHASE 21C: NOT AUTHORIZED
- NO FRONTIER EXECUTION AUTHORIZED: YES
