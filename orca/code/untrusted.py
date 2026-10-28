"""Untrusted code execution. Disabled unless a real isolator is present."""

from __future__ import annotations

import shutil


class UntrustedError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def isolator() -> str | None:
    if shutil.which("docker"):
        return "docker"
    return None


def execute(source: str, *, user_id: str) -> dict:
    if not user_id:
        raise UntrustedError("unauthenticated")
    if not isinstance(source, str) or not source.strip():
        raise UntrustedError("source_refused")
    if isolator() is None:
        raise UntrustedError("isolation_unavailable")
    # Docker is present but this branch has not run breakout, privilege,
    # mount, or network-denial qualification. Subprocess isolation is not
    # a substitute. Execution stays closed.
    raise UntrustedError("isolation_unqualified")
