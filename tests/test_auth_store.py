"""
Tests for orca/auth/store.py — signup_seq atomic assignment and
model_access_allowed() plan gating.

These lock in tonight's real fix: before this, model_variant came straight
from the client request with zero check against the user's tier — any
authenticated user could call orca-ultra (Aeternum) for free. Regression
here means a real revenue/security hole reopens silently.
"""
from __future__ import annotations

import copy
import threading

import pytest


def test_signup_seq_assigned_in_order(isolated_home):
    store = isolated_home
    u1 = store.create_user("a@test.com", "pw12345678")
    u2 = store.create_user("b@test.com", "pw12345678")
    u3 = store.create_user("c@test.com", "pw12345678")
    assert (u1.signup_seq, u2.signup_seq, u3.signup_seq) == (1, 2, 3)


def test_signup_seq_persists_and_refetches(isolated_home):
    store = isolated_home
    created = store.create_user("a@test.com", "pw12345678")
    fetched = store.get_user_by_id(created.id)
    assert fetched.signup_seq == created.signup_seq == 1


def test_signup_seq_atomic_under_concurrency(isolated_home):
    """
    The whole reason signup_seq uses UPDATE...RETURNING instead of
    COUNT(*)-then-insert: concurrent signups must never collide on the
    same sequence number. 20 threads creating users simultaneously must
    produce 20 unique, contiguous sequence numbers.
    """
    store = isolated_home
    results = []
    lock = threading.Lock()

    def make_user(i):
        u = store.create_user(f"user{i}@test.com", "pw12345678")
        with lock:
            results.append(u.signup_seq)

    threads = [threading.Thread(target=make_user, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 20
    assert len(set(results)) == 20, f"duplicate signup_seq assigned under concurrency: {results}"
    assert sorted(results) == list(range(1, 21))


def test_nano_always_allowed_including_anonymous(isolated_home):
    store = isolated_home
    allowed, reason = store.model_access_allowed(None, "nano")
    assert allowed is True
    assert reason == ""


def test_core_denied_for_anonymous(isolated_home):
    store = isolated_home
    allowed, reason = store.model_access_allowed(None, "core")
    assert allowed is False
    assert "Novus" in reason


def test_core_allowed_within_first_100_signups(isolated_home):
    store = isolated_home
    user = store.create_user("early@test.com", "pw12345678")
    assert user.signup_seq == 1
    allowed, _ = store.model_access_allowed(user, "core")
    assert allowed is True


def test_core_denied_after_signup_100_on_free_tier(isolated_home):
    store = isolated_home
    user = store.create_user("late@test.com", "pw12345678")
    late_user = copy.copy(user)
    late_user.signup_seq = 101
    late_user.tier = "free"
    allowed, reason = store.model_access_allowed(late_user, "core")
    assert allowed is False
    assert "Novus" in reason


def test_core_allowed_on_paid_tier_regardless_of_signup_seq(isolated_home):
    store = isolated_home
    user = store.create_user("paiduser@test.com", "pw12345678")
    late_paid = copy.copy(user)
    late_paid.signup_seq = 9999
    late_paid.tier = "pro"
    allowed, _ = store.model_access_allowed(late_paid, "core")
    assert allowed is True


def test_ultra_denied_on_free_tier_even_within_first_100(isolated_home):
    """
    Aeternum is paid-only, always — the first-100 exception applies to
    Novus, not Aeternum. A user with signup_seq=1 must still be denied.
    """
    store = isolated_home
    user = store.create_user("early@test.com", "pw12345678")
    assert user.signup_seq == 1
    allowed, reason = store.model_access_allowed(user, "ultra")
    assert allowed is False
    assert "Aeternum" in reason


def test_ultra_allowed_on_pro_tier(isolated_home):
    store = isolated_home
    user = store.create_user("pro@test.com", "pw12345678")
    user.tier = "pro"
    allowed, _ = store.model_access_allowed(user, "ultra")
    assert allowed is True


def test_ultra_allowed_on_enterprise_tier(isolated_home):
    store = isolated_home
    user = store.create_user("ent@test.com", "pw12345678")
    user.tier = "enterprise"
    allowed, _ = store.model_access_allowed(user, "ultra")
    assert allowed is True


def test_unknown_variant_fails_closed(isolated_home):
    store = isolated_home
    user = store.create_user("someone@test.com", "pw12345678")
    user.tier = "enterprise"
    allowed, reason = store.model_access_allowed(user, "not-a-real-variant")
    assert allowed is False
    assert "Unknown model variant" in reason


def test_orca_prefixed_variant_names_normalize_correctly(isolated_home):
    """model_access_allowed accepts 'orca-nano' etc, not just 'nano'."""
    store = isolated_home
    allowed, _ = store.model_access_allowed(None, "orca-nano")
    assert allowed is True


def test_none_model_variant_defaults_to_core(isolated_home):
    """_get_session defaults model_variant to 'core' when None — the gate must match that default."""
    store = isolated_home
    allowed, reason = store.model_access_allowed(None, None)
    assert allowed is False
    assert "Novus" in reason
