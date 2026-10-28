from __future__ import annotations

import pytest

from orca.governance.deny_principal import PrincipalError, authenticate, authorize


def test_authenticate_discards_every_claim():
    with pytest.raises(PrincipalError) as exc:
        authenticate(user_id="founder", role="admin", token="anything")
    assert exc.value.code == "principal_not_authenticated"


def test_authorize_never_succeeds():
    with pytest.raises(PrincipalError) as exc:
        authorize(object(), action="read")
    assert exc.value.code == "principal_not_authenticated"


def test_empty_claims_still_denied():
    with pytest.raises(PrincipalError) as exc:
        authenticate()
    assert exc.value.code == "principal_not_authenticated"
