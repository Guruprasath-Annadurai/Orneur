"""
FAKE_TEST_PROVIDER behavior: idempotency dedup, tenant-scoped state
isolation, OUTCOME_UNKNOWN race modeling (spec §13-14, §35, §65-66).
"""
from __future__ import annotations

import pytest

from orca.connectors.contracts import (
    ConnectorIdentity,
    ConnectorInstance,
    ConnectorReadRequest,
    ConnectorType,
    ConnectorWriteRequest,
    OutcomeStatus,
)
from orca.connectors.fake_provider import FakeProviderState, fake_read, fake_write


def _instance(tenant_id="org-1"):
    return ConnectorInstance(connector_type=ConnectorType.TICKETING, tenant_id=tenant_id, owner_principal_id="u1")


def test_fake_write_then_read_round_trip():
    state = FakeProviderState()
    instance = _instance()
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    write_req = ConnectorWriteRequest(identity=identity, connector_instance_id=instance.connector_instance_id, arguments={"text": "hello world"})
    write_result = fake_write(identity, instance, write_req, state)
    assert write_result.status == OutcomeStatus.SUCCESS

    read_req = ConnectorReadRequest(identity=identity, connector_instance_id=instance.connector_instance_id, query="hello")
    read_result = fake_read(identity, instance, read_req, state)
    assert len(read_result.normalized_content) == 1


def test_fake_write_idempotency_key_deduplicates():
    state = FakeProviderState()
    instance = _instance()
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    req = ConnectorWriteRequest(identity=identity, connector_instance_id=instance.connector_instance_id, arguments={"text": "once"}, idempotency_key="idem-1")
    r1 = fake_write(identity, instance, req, state)
    r2 = fake_write(identity, instance, req, state)
    assert r1.status == OutcomeStatus.SUCCESS
    assert r2.status == OutcomeStatus.SUCCESS
    key = (instance.tenant_id, instance.connector_instance_id)
    assert len(state.objects[key]) == 1


def test_fake_write_network_break_reports_outcome_unknown_but_still_applies():
    """spec §13/§35: the write DOES land in the fake remote state (as a
    real provider's write might have actually succeeded), but the response
    honestly reports OUTCOME_UNKNOWN -- never a false SUCCESS or a false
    FAILURE that would invite an unsafe blind retry."""
    state = FakeProviderState(simulate_network_break_after_send=True)
    instance = _instance()
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    req = ConnectorWriteRequest(identity=identity, connector_instance_id=instance.connector_instance_id, arguments={"text": "risky"}, idempotency_key="idem-risky")
    result = fake_write(identity, instance, req, state)
    assert result.status == OutcomeStatus.OUTCOME_UNKNOWN
    key = (instance.tenant_id, instance.connector_instance_id)
    assert len(state.objects[key]) == 1


def test_fake_provider_state_isolated_across_tenants():
    state = FakeProviderState()
    instance_a = _instance(tenant_id="org-A")
    instance_b = ConnectorInstance(connector_instance_id=instance_a.connector_instance_id, connector_type=ConnectorType.TICKETING, tenant_id="org-B", owner_principal_id="u2")
    identity_a = ConnectorIdentity(tenant_id="org-A", principal_id="u1")
    identity_b = ConnectorIdentity(tenant_id="org-B", principal_id="u2")

    fake_write(identity_a, instance_a, ConnectorWriteRequest(identity=identity_a, connector_instance_id=instance_a.connector_instance_id, arguments={"text": "org-A secret"}), state)
    result_b = fake_read(identity_b, instance_b, ConnectorReadRequest(identity=identity_b, connector_instance_id=instance_b.connector_instance_id, query="secret"), state)
    assert result_b.normalized_content == []


def test_fake_read_raises_on_tenant_mismatch():
    state = FakeProviderState()
    instance = _instance(tenant_id="org-B")
    bad_identity = ConnectorIdentity(tenant_id="org-A", principal_id="attacker")
    with pytest.raises(PermissionError):
        fake_read(bad_identity, instance, ConnectorReadRequest(identity=bad_identity, connector_instance_id=instance.connector_instance_id, query="x"), state)


def test_fake_write_raises_on_tenant_mismatch():
    state = FakeProviderState()
    instance = _instance(tenant_id="org-B")
    bad_identity = ConnectorIdentity(tenant_id="org-A", principal_id="attacker")
    with pytest.raises(PermissionError):
        fake_write(bad_identity, instance, ConnectorWriteRequest(identity=bad_identity, connector_instance_id=instance.connector_instance_id, arguments={"text": "x"}), state)
