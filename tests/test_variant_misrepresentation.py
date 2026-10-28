from __future__ import annotations

import pytest

from orca.auth.store import User
from orca.serve.inference import InferenceError, complete
from orca.serve.model_catalog import authorize_model, provision_model, reset_catalog_for_tests


def _user(tier="free"):
    return User(id="u-var", email="v@example.com", name="v", tier=tier, verified=True)


def test_spoofed_nano_cannot_lower_ultra_catalog_tier():
    reset_catalog_for_tests()
    with pytest.raises(Exception) as exc:
        authorize_model(user=_user("free"), model="pro-llama", claimed_variant="nano")
    assert exc.value.code == "variant_mismatch"
    with pytest.raises(Exception) as exc:
        authorize_model(user=_user("free"), model="pro-llama", claimed_variant=None)
    assert exc.value.code == "model_access_denied"
    entry = authorize_model(user=_user("pro"), model="pro-llama", claimed_variant="ultra")
    assert entry.tier == "ultra"


def test_unknown_and_native_fail_closed():
    reset_catalog_for_tests()
    with pytest.raises(Exception) as exc:
        authorize_model(user=_user(), model="definitely-not-provisioned", claimed_variant=None)
    assert exc.value.code == "unknown_model"
    with pytest.raises(Exception) as exc:
        authorize_model(user=_user(), model="genesis", claimed_variant=None)
    assert exc.value.code == "native_identity_refused"


def test_alias_and_admin_mismatch(ollama_fixture):
    reset_catalog_for_tests()
    provision_model("alias-src", "nano", aliases=("alias-src:latest",), development=True)
    authorize_model(user=_user(), model="alias-src:latest", claimed_variant=None)
    with pytest.raises(InferenceError) as exc:
        complete(
            user=_user(),
            message="hi",
            model="never-listed-ollama",
            host=ollama_fixture,
            session_id="var-1",
            model_variant="nano",
            synthetic_provider=True,
        )
    assert exc.value.code == "unknown_model"
