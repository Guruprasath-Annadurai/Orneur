# Genesis Frontier Provider Resolution Plan — Phase 21B.4.19

**CONTROL PLANE ONLY. No provider email, support ticket, web form or chat
was sent. No provider account was accessed or changed. No opt-out,
ZDR, enterprise agreement, or commercial notice was activated, accepted
or sent. No GPU, inference, paid API, weight download, benchmark,
holdout, or training. Phase 21C is not authorized.**

Machine-readable companions (same directory tree):
`evidence/GENESIS_FRONTIER_PROVIDER_ACTION_QUEUE_2026-09-24.json`,
`evidence/GENESIS_FRONTIER_PROVIDER_RESPONSE_SCHEMA_2026-09-24.json`,
`evidence/GENESIS_FRONTIER_PROVIDER_CLARIFICATION_PACKETS_2026-09-24.md`,
`evidence/GENESIS_FRONTIER_ACCOUNT_SETTING_EVIDENCE_SPEC_2026-09-24.md`,
`evidence/GENESIS_FRONTIER_PROVIDER_RESOLUTION_SHA256_INDEX_2026-09-24.json`.
Code: `orca/eval/frontier_provider_resolution.py`.

## Doctrine

PROVIDER RESOLUTION REQUIRES EVIDENCE. STATE CHANGE REQUIRES VERIFIED
EVIDENCE. FULL-PROTOCOL PROMOTION REQUIRES MACHINE VALIDATION.

A blocker does not move because a draft exists, a setting probably
exists, another provider offers something similar, a support page hints
at a possibility, the owner intends to write, a reply is expected, a
reply is ambiguous, or someone says "looks okay." None of those is
evidence.

## Current quorum (unchanged, honest)

Validated full-protocol ready: **0** · quorum-counting: **0** ·
independent lineages: **0** · status: **QUORUM_BLOCKED**. Locked 6 / 4 / 3.
Registry state is untouched by this phase.

## What Claude can prepare / what needs whom

| Category | Examples | Who |
|---|---|---|
| Claude prepares | drafts, checklists, schemas, validators, queue, graph | Claude (done here) |
| Owner authorization | sending any email/ticket, changing/inspecting a provider account, accepting terms, billing checks | Owner, per action id, default `NOT_AUTHORIZED` |
| Provider response | answers to packet questions, DPA, enterprise terms | Provider |
| Future account action | verified setting changes with evidence | Owner, separately authorized |
| Future execution | any API run | Not authorized (Phase 21C) |

## Action state machine (§8)

States: `NOT_REQUIRED`, `PREPARED`, `AWAITING_OWNER_AUTHORIZATION`,
`AUTHORIZED_NOT_EXECUTED`, `EXECUTED_AWAITING_PROVIDER`,
`PROVIDER_REPLIED_UNVERIFIED`, `EVIDENCE_VERIFIED`,
`EVIDENCE_INSUFFICIENT`, `RESOLVED`, `BLOCKED`, `EXPIRED_OR_STALE`.
"Sent" is not a state and never equals resolution.

Each forward step needs its own evidence: authorization needs recorded
owner authorization evidence; execution needs prior authorization
evidence plus execution evidence; a reply needs the received record;
`EVIDENCE_VERIFIED`/`RESOLVED` need a persisted `verified_evidence_ref`.
`BLOCKED` is terminal in this phase (e.g. `GLB-02` RUN_FRONTIER_API).

## Owner authorization model (§9/§10)

Every action type (`SEND_PROVIDER_EMAIL`, `SUBMIT_SUPPORT_TICKET`,
`CHANGE_PROVIDER_ACCOUNT_SETTING`, `INSPECT_PROVIDER_ACCOUNT_SETTING`,
`ENABLE_NO_TRAINING`, `ENABLE_ZDR`, `ACCEPT_ENTERPRISE_TERM`,
`SEND_COMMERCIAL_NOTICE`, `VERIFY_BILLING_CREDITS`, `RUN_FRONTIER_API`)
has `requires_owner_authorization: true`, `claude_can_execute: false`,
and defaults `NOT_AUTHORIZED`. The validator rejects any executed action
lacking authorization evidence, and `assert_queue_fully_unauthorized()`
proves this phase's queue has zero authorizations and zero executions.

## Evidence standard and ingestion (§18/§19)

Tiers: **A** published primary-source terms; **B** official provider
written response; **C** provider account setting with captured evidence
plus documentation; **D** informal (never resolves a hard blocker). A
record is VERIFIED only with: official provider domain, persisted raw
source whose recomputed SHA-256 matches, named reviewer, timestamp,
answered question ids, quoted clauses, no remaining ambiguity behind any
approved change, and only permitted, evidence-kind-matched changes. See
the response schema. No response is automatically trusted.

## Fail-closed state-transition rules (§21/§22)

| Field | Transition | Only if |
|---|---|---|
| `private_holdout_status` | REVIEW_REQUIRED/BLOCKED → PERMITTED | verified `NO_TRAINING_CONFIDENTIALITY` evidence for the intended access path AND verified account-setting evidence where the route is a setting |
| `automated_evaluation_status` | REVIEW_REQUIRED → CLEAR | verified `AUTOMATED_EVALUATION_PERMISSION` evidence |
| `license_or_terms_status` | REVIEW_REQUIRED → CLEAR | verified `TERMS_CLARIFICATION` evidence |
| `evidence_retention_status` | REVIEW_REQUIRED → PERMITTED | verified `RETENTION_RIGHTS` evidence |
| `model_identity_attributable` | false → true | verified `PROVIDER_VERSION_IDENTITY` evidence |
| `access_path_identified` | false → true | verified `ACCESS_PATH_TERMS` evidence |
| `access_preflight_status` | → counting status | **never by a response**; only `promote_access_status()` → `validate_full_protocol_access_readiness()` passing on the entry's own dimensions |

Required sequence: evidence received → ingested → verified → dimensions
updated → fail-closed validator run → only then access status may change →
quorum recomputed (which re-derives readiness again). `SELF_HOST_COMPUTE_
PROHIBITIVE` and `ZERO_CASH_CHECK_REQUIRED` are compute/financial and are
never resolvable by provider evidence.

## Quorum recovery dependency graph (§23)

Full per-reference graph (blocker → owner action → provider action →
evidence → machine field → readiness) is in the action queue JSON's
`dependency_graph`. Summary of unresolved evidence dimensions today:

| Reference | Unresolved dimensions | Critical-path burden |
|---|---|---|
| Qwen3.8-Max | terms, retention, automated evaluation, model identity | 2 |
| DeepSeek V4.1-Flash | private holdout | 3 |
| Mistral Large 3 | automated evaluation, private holdout | 3 |
| GLM-5.3 (flagship) | terms, retention, automated evaluation, private holdout | 3 |
| MiniMax M3 | terms, retention, automated evaluation, private holdout, access path | 3 |
| Kimi K3 | private holdout (needs written enterprise agreement) | 5 |

Burden is relative operational effort (1 = a question round, 2 = a
scope-dependent follow-up or setting with verification, 4 = a
negotiated contract), **not** the probability of a favorable answer, and
never a model-quality ranking. It is computed by
`compute_minimum_conditional_path()` from the registry plus the queue.

### Shortest CURRENTLY KNOWN conditional path to 4 references / 3+ lineages

Assumes nothing about provider answers and is **not** achieved:

> IF Qwen (Alibaba) verifies QWN-Q1–Q8 (benchmarking permission, retention
> rights, and a verifiable stable dated identifier)
> AND DeepSeek verifies an API-applicable, prospective opt-out (DSK-01/02)
> and it is verified active (DSK-03)
> AND Mistral verifies automated-evaluation permission (MIS-01) and the
> API toggle is verified disabled (MIS-02)
> AND GLM (Zhipu AI / Z.ai) verifies the DPA terms and an applicable
> no-training control (GLM-01/02)
> THEN a 4-reference / 4-organization path exists (each still needs the
> fail-closed validator and a fresh zero-cash check at run time).

**Fallback:** replace GLM with MiniMax (verified applicability answer,
hosted-API terms, and any required notice). **Second fallback:** Kimi in
place of one of them only if an executed written no-training agreement
exists. Kimi is last-ranked purely on contract burden.

## Human action queue (all `NOT_AUTHORIZED`; Claude cannot execute any)

Authorize by action id, one at a time. One authorization never covers
another action.

**P0**

| ID | Provider / model | Type | Owner does | Why | Expected evidence | Risk/cost |
|---|---|---|---|---|---|---|
| QWN-01 | Alibaba / Qwen3.8-Max | email | send packet | shortest path; terms, retention, automated eval, identity | Tier B/A | free, low |
| MIS-01 | Mistral / Large 3 | email | send packet | automated-eval permission; toggle scope; retention | Tier B/A | free, low |
| DSK-01 | DeepSeek / V4.1-Flash | email | send packet | single remaining gap: API opt-out applicability | Tier B/A | free, low |

**P1**

| ID | Provider / model | Type | Owner does | Why | Expected evidence | Risk/cost |
|---|---|---|---|---|---|---|
| GLM-01 | Z.ai / GLM-5.3 | email | send packet | DPA and evaluation/training terms | Tier A/B | free, low |
| MIS-02 | Mistral / Large 3 | account setting | disable API "Anonymous improvement data" per checklist (after MIS-01) | holdout route | Tier C | free, reversible |
| DSK-02 | DeepSeek / V4.1-Flash | inspect setting | read-only look and capture | find any API-applicable setting | screenshots | free, minimal |
| DSK-03 | DeepSeek / V4.1-Flash | enable no-training | only after DSK-01/02 verified | holdout route | Tier C | free, reversible |
| MNX-01 | MiniMax / M3 | email | send applicability question (not the notice) | Commercial Use ambiguity | Tier B | free, low |
| KMI-01 | Moonshot / Kimi K3 | email | send enterprise inquiry | learn if a no-training arrangement exists | Tier B | free to ask |

**P2**

| ID | Provider / model | Type | Owner does | Why | Expected evidence | Risk/cost |
|---|---|---|---|---|---|---|
| GLM-02 | Z.ai / GLM-5.3 | enable no-training | only after GLM-01 verified | holdout route | Tier B/C | unknown |
| MIS-03 | Mistral / Large 3 | enable ZDR | only if MIS-Q6 requires | confidentiality | Tier B/C | plan may apply |
| MNX-02 | MiniMax / M3 | commercial notice | only if MNX-01 says YES | compliance path | sent record + attribution | free |
| KMI-02 | Moonshot / Kimi K3 | accept enterprise term | only if KMI-01 shows acceptable terms and owner approves | holdout route | executed agreement | possibly significant spend |
| GLB-01 | ALL | verify billing/credits | not needed until a future run | zero-cash gate | live billing evidence | none now |
| GLB-02 | ALL | RUN_FRONTIER_API | **BLOCKED — do not authorize** | Phase 21C not authorized | n/a | paid inference |

## Phase 21B.4.19.1 closure — authority, binding, dependencies, evidence refs

Independent audit passed the architecture and found four fail-closed
defects. All four are closed in `orca/eval/frontier_provider_resolution.py`;
no reference state, action state, or quorum figure changed.

1. **Provider ↔ reference binding.** `REFERENCE_PROVIDER` is the single
   canonical map (DeepSeek V4.1-Flash → DeepSeek AI; GLM-5.3 (flagship) →
   Zhipu AI / Z.ai; Mistral Large 3 → Mistral AI; MiniMax M3 → MiniMax;
   Qwen3.8-Max → Alibaba; Kimi K3 → Moonshot AI). A provider response,
   account-setting record, verified-evidence ref, execution record or queue
   action whose provider is not the canonical owner of its reference is
   rejected — even when the sender domain is genuinely official for some
   other provider. Answered question ids must come from the provider's own
   family (`MIS-Q*`, `DSK-Q*`, `KMI-Q*`, `GLM-Q*`, `MNX-Q*`, `QWN-Q*`). Only
   `GLB-01`/`GLB-02` may use provider/reference `ALL`.
2. **Structured owner authorization.** A non-empty dict authorizes nothing.
   An authorization is a strict record `{action_id, decision=AUTHORIZED,
   authorized_by_role=OWNER, authorized_at_utc, authorization_source_kind,
   authorization_source_ref, scope=EXACT_ACTION_ONLY}` for exactly one
   action id; unknown keys, wildcard/provider-wide/phase-wide scope, empty
   source refs and malformed timestamps are rejected.
   `advance_action_state(... AUTHORIZED_NOT_EXECUTED ...)` calls the
   validator, so MIS-01's authorization cannot authorize MIS-02/MIS-03, nor
   another provider's action.
3. **Enforced dependencies.** `depends_on` is checked at authorization and
   again at execution. Completion rule: the dependency must be **RESOLVED**
   (a merely authorized, executed, replied, or EVIDENCE_VERIFIED dependency
   is not complete). The dependency context (`build_action_lookup(queue)`) and
   an `evidence_root` are mandatory arguments — missing context fails
   closed, and a dependency's persisted evidence is re-hashed. DSK-03
   requires both DSK-01 and DSK-02. The queue validator also rejects a
   queue in which a dependent action is authorized/executed while a
   dependency is not RESOLVED, and any dependency cycle. `GLB-02`
   (`RUN_FRONTIER_API`, BLOCKED) cannot be moved by authorization or
   dependency state.
4. **Durable, validated evidence references.** Entering an
   execution-asserting state persists a structured `execution_evidence_ref`
   bound to the action's id/type/provider/reference with a source ref and a
   UTC time not earlier than the authorization. `EVIDENCE_VERIFIED` accepts
   only the ORIGINAL evidence record (re-validated in full); the canonical
   `verified_evidence_ref` is *derived* by
   `build_verified_provider_evidence_ref()` /
   `build_verified_account_setting_evidence_ref()` — never hand-authored,
   never a string. `RESOLVED` re-verifies the persisted source bytes.
   Evidence type must suit the action type (an email action cannot be closed
   by account-setting evidence).

**What machine validation proves — and does not.** It proves internal
consistency: provider/reference/question-family binding, structural
completeness, persisted source bytes that hash to the recorded SHA-256, an
official-domain sender *string*, a permitted evidence tier, and exact-action
authorization structure. It does **not** cryptographically prove that a
human has not fabricated metadata (sender identity, message id, timestamps,
authorization text) or the saved file's content, and it cannot prove an
email was really sent. Human/connector provenance remains part of evidence
review.

Real queue after this closure: 15 actions, 0 authorized, 0 executed, 0
resolved, no authorization/execution/verified evidence, all counters 0;
`GLB-02` BLOCKED.

## Phase 21B.4.19.2 closure — outcome-bound dependencies

One semantic defect remained after 21B.4.19.1: a dependency counted as
satisfied when its upstream action was merely `RESOLVED`. But `RESOLVED`
only proves the provider interaction/evidence cycle concluded — a provider
may definitively answer **NO** (valid, conclusive evidence) and the upstream
action is legitimately `RESOLVED`, yet the conditional downstream action
(e.g. DSK-03 `ENABLE_NO_TRAINING`) must stay locked.

**Canonical rule: `RESOLVED != PREREQUISITE_SATISFIED`.** Lifecycle state and
prerequisite satisfaction are now separate.

- **Outcome model** (`resolution_outcome`, separate from `state`):
  `NOT_ASSESSED`, `PREREQUISITE_SATISFIED`, `PREREQUISITE_NOT_SATISFIED`,
  `PARTIAL_INFORMATION`, `NO_FOLLOWUP_REQUIRED`. `state=RESOLVED` with
  `PREREQUISITE_NOT_SATISFIED` is valid and does not unlock anything.
  Only `PREREQUISITE_SATISFIED` can unlock a dependent.
- **Durable resolution assessment** (`resolution_assessment`): an
  `EVIDENCE_REVIEWER` decision bound to the action, provider, reference and
  the action's own verified-evidence ref, with structured fact codes, the
  provider questions addressed, a UTC time, and a persisted review record
  whose SHA-256 is recorded and re-checked (byte for byte) at every
  dependency check. Question coverage is derived from the validated
  original provider record, not reviewer assertion.
- **Structured facts, not prose** (`ACTION_FACT_CODES`): e.g. MIS-01 →
  `MISTRAL_API_TRAINING_OPTOUT_APPLICABLE`, `MISTRAL_ZDR_APPLICABLE`,
  `MISTRAL_AUTOMATED_EVALUATION_PERMITTED` (+ negatives); DSK-01 →
  `DEEPSEEK_API_OPTOUT_APPLICABLE`, `..._PROSPECTIVE`; DSK-02 →
  `DEEPSEEK_ACCOUNT_SETTING_PRESENT`; GLM-01 →
  `GLM_NO_TRAINING_CONTROL_AVAILABLE`, `..._APPLIES_TO_GLM_5_3`; MNX-01 → one
  mutually-exclusive conclusion (`APPLIES` / `DOES_NOT_APPLY` /
  `STILL_AMBIGUOUS`); KMI-01 →
  `KIMI_ACCEPTABLE_ENTERPRISE_NO_TRAINING_PATH_AVAILABLE`. Each fact names the
  questions that must have been answered (MNX-Q2 alone can never establish a
  Commercial Use conclusion; an unrelated Moonshot pricing answer can never
  establish an acceptable enterprise path). Wrong-action facts, unknown
  codes, contradictions, unsorted/duplicate lists are rejected.
- **Dependency requirement policy** (`DEPENDENCY_REQUIREMENTS`): MIS-02 needs
  the training-opt-out-applicable fact from MIS-01; MIS-03 needs the
  ZDR-applicable fact; DSK-03 needs both DSK-01 facts (applicable +
  prospective) AND DSK-02's setting-present fact; GLM-02 needs
  control-available AND applies-to-GLM-5.3; MNX-02 needs
  `MINIMAX_COMMERCIAL_USE_APPLIES` (`DOES_NOT_APPLY` never satisfies it);
  KMI-02 needs the acceptable-path fact.
- **Gate** (authorize *or* execute a dependent): dependency `RESOLVED` **and**
  its verified evidence re-proves **and** its assessment validates against
  the persisted review record **and** outcome is `PREREQUISITE_SATISFIED`
  **and** every fact required for *this* dependent is present. Anything
  else fails closed. The queue validator additionally requires the policy to
  match the declared `depends_on` graph exactly.
- **Negative answers close the branch, never re-open the upstream action.**
  A definitive-negative fact lets `close_unavailable_branch()` move the
  conditional action to `NOT_REQUIRED` permanently (e.g. MNX-02 when
  Commercial Use does not apply; KMI-02 when no acceptable enterprise path
  exists). Ambiguous or partial outcomes neither unlock nor close it.
- **Registry untouched.** Outcomes and facts control action sequencing only;
  `apply_verified_evidence`, `resolve_blocker_token` and
  `promote_access_status` remain the only routes to registry state.
- **Honest limits.** Software cannot semantically understand provider prose.
  Machine validation proves exact binding, valid enums/facts, question
  coverage, timestamps and the review record's hash; the human
  `EVIDENCE_REVIEWER` supplies the interpretation. It is tamper-evident, not
  proof of authenticity. MNX-02's alternative unlock (a separate future exact
  owner election of the conservative Commercial-Use path) is deliberately
  **not implemented** here, so there is no bypass.

Real queue after this closure: 15 actions, 0 authorized, 0 executed, 0
resolved, 0 resolution assessments, no outcome and no established facts on
any action; `GLB-02` BLOCKED.

## Authorization boundary

This phase ends before the queue is executed. Valid future
authorizations are per-action, e.g. "Authorize sending MIS-01",
"Authorize DSK-02 inspection." No bundled or silent consent.

## Future execution boundary

`GLB-01` (fresh zero-owner-cash check) and `GLB-02` (RUN_FRONTIER_API)
exist only to make the boundary explicit. No frontier execution is
authorized; every future run additionally requires `owner_billed_delta_usd
== 0`, a re-verified account setting, a still-fresh provider response,
and an explicit Phase 21C authorization.

## Program state (unchanged)

- TARGET REFERENCES: 6
- MINIMUM USABLE: 4
- MINIMUM LINEAGES: 3
- GENESIS FOUNDATION: NOT SELECTED
- GENESIS FRONTIER STATUS: UNPROVEN
- PHASE 21C: NOT AUTHORIZED
- FRONTIER EXECUTION AUTHORIZED: NO
