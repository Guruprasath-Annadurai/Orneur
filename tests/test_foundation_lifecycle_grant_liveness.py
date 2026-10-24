"""Lifecycle must not treat an expired or revoked grant as a complete chain."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orca.foundation_x.lifecycle import LifecycleChain, LifecycleDecision, assess_lifecycle
from orca.genesis.governance.authorization import (
    NativePretrainingNotAuthorized,
    assert_execution_permitted,
    grant_time_validity_reasons,
    reset_in_process_nonce_guard_for_new_process,
)
from tests.test_genesis_governance_authorization import World

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_nonce_guard():
    reset_in_process_nonce_guard_for_new_process()
    yield
    reset_in_process_nonce_guard_for_new_process()


def _chain_for(grant) -> LifecycleChain:
    return LifecycleChain(
        dataset_id=grant.dataset_manifest_id,
        dataset_digest=grant.dataset_content_digest,
        transformation_digest=grant.transformation_code_digest,
        tokenizer_id="tok",
        expected_tokenizer_id="tok",
        tokenizer_digest=grant.tokenizer_digest,
        config_digest=grant.model_config_digest,
        authorization_kind="FOUNDER_GRANT",
        authorization_synthetic=False,
        run_id=grant.run_id,
        training_state_digest="st",
        checkpoint_digest="ck",
        checkpoint_dataset_digest=grant.dataset_content_digest,
        evaluation_id="ev",
        evaluation_approved=True,
        model_family="genesis",
        model_family_trained=True,
    )


def test_expired_grant_fails_lifecycle_and_still_verifies_integrity(monkeypatch):
    grant = World().authorize(monkeypatch=monkeypatch)
    grant.verify_integrity()
    expires = datetime.strptime(grant.expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    decision, reasons = assess_lifecycle(
        _chain_for(grant), grant=grant, now=expires, revocation_check=lambda _id: False,
    )
    assert decision == LifecycleDecision.FAIL_CLOSED
    assert any("EXPIRED" in reason for reason in reasons)
    with pytest.raises(NativePretrainingNotAuthorized, match="EXPIRED"):
        assert_execution_permitted(grant, revocation_check=lambda _id: False, now=expires)


def test_not_yet_valid_grant_fails_lifecycle(monkeypatch):
    grant = World().authorize(monkeypatch=monkeypatch)
    issued = datetime.strptime(grant.issued_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    before = issued - timedelta(seconds=1)
    decision, reasons = assess_lifecycle(
        _chain_for(grant), grant=grant, now=before, revocation_check=lambda _id: False,
    )
    assert decision == LifecycleDecision.FAIL_CLOSED
    assert any("NOT_YET_VALID" in reason for reason in reasons)
    assert grant_time_validity_reasons(grant, issued) == []
    with pytest.raises(NativePretrainingNotAuthorized, match="NOT_YET_VALID"):
        assert_execution_permitted(grant, revocation_check=lambda _id: False, now=before)


def test_revoked_grant_fails_lifecycle_and_execution(monkeypatch):
    grant = World().authorize(monkeypatch=monkeypatch)
    decision, reasons = assess_lifecycle(
        _chain_for(grant), grant=grant, revocation_check=lambda _id: True,
    )
    assert decision == LifecycleDecision.FAIL_CLOSED
    assert any("AUTHORIZATION_REVOKED_LIVE" in reason for reason in reasons)
    with pytest.raises(NativePretrainingNotAuthorized, match="AUTHORIZATION_REVOKED_LIVE"):
        assert_execution_permitted(grant, revocation_check=lambda _id: True)


def test_complete_chain_never_authorizes_training(monkeypatch):
    grant = World().authorize(monkeypatch=monkeypatch)
    decision, notes = assess_lifecycle(
        _chain_for(grant), grant=grant, revocation_check=lambda _id: False,
    )
    assert decision == LifecycleDecision.CHAIN_COMPLETE_TRAINING_NOT_AUTHORIZED
    assert any("does not start training" in note for note in notes)


def test_acceptance_ledger_numerator_is_unchanged():
    import json

    ledger = json.loads((REPO_ROOT / "docs/orneur/acceptance/acceptance_ledger.json").read_text())
    assert ledger == []
