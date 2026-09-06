"""
Tests for orca/license/stripe_hook.py signature verification.

Locks in tonight's real fix: a missing STRIPE_WEBHOOK_SECRET used to
silently accept ANY unsigned payload ("dev mode"). That's a real
free-tier-upgrade exploit if the secret is ever unset in production
(missing env var, misconfigured deploy). Now it fails closed by default.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import pytest

from orca.license import stripe_hook


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("ORCA_ALLOW_UNSIGNED_WEBHOOKS", raising=False)


def _make_signed_header(secret: str, payload: bytes, timestamp: int | None = None) -> str:
    ts = timestamp if timestamp is not None else int(time.time())
    signed = f"{ts}".encode() + b"." + payload
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_missing_secret_fails_closed_by_default():
    """The core regression test — this must raise, not silently accept."""
    payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {}}}).encode()
    with pytest.raises(ValueError, match="STRIPE_WEBHOOK_SECRET not configured"):
        stripe_hook._verify_signature(payload, "", "")


def test_missing_secret_allows_unsigned_only_with_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("ORCA_ALLOW_UNSIGNED_WEBHOOKS", "1")
    payload = json.dumps({"type": "ping"}).encode()
    event = stripe_hook._verify_signature(payload, "", "")
    assert event["type"] == "ping"


def test_valid_signature_accepted():
    secret = "whsec_test_secret"
    payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {}}}).encode()
    sig_header = _make_signed_header(secret, payload)
    event = stripe_hook._verify_signature(payload, sig_header, secret)
    assert event["type"] == "checkout.session.completed"


def test_invalid_signature_rejected():
    secret = "whsec_test_secret"
    payload = json.dumps({"type": "checkout.session.completed"}).encode()
    bad_header = f"t={int(time.time())},v1=deadbeef00112233"
    with pytest.raises(ValueError, match="signature verification failed"):
        stripe_hook._verify_signature(payload, bad_header, secret)


def test_wrong_secret_rejected():
    real_secret = "whsec_real"
    wrong_secret = "whsec_wrong"
    payload = json.dumps({"type": "checkout.session.completed"}).encode()
    sig_header = _make_signed_header(real_secret, payload)
    with pytest.raises(ValueError, match="signature verification failed"):
        stripe_hook._verify_signature(payload, sig_header, wrong_secret)


def test_stale_timestamp_rejected_as_replay():
    secret = "whsec_test_secret"
    payload = json.dumps({"type": "checkout.session.completed"}).encode()
    old_timestamp = int(time.time()) - 400  # older than the 300s window
    sig_header = _make_signed_header(secret, payload, timestamp=old_timestamp)
    with pytest.raises(ValueError, match="too old"):
        stripe_hook._verify_signature(payload, sig_header, secret)


def test_price_to_params_unknown_price_defaults_safely(monkeypatch):
    monkeypatch.delenv("STRIPE_PRICE_PRO", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_PRO_YEAR", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ENT", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ENT_YEAR", raising=False)
    tier, seats, days = stripe_hook._price_to_params("price_unknown_123")
    assert tier == "pro"
    assert seats == 1
    assert days == 31


def test_price_to_params_maps_known_prices(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ENT_YEAR", "price_enterprise_yearly")
    tier, seats, days = stripe_hook._price_to_params("price_enterprise_yearly")
    assert tier == "enterprise"
    assert seats == 5
    assert days == 365
