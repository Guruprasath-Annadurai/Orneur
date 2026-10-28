from __future__ import annotations

import pytest

from orca.code.untrusted import UntrustedError, daemon_usable, execute, isolator


def test_untrusted_execute_requires_user():
    with pytest.raises(UntrustedError) as exc:
        execute("print(1)", user="not-a-user")
    assert exc.value.code == "unauthenticated"


def test_untrusted_without_daemon_is_unavailable(monkeypatch):
    monkeypatch.setattr("orca.code.untrusted.daemon_usable", lambda: False)
    monkeypatch.setattr("orca.code.untrusted.isolator", lambda: None)
    from orca.auth.store import User

    user = User(id="user-a", email="a@example.com", name="a", tier="free", verified=True)
    with pytest.raises(UntrustedError) as exc:
        execute("print(1)", user=user)
    assert exc.value.code == "isolation_unavailable"


def test_isolator_matches_daemon():
    if daemon_usable():
        assert isolator() == "docker"
    else:
        assert isolator() is None
