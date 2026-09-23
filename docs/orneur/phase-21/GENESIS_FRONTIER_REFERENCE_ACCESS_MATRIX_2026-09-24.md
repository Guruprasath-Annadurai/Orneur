# Genesis Frontier Reference Access Matrix — Phase 21B.4.18 update (reconciled 21B.4.18.1)

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

## Phase 21B.4.18.1 canonical-state reconciliation

Independent audit passed Phase 21B.4.18's architecture but found three
internal inconsistencies between the delivered final report and the
underlying registry/evidence. This file (and the blocker matrix and
provider clarification artifacts) were corrected in place; no legal
conclusion was invented, no reference was promoted, and no quorum
metric changed as a result of these corrections.

1. **MiniMax M3 — commercial-use applicability.** The Phase 21B.4.18
   final report incorrectly framed MiniMax's commercial-use question as
   already-resolved ("clarification required: NO"), while the registry
   itself correctly carried `license_or_terms_status=REVIEW_REQUIRED`
   and `non_financial_blocker_status` including
   `COMMERCIAL_USE_AMBIGUITY`. The registry state was already correct
   (OPTION A of the reconciliation instructions: applicability remains
   genuinely ambiguous); the blocker matrix and provider-clarification
   artifacts are now corrected to match it — `clarification required:
   YES`, with a genuine applicability question drafted (not sent)
   alongside the conditional compliance-notice draft. No registry field
   changed.
2. **Kimi K3 — blocker taxonomy.** `private_holdout_status=BLOCKED` was
   already correct in the registry, but its `non_financial_blocker_
   status` used `PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED` — a token
   meaning "unknown," when the evidence (Moonshot's own live-refetched
   ToS §4) actually CONFIRMS default training-on-content. This is now
   corrected to `PROVIDER_TRAINING_ON_INPUTS` (a confirmed-condition
   taxonomy token), with `WRITTEN_PROVIDER_CLARIFICATION_REQUIRED`
   retained to reflect that the enterprise written-agreement route is a
   real, identified (if unexercised) path — Kimi is not characterized
   as having no route at all.
3. **Mistral Large 3 — retention claim.** The Phase 21B.4.18 final
   report asserted "30 rolling days for abuse monitoring unless ZDR
   activated" without noting that Mistral's own Privacy Policy (the
   source of that figure) scopes itself OUT of exactly ORNEUR's
   business/API use case ("does not apply if you use our Mistral AI
   Products to process personal data in the context of your business
   activities"). Re-verified live this phase against the same primary
   source. The canonical statement is now: ordinary (non-ZDR) API
   retention duration for a business/API customer is **NOT PRECISELY
   ESTABLISHED IN THIS PHASE** (the Data Processing Addendum, not the
   Privacy Policy, is the more likely governing document, and its
   specific retention terms were not located); ZDR remains available
   for eligible supported stateless API calls, independent of this open
   question.

None of these three corrections changed any `access_preflight_status`,
promoted any reference, or altered `quorum_counting_count` /
`quorum_status` — all remain exactly as Phase 21B.4.18 left them (see
below).

## Program state (unchanged)

- GENESIS FOUNDATION: NOT SELECTED
- GENESIS FRONTIER STATUS: UNPROVEN
- PHASE 21C: NOT AUTHORIZED
- NO FRONTIER EXECUTION AUTHORIZED: YES
