"""
Genesis Frontier Provider Resolution control plane (Phase 21B.4.19).

Turns the remaining frontier-reference blockers (provider clarification,
provider account settings, enterprise agreements, model-version
confirmation) into an independently auditable, fail-closed workflow.

Doctrine (phase §4): PROVIDER RESOLUTION REQUIRES EVIDENCE. STATE CHANGE
REQUIRES VERIFIED EVIDENCE. FULL-PROTOCOL PROMOTION REQUIRES MACHINE
VALIDATION. Nothing in this module sends a message, submits a ticket,
changes a provider account setting, calls a provider API, or executes a
model -- it only models actions, validates evidence records, and gates
registry-dimension changes. Every external/account-mutating action
defaults to NOT_AUTHORIZED; only a separate, explicit owner authorization
(recorded as `authorization_evidence`) can ever move one forward.

Fail-closed layering (the existing Phase 21B.4.17.2/.18 validator stays
authoritative):

1. `validate_provider_response()` / `validate_account_setting_evidence()`
   decide whether an evidence record is VERIFIED (persisted source,
   matching SHA-256, official provider domain, tier A/B/C, specific,
   unambiguous).
2. `apply_verified_evidence()` / `resolve_blocker_token()` change ONE
   underlying evidence dimension (or remove ONE blocker token) only when
   verified evidence explicitly approves exactly that change. They never
   touch `access_preflight_status`.
3. `promote_access_status()` is the only way to a counting access status,
   and it runs `validate_full_protocol_access_readiness()` against the
   entry's own dimensions -- a provider reply can never bypass it.
4. `compute_admission_quorum()` (unchanged) re-derives readiness again at
   count time.
"""
from __future__ import annotations

import hashlib
import itertools
import re
from copy import deepcopy
from pathlib import Path

from orca.eval.candidate_registry import EXPECTED_REFERENCE_NAMES, _validate_reference
from orca.eval.frontier_reference_admission_quorum import (
    _COUNTING_ACCESS_PREFLIGHT_STATUSES,
    MINIMUM_INDEPENDENT_ORGANIZATIONS,
    MINIMUM_USABLE_REFERENCES,
    validate_full_protocol_access_readiness,
)

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

# "SENT" is deliberately not a state and never equals resolution (§8).
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
    "authorization_evidence", "verified_evidence_ref",
)

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
# before the token may be removed. Tokens absent here that need only a
# verified response are handled separately; SELF_HOST_COMPUTE_PROHIBITIVE
# and ZERO_CASH_CHECK_REQUIRED are compute/financial, never resolvable by
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


class ProviderResolutionError(ValueError):
    """An action, evidence record, or state transition violates the
    Phase 21B.4.19 fail-closed provider-resolution rules."""


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


# ── action queue validation (§10/§27) ─────────────────────────────────────


def validate_action(action: dict) -> None:
    _require_fields(action, ACTION_REQUIRED_FIELDS, f"action {action.get('action_id', '<unnamed>')!r}")
    aid = action["action_id"]
    if action["action_type"] not in EXTERNAL_ACTION_TYPES:
        raise ProviderResolutionError(f"action {aid!r} has unrecognized action_type={action['action_type']!r}")
    if action["reference_name"] != "ALL" and action["reference_name"] not in EXPECTED_REFERENCE_NAMES:
        raise ProviderResolutionError(f"action {aid!r} targets unregistered reference {action['reference_name']!r}")
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

    # No executed action without prior authorization evidence (§27).
    if action["executed_status"] == "EXECUTED":
        if action["authorization_status"] != "AUTHORIZED" or not action["authorization_evidence"]:
            raise ProviderResolutionError(
                f"action {aid!r} is EXECUTED without AUTHORIZED status and persisted authorization_evidence"
            )
    if action["authorization_status"] == "AUTHORIZED" and not action["authorization_evidence"]:
        raise ProviderResolutionError(f"action {aid!r} is AUTHORIZED without authorization_evidence")
    if action["state"] == "AUTHORIZED_NOT_EXECUTED" and action["authorization_status"] != "AUTHORIZED":
        raise ProviderResolutionError(f"action {aid!r} state AUTHORIZED_NOT_EXECUTED requires AUTHORIZED status")
    if action["state"] in _EXECUTION_ASSERTING_STATES and action["executed_status"] != "EXECUTED":
        raise ProviderResolutionError(f"action {aid!r} state {action['state']!r} asserts execution but executed_status is not EXECUTED")
    # A blocker/action may not be RESOLVED or EVIDENCE_VERIFIED without a
    # persisted verified-evidence reference (§27).
    if action["state"] in _VERIFIED_EVIDENCE_STATES and not action["verified_evidence_ref"]:
        raise ProviderResolutionError(f"action {aid!r} state {action['state']!r} requires a persisted verified_evidence_ref")


def validate_action_queue(queue: dict) -> None:
    for key in ("schema_version", "phase", "actions", "messages_sent", "support_tickets_submitted",
                "account_settings_changed", "commercial_notices_sent"):
        if key not in queue:
            raise ProviderResolutionError(f"action queue missing top-level key {key!r}")
    ids = [a.get("action_id") for a in queue["actions"]]
    if len(ids) != len(set(ids)):
        raise ProviderResolutionError("action queue contains duplicate action_id values")
    for action in queue["actions"]:
        validate_action(action)
    known = set(ids)
    for action in queue["actions"]:
        for dep in action["depends_on"]:
            if dep not in known:
                raise ProviderResolutionError(f"action {action['action_id']!r} depends on unknown action {dep!r}")


def assert_queue_fully_unauthorized(queue: dict) -> None:
    """Phase 21B.4.19 authorizes NO external action: every action must
    still be NOT_AUTHORIZED / NOT_EXECUTED with no authorization evidence,
    and every phase-level counter must be zero."""
    validate_action_queue(queue)
    for counter in ("messages_sent", "support_tickets_submitted", "account_settings_changed", "commercial_notices_sent"):
        if queue[counter] != 0:
            raise ProviderResolutionError(f"queue counter {counter}={queue[counter]!r}, expected 0")
    for action in queue["actions"]:
        if action["authorization_status"] != "NOT_AUTHORIZED" or action["executed_status"] != "NOT_EXECUTED":
            raise ProviderResolutionError(f"action {action['action_id']!r} is not NOT_AUTHORIZED/NOT_EXECUTED")
        if action["authorization_evidence"] is not None:
            raise ProviderResolutionError(f"action {action['action_id']!r} carries authorization_evidence in a no-authorization phase")


def advance_action_state(
    action: dict,
    new_state: str,
    *,
    authorization_evidence: dict | None = None,
    execution_evidence: dict | None = None,
    verified_evidence_ref: str | None = None,
) -> dict:
    """Returns a NEW action dict in `new_state`, or raises. Never mutates
    the input. Each forward step requires its own evidence."""
    validate_action(action)
    old_state = action["state"]
    if new_state not in ACTION_STATES:
        raise ProviderResolutionError(f"unrecognized target state {new_state!r}")
    if new_state not in _ALLOWED_TRANSITIONS[old_state]:
        raise ProviderResolutionError(f"transition {old_state} -> {new_state} is not permitted")
    updated = deepcopy(action)
    if new_state == "AUTHORIZED_NOT_EXECUTED":
        if not authorization_evidence:
            raise ProviderResolutionError("AUTHORIZED_NOT_EXECUTED requires explicit owner authorization_evidence")
        updated["authorization_status"] = "AUTHORIZED"
        updated["authorization_evidence"] = deepcopy(authorization_evidence)
    elif new_state == "EXECUTED_AWAITING_PROVIDER":
        if updated["authorization_status"] != "AUTHORIZED" or not updated["authorization_evidence"]:
            raise ProviderResolutionError("execution requires prior owner authorization evidence")
        if not execution_evidence:
            raise ProviderResolutionError("EXECUTED_AWAITING_PROVIDER requires execution_evidence")
        updated["executed_status"] = "EXECUTED"
    elif new_state == "PROVIDER_REPLIED_UNVERIFIED":
        if not execution_evidence:
            raise ProviderResolutionError("PROVIDER_REPLIED_UNVERIFIED requires the received record as execution_evidence")
    elif new_state in _VERIFIED_EVIDENCE_STATES:
        if not verified_evidence_ref:
            raise ProviderResolutionError(f"{new_state} requires a persisted verified_evidence_ref")
        updated["verified_evidence_ref"] = verified_evidence_ref
    updated["state"] = new_state
    validate_action(updated)
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
    """Raises unless the record is structurally valid. A record whose
    review_status is VERIFIED is additionally held to the full evidence
    standard: persisted source under `evidence_root` whose bytes hash to
    `sha256`, tier A/B/C, official provider domain, at least one answered
    question, a named reviewer, no remaining ambiguity behind any approved
    state change, and only permitted, evidence-kind-matched changes."""
    _require_fields(record, RESPONSE_REQUIRED_FIELDS, "provider response")
    if record["evidence_tier"] not in EVIDENCE_TIERS:
        raise ProviderResolutionError(f"unrecognized evidence_tier={record['evidence_tier']!r}")
    if record["review_status"] not in REVIEW_STATUSES:
        raise ProviderResolutionError(f"unrecognized review_status={record['review_status']!r}")
    if record["reference_name"] not in EXPECTED_REFERENCE_NAMES:
        raise ProviderResolutionError(f"response targets unregistered reference {record['reference_name']!r}")
    if record["provider"] not in OFFICIAL_PROVIDER_DOMAINS:
        raise ProviderResolutionError(f"unrecognized provider {record['provider']!r}")
    if not isinstance(record["question_ids_answered"], list) or not isinstance(record["approved_state_changes"], list):
        raise ProviderResolutionError("question_ids_answered and approved_state_changes must be lists")

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
    hash-verified, and carries no real account identifier or secret."""
    _require_fields(record, ACCOUNT_SETTING_REQUIRED_FIELDS, "account-setting evidence")
    for forbidden in _FORBIDDEN_ACCOUNT_SECRET_KEYS:
        if forbidden in record:
            raise ProviderResolutionError(f"account-setting evidence must not store {forbidden!r}")
    if record["account_identifier_category"] not in ALLOWED_ACCOUNT_IDENTIFIER_CATEGORIES:
        raise ProviderResolutionError("account_identifier_category must be a redacted category, never a real identifier")
    if record["provider"] not in OFFICIAL_PROVIDER_DOMAINS or record["reference_name"] not in EXPECTED_REFERENCE_NAMES:
        raise ProviderResolutionError("account-setting evidence targets an unrecognized provider/reference")
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
