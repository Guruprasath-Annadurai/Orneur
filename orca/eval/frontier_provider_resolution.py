"""
Genesis Frontier Provider Resolution control plane (Phase 21B.4.19,
authority/binding closure Phase 21B.4.19.1).

Turns the remaining frontier-reference blockers (provider clarification,
provider account settings, enterprise agreements, model-version
confirmation) into an independently auditable, fail-closed workflow.

Doctrine (phase §4): PROVIDER RESOLUTION REQUIRES EVIDENCE. STATE CHANGE
REQUIRES VERIFIED EVIDENCE. FULL-PROTOCOL PROMOTION REQUIRES MACHINE
VALIDATION. Nothing in this module sends a message, submits a ticket,
changes a provider account setting, calls a provider API, or executes a
model -- it only models actions, validates evidence records, and gates
registry-dimension changes. Every external/account-mutating action
defaults to NOT_AUTHORIZED; only a separate, structured, exact-action
owner authorization can ever move one forward.

Fail-closed layering (the existing Phase 21B.4.17.2/.18 validator stays
authoritative):

1. `validate_provider_response()` / `validate_account_setting_evidence()`
   decide whether an evidence record is VERIFIED (persisted source,
   matching SHA-256, official provider domain, tier A/B/C, specific,
   unambiguous) AND bound to the reference's canonical provider.
2. `apply_verified_evidence()` / `resolve_blocker_token()` change ONE
   underlying evidence dimension (or remove ONE blocker token) only when
   verified evidence explicitly approves exactly that change. They never
   touch `access_preflight_status`.
3. `promote_access_status()` is the only way to a counting access status,
   and it runs `validate_full_protocol_access_readiness()` against the
   entry's own dimensions -- a provider reply can never bypass it.
4. `compute_admission_quorum()` (unchanged) re-derives readiness again at
   count time.

Phase 21B.4.19.1 closes four control-plane defects:

* PROVIDER BINDING -- `REFERENCE_PROVIDER` is the one canonical
  reference->provider map. A provider response, account-setting record,
  or queue action whose provider is not the canonical provider of its
  reference is rejected, even when the sender domain is genuinely
  official for some other provider. Answered question ids must belong to
  the provider's documented question family (`PROVIDER_QUESTION_PREFIX`).
  Only the documented global actions (`GLOBAL_ACTION_IDS`) may use ALL.
* OWNER AUTHORIZATION -- an authorization is a strict structured record
  (`validate_owner_authorization`), bound to exactly one action id. An
  arbitrary non-empty dict authorizes nothing; there is no wildcard,
  provider-wide, phase-wide, or dependency-implying authorization.
* DEPENDENCIES -- `depends_on` is enforced. A dependent action cannot
  become AUTHORIZED_NOT_EXECUTED or EXECUTED_AWAITING_PROVIDER until each
  dependency is RESOLVED (completion rule: RESOLVED only -- a merely
  EVIDENCE_VERIFIED, replied, executed or authorized dependency is not
  complete). The dependency context is a mandatory explicit argument
  (`build_action_lookup(queue)`); no global state; missing context fails
  closed.
* DURABLE EVIDENCE REFERENCES -- entering an execution-asserting state
  persists a validated, structured `execution_evidence_ref` bound to the
  action's id/type/provider/reference. Entering EVIDENCE_VERIFIED
  requires the ORIGINAL evidence record, which is re-validated and from
  which the canonical `verified_evidence_ref` is derived by
  `build_verified_provider_evidence_ref()` /
  `build_verified_account_setting_evidence_ref()`; RESOLVED re-verifies
  that persisted source. A caller-supplied string is never trusted.

Phase 21B.4.19.2 closes one semantic defect: RESOLVED != PREREQUISITE_
SATISFIED. RESOLVED only proves the provider interaction/evidence cycle
concluded -- a provider may definitively answer "NO", which is valid,
conclusive evidence that must still not unlock a conditional downstream
action. A dependency now satisfies a dependent only if ALL hold: the
dependency is RESOLVED; its verified evidence still re-proves; it carries
a durable RESOLUTION ASSESSMENT (an EVIDENCE_REVIEWER decision bound to
the action, provider, reference and verified-evidence ref, backed by a
persisted, SHA-256-hashed review record); the assessment outcome is
PREREQUISITE_SATISFIED; and every fact that `DEPENDENCY_REQUIREMENTS`
demands for THIS dependent is established. Facts are structured codes
(never free text), each tied to the provider questions that must have
been answered. Outcomes and facts control ACTION SEQUENCING ONLY -- they
never mutate registry dimensions (`apply_verified_evidence`,
`resolve_blocker_token` and `promote_access_status` stay the only routes).
Software cannot semantically understand provider prose: it proves exact
binding, enum/fact validity, question coverage, timestamps and the review
record's hash; the EVIDENCE_REVIEWER supplies the interpretation.

What machine validation proves and does NOT prove: it proves internal
consistency (provider/reference/question-family binding, structural
completeness, persisted source bytes that hash to the recorded SHA-256,
an official-domain sender string, a permitted evidence tier). It does
NOT cryptographically prove that a human has not fabricated the metadata
(sender identity, message id, timestamps) or the saved file's content.
Human/connector provenance remains part of evidence review; nothing here
claims more.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from orca.eval.candidate_registry import EXPECTED_REFERENCE_NAMES, _validate_reference
from orca.eval.frontier_reference_admission_quorum import (
    _COUNTING_ACCESS_PREFLIGHT_STATUSES,
    MINIMUM_INDEPENDENT_ORGANIZATIONS,
    MINIMUM_USABLE_REFERENCES,
    validate_full_protocol_access_readiness,
)

# ── canonical provider identity (Phase 21B.4.19.1 §3) ─────────────────────

REFERENCE_PROVIDER: dict[str, str] = {
    "DeepSeek V4.1-Flash": "DeepSeek AI",
    "GLM-5.3 (flagship)": "Zhipu AI / Z.ai",
    "Mistral Large 3": "Mistral AI",
    "MiniMax M3": "MiniMax",
    "Qwen3.8-Max": "Alibaba",
    "Kimi K3": "Moonshot AI",
}

# Documented question-id families (packet ids). A response may only claim
# to have answered ids from its own provider's family (§20).
PROVIDER_QUESTION_PREFIX: dict[str, str] = {
    "Mistral AI": "MIS-Q",
    "DeepSeek AI": "DSK-Q",
    "Moonshot AI": "KMI-Q",
    "Zhipu AI / Z.ai": "GLM-Q",
    "MiniMax": "MNX-Q",
    "Alibaba": "QWN-Q",
}

# The only actions that may use provider=ALL / reference=ALL (§6).
GLOBAL_ACTION_IDS = frozenset({"GLB-01", "GLB-02"})
GLOBAL_ACTION_TYPES = frozenset({"VERIFY_BILLING_CREDITS", "RUN_FRONTIER_API"})

# ── action state machine (§8) ─────────────────────────────────────────────

ACTION_STATES = (
    "NOT_REQUIRED",
    "PREPARED",
    "AWAITING_OWNER_AUTHORIZATION",
    "AUTHORIZED_NOT_EXECUTED",
    "EXECUTED_AWAITING_PROVIDER",
    "PROVIDER_REPLIED_UNVERIFIED",
    "EVIDENCE_VERIFIED",
    "EVIDENCE_INSUFFICIENT",
    "RESOLVED",
    "BLOCKED",
    "EXPIRED_OR_STALE",
)

# "SENT" is deliberately not a state and never equals resolution.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "NOT_REQUIRED": frozenset(),
    "PREPARED": frozenset({"AWAITING_OWNER_AUTHORIZATION", "NOT_REQUIRED", "BLOCKED"}),
    "AWAITING_OWNER_AUTHORIZATION": frozenset({"AUTHORIZED_NOT_EXECUTED", "BLOCKED", "EXPIRED_OR_STALE"}),
    "AUTHORIZED_NOT_EXECUTED": frozenset({"EXECUTED_AWAITING_PROVIDER", "BLOCKED", "EXPIRED_OR_STALE"}),
    "EXECUTED_AWAITING_PROVIDER": frozenset({"PROVIDER_REPLIED_UNVERIFIED", "EXPIRED_OR_STALE"}),
    "PROVIDER_REPLIED_UNVERIFIED": frozenset({"EVIDENCE_VERIFIED", "EVIDENCE_INSUFFICIENT"}),
    "EVIDENCE_VERIFIED": frozenset({"RESOLVED", "EVIDENCE_INSUFFICIENT"}),
    "EVIDENCE_INSUFFICIENT": frozenset({"PREPARED", "BLOCKED", "EXPIRED_OR_STALE"}),
    "RESOLVED": frozenset({"EXPIRED_OR_STALE"}),
    "BLOCKED": frozenset(),
    "EXPIRED_OR_STALE": frozenset({"PREPARED"}),
}

# States that assert an external action actually happened.
_EXECUTION_ASSERTING_STATES = frozenset(
    {"EXECUTED_AWAITING_PROVIDER", "PROVIDER_REPLIED_UNVERIFIED", "EVIDENCE_VERIFIED", "RESOLVED"}
)
_VERIFIED_EVIDENCE_STATES = frozenset({"EVIDENCE_VERIFIED", "RESOLVED"})
# Dependency completion rule (§10): only RESOLVED completes a dependency.
DEPENDENCY_COMPLETE_STATE = "RESOLVED"
_DEPENDENCY_GATED_TARGET_STATES = frozenset({"AUTHORIZED_NOT_EXECUTED", "EXECUTED_AWAITING_PROVIDER"})

# ── owner authorization model (§9/§10) ────────────────────────────────────

EXTERNAL_ACTION_TYPES = (
    "SEND_PROVIDER_EMAIL",
    "SUBMIT_SUPPORT_TICKET",
    "CHANGE_PROVIDER_ACCOUNT_SETTING",
    "INSPECT_PROVIDER_ACCOUNT_SETTING",
    "ENABLE_NO_TRAINING",
    "ENABLE_ZDR",
    "ACCEPT_ENTERPRISE_TERM",
    "SEND_COMMERCIAL_NOTICE",
    "VERIFY_BILLING_CREDITS",
    "RUN_FRONTIER_API",
)
AUTHORIZATION_STATUSES = ("NOT_AUTHORIZED", "AUTHORIZED")
EXECUTED_STATUSES = ("NOT_EXECUTED", "EXECUTED")
PRIORITIES = ("P0", "P1", "P2")

ACTION_REQUIRED_FIELDS = (
    "action_id", "provider", "reference_name", "action_type", "purpose", "blocker_target",
    "prepared_artifact", "requires_owner_authorization", "authorization_status", "executed_status",
    "evidence_required_after_execution", "expected_state_transition",
    "expiry_or_freshness_requirement", "notes",
    "state", "priority", "burden", "critical_path", "depends_on", "claude_can_execute",
    "authorization_evidence", "execution_evidence_ref", "verified_evidence_ref",
    "resolution_outcome", "resolution_assessment",
)

# Structured owner authorization record (§7/§9). Strict: no other keys.
OWNER_AUTHORIZATION_FIELDS = (
    "action_id", "decision", "authorized_by_role", "authorized_at_utc",
    "authorization_source_kind", "authorization_source_ref", "scope",
)
AUTHORIZATION_SOURCE_KINDS = ("OWNER_CHAT_MESSAGE", "OWNER_WRITTEN_RECORD")
AUTHORIZATION_SCOPE_EXACT = "EXACT_ACTION_ONLY"

# Structured execution evidence (§13/§14). Strict: no other keys.
EXECUTION_EVIDENCE_FIELDS = (
    "action_id", "action_type", "provider", "reference_name", "executed_at_utc", "source_ref",
)

# Canonical verified-evidence reference shapes (§16). Strict: no other keys.
VERIFIED_REF_FIELDS: dict[str, tuple[str, ...]] = {
    "PROVIDER_RESPONSE": (
        "evidence_type", "provider", "reference_name", "source_location", "sha256",
        "message_id", "evidence_tier", "received_at_utc",
    ),
    "ACCOUNT_SETTING": (
        "evidence_type", "provider", "reference_name", "source_location", "sha256",
        "setting_name", "effective_timestamp_utc",
    ),
}
_SETTING_ACTION_TYPES = frozenset({
    "CHANGE_PROVIDER_ACCOUNT_SETTING", "INSPECT_PROVIDER_ACCOUNT_SETTING", "ENABLE_NO_TRAINING", "ENABLE_ZDR",
})
# Which verified-evidence kinds may close which action types. Setting
# actions may also be closed by a written provider confirmation; every
# other action type needs a provider response.
_ALLOWED_EVIDENCE_TYPES_BY_ACTION: dict[str, frozenset[str]] = {
    **{t: frozenset({"ACCOUNT_SETTING", "PROVIDER_RESPONSE"}) for t in _SETTING_ACTION_TYPES},
    **{t: frozenset({"PROVIDER_RESPONSE"}) for t in EXTERNAL_ACTION_TYPES if t not in _SETTING_ACTION_TYPES},
}

# ── provider evidence standard (§18/§19) ──────────────────────────────────

EVIDENCE_TIERS = ("A", "B", "C", "D")
RESOLVING_EVIDENCE_TIERS = frozenset({"A", "B", "C"})  # Tier D can never resolve a hard blocker
REVIEW_STATUSES = ("UNREVIEWED", "VERIFIED", "INSUFFICIENT", "REJECTED")

# Keyed by the registry `organization` value.
OFFICIAL_PROVIDER_DOMAINS: dict[str, tuple[str, ...]] = {
    "DeepSeek AI": ("deepseek.com",),
    "Zhipu AI / Z.ai": ("z.ai", "zhipuai.cn", "bigmodel.cn"),
    "Mistral AI": ("mistral.ai",),
    "MiniMax": ("minimax.io", "minimaxi.com"),
    "Alibaba": ("alibabacloud.com", "aliyun.com"),
    "Moonshot AI": ("moonshot.ai", "kimi.ai", "kimi.com", "moonshot.cn"),
}

RESPONSE_REQUIRED_FIELDS = (
    "provider", "reference_name", "incoming_channel", "sender_identity", "sender_domain",
    "message_id", "received_at_utc", "question_ids_answered", "raw_response_location", "sha256",
    "quoted_authoritative_clauses", "interpretation", "remaining_ambiguity", "evidence_tier",
    "review_status", "approved_state_changes", "reviewer", "expiry_or_freshness",
)

ACCOUNT_SETTING_REQUIRED_FIELDS = (
    "provider", "reference_name", "account_identifier_category", "setting_name", "old_state",
    "new_state", "effective_scope", "effective_timestamp_utc", "screenshot_evidence_reference",
    "sha256", "provider_documentation_reference", "prospective", "retroactive", "api_specific",
    "verification_result", "reviewer",
)
# The record stores only a CATEGORY of account identifier, never a real
# account/org/project id or secret (§20).
ALLOWED_ACCOUNT_IDENTIFIER_CATEGORIES = ("ORG_ID_REDACTED", "PROJECT_ID_REDACTED", "NONE")
_FORBIDDEN_ACCOUNT_SECRET_KEYS = ("account_identifier", "account_number", "api_key", "token", "password", "secret")

# ── state-transition rules (§21/§22) ──────────────────────────────────────

# (old, new) pairs permitted per dimension, and the evidence_kind a
# verified approved change must carry to justify it.
DIMENSION_TRANSITIONS: dict[str, frozenset[tuple]] = {
    "private_holdout_status": frozenset({("REVIEW_REQUIRED", "PERMITTED"), ("BLOCKED", "PERMITTED")}),
    "automated_evaluation_status": frozenset({("REVIEW_REQUIRED", "CLEAR")}),
    "license_or_terms_status": frozenset({("REVIEW_REQUIRED", "CLEAR")}),
    "evidence_retention_status": frozenset({("REVIEW_REQUIRED", "PERMITTED")}),
    "model_identity_attributable": frozenset({(False, True)}),
    "access_path_identified": frozenset({(False, True)}),
    "reference_evaluation_admission_status": frozenset({("REVIEW_REQUIRED", "ADMITTED")}),
}
DIMENSION_EVIDENCE_KIND: dict[str, str] = {
    "private_holdout_status": "NO_TRAINING_CONFIDENTIALITY",
    "automated_evaluation_status": "AUTOMATED_EVALUATION_PERMISSION",
    "license_or_terms_status": "TERMS_CLARIFICATION",
    "evidence_retention_status": "RETENTION_RIGHTS",
    "model_identity_attributable": "PROVIDER_VERSION_IDENTITY",
    "access_path_identified": "ACCESS_PATH_TERMS",
    "reference_evaluation_admission_status": "TERMS_CLARIFICATION",
}

# blocker token -> (dimension, satisfied value) that must already hold
# before the token may be removed. SELF_HOST_COMPUTE_PROHIBITIVE and
# ZERO_CASH_CHECK_REQUIRED are compute/financial, never resolvable by
# provider evidence.
_BLOCKER_REQUIRED_DIMENSION: dict[str, tuple[str, object]] = {
    "TERMS_AMBIGUITY": ("license_or_terms_status", "CLEAR"),
    "COMMERCIAL_USE_AMBIGUITY": ("license_or_terms_status", "CLEAR"),
    "AUTOMATED_EVALUATION_UNRESOLVED": ("automated_evaluation_status", "CLEAR"),
    "PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED": ("private_holdout_status", "PERMITTED"),
    "PROVIDER_TRAINING_ON_INPUTS": ("private_holdout_status", "PERMITTED"),
    "EVIDENCE_RETENTION_UNRESOLVED": ("evidence_retention_status", "PERMITTED"),
    "MODEL_IDENTITY_INSUFFICIENT": ("model_identity_attributable", True),
    "ACCESS_PATH_UNVERIFIED": ("access_path_identified", True),
}
_BLOCKER_NEEDS_VERIFIED_RESPONSE = frozenset({"WRITTEN_PROVIDER_CLARIFICATION_REQUIRED"})
_BLOCKER_NEEDS_ACCOUNT_SETTING = frozenset({"PROVIDER_ACCOUNT_SETTING_REQUIRED"})
_BLOCKER_NEVER_PROVIDER_RESOLVABLE = frozenset({"SELF_HOST_COMPUTE_PROHIBITIVE", "ZERO_CASH_CHECK_REQUIRED"})

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_WILDCARD_TOKENS = frozenset({"*", "ALL", "ANY", "N/A", "NONE", "NULL", "TBD"})


class ProviderResolutionError(ValueError):
    """An action, evidence record, or state transition violates the
    Phase 21B.4.19/.19.1 fail-closed provider-resolution rules."""


# Import-time consistency: the canonical map must cover exactly the six
# locked references and exactly the providers with domains/question
# families -- a drifted mapping fails loudly, never silently.
if (
    set(REFERENCE_PROVIDER) != set(EXPECTED_REFERENCE_NAMES)
    or set(REFERENCE_PROVIDER.values()) != set(OFFICIAL_PROVIDER_DOMAINS)
    or set(REFERENCE_PROVIDER.values()) != set(PROVIDER_QUESTION_PREFIX)
):
    raise ProviderResolutionError("REFERENCE_PROVIDER is inconsistent with the locked reference/provider sets")


# ── resolution outcome model (Phase 21B.4.19.2) ───────────────────────────
# Lifecycle state (RESOLVED) is separate from whether the provider's answer
# satisfied a downstream prerequisite. `state=RESOLVED` with
# `resolution_outcome=PREREQUISITE_NOT_SATISFIED` is VALID: the action is
# completed but must not unlock a conditional dependent.

RESOLUTION_OUTCOMES = (
    "NOT_ASSESSED",
    "PREREQUISITE_SATISFIED",
    "PREREQUISITE_NOT_SATISFIED",
    "PARTIAL_INFORMATION",
    "NO_FOLLOWUP_REQUIRED",
)
_ASSESSABLE_OUTCOMES = frozenset(RESOLUTION_OUTCOMES) - {"NOT_ASSESSED"}
ASSESSOR_ROLE = "EVIDENCE_REVIEWER"
REVIEW_RECORD_SCHEMA = "genesis-provider-resolution-review-v1"

RESOLUTION_ASSESSMENT_FIELDS = (
    "action_id", "provider", "reference_name", "verified_evidence_ref", "outcome",
    "assessed_by_role", "assessed_at_utc", "assessment_source_ref", "assessment_sha256",
    "facts_established", "questions_addressed",
)

# Structured, action-specific fact codes (never free text). Only these
# facts may be established by these actions; a fact from another action is
# rejected. Negative facts are recordable (they let a branch be closed)
# but never unlock anything.
ACTION_FACT_CODES: dict[str, frozenset[str]] = {
    "MIS-01": frozenset({
        "MISTRAL_API_TRAINING_OPTOUT_APPLICABLE", "MISTRAL_API_TRAINING_OPTOUT_NOT_APPLICABLE",
        "MISTRAL_ZDR_APPLICABLE", "MISTRAL_ZDR_NOT_APPLICABLE",
        "MISTRAL_AUTOMATED_EVALUATION_PERMITTED", "MISTRAL_AUTOMATED_EVALUATION_NOT_PERMITTED",
    }),
    "DSK-01": frozenset({
        "DEEPSEEK_API_OPTOUT_APPLICABLE", "DEEPSEEK_API_OPTOUT_NOT_APPLICABLE",
        "DEEPSEEK_API_OPTOUT_PROSPECTIVE", "DEEPSEEK_API_OPTOUT_NOT_PROSPECTIVE",
    }),
    "DSK-02": frozenset({"DEEPSEEK_ACCOUNT_SETTING_PRESENT", "DEEPSEEK_ACCOUNT_SETTING_ABSENT"}),
    "GLM-01": frozenset({
        "GLM_NO_TRAINING_CONTROL_AVAILABLE", "GLM_NO_TRAINING_CONTROL_NOT_AVAILABLE",
        "GLM_NO_TRAINING_CONTROL_APPLIES_TO_GLM_5_3", "GLM_NO_TRAINING_CONTROL_DOES_NOT_APPLY_TO_GLM_5_3",
    }),
    "MNX-01": frozenset({
        "MINIMAX_COMMERCIAL_USE_APPLIES", "MINIMAX_COMMERCIAL_USE_DOES_NOT_APPLY",
        "MINIMAX_COMMERCIAL_USE_STILL_AMBIGUOUS",
    }),
    "KMI-01": frozenset({
        "KIMI_ACCEPTABLE_ENTERPRISE_NO_TRAINING_PATH_AVAILABLE",
        "KIMI_ENTERPRISE_NO_TRAINING_PATH_NOT_AVAILABLE",
    }),
}

# The provider questions that must have been answered for a fact to be
# established (§16) -- e.g. MNX-Q2 alone can never establish a Commercial
# Use conclusion, and an unrelated Kimi pricing question can never
# establish an acceptable enterprise path. Facts whose evidence is a
# read-only account capture (DSK-02) need no question.
FACT_REQUIRED_QUESTIONS: dict[str, frozenset[str]] = {
    "MISTRAL_API_TRAINING_OPTOUT_APPLICABLE": frozenset({"MIS-Q2", "MIS-Q3", "MIS-Q4"}),
    "MISTRAL_API_TRAINING_OPTOUT_NOT_APPLICABLE": frozenset({"MIS-Q2"}),
    "MISTRAL_ZDR_APPLICABLE": frozenset({"MIS-Q5"}),
    "MISTRAL_ZDR_NOT_APPLICABLE": frozenset({"MIS-Q5"}),
    "MISTRAL_AUTOMATED_EVALUATION_PERMITTED": frozenset({"MIS-Q1"}),
    "MISTRAL_AUTOMATED_EVALUATION_NOT_PERMITTED": frozenset({"MIS-Q1"}),
    "DEEPSEEK_API_OPTOUT_APPLICABLE": frozenset({"DSK-Q1"}),
    "DEEPSEEK_API_OPTOUT_NOT_APPLICABLE": frozenset({"DSK-Q1"}),
    "DEEPSEEK_API_OPTOUT_PROSPECTIVE": frozenset({"DSK-Q2"}),
    "DEEPSEEK_API_OPTOUT_NOT_PROSPECTIVE": frozenset({"DSK-Q2"}),
    "DEEPSEEK_ACCOUNT_SETTING_PRESENT": frozenset(),
    "DEEPSEEK_ACCOUNT_SETTING_ABSENT": frozenset(),
    "GLM_NO_TRAINING_CONTROL_AVAILABLE": frozenset({"GLM-Q6"}),
    "GLM_NO_TRAINING_CONTROL_NOT_AVAILABLE": frozenset({"GLM-Q6"}),
    "GLM_NO_TRAINING_CONTROL_APPLIES_TO_GLM_5_3": frozenset({"GLM-Q7"}),
    "GLM_NO_TRAINING_CONTROL_DOES_NOT_APPLY_TO_GLM_5_3": frozenset({"GLM-Q7"}),
    "MINIMAX_COMMERCIAL_USE_APPLIES": frozenset({"MNX-Q1"}),
    "MINIMAX_COMMERCIAL_USE_DOES_NOT_APPLY": frozenset({"MNX-Q1"}),
    "MINIMAX_COMMERCIAL_USE_STILL_AMBIGUOUS": frozenset({"MNX-Q1"}),
    "KIMI_ACCEPTABLE_ENTERPRISE_NO_TRAINING_PATH_AVAILABLE": frozenset({"KMI-Q1", "KMI-Q2", "KMI-Q3", "KMI-Q4", "KMI-Q5"}),
    "KIMI_ENTERPRISE_NO_TRAINING_PATH_NOT_AVAILABLE": frozenset({"KMI-Q1"}),
}

# At most one fact from each group may be established (a positive and its
# negative are contradictory; the three MiniMax conclusions are
# mutually exclusive).
CONTRADICTORY_FACT_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"MISTRAL_API_TRAINING_OPTOUT_APPLICABLE", "MISTRAL_API_TRAINING_OPTOUT_NOT_APPLICABLE"}),
    frozenset({"MISTRAL_ZDR_APPLICABLE", "MISTRAL_ZDR_NOT_APPLICABLE"}),
    frozenset({"MISTRAL_AUTOMATED_EVALUATION_PERMITTED", "MISTRAL_AUTOMATED_EVALUATION_NOT_PERMITTED"}),
    frozenset({"DEEPSEEK_API_OPTOUT_APPLICABLE", "DEEPSEEK_API_OPTOUT_NOT_APPLICABLE"}),
    frozenset({"DEEPSEEK_API_OPTOUT_PROSPECTIVE", "DEEPSEEK_API_OPTOUT_NOT_PROSPECTIVE"}),
    frozenset({"DEEPSEEK_ACCOUNT_SETTING_PRESENT", "DEEPSEEK_ACCOUNT_SETTING_ABSENT"}),
    frozenset({"GLM_NO_TRAINING_CONTROL_AVAILABLE", "GLM_NO_TRAINING_CONTROL_NOT_AVAILABLE"}),
    frozenset({"GLM_NO_TRAINING_CONTROL_APPLIES_TO_GLM_5_3", "GLM_NO_TRAINING_CONTROL_DOES_NOT_APPLY_TO_GLM_5_3"}),
    frozenset({"MINIMAX_COMMERCIAL_USE_APPLIES", "MINIMAX_COMMERCIAL_USE_DOES_NOT_APPLY", "MINIMAX_COMMERCIAL_USE_STILL_AMBIGUOUS"}),
    frozenset({"KIMI_ACCEPTABLE_ENTERPRISE_NO_TRAINING_PATH_AVAILABLE", "KIMI_ENTERPRISE_NO_TRAINING_PATH_NOT_AVAILABLE"}),
)

# Canonical dependency requirement policy (§9): for each dependent action,
# for each dependency, the positive facts that must be established
# (`required_facts`) and the definitive-negative facts that close the
# branch (`closing_facts`). MNX-02 unlocks ONLY on COMMERCIAL_USE_APPLIES
# -- DOES_NOT_APPLY never satisfies it (it closes the branch); a separate
# future exact owner election of the conservative path is deliberately
# NOT implemented here, so there is no bypass.
DEPENDENCY_REQUIREMENTS: dict[str, dict[str, dict[str, frozenset[str]]]] = {
    "MIS-02": {"MIS-01": {
        "required_facts": frozenset({"MISTRAL_API_TRAINING_OPTOUT_APPLICABLE"}),
        "closing_facts": frozenset({"MISTRAL_API_TRAINING_OPTOUT_NOT_APPLICABLE"}),
    }},
    "MIS-03": {"MIS-01": {
        "required_facts": frozenset({"MISTRAL_ZDR_APPLICABLE"}),
        "closing_facts": frozenset({"MISTRAL_ZDR_NOT_APPLICABLE"}),
    }},
    "DSK-03": {
        "DSK-01": {
            "required_facts": frozenset({"DEEPSEEK_API_OPTOUT_APPLICABLE", "DEEPSEEK_API_OPTOUT_PROSPECTIVE"}),
            "closing_facts": frozenset({"DEEPSEEK_API_OPTOUT_NOT_APPLICABLE", "DEEPSEEK_API_OPTOUT_NOT_PROSPECTIVE"}),
        },
        "DSK-02": {
            "required_facts": frozenset({"DEEPSEEK_ACCOUNT_SETTING_PRESENT"}),
            "closing_facts": frozenset({"DEEPSEEK_ACCOUNT_SETTING_ABSENT"}),
        },
    },
    "GLM-02": {"GLM-01": {
        "required_facts": frozenset({"GLM_NO_TRAINING_CONTROL_AVAILABLE", "GLM_NO_TRAINING_CONTROL_APPLIES_TO_GLM_5_3"}),
        "closing_facts": frozenset({"GLM_NO_TRAINING_CONTROL_NOT_AVAILABLE", "GLM_NO_TRAINING_CONTROL_DOES_NOT_APPLY_TO_GLM_5_3"}),
    }},
    "MNX-02": {"MNX-01": {
        "required_facts": frozenset({"MINIMAX_COMMERCIAL_USE_APPLIES"}),
        "closing_facts": frozenset({"MINIMAX_COMMERCIAL_USE_DOES_NOT_APPLY"}),
    }},
    "KMI-02": {"KMI-01": {
        "required_facts": frozenset({"KIMI_ACCEPTABLE_ENTERPRISE_NO_TRAINING_PATH_AVAILABLE"}),
        "closing_facts": frozenset({"KIMI_ENTERPRISE_NO_TRAINING_PATH_NOT_AVAILABLE"}),
    }},
}

# Facts that, if established, unlock at least one dependent of the action.
UNLOCK_FACTS: dict[str, frozenset[str]] = {}
for _dependent, _deps in DEPENDENCY_REQUIREMENTS.items():
    for _dep_id, _req in _deps.items():
        UNLOCK_FACTS[_dep_id] = UNLOCK_FACTS.get(_dep_id, frozenset()) | _req["required_facts"]

# Import-time consistency of the policy tables: a drifted table fails
# loudly rather than silently mis-gating an action.
_all_facts = frozenset().union(*ACTION_FACT_CODES.values())
if set(FACT_REQUIRED_QUESTIONS) != set(_all_facts):
    raise ProviderResolutionError("FACT_REQUIRED_QUESTIONS does not cover exactly the defined fact codes")
for _group in CONTRADICTORY_FACT_GROUPS:
    if not _group <= _all_facts:
        raise ProviderResolutionError("CONTRADICTORY_FACT_GROUPS references an undefined fact code")
for _dependent, _deps in DEPENDENCY_REQUIREMENTS.items():
    for _dep_id, _req in _deps.items():
        if not (_req["required_facts"] | _req["closing_facts"]) <= ACTION_FACT_CODES.get(_dep_id, frozenset()):
            raise ProviderResolutionError(f"DEPENDENCY_REQUIREMENTS[{_dependent}][{_dep_id}] uses facts the dependency cannot establish")
        if _req["required_facts"] & _req["closing_facts"]:
            raise ProviderResolutionError(f"DEPENDENCY_REQUIREMENTS[{_dependent}][{_dep_id}] has a fact that both unlocks and closes")


# ── helpers ───────────────────────────────────────────────────────────────


def _is_official_domain(provider: str, domain: str) -> bool:
    domain = str(domain).strip().lower().rstrip(".")
    for official in OFFICIAL_PROVIDER_DOMAINS.get(provider, ()):
        if domain == official or domain.endswith("." + official):
            return True
    return False


def _sha256_of_file(evidence_root: Path, location: str) -> str:
    root = Path(evidence_root).resolve()
    path = (root / location).resolve()
    try:
        path.relative_to(root)
    except ValueError as e:
        raise ProviderResolutionError(f"raw_response_location {location!r} escapes the evidence root") from e
    if not path.is_file():
        raise ProviderResolutionError(f"raw_response_location {location!r} does not exist under the evidence root")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_fields(record: dict, required: tuple[str, ...], label: str) -> None:
    missing = [f for f in required if f not in record]
    if missing:
        raise ProviderResolutionError(f"{label} missing required field(s): {missing}")


def _require_exact_keys(record, required: tuple[str, ...], label: str) -> None:
    if not isinstance(record, dict):
        raise ProviderResolutionError(f"{label} must be a structured record, got {type(record).__name__}")
    _require_fields(record, required, label)
    unknown = sorted(set(record) - set(required))
    if unknown:
        raise ProviderResolutionError(f"{label} has unexpected field(s) {unknown}; only {list(required)} are allowed")


def _parse_utc(value, label: str) -> datetime:
    if not isinstance(value, str) or not _UTC_RE.match(value):
        raise ProviderResolutionError(f"{label} must be a UTC ISO-8601 timestamp ending in 'Z', got {value!r}")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as e:
        raise ProviderResolutionError(f"{label} is not a valid timestamp: {value!r}") from e


def _nonempty_ref(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderResolutionError(f"{label} must be a non-empty string")
    if value.strip().upper() in _WILDCARD_TOKENS or "*" in value:
        raise ProviderResolutionError(f"{label} must not be a wildcard/placeholder, got {value!r}")
    return value


def canonical_provider_for(reference_name: str) -> str:
    try:
        return REFERENCE_PROVIDER[reference_name]
    except KeyError as e:
        raise ProviderResolutionError(f"unregistered reference {reference_name!r}") from e


def _check_provider_binding(provider, reference_name, label: str) -> None:
    """The provider must be the canonical owner of the reference -- a
    valid domain for some OTHER provider never substitutes (§4/§5)."""
    canonical = canonical_provider_for(reference_name)
    if provider != canonical:
        raise ProviderResolutionError(
            f"{label}: provider {provider!r} does not own reference {reference_name!r} (canonical provider is {canonical!r})"
        )


def _check_question_families(provider: str, question_ids, label: str) -> None:
    prefix = PROVIDER_QUESTION_PREFIX[provider]
    pattern = re.compile(re.escape(prefix) + r"\d+[A-Za-z0-9._-]*$")
    for qid in question_ids:
        if not isinstance(qid, str) or not pattern.match(qid):
            raise ProviderResolutionError(
                f"{label}: question id {qid!r} is not in {provider!r}'s documented family {prefix}*"
            )


# ── owner authorization (Phase 21B.4.19.1 §7-§9) ──────────────────────────


def validate_owner_authorization(record, *, action_id: str) -> None:
    """A structured OWNER authorization for exactly one action. Rejects an
    arbitrary non-empty dict, a wrong/wildcard action id, a non-OWNER
    role, a non-AUTHORIZED decision, any scope other than
    EXACT_ACTION_ONLY (so no provider-wide, phase-wide or
    dependency-implying grant), an empty source ref, and a malformed
    timestamp. One authorization authorizes one action -- never its
    dependencies or follow-ups."""
    _require_exact_keys(record, OWNER_AUTHORIZATION_FIELDS, f"owner authorization for {action_id!r}")
    if record["action_id"] != action_id:
        raise ProviderResolutionError(
            f"owner authorization is for action_id={record['action_id']!r}, not {action_id!r} -- one authorization "
            "authorizes exactly one action"
        )
    if str(record["action_id"]).strip().upper() in _WILDCARD_TOKENS or "*" in str(record["action_id"]):
        raise ProviderResolutionError("wildcard action_id is not an authorization")
    if record["decision"] != "AUTHORIZED":
        raise ProviderResolutionError(f"owner authorization decision must be AUTHORIZED, got {record['decision']!r}")
    if record["authorized_by_role"] != "OWNER":
        raise ProviderResolutionError(f"authorization must come from role OWNER, got {record['authorized_by_role']!r}")
    if record["scope"] != AUTHORIZATION_SCOPE_EXACT:
        raise ProviderResolutionError(
            f"authorization scope must be {AUTHORIZATION_SCOPE_EXACT!r} (no wildcard, provider-wide or phase-wide "
            f"authorization), got {record['scope']!r}"
        )
    if record["authorization_source_kind"] not in AUTHORIZATION_SOURCE_KINDS:
        raise ProviderResolutionError(
            f"authorization_source_kind must be one of {AUTHORIZATION_SOURCE_KINDS}, got {record['authorization_source_kind']!r}"
        )
    _nonempty_ref(record["authorization_source_ref"], "authorization_source_ref")
    _parse_utc(record["authorized_at_utc"], "authorized_at_utc")


# ── execution evidence (Phase 21B.4.19.1 §13/§14) ─────────────────────────


def validate_execution_evidence(record, *, action: dict) -> None:
    """Structured evidence that THIS action was executed: it must name the
    action's own id, type, provider and reference, a real source ref, and
    a valid UTC timestamp not earlier than the recorded authorization."""
    aid = action["action_id"]
    _require_exact_keys(record, EXECUTION_EVIDENCE_FIELDS, f"execution evidence for {aid!r}")
    for field, expected in (
        ("action_id", aid),
        ("action_type", action["action_type"]),
        ("provider", action["provider"]),
        ("reference_name", action["reference_name"]),
    ):
        if record[field] != expected:
            raise ProviderResolutionError(
                f"execution evidence {field}={record[field]!r} does not match action {aid!r} ({expected!r})"
            )
    _nonempty_ref(record["source_ref"], "execution evidence source_ref")
    executed_at = _parse_utc(record["executed_at_utc"], "executed_at_utc")
    authorization = action.get("authorization_evidence")
    if authorization:
        if executed_at < _parse_utc(authorization["authorized_at_utc"], "authorized_at_utc"):
            raise ProviderResolutionError("execution evidence predates the owner authorization")


def _validate_received_record(record, action: dict) -> None:
    """The marker that a provider/console reply arrived (still
    UNVERIFIED): it must be bound to this action's provider/reference and
    point at a persisted source. It proves nothing yet."""
    label = f"received record for {action['action_id']!r}"
    if not isinstance(record, dict) or not record:
        raise ProviderResolutionError(f"{label} must be a structured record")
    if record.get("provider") != action["provider"] or record.get("reference_name") != action["reference_name"]:
        raise ProviderResolutionError(f"{label} is not bound to provider/reference {action['provider']!r}/{action['reference_name']!r}")
    location = record.get("raw_response_location") or record.get("screenshot_evidence_reference")
    _nonempty_ref(location, f"{label} persisted source location")
    _parse_utc(record.get("received_at_utc") or record.get("effective_timestamp_utc"), f"{label} timestamp")
    if "question_ids_answered" in record:
        _check_question_families(action["provider"], record["question_ids_answered"], label)


# ── verified evidence references (Phase 21B.4.19.1 §15-§18) ───────────────


def validate_verified_evidence_ref(ref, *, action: dict, evidence_root: Path | None = None) -> None:
    """Shape + binding check of a canonical verified-evidence reference.
    With `evidence_root` the persisted source is re-read and its SHA-256
    recomputed, so a RESOLVED action's evidence is re-proved, not
    remembered. Global (provider=ALL) actions have no provider-bound
    evidence path in this phase and can never hold one."""
    aid = action["action_id"]
    if not isinstance(ref, dict):
        raise ProviderResolutionError(f"verified_evidence_ref for {aid!r} must be a structured reference, not {type(ref).__name__}")
    evidence_type = ref.get("evidence_type")
    if evidence_type not in VERIFIED_REF_FIELDS:
        raise ProviderResolutionError(f"verified_evidence_ref for {aid!r} has unrecognized evidence_type={evidence_type!r}")
    _require_exact_keys(ref, VERIFIED_REF_FIELDS[evidence_type], f"verified_evidence_ref for {aid!r}")
    if action["provider"] == "ALL" or action["reference_name"] == "ALL":
        raise ProviderResolutionError(f"global action {aid!r} has no provider-bound verified-evidence path")
    if ref["provider"] != action["provider"] or ref["reference_name"] != action["reference_name"]:
        raise ProviderResolutionError(
            f"verified_evidence_ref for {aid!r} is bound to {ref['provider']!r}/{ref['reference_name']!r}, "
            f"not the action's {action['provider']!r}/{action['reference_name']!r}"
        )
    _check_provider_binding(ref["provider"], ref["reference_name"], f"verified_evidence_ref for {aid!r}")
    if evidence_type not in _ALLOWED_EVIDENCE_TYPES_BY_ACTION[action["action_type"]]:
        raise ProviderResolutionError(f"{evidence_type} evidence cannot close a {action['action_type']} action")
    if not _HEX64_RE.match(str(ref["sha256"])):
        raise ProviderResolutionError(f"verified_evidence_ref for {aid!r} requires a 64-hex sha256")
    _nonempty_ref(ref["source_location"], "verified_evidence_ref source_location")
    if evidence_root is not None and _sha256_of_file(evidence_root, ref["source_location"]) != ref["sha256"]:
        raise ProviderResolutionError(f"verified_evidence_ref for {aid!r}: persisted source no longer matches its sha256")


def build_verified_provider_evidence_ref(record: dict, *, evidence_root: Path) -> dict:
    """Derive the canonical ref FROM a record that has actually passed
    `validate_provider_response()` as VERIFIED. Callers never hand-author
    a trusted ref."""
    validate_provider_response(record, evidence_root=evidence_root)
    if record["review_status"] != "VERIFIED":
        raise ProviderResolutionError("only a VERIFIED provider response can produce a verified evidence ref")
    return {
        "evidence_type": "PROVIDER_RESPONSE",
        "provider": record["provider"],
        "reference_name": record["reference_name"],
        "source_location": record["raw_response_location"],
        "sha256": record["sha256"],
        "message_id": record["message_id"],
        "evidence_tier": record["evidence_tier"],
        "received_at_utc": record["received_at_utc"],
    }


def build_verified_account_setting_evidence_ref(record: dict, *, evidence_root: Path) -> dict:
    validate_account_setting_evidence(record, evidence_root=evidence_root)
    return {
        "evidence_type": "ACCOUNT_SETTING",
        "provider": record["provider"],
        "reference_name": record["reference_name"],
        "source_location": record["screenshot_evidence_reference"],
        "sha256": record["sha256"],
        "setting_name": record["setting_name"],
        "effective_timestamp_utc": record["effective_timestamp_utc"],
    }


def _derive_verified_ref(record, evidence_root: Path) -> dict:
    if not isinstance(record, dict):
        raise ProviderResolutionError("verified evidence must be supplied as the original evidence record, not a string or reference")
    if "screenshot_evidence_reference" in record:
        return build_verified_account_setting_evidence_ref(record, evidence_root=evidence_root)
    return build_verified_provider_evidence_ref(record, evidence_root=evidence_root)


# ── resolution assessment (Phase 21B.4.19.2 §5-§7/§14/§16) ────────────────


def review_record_bytes(
    *, action_id: str, provider: str, reference_name: str, outcome: str, facts_established, questions_addressed,
    verified_evidence_ref: dict, assessed_by_role: str, assessed_at_utc: str,
) -> bytes:
    """The canonical bytes of the durable review record. The record lives
    on disk under the evidence root at `assessment_source_ref`; its
    SHA-256 is `assessment_sha256`. Deterministic, so the assessment and
    the persisted file can be cross-checked byte for byte."""
    payload = {
        "schema": REVIEW_RECORD_SCHEMA,
        "action_id": action_id,
        "provider": provider,
        "reference_name": reference_name,
        "outcome": outcome,
        "facts_established": sorted(facts_established),
        "questions_addressed": sorted(questions_addressed),
        "verified_evidence_sha256": verified_evidence_ref["sha256"],
        "verified_evidence_source_location": verified_evidence_ref["source_location"],
        "assessed_by_role": assessed_by_role,
        "assessed_at_utc": assessed_at_utc,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _bytes_of_file(evidence_root: Path, location: str) -> bytes:
    root = Path(evidence_root).resolve()
    path = (root / location).resolve()
    try:
        path.relative_to(root)
    except ValueError as e:
        raise ProviderResolutionError(f"assessment_source_ref {location!r} escapes the evidence root") from e
    if not path.is_file():
        raise ProviderResolutionError(f"assessment_source_ref {location!r} does not exist under the evidence root")
    return path.read_bytes()


def _validate_fact_set(action_id: str, facts, label: str) -> None:
    if not isinstance(facts, list) or any(not isinstance(f, str) for f in facts):
        raise ProviderResolutionError(f"{label}: facts_established must be a list of structured fact codes")
    if facts != sorted(set(facts)):
        raise ProviderResolutionError(f"{label}: facts_established must be a sorted, duplicate-free list")
    allowed = ACTION_FACT_CODES.get(action_id, frozenset())
    unknown = [f for f in facts if f not in allowed]
    if unknown:
        raise ProviderResolutionError(f"{label}: fact code(s) {unknown} are not defined for action {action_id!r}")
    for group in CONTRADICTORY_FACT_GROUPS:
        clash = sorted(group & set(facts))
        if len(clash) > 1:
            raise ProviderResolutionError(f"{label}: contradictory/mutually-exclusive facts {clash}")


def _check_question_coverage(facts, questions, label: str) -> None:
    for fact in facts:
        missing = FACT_REQUIRED_QUESTIONS[fact] - set(questions)
        if missing:
            raise ProviderResolutionError(
                f"{label}: fact {fact!r} requires question(s) {sorted(missing)} to have been answered"
            )


def _check_outcome_consistency(action_id: str, outcome: str, facts, label: str) -> None:
    unlock = UNLOCK_FACTS.get(action_id, frozenset())
    if outcome == "PREREQUISITE_SATISFIED":
        if not (unlock & set(facts)):
            raise ProviderResolutionError(f"{label}: PREREQUISITE_SATISFIED requires at least one dependency-unlocking positive fact")
    elif outcome == "PREREQUISITE_NOT_SATISFIED":
        if unlock & set(facts):
            raise ProviderResolutionError(f"{label}: PREREQUISITE_NOT_SATISFIED may not carry dependency-unlocking facts")
    elif outcome == "NO_FOLLOWUP_REQUIRED":
        if unlock:
            raise ProviderResolutionError(f"{label}: action has downstream dependents; NO_FOLLOWUP_REQUIRED is not valid")
        if facts:
            raise ProviderResolutionError(f"{label}: NO_FOLLOWUP_REQUIRED must carry no facts")


def validate_resolution_assessment(assessment, *, action: dict, evidence_root: Path | None = None) -> None:
    """Structural + binding validation of an assessment, and -- with
    `evidence_root` -- byte-level re-verification of the persisted review
    record. Proves: exact action/provider/reference binding, binding to the
    action's own verified-evidence ref, valid outcome/role/timestamp, only
    facts defined for this action (no contradictions), question-family and
    fact-to-question coverage, and that the durable review record's bytes
    hash to `assessment_sha256` and match the assessment exactly. It does
    not (and cannot) judge the semantic correctness of the reviewer's
    reading of the provider's prose."""
    aid = action["action_id"]
    label = f"resolution assessment for {aid!r}"
    _require_exact_keys(assessment, RESOLUTION_ASSESSMENT_FIELDS, label)
    if action["provider"] == "ALL" or action["reference_name"] == "ALL":
        raise ProviderResolutionError(f"global action {aid!r} has no provider-bound resolution assessment")
    if assessment["action_id"] != aid:
        raise ProviderResolutionError(f"{label} is for action_id={assessment['action_id']!r}")
    if assessment["provider"] != action["provider"] or assessment["reference_name"] != action["reference_name"]:
        raise ProviderResolutionError(
            f"{label} is bound to {assessment['provider']!r}/{assessment['reference_name']!r}, "
            f"not {action['provider']!r}/{action['reference_name']!r}"
        )
    _check_provider_binding(assessment["provider"], assessment["reference_name"], label)
    if not action.get("verified_evidence_ref") or assessment["verified_evidence_ref"] != action["verified_evidence_ref"]:
        raise ProviderResolutionError(f"{label} does not reference the action's own verified evidence")
    if assessment["outcome"] not in _ASSESSABLE_OUTCOMES:
        raise ProviderResolutionError(f"{label} has invalid outcome {assessment['outcome']!r}")
    if assessment["assessed_by_role"] != ASSESSOR_ROLE:
        raise ProviderResolutionError(f"{label} must be assessed by role {ASSESSOR_ROLE!r}, got {assessment['assessed_by_role']!r}")
    _parse_utc(assessment["assessed_at_utc"], "assessed_at_utc")
    _nonempty_ref(assessment["assessment_source_ref"], "assessment_source_ref (durable review record)")
    if not _HEX64_RE.match(str(assessment["assessment_sha256"])):
        raise ProviderResolutionError(f"{label} requires a 64-hex assessment_sha256 of the review record")
    _validate_fact_set(aid, assessment["facts_established"], label)
    questions = assessment["questions_addressed"]
    if not isinstance(questions, list) or questions != sorted(set(questions)):
        raise ProviderResolutionError(f"{label}: questions_addressed must be a sorted, duplicate-free list")
    _check_question_families(action["provider"], questions, label)
    _check_question_coverage(assessment["facts_established"], questions, label)
    _check_outcome_consistency(aid, assessment["outcome"], assessment["facts_established"], label)
    if evidence_root is not None:
        data = _bytes_of_file(evidence_root, assessment["assessment_source_ref"])
        if hashlib.sha256(data).hexdigest() != assessment["assessment_sha256"]:
            raise ProviderResolutionError(f"{label}: review record bytes do not match assessment_sha256")
        expected = review_record_bytes(
            action_id=aid, provider=assessment["provider"], reference_name=assessment["reference_name"],
            outcome=assessment["outcome"], facts_established=assessment["facts_established"],
            questions_addressed=questions, verified_evidence_ref=assessment["verified_evidence_ref"],
            assessed_by_role=assessment["assessed_by_role"], assessed_at_utc=assessment["assessed_at_utc"],
        )
        if data != expected:
            raise ProviderResolutionError(f"{label}: persisted review record does not match the assessment's facts/outcome")


def assess_action_resolution(
    action: dict,
    *,
    outcome: str,
    facts_established,
    questions_addressed=(),
    assessed_at_utc: str,
    assessment_source_ref: str,
    evidence_root: Path,
    provider_evidence_record: dict | None = None,
    assessed_by_role: str = ASSESSOR_ROLE,
) -> dict:
    """Attach a durable resolution assessment to a RESOLVED action and
    return a NEW action (the input is never mutated). Fail-closed:

    * the action must be RESOLVED with verified evidence that still
      re-proves against `evidence_root`, and must not already be assessed;
    * facts must be defined for this action, sorted/duplicate-free, and
      non-contradictory; every fact's required questions must be among
      `questions_addressed`, which must be in the provider's family;
    * for provider-response evidence the ORIGINAL record must be supplied,
      is re-validated, must rebuild the action's own verified ref, and must
      actually have answered every claimed question -- coverage is derived
      from validated evidence, not reviewer assertion;
    * the persisted review record at `assessment_source_ref` must equal the
      canonical bytes for this assessment (its SHA-256 is recorded).
    """
    validate_action(action, evidence_root=evidence_root)
    aid = action["action_id"]
    if action["state"] != DEPENDENCY_COMPLETE_STATE:
        raise ProviderResolutionError(f"action {aid!r} must be RESOLVED to be assessed, not {action['state']!r}")
    if action["resolution_assessment"] is not None:
        raise ProviderResolutionError(f"action {aid!r} already carries a resolution assessment (immutable)")
    facts = sorted(set(facts_established)) if isinstance(facts_established, (list, tuple, set, frozenset)) else facts_established
    questions = sorted(set(questions_addressed))
    ref = action["verified_evidence_ref"]
    if ref["evidence_type"] == "PROVIDER_RESPONSE":
        needs_record = bool(facts) or bool(questions)
        if needs_record:
            if not isinstance(provider_evidence_record, dict):
                raise ProviderResolutionError("the original provider evidence record is required to assess question/fact coverage")
            if build_verified_provider_evidence_ref(provider_evidence_record, evidence_root=evidence_root) != ref:
                raise ProviderResolutionError("provider_evidence_record does not rebuild the action's verified evidence ref")
            unanswered = sorted(set(questions) - set(provider_evidence_record["question_ids_answered"]))
            if unanswered:
                raise ProviderResolutionError(f"the evidence never answered claimed question(s) {unanswered}")
    elif questions:
        raise ProviderResolutionError("account-setting evidence answers no provider questions")
    # cheap semantic checks first, so a missing review file never masks them
    label = f"resolution assessment for {aid!r}"
    if outcome not in _ASSESSABLE_OUTCOMES:
        raise ProviderResolutionError(f"{label} has invalid outcome {outcome!r}")
    _validate_fact_set(aid, facts, label)
    _check_question_families(action["provider"], questions, label)
    _check_question_coverage(facts, questions, label)
    _check_outcome_consistency(aid, outcome, facts, label)
    data = _bytes_of_file(evidence_root, assessment_source_ref)
    assessment = {
        "action_id": aid,
        "provider": action["provider"],
        "reference_name": action["reference_name"],
        "verified_evidence_ref": deepcopy(ref),
        "outcome": outcome,
        "assessed_by_role": assessed_by_role,
        "assessed_at_utc": assessed_at_utc,
        "assessment_source_ref": assessment_source_ref,
        "assessment_sha256": hashlib.sha256(data).hexdigest(),
        "facts_established": facts,
        "questions_addressed": questions,
    }
    validate_resolution_assessment(assessment, action=action, evidence_root=evidence_root)
    updated = deepcopy(action)
    updated["resolution_assessment"] = assessment
    updated["resolution_outcome"] = outcome
    validate_action(updated, evidence_root=evidence_root)
    return updated


def _require_prerequisite_satisfied(dependent_id: str, dep_id: str, dep: dict, evidence_root) -> None:
    """A dependency satisfies a dependent only when its RESOLVED action
    carries a valid assessment with outcome PREREQUISITE_SATISFIED and
    every fact demanded for THIS dependent (§10). RESOLVED alone never
    does."""
    req = DEPENDENCY_REQUIREMENTS.get(dependent_id, {}).get(dep_id)
    if req is None:
        raise ProviderResolutionError(f"no dependency requirement policy for {dependent_id!r} on {dep_id!r}")
    assessment = dep.get("resolution_assessment")
    if not assessment:
        raise ProviderResolutionError(
            f"dependency {dep_id!r} of {dependent_id!r} is RESOLVED but has no resolution assessment "
            "(RESOLVED != PREREQUISITE_SATISFIED)"
        )
    validate_resolution_assessment(assessment, action=dep, evidence_root=evidence_root)
    if dep.get("resolution_outcome") != assessment["outcome"]:
        raise ProviderResolutionError(f"dependency {dep_id!r} resolution_outcome disagrees with its assessment")
    if assessment["outcome"] != "PREREQUISITE_SATISFIED":
        raise ProviderResolutionError(
            f"dependency {dep_id!r} of {dependent_id!r} has outcome {assessment['outcome']!r}, which does not allow follow-up"
        )
    missing = sorted(req["required_facts"] - set(assessment["facts_established"]))
    if missing:
        raise ProviderResolutionError(
            f"dependency {dep_id!r} did not establish required fact(s) {missing} for {dependent_id!r}"
        )


def close_unavailable_branch(action: dict, *, dependency_actions: dict, evidence_root: Path) -> dict:
    """When a dependency is RESOLVED with a definitive-negative fact for
    this dependent (its `closing_facts`), the conditional action is
    permanently unavailable: it moves to NOT_REQUIRED and can never be
    executed. Ambiguous or partial outcomes do NOT close a branch (the
    action simply stays ineligible). The upstream action is never
    re-opened -- the provider question was answered."""
    validate_action(action, evidence_root=evidence_root)
    aid = action["action_id"]
    reqs = DEPENDENCY_REQUIREMENTS.get(aid)
    if not reqs:
        raise ProviderResolutionError(f"action {aid!r} is not a conditional dependent action")
    if action["state"] != "PREPARED":
        raise ProviderResolutionError(f"only a PREPARED conditional action can be closed, {aid!r} is {action['state']!r}")
    if not isinstance(dependency_actions, dict) or not dependency_actions:
        raise ProviderResolutionError(f"closing {aid!r} requires the dependency_actions context")
    for dep_id, req in reqs.items():
        dep = dependency_actions.get(dep_id)
        if not dep:
            continue
        validate_action(dep, evidence_root=evidence_root)
        if dep["state"] != DEPENDENCY_COMPLETE_STATE or not dep["resolution_assessment"]:
            continue
        validate_resolution_assessment(dep["resolution_assessment"], action=dep, evidence_root=evidence_root)
        if req["closing_facts"] & set(dep["resolution_assessment"]["facts_established"]):
            return advance_action_state(action, "NOT_REQUIRED")
    raise ProviderResolutionError(f"no dependency has definitively closed the branch for {aid!r}")


# ── action queue validation (§10/§27) ─────────────────────────────────────


def validate_action(action: dict, *, evidence_root: Path | None = None) -> None:
    _require_fields(action, ACTION_REQUIRED_FIELDS, f"action {action.get('action_id', '<unnamed>')!r}")
    aid = action["action_id"]
    if action["action_type"] not in EXTERNAL_ACTION_TYPES:
        raise ProviderResolutionError(f"action {aid!r} has unrecognized action_type={action['action_type']!r}")

    # Provider/reference binding (§6): specific actions use the canonical
    # provider; only the documented global actions may use ALL/ALL.
    if action["reference_name"] == "ALL" or action["provider"] == "ALL":
        if not (
            action["reference_name"] == "ALL" and action["provider"] == "ALL"
            and aid in GLOBAL_ACTION_IDS and action["action_type"] in GLOBAL_ACTION_TYPES
        ):
            raise ProviderResolutionError(
                f"action {aid!r} uses ALL for provider/reference but is not a documented global action "
                f"({sorted(GLOBAL_ACTION_IDS)})"
            )
    else:
        if action["reference_name"] not in EXPECTED_REFERENCE_NAMES:
            raise ProviderResolutionError(f"action {aid!r} targets unregistered reference {action['reference_name']!r}")
        _check_provider_binding(action["provider"], action["reference_name"], f"action {aid!r}")
        if aid in GLOBAL_ACTION_IDS or action["action_type"] in GLOBAL_ACTION_TYPES:
            raise ProviderResolutionError(f"global action/type {aid!r}/{action['action_type']!r} must use provider=ALL and reference=ALL")

    if action["requires_owner_authorization"] is not True:
        raise ProviderResolutionError(f"action {aid!r} is external/account-mutating and must require owner authorization")
    if action["claude_can_execute"] is not False:
        raise ProviderResolutionError(f"action {aid!r} must never be Claude-executable")
    if action["authorization_status"] not in AUTHORIZATION_STATUSES:
        raise ProviderResolutionError(f"action {aid!r} has unrecognized authorization_status={action['authorization_status']!r}")
    if action["executed_status"] not in EXECUTED_STATUSES:
        raise ProviderResolutionError(f"action {aid!r} has unrecognized executed_status={action['executed_status']!r}")
    if action["state"] not in ACTION_STATES:
        raise ProviderResolutionError(f"action {aid!r} has unrecognized state={action['state']!r}")
    if action["priority"] not in PRIORITIES:
        raise ProviderResolutionError(f"action {aid!r} has unrecognized priority={action['priority']!r}")
    if not isinstance(action["burden"], int) or action["burden"] < 0:
        raise ProviderResolutionError(f"action {aid!r} has invalid burden={action['burden']!r}")
    if not isinstance(action["depends_on"], list):
        raise ProviderResolutionError(f"action {aid!r} depends_on must be a list")
    if aid in action["depends_on"]:
        raise ProviderResolutionError(f"action {aid!r} may not depend on itself")

    # No executed action without prior authorization evidence (§27).
    if action["executed_status"] == "EXECUTED":
        if action["authorization_status"] != "AUTHORIZED" or not action["authorization_evidence"]:
            raise ProviderResolutionError(
                f"action {aid!r} is EXECUTED without AUTHORIZED status and persisted authorization_evidence"
            )
    if action["authorization_status"] == "AUTHORIZED":
        if not action["authorization_evidence"]:
            raise ProviderResolutionError(f"action {aid!r} is AUTHORIZED without authorization_evidence")
        validate_owner_authorization(action["authorization_evidence"], action_id=aid)
    elif action["authorization_evidence"] is not None:
        raise ProviderResolutionError(f"action {aid!r} is NOT_AUTHORIZED but carries authorization_evidence")

    if action["state"] == "AUTHORIZED_NOT_EXECUTED" and action["authorization_status"] != "AUTHORIZED":
        raise ProviderResolutionError(f"action {aid!r} state AUTHORIZED_NOT_EXECUTED requires AUTHORIZED status")
    if action["state"] in _EXECUTION_ASSERTING_STATES and action["executed_status"] != "EXECUTED":
        raise ProviderResolutionError(f"action {aid!r} state {action['state']!r} asserts execution but executed_status is not EXECUTED")

    # Durable execution evidence (§13): present exactly when executed.
    if action["executed_status"] == "EXECUTED":
        if not action["execution_evidence_ref"]:
            raise ProviderResolutionError(f"action {aid!r} is EXECUTED without a persisted execution_evidence_ref")
        validate_execution_evidence(action["execution_evidence_ref"], action=action)
    elif action["execution_evidence_ref"] is not None:
        raise ProviderResolutionError(f"action {aid!r} is NOT_EXECUTED but carries an execution_evidence_ref")

    # A blocker/action may not be RESOLVED or EVIDENCE_VERIFIED without a
    # validated structured verified-evidence reference (§15/§27).
    if action["state"] in _VERIFIED_EVIDENCE_STATES:
        if not action["verified_evidence_ref"]:
            raise ProviderResolutionError(f"action {aid!r} state {action['state']!r} requires a persisted verified_evidence_ref")
        validate_verified_evidence_ref(action["verified_evidence_ref"], action=action, evidence_root=evidence_root)
    elif action["verified_evidence_ref"] is not None and action["state"] != "EXPIRED_OR_STALE":
        raise ProviderResolutionError(f"action {aid!r} carries a verified_evidence_ref outside a verified/expired state")

    # Resolution assessment (Phase 21B.4.19.2): only a RESOLVED action may
    # carry one, and the outcome must agree with the durable assessment.
    assessment = action["resolution_assessment"]
    if assessment is None:
        if action["resolution_outcome"] is not None:
            raise ProviderResolutionError(f"action {aid!r} has a resolution_outcome without a resolution assessment")
    else:
        if action["state"] != DEPENDENCY_COMPLETE_STATE:
            raise ProviderResolutionError(f"action {aid!r} carries a resolution assessment outside RESOLVED")
        validate_resolution_assessment(assessment, action=action, evidence_root=evidence_root)
        if action["resolution_outcome"] != assessment["outcome"]:
            raise ProviderResolutionError(f"action {aid!r} resolution_outcome disagrees with its assessment")


def _assert_acyclic(actions: list[dict]) -> None:
    graph = {a["action_id"]: list(a["depends_on"]) for a in actions}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> None:
        if node in done:
            return
        if node in visiting:
            raise ProviderResolutionError(f"dependency cycle involving action {node!r}")
        visiting.add(node)
        for dep in graph.get(node, []):
            visit(dep)
        visiting.discard(node)
        done.add(node)

    for node in graph:
        visit(node)


def validate_action_queue(queue: dict, *, evidence_root: Path | None = None) -> None:
    for key in ("schema_version", "phase", "actions", "messages_sent", "support_tickets_submitted",
                "account_settings_changed", "commercial_notices_sent"):
        if key not in queue:
            raise ProviderResolutionError(f"action queue missing top-level key {key!r}")
    ids = [a.get("action_id") for a in queue["actions"]]
    if len(ids) != len(set(ids)):
        raise ProviderResolutionError("action queue contains duplicate action_id values")
    for action in queue["actions"]:
        validate_action(action, evidence_root=evidence_root)
    known = {a["action_id"]: a for a in queue["actions"]}
    for action in queue["actions"]:
        for dep in action["depends_on"]:
            if dep not in known:
                raise ProviderResolutionError(f"action {action['action_id']!r} depends on unknown action {dep!r}")
    _assert_acyclic(queue["actions"])
    # Dependency requirement policy must cover exactly the declared graph
    # (Phase 21B.4.19.2): no dependent without a fact policy, no policy
    # without a dependency.
    for action in queue["actions"]:
        policy = DEPENDENCY_REQUIREMENTS.get(action["action_id"])
        if action["depends_on"]:
            if policy is None or set(policy) != set(action["depends_on"]):
                raise ProviderResolutionError(
                    f"action {action['action_id']!r}: depends_on {action['depends_on']} has no matching "
                    "dependency requirement policy"
                )
        elif policy:
            raise ProviderResolutionError(f"action {action['action_id']!r} has a requirement policy but no depends_on")
    # Queue-level consistency: a dependent action that claims to be
    # authorized/executed must have every dependency RESOLVED AND
    # prerequisite-satisfied (RESOLVED alone is not enough).
    for action in queue["actions"]:
        if action["authorization_status"] == "AUTHORIZED" or action["executed_status"] == "EXECUTED":
            for dep in action["depends_on"]:
                if known[dep]["state"] != DEPENDENCY_COMPLETE_STATE:
                    raise ProviderResolutionError(
                        f"action {action['action_id']!r} is authorized/executed but dependency {dep!r} is "
                        f"{known[dep]['state']!r}, not {DEPENDENCY_COMPLETE_STATE}"
                    )
                _require_prerequisite_satisfied(action["action_id"], dep, known[dep], evidence_root)


def build_action_lookup(queue: dict, *, evidence_root: Path | None = None) -> dict[str, dict]:
    """The explicit dependency context for `advance_action_state`: the
    validated queue's actions keyed by id. Returned dicts are copies, so
    there is no shared mutable state."""
    validate_action_queue(queue, evidence_root=evidence_root)
    return {a["action_id"]: deepcopy(a) for a in queue["actions"]}


def assert_queue_fully_unauthorized(queue: dict) -> None:
    """Phase 21B.4.19/.19.1 authorizes NO external action: every action
    must still be NOT_AUTHORIZED / NOT_EXECUTED with no authorization,
    execution or verified evidence, and every phase-level counter must
    be zero."""
    validate_action_queue(queue)
    for counter in ("messages_sent", "support_tickets_submitted", "account_settings_changed", "commercial_notices_sent"):
        if queue[counter] != 0:
            raise ProviderResolutionError(f"queue counter {counter}={queue[counter]!r}, expected 0")
    for action in queue["actions"]:
        if action["authorization_status"] != "NOT_AUTHORIZED" or action["executed_status"] != "NOT_EXECUTED":
            raise ProviderResolutionError(f"action {action['action_id']!r} is not NOT_AUTHORIZED/NOT_EXECUTED")
        for field in ("authorization_evidence", "execution_evidence_ref", "verified_evidence_ref",
                      "resolution_outcome", "resolution_assessment"):
            if action[field] is not None:
                raise ProviderResolutionError(f"action {action['action_id']!r} carries {field} in a no-authorization phase")
        if action["state"] in _EXECUTION_ASSERTING_STATES | {"AUTHORIZED_NOT_EXECUTED"}:
            raise ProviderResolutionError(f"action {action['action_id']!r} is in advanced state {action['state']!r}")


def _require_dependencies_resolved(action: dict, dependency_actions, evidence_root) -> None:
    """Fail-closed dependency gate (§10/§11). The dependency context and
    an evidence root are mandatory whenever an action has dependencies,
    because a dependency only counts once its own verified evidence
    re-proves against persisted bytes."""
    deps = action["depends_on"]
    if not deps:
        return
    if not isinstance(dependency_actions, dict) or not dependency_actions:
        raise ProviderResolutionError(
            f"action {action['action_id']!r} has dependencies {deps}; a dependency_actions context is mandatory"
        )
    if evidence_root is None:
        raise ProviderResolutionError(
            f"action {action['action_id']!r} has dependencies {deps}; an evidence_root is mandatory to re-verify them"
        )
    for dep_id in deps:
        dep = dependency_actions.get(dep_id)
        if dep is None or dep.get("action_id") != dep_id:
            raise ProviderResolutionError(f"dependency {dep_id!r} of {action['action_id']!r} is missing from the dependency context")
        validate_action(dep, evidence_root=evidence_root)
        if dep["state"] != DEPENDENCY_COMPLETE_STATE:
            raise ProviderResolutionError(
                f"action {action['action_id']!r} cannot proceed: dependency {dep_id!r} is {dep['state']!r}, "
                f"not {DEPENDENCY_COMPLETE_STATE}"
            )
        _require_prerequisite_satisfied(action["action_id"], dep_id, dep, evidence_root)


def advance_action_state(
    action: dict,
    new_state: str,
    *,
    authorization_evidence: dict | None = None,
    execution_evidence: dict | None = None,
    received_record: dict | None = None,
    verified_evidence_record: dict | None = None,
    evidence_root: Path | None = None,
    dependency_actions: dict | None = None,
) -> dict:
    """Returns a NEW action dict in `new_state`, or raises. Never mutates
    the input. Each forward step requires its own validated evidence:

    * AUTHORIZED_NOT_EXECUTED: a structured owner authorization for this
      exact action, and every dependency RESOLVED.
    * EXECUTED_AWAITING_PROVIDER: prior authorization, dependencies still
      RESOLVED, and structured execution evidence bound to this action.
    * PROVIDER_REPLIED_UNVERIFIED: a received record bound to this
      action's provider/reference.
    * EVIDENCE_VERIFIED: the ORIGINAL evidence record + evidence_root; the
      record is fully re-validated and the canonical verified ref derived
      from it. A string or hand-authored ref is never accepted.
    * RESOLVED: the persisted verified evidence is re-verified against
      evidence_root.
    """
    validate_action(action, evidence_root=evidence_root)
    old_state = action["state"]
    if new_state not in ACTION_STATES:
        raise ProviderResolutionError(f"unrecognized target state {new_state!r}")
    if new_state not in _ALLOWED_TRANSITIONS[old_state]:
        raise ProviderResolutionError(f"transition {old_state} -> {new_state} is not permitted")

    if new_state in _DEPENDENCY_GATED_TARGET_STATES:
        _require_dependencies_resolved(action, dependency_actions, evidence_root)

    updated = deepcopy(action)
    if new_state == "AUTHORIZED_NOT_EXECUTED":
        validate_owner_authorization(authorization_evidence, action_id=action["action_id"])
        updated["authorization_status"] = "AUTHORIZED"
        updated["authorization_evidence"] = deepcopy(authorization_evidence)
    elif new_state == "EXECUTED_AWAITING_PROVIDER":
        if updated["authorization_status"] != "AUTHORIZED" or not updated["authorization_evidence"]:
            raise ProviderResolutionError("execution requires prior owner authorization evidence")
        validate_execution_evidence(execution_evidence, action=updated)
        updated["executed_status"] = "EXECUTED"
        updated["execution_evidence_ref"] = deepcopy(execution_evidence)
    elif new_state == "PROVIDER_REPLIED_UNVERIFIED":
        _validate_received_record(received_record, updated)
    elif new_state == "EVIDENCE_VERIFIED":
        if evidence_root is None:
            raise ProviderResolutionError("EVIDENCE_VERIFIED requires an evidence_root to validate the evidence record")
        ref = _derive_verified_ref(verified_evidence_record, evidence_root)
        validate_verified_evidence_ref(ref, action=updated, evidence_root=evidence_root)
        updated["verified_evidence_ref"] = ref
    elif new_state == "RESOLVED":
        if evidence_root is None:
            raise ProviderResolutionError("RESOLVED requires an evidence_root to re-verify the persisted evidence")
        validate_verified_evidence_ref(updated["verified_evidence_ref"], action=updated, evidence_root=evidence_root)
    elif new_state == "PREPARED":
        # A fresh cycle after EVIDENCE_INSUFFICIENT / EXPIRED_OR_STALE needs
        # a fresh authorization; nothing carries over.
        updated["authorization_status"] = "NOT_AUTHORIZED"
        updated["authorization_evidence"] = None
        updated["executed_status"] = "NOT_EXECUTED"
        updated["execution_evidence_ref"] = None
        updated["verified_evidence_ref"] = None
        updated["resolution_outcome"] = None
        updated["resolution_assessment"] = None
    elif new_state == "EXPIRED_OR_STALE":
        # a stale action no longer satisfies anything it once unlocked
        updated["resolution_outcome"] = None
        updated["resolution_assessment"] = None
    updated["state"] = new_state
    validate_action(updated, evidence_root=evidence_root)
    return updated


# ── provider response validation (§18/§19/§27) ────────────────────────────


def _validate_approved_changes(record: dict) -> None:
    for change in record["approved_state_changes"]:
        if "blocker_resolved" in change:
            token = change["blocker_resolved"]
            if token in _BLOCKER_NEVER_PROVIDER_RESOLVABLE:
                raise ProviderResolutionError(f"blocker {token!r} can never be resolved by provider evidence")
            continue
        field = change.get("field")
        if field == "access_preflight_status" or field == "full_protocol_access_validation":
            raise ProviderResolutionError(
                f"a provider response may never approve a change to {field!r}; readiness is derived by "
                "validate_full_protocol_access_readiness() only"
            )
        if field not in DIMENSION_TRANSITIONS:
            raise ProviderResolutionError(f"approved change targets unsupported field {field!r}")
        if (change.get("from"), change.get("to")) not in DIMENSION_TRANSITIONS[field]:
            raise ProviderResolutionError(
                f"approved change {field}: {change.get('from')!r} -> {change.get('to')!r} is not a permitted transition"
            )
        if change.get("evidence_kind") != DIMENSION_EVIDENCE_KIND[field]:
            raise ProviderResolutionError(
                f"approved change to {field!r} requires evidence_kind={DIMENSION_EVIDENCE_KIND[field]!r}, "
                f"got {change.get('evidence_kind')!r}"
            )


def validate_provider_response(record: dict, *, evidence_root: Path | None = None) -> None:
    """Raises unless the record is structurally valid AND bound to the
    reference's canonical provider. A record whose review_status is
    VERIFIED is additionally held to the full evidence standard:
    persisted source under `evidence_root` whose bytes hash to `sha256`,
    tier A/B/C, official provider domain, at least one answered question
    from the provider's own family, a named reviewer, no remaining
    ambiguity behind any approved state change, and only permitted,
    evidence-kind-matched changes."""
    _require_fields(record, RESPONSE_REQUIRED_FIELDS, "provider response")
    if record["evidence_tier"] not in EVIDENCE_TIERS:
        raise ProviderResolutionError(f"unrecognized evidence_tier={record['evidence_tier']!r}")
    if record["review_status"] not in REVIEW_STATUSES:
        raise ProviderResolutionError(f"unrecognized review_status={record['review_status']!r}")
    if record["reference_name"] not in EXPECTED_REFERENCE_NAMES:
        raise ProviderResolutionError(f"response targets unregistered reference {record['reference_name']!r}")
    if record["provider"] not in OFFICIAL_PROVIDER_DOMAINS:
        raise ProviderResolutionError(f"unrecognized provider {record['provider']!r}")
    _check_provider_binding(record["provider"], record["reference_name"], "provider response")
    if not isinstance(record["question_ids_answered"], list) or not isinstance(record["approved_state_changes"], list):
        raise ProviderResolutionError("question_ids_answered and approved_state_changes must be lists")
    _check_question_families(record["provider"], record["question_ids_answered"], "provider response")

    if record["review_status"] != "VERIFIED":
        if record["approved_state_changes"]:
            raise ProviderResolutionError("only a VERIFIED response may carry approved_state_changes")
        return

    if record["evidence_tier"] not in RESOLVING_EVIDENCE_TIERS:
        raise ProviderResolutionError("Tier D (informal/non-authoritative) evidence can never be VERIFIED")
    if not record["raw_response_location"]:
        raise ProviderResolutionError("VERIFIED response requires a persisted raw_response_location")
    if not _HEX64_RE.match(str(record["sha256"])):
        raise ProviderResolutionError("VERIFIED response requires a 64-hex sha256")
    if evidence_root is None:
        raise ProviderResolutionError("VERIFIED response cannot be validated without an evidence_root to read the source from")
    if _sha256_of_file(evidence_root, record["raw_response_location"]) != record["sha256"]:
        raise ProviderResolutionError("raw_response_location bytes do not match the recorded sha256")
    if not _is_official_domain(record["provider"], record["sender_domain"]):
        raise ProviderResolutionError(
            f"sender_domain {record['sender_domain']!r} is not an official domain for {record['provider']!r}"
        )
    if not record["question_ids_answered"]:
        raise ProviderResolutionError("VERIFIED response must answer at least one question")
    if not record["reviewer"] or not record["received_at_utc"] or not record["message_id"]:
        raise ProviderResolutionError("VERIFIED response requires reviewer, received_at_utc and message_id")
    if not record["quoted_authoritative_clauses"]:
        raise ProviderResolutionError("VERIFIED response requires quoted authoritative clauses")
    if record["approved_state_changes"] and record["remaining_ambiguity"]:
        raise ProviderResolutionError("a response with remaining ambiguity may not approve state changes")
    _validate_approved_changes(record)


def validate_account_setting_evidence(record: dict, *, evidence_root: Path | None = None) -> None:
    """Account-setting evidence (§20). Counts only when the setting was
    verified ACTIVE, is prospective, API-specific, screenshot-backed and
    hash-verified, is bound to the reference's canonical provider, and
    carries no real account identifier or secret."""
    _require_fields(record, ACCOUNT_SETTING_REQUIRED_FIELDS, "account-setting evidence")
    for forbidden in _FORBIDDEN_ACCOUNT_SECRET_KEYS:
        if forbidden in record:
            raise ProviderResolutionError(f"account-setting evidence must not store {forbidden!r}")
    if record["account_identifier_category"] not in ALLOWED_ACCOUNT_IDENTIFIER_CATEGORIES:
        raise ProviderResolutionError("account_identifier_category must be a redacted category, never a real identifier")
    if record["provider"] not in OFFICIAL_PROVIDER_DOMAINS or record["reference_name"] not in EXPECTED_REFERENCE_NAMES:
        raise ProviderResolutionError("account-setting evidence targets an unrecognized provider/reference")
    _check_provider_binding(record["provider"], record["reference_name"], "account-setting evidence")
    if record["verification_result"] != "VERIFIED_ACTIVE":
        raise ProviderResolutionError("account-setting evidence requires verification_result=VERIFIED_ACTIVE")
    if record["prospective"] is not True or record["api_specific"] is not True:
        raise ProviderResolutionError("setting must be verified prospective and API-specific")
    if record["old_state"] == record["new_state"]:
        raise ProviderResolutionError("account-setting evidence must record an actual old_state -> new_state change")
    if not record["provider_documentation_reference"] or not record["screenshot_evidence_reference"]:
        raise ProviderResolutionError("account-setting evidence requires screenshot and provider-documentation references")
    if not _HEX64_RE.match(str(record["sha256"])):
        raise ProviderResolutionError("account-setting evidence requires a 64-hex sha256")
    if evidence_root is None:
        raise ProviderResolutionError("account-setting evidence cannot be validated without an evidence_root")
    if _sha256_of_file(evidence_root, record["screenshot_evidence_reference"]) != record["sha256"]:
        raise ProviderResolutionError("screenshot evidence bytes do not match the recorded sha256")


# ── evidence-gated state transitions (§21/§22) ────────────────────────────


def _verified_responses_for(entry: dict, responses, evidence_root: Path) -> list[dict]:
    verified = []
    for record in responses:
        if record.get("reference_name") != entry["reference_name"]:
            continue
        validate_provider_response(record, evidence_root=evidence_root)
        if record["review_status"] == "VERIFIED":
            verified.append(record)
    return verified


def _verified_account_settings_for(entry: dict, records, evidence_root: Path) -> list[dict]:
    verified = []
    for record in records:
        if record.get("reference_name") != entry["reference_name"]:
            continue
        validate_account_setting_evidence(record, evidence_root=evidence_root)
        verified.append(record)
    return verified


def apply_verified_evidence(
    entry: dict,
    field: str,
    new_value,
    *,
    provider_responses=(),
    account_setting_records=(),
    evidence_root: Path,
    requires_account_setting: bool = False,
) -> dict:
    """Returns a NEW registry-entry copy with exactly one evidence
    dimension changed, or raises. The change must be a permitted
    transition AND explicitly approved (with the matching evidence_kind)
    by a VERIFIED provider response for this exact reference. Never
    touches access_preflight_status, blocker tokens, or any other field."""
    if field not in DIMENSION_TRANSITIONS:
        raise ProviderResolutionError(f"{field!r} is not a resolvable evidence dimension")
    if (entry[field], new_value) not in DIMENSION_TRANSITIONS[field]:
        raise ProviderResolutionError(f"{field}: {entry[field]!r} -> {new_value!r} is not a permitted transition")
    verified = _verified_responses_for(entry, provider_responses, evidence_root)
    approving = [
        r for r in verified
        if any(c.get("field") == field and c.get("to") == new_value and c.get("from") == entry[field]
               for c in r["approved_state_changes"])
    ]
    if not approving:
        raise ProviderResolutionError(
            f"no VERIFIED provider evidence approves {field}: {entry[field]!r} -> {new_value!r} "
            f"for {entry['reference_name']!r}"
        )
    if requires_account_setting and not _verified_account_settings_for(entry, account_setting_records, evidence_root):
        raise ProviderResolutionError(
            f"{field} change requires VERIFIED account-setting evidence for {entry['reference_name']!r}"
        )
    updated = deepcopy(entry)
    updated[field] = new_value
    _validate_reference(updated)
    return updated


def resolve_blocker_token(
    entry: dict,
    token: str,
    *,
    provider_responses=(),
    account_setting_records=(),
    evidence_root: Path,
) -> dict:
    """Returns a NEW entry with one blocker token removed (or the blocker
    field set to NONE when it was the last), only when verified evidence
    approves that resolution AND the underlying dimension already
    satisfies it."""
    tokens = [t for t in entry["non_financial_blocker_status"].split(",") if t and t != "NONE"]
    if token not in tokens:
        raise ProviderResolutionError(f"blocker {token!r} is not present on {entry['reference_name']!r}")
    if token in _BLOCKER_NEVER_PROVIDER_RESOLVABLE:
        raise ProviderResolutionError(f"blocker {token!r} can never be resolved by provider evidence")
    if token in _BLOCKER_REQUIRED_DIMENSION:
        dim, value = _BLOCKER_REQUIRED_DIMENSION[token]
        if entry[dim] != value:
            raise ProviderResolutionError(f"blocker {token!r} cannot be resolved while {dim}={entry[dim]!r} (needs {value!r})")
    verified = _verified_responses_for(entry, provider_responses, evidence_root)
    if token in _BLOCKER_NEEDS_ACCOUNT_SETTING:
        if not _verified_account_settings_for(entry, account_setting_records, evidence_root):
            raise ProviderResolutionError(f"blocker {token!r} requires VERIFIED account-setting evidence")
    elif not any(c.get("blocker_resolved") == token for r in verified for c in r["approved_state_changes"]):
        raise ProviderResolutionError(f"no VERIFIED provider evidence approves resolving blocker {token!r}")
    tokens.remove(token)
    updated = deepcopy(entry)
    updated["non_financial_blocker_status"] = ",".join(tokens) if tokens else "NONE"
    _validate_reference(updated)
    return updated


def promote_access_status(entry: dict, new_status: str) -> dict:
    """The ONLY route to a counting access status. Runs the authoritative
    fail-closed validator against the entry's own evidence dimensions; a
    provider reply, a draft, or a checklist can never bypass it."""
    if new_status not in _COUNTING_ACCESS_PREFLIGHT_STATUSES:
        raise ProviderResolutionError(f"{new_status!r} is not a counting access status")
    validate_full_protocol_access_readiness(
        new_status,
        reference_evaluation_admission_status=entry["reference_evaluation_admission_status"],
        license_or_terms_status=entry["license_or_terms_status"],
        evidence_retention_status=entry["evidence_retention_status"],
        automated_evaluation_status=entry["automated_evaluation_status"],
        private_holdout_status=entry["private_holdout_status"],
        access_path_identified=entry["access_path_identified"],
        model_identity_attributable=entry["model_identity_attributable"],
        non_financial_blocker_status=entry["non_financial_blocker_status"],
    )
    updated = deepcopy(entry)
    updated["access_preflight_status"] = new_status
    updated["full_protocol_access_validation"] = "PASSED"
    _validate_reference(updated)
    return updated


# ── quorum recovery dependency graph (§23) ────────────────────────────────


def unresolved_dimensions(entry: dict) -> list[str]:
    """Evidence dimensions still short of full-protocol readiness. The
    admission status follows terms, so it is not listed separately."""
    needed = []
    if entry["license_or_terms_status"] != "CLEAR":
        needed.append("license_or_terms_status")
    if entry["evidence_retention_status"] != "PERMITTED":
        needed.append("evidence_retention_status")
    if entry["automated_evaluation_status"] != "CLEAR":
        needed.append("automated_evaluation_status")
    if entry["private_holdout_status"] != "PERMITTED":
        needed.append("private_holdout_status")
    if not entry["access_path_identified"]:
        needed.append("access_path_identified")
    if not entry["model_identity_attributable"]:
        needed.append("model_identity_attributable")
    return needed


def compute_minimum_conditional_path(frontier_references, actions, *, top_alternatives: int = 2) -> dict:
    """CONDITIONAL planning only -- assumes nothing about provider
    answers. Chooses the set of `MINIMUM_USABLE_REFERENCES` references
    spanning >= `MINIMUM_INDEPENDENT_ORGANIZATIONS` organizations that
    minimizes (total critical-path action burden, total unresolved
    dimensions, names). Burden comes from each reference's actions marked
    `critical_path`. Returns the primary path and ranked fallbacks; it
    never claims any path is achieved."""
    per_ref = {}
    for entry in frontier_references:
        name = entry["reference_name"]
        burden = sum(a["burden"] for a in actions if a["reference_name"] == name and a["critical_path"])
        per_ref[name] = {
            "organization": entry["organization"],
            "burden": burden,
            "unresolved_dimensions": unresolved_dimensions(entry),
        }
    candidates = []
    for combo in itertools.combinations(sorted(per_ref), MINIMUM_USABLE_REFERENCES):
        orgs = {per_ref[n]["organization"] for n in combo}
        if len(orgs) < MINIMUM_INDEPENDENT_ORGANIZATIONS:
            continue
        candidates.append((
            sum(per_ref[n]["burden"] for n in combo),
            sum(len(per_ref[n]["unresolved_dimensions"]) for n in combo),
            combo,
        ))
    candidates.sort()
    if not candidates:
        return {"primary": None, "fallbacks": [], "per_reference": per_ref, "achieved": False}

    def _render(item):
        burden, dims, combo = item
        return {
            "references": list(combo),
            "organizations": sorted({per_ref[n]["organization"] for n in combo}),
            "total_burden": burden,
            "total_unresolved_dimensions": dims,
        }

    return {
        "primary": _render(candidates[0]),
        "fallbacks": [_render(c) for c in candidates[1:1 + top_alternatives]],
        "per_reference": per_ref,
        "achieved": False,  # conditional on future verified provider evidence
    }
