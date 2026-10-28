from __future__ import annotations

import shutil

import pytest

from orca.code.untrusted import UntrustedError, execute, isolator


def test_docker_absent_keeps_untrusted_execution_disabled():
    assert shutil.which("docker") is None
    assert isolator() is None
    with pytest.raises(UntrustedError) as exc:
        execute("print(1)", user_id="user-a")
    assert exc.value.code == "isolation_unavailable"
