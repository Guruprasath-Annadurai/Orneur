"""
Phase 13.1 §38-39 -- audit/log injection and error-leak red-team
campaign.
"""
from __future__ import annotations

import dataclasses
import json

from orca.connectors.security import redact_secrets
from orca.godmode.audit import record_elevation_event, reset_audit_log_for_tests
from orca.godmode.contracts import ElevationAuditEventType


_LOG_INJECTION_PAYLOAD = (
    'legit-resource\n[CRITICAL] fake severity injected\n'
    '{"event_type": "ISSUE", "result": "forged-entry"}\r\n\x1b[31mANSI escape\x1b[0m'
)


def test_audit01_log_injection_payload_stays_a_single_json_string_field_when_serialized():
    """Attack: a resource_scope/capability field containing newlines, a
    fake severity marker, a fake embedded JSON object, and an ANSI escape
    sequence, attempting to forge additional log entries or corrupt a
    structured audit record. Required: the structured (dataclass ->
    asdict -> json.dumps) serialization path keeps the entire payload as
    ONE string VALUE under its own real field key -- it can never inject
    a sibling top-level key or a second JSON object."""
    reset_audit_log_for_tests()
    event = record_elevation_event(
        event_type=ElevationAuditEventType.ISSUE, principal_id="attacker", tenant_id="t1",
        resource_scope=_LOG_INJECTION_PAYLOAD, capability="CONNECTOR_WRITE", operation_scope="write", result="ALLOW",
    )
    serialized = json.dumps(dataclasses.asdict(event))
    parsed_back = json.loads(serialized)

    # The entire injection payload round-trips as the value of exactly
    # ONE real field -- no new top-level key was created, and the
    # "forged-entry" fake result value never became the REAL event's
    # result field.
    assert parsed_back["resource_scope"] == _LOG_INJECTION_PAYLOAD
    assert parsed_back["result"] == "ALLOW"  # the real field, untouched by the embedded fake JSON
    assert set(parsed_back.keys()) == {f.name for f in dataclasses.fields(event)}  # no injected sibling key


def test_audit02_secret_pattern_in_audit_field_is_redacted_before_storage():
    """The audit module already reuses redact_secrets() on capability/
    resource_scope fields -- confirmed directly rather than assumed."""
    reset_audit_log_for_tests()
    event = record_elevation_event(
        event_type=ElevationAuditEventType.ISSUE, principal_id="u1", tenant_id="t1",
        capability="token: sk-abcdefghijklmnopqrstuvwxyz123456", resource_scope="api_key=verysecretvalue1234567890",
        operation_scope="write", result="ALLOW",
    )
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in event.capability
    assert "verysecretvalue1234567890" not in event.resource_scope


# --------------------------------------------------------------- error-leak campaign (spec §39)


def test_error01_lease_issuance_error_never_leaks_the_arguments_hash_preimage():
    """A LeaseIssuanceError's message must never reconstruct or leak a
    raw secret value that was hashed into arguments_hash -- confirmed by
    checking a real rejection path's exception text."""
    from datetime import datetime, timedelta, timezone
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import LeaseIssuanceError, issue_lease

    secret_value = "sk-realsecretvalue0000000000000000"
    approval = GodmodeApproval(
        approval_id="ap-err-1", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="*", resource_scope="*", operation_scope="*", arguments_hash="irrelevant",
        duration_s=300, reason=f"use credential {secret_value}", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    try:
        issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester")
        assert False, "wildcard capability/resource/operation should have been rejected"
    except LeaseIssuanceError as e:
        assert secret_value not in str(e)


def test_error02_connector_security_redaction_scrubs_common_credential_shapes_from_error_text():
    """Reuses the real redact_secrets() function directly against a
    simulated error message string -- the actual defense a caller must
    apply before logging/raising with any user- or connector-derived
    text."""
    raw_error_text = "Connection failed: Authorization: Bearer sk-liveSECRETtoken1234567890abcdef, retrying..."
    redacted = redact_secrets(raw_error_text)
    assert "sk-liveSECRETtoken1234567890abcdef" not in redacted
