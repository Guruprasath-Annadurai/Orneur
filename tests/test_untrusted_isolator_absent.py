from __future__ import annotations

import pytest

from orca.code.untrusted import UntrustedError, execute, isolator


def test_untrusted_execution_stays_closed_without_qualification():
    code = isolator()
    with pytest.raises(UntrustedError) as exc:
        execute("print(1)", user_id="user-a")
    if code is None:
        assert exc.value.code == "isolation_unavailable"
    else:
        assert code == "docker"
        assert exc.value.code == "isolation_unqualified"


def test_untrusted_execute_requires_user():
    with pytest.raises(UntrustedError) as exc:
        execute("print(1)", user_id="")
    assert exc.value.code == "unauthenticated"
