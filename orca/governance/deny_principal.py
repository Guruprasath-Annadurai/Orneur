"""Deny-all runtime principal adapter.

PR #115's `orca.core_runtime.principal` is not in this tree. This adapter
implements the same fail-closed rule without merging that branch and
without treating caller-supplied claims as authority.
"""

from __future__ import annotations

from typing import Any


class PrincipalError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def authenticate(**claims: Any) -> None:
    """Every authentication attempt is refused. Claims are discarded."""
    raise PrincipalError("principal_not_authenticated")


def authorize(principal: object, *args: Any, **kwargs: Any) -> None:
    raise PrincipalError("principal_not_authenticated")
