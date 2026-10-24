"""Authenticated-principal contract.

The local runtime does not authenticate a user. This module is the
integration point for a later authorization check. It refuses every
claim. It does not issue a principal and it does not grant cross-user
access to the journal.
"""
from __future__ import annotations


class PrincipalError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def authenticate(**_claims) -> dict:
    """Refuse authentication. No principal is returned."""
    raise PrincipalError("principal_not_authenticated")
