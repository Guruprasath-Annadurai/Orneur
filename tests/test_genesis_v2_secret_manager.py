"""Secret-manager policy: structural field-presence AND semantic role-scope correctness, reconciled against the
current X25519 architecture (item 2 of the deployment-decision-accuracy-closure phase)."""
import copy

from orca.eval.genesis_v2 import secret_manager as SM
from orca.eval.genesis_v2 import spec


def test_real_committed_policy_passes_structural_and_semantic_validation():
    assert SM.validate_policy() == []
    assert SM.validate_env_var_cross_references() == []


def test_corpus_secret_is_scoped_to_the_generator_not_a_reader_role():
    """The exact bug this round fixes: an earlier draft scoped corpus_secret to the qualification runner."""
    pol = SM.SECRET_CLASSES["corpus_secret"]
    assert "generator" in pol["access_scope"].lower()
    assert "qualification" not in pol["access_scope"].lower() and "verifier" not in pol["access_scope"].lower()
    assert pol["env_var"] == spec.SECRET_ENV


def test_vault_public_key_is_scoped_to_the_generator():
    pol = SM.SECRET_CLASSES["vault_public_key"]
    assert "generator" in pol["access_scope"].lower()
    assert "qualification" not in pol["access_scope"].lower() and "verifier" not in pol["access_scope"].lower()
    assert pol["env_var"] == spec.VAULT_PUBLIC_KEY_ENV


def test_vault_private_key_is_scoped_to_a_reader_role_never_the_generator():
    pol = SM.SECRET_CLASSES["vault_private_key"]
    assert "generator" not in pol["access_scope"].lower()
    assert "qualification" in pol["access_scope"].lower() or "verifier" in pol["access_scope"].lower()
    assert pol["env_var"] == spec.VAULT_PRIVATE_KEY_ENV


def test_legacy_symmetric_key_class_is_present_but_clearly_retired():
    """Preserve historical compatibility (the class stays, for audit continuity) without presenting it as active."""
    pol = SM.SECRET_CLASSES.get("aes_encryption_key_LEGACY_RETIRED")
    assert pol is not None
    assert "retired" in pol["access_scope"].lower()
    assert "RETIRED" in pol["env_var"]


# ---------------------------------------------------------------- semantic validation actually catches mistakes
def test_validate_policy_catches_corpus_secret_scoped_to_a_reader_role(monkeypatch):
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    bad["corpus_secret"]["access_scope"] = "qualification runner process only"
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_policy()
    assert any("corpus_secret" in p for p in problems)


def test_validate_policy_catches_vault_public_key_scoped_to_a_reader_role(monkeypatch):
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    bad["vault_public_key"]["access_scope"] = "creation-time-verifier process only"
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_policy()
    assert any("vault_public_key" in p for p in problems)


def test_validate_policy_catches_vault_private_key_scoped_to_the_generator(monkeypatch):
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    bad["vault_private_key"]["access_scope"] = "generator process only"
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_policy()
    assert any("vault_private_key" in p for p in problems)


def test_validate_policy_catches_a_removed_legacy_class(monkeypatch):
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    del bad["aes_encryption_key_LEGACY_RETIRED"]
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_policy()
    assert any("retired" in p.lower() for p in problems)


def test_validate_policy_catches_a_legacy_class_no_longer_marked_retired(monkeypatch):
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    bad["aes_encryption_key_LEGACY_RETIRED"]["access_scope"] = "qualification runner process only"   # presented as active again
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_policy()
    assert any("must be clearly marked as retired" in p for p in problems)


def test_validate_policy_still_catches_missing_fields_and_low_entropy(monkeypatch):
    original = copy.deepcopy(SM.SECRET_CLASSES)   # snapshot BEFORE any monkeypatch, so each variant starts clean

    bad = copy.deepcopy(original)
    bad["corpus_secret"].pop("owner")
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    assert any("corpus_secret: field mismatch" in p for p in SM.validate_policy())

    bad2 = copy.deepcopy(original)
    bad2["corpus_secret"]["minimum_entropy_bytes"] = 8
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad2)
    assert any("entropy floor too low" in p for p in SM.validate_policy())


# --------------------------------- item 4: permitted_readers checked INDEPENDENTLY of access_scope, catching a
# contradiction where one field is correct and the other still names the wrong role
def test_validate_policy_catches_corpus_secret_permitted_readers_contradicting_a_correct_access_scope(monkeypatch):
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    assert "generator" in bad["corpus_secret"]["access_scope"].lower()   # access_scope stays CORRECT
    bad["corpus_secret"]["permitted_readers"] = ["qualification runner identity"]   # but permitted_readers is WRONG
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_policy()
    assert any("corpus_secret" in p and "permitted_readers" in p for p in problems)
    # the access_scope-only checks must NOT also fire -- proving this is a genuinely independent check, not a
    # duplicate of the access_scope logic re-reading the same field
    assert not any("corpus_secret: access_scope" in p for p in problems)


def test_validate_policy_catches_vault_public_key_permitted_readers_contradicting_a_correct_access_scope(monkeypatch):
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    assert "generator" in bad["vault_public_key"]["access_scope"].lower()
    bad["vault_public_key"]["permitted_readers"] = ["creation-time-verifier identity"]
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_policy()
    assert any("vault_public_key" in p and "permitted_readers" in p for p in problems)
    assert not any("vault_public_key: access_scope" in p for p in problems)


def test_validate_policy_catches_vault_private_key_permitted_readers_contradicting_a_correct_access_scope(monkeypatch):
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    assert "qualification" in bad["vault_private_key"]["access_scope"].lower() or "verifier" in bad["vault_private_key"]["access_scope"].lower()
    bad["vault_private_key"]["permitted_readers"] = ["generator identity"]   # the exact credential-boundary mistake this class must never allow
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_policy()
    assert any("vault_private_key" in p and "permitted_readers" in p for p in problems)
    assert not any("vault_private_key: access_scope" in p for p in problems)


def test_validate_policy_catches_access_scope_contradicting_a_correct_permitted_readers(monkeypatch):
    """The mirror image: permitted_readers is correct, access_scope is the one that's wrong -- proving neither
    field is treated as authoritative over the other; both are independently checked."""
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    assert bad["corpus_secret"]["permitted_readers"] == ["generator identity"]   # permitted_readers stays CORRECT
    bad["corpus_secret"]["access_scope"] = "qualification runner process only"   # but access_scope is WRONG
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_policy()
    assert any("corpus_secret: access_scope" in p for p in problems)
    assert not any("corpus_secret: permitted_readers" in p for p in problems)


def test_env_var_cross_reference_catches_drift(monkeypatch):
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    bad["vault_private_key"]["env_var"] = "ORNEUR_GENESIS_V2_WRONG_VAR_NAME"
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_env_var_cross_references()
    assert any("vault_private_key" in p for p in problems)


def test_env_var_cross_reference_catches_a_missing_class(monkeypatch):
    bad = copy.deepcopy(SM.SECRET_CLASSES)
    del bad["corpus_secret"]
    monkeypatch.setattr(SM, "SECRET_CLASSES", bad)
    problems = SM.validate_env_var_cross_references()
    assert any("corpus_secret" in p and "missing" in p for p in problems)


# ---------------------------------------------------------------- probes remain presence-only
def test_probe_secret_manager_never_returns_a_secret_value():
    r = SM.probe_secret_manager()
    assert set(r) == {"mechanism", "available", "note"}
    assert isinstance(r["available"], bool)


def test_keychain_entry_present_fails_closed_when_keychain_unavailable(monkeypatch):
    monkeypatch.setattr(SM, "macos_keychain_available", lambda: False)
    assert SM.keychain_entry_present("svc", "acct") is False
