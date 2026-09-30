"""Read-only evidence snapshot script: aggregates existing read-only checks, never touches a secret, never
activates/authorizes/generates anything, always exits 0. Item 3 of the deployment-decision-accuracy-closure phase:
role-aware collection, an explicit security contract, and tests against SYNTHETIC POPULATED environments -- not only
the current unconfigured baseline. Item 3 of the authenticated-transfer-and-evidence-integrity-closure phase:
`_safe()` no longer forwards ANY part of an underlying exception's message text (previously scrubbed only via a
64-hex-character regex, which the audit correctly flagged as insufficient alone -- it would miss a base64-encoded
secret, a variable-length secret, or a secret embedded in a path). It now returns a fixed, allowlisted error code
plus a static per-check description, proven below against hex-, base64-, variable-length-, and path-shaped
adversarial exception messages."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "genesis_v2_evidence_snapshot.py"


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
    else:
        pytest.importorskip("cryptography")


def _run(*extra_args, env=None):
    full_env = {**os.environ, **(env or {})}
    return subprocess.run([sys.executable, str(SCRIPT), *extra_args], cwd=ROOT, capture_output=True, text=True, env=full_env)


def _load_module():
    """Import the script directly (not via subprocess) so _safe() can be unit-tested in-process."""
    spec = importlib.util.spec_from_file_location("genesis_v2_evidence_snapshot", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _clean_env(**extra):
    """A minimal env with no pre-existing ORNEUR_GENESIS vars, plus whatever synthetic values are supplied."""
    base = {k: v for k, v in os.environ.items() if not k.startswith("ORNEUR_GENESIS")}
    base.update(extra)
    return base


def test_evidence_snapshot_runs_read_only_and_exits_zero_without_a_vault():
    p = _run(env=_clean_env())
    assert p.returncode == 0
    doc = json.loads(p.stdout)
    assert doc["document"] == "GENESIS_V2_EVIDENCE_SNAPSHOT"
    assert doc["vault_isolation"]["status"] == "NOT_CONFIGURED"
    for key in ("owner_preflight", "privacy_scan", "role_preflight_owner", "role_preflight_generator", "role_preflight_verifier"):
        assert key in doc


def test_evidence_snapshot_includes_vault_check_when_vault_given(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)
    p = _run("--vault", str(vault), env=_clean_env())
    assert p.returncode == 0
    doc = json.loads(p.stdout)
    assert "pass" in doc["vault_isolation"]   # real verify_vault_isolation() output, not the NOT_CONFIGURED placeholder


def test_evidence_snapshot_never_contains_a_real_secret_shaped_value():
    p = _run(env=_clean_env())
    assert p.returncode == 0
    blob = p.stdout
    import re
    assert not re.search(r"\b[0-9a-fA-F]{64}\b", blob)
    for forbidden in ("-----BEGIN", "/Users/", "/home/"):
        assert forbidden not in blob


def test_evidence_snapshot_role_preflights_agree_with_direct_calls():
    """Cross-check: the script's aggregated role_preflight_* sections must match calling the same functions directly
    -- proves the script is genuinely composing existing functions, not reimplementing or diverging from them."""
    from orca.eval.genesis_v2 import store as ST
    p = _run(env=_clean_env())
    doc = json.loads(p.stdout)
    assert doc["role_preflight_owner"]["status"] == ST.owner_setup_preflight()["status"]
    assert doc["role_preflight_generator"]["status"] == ST.generator_setup_preflight()["status"]
    assert doc["role_preflight_verifier"]["status"] == ST.verifier_setup_preflight()["status"]


def test_evidence_snapshot_never_writes_anything(tmp_path):
    """No registry, vault, or ledger write occurs -- confirmed by running twice and diffing the repository's own
    tracked/untracked state via git, which must show no new files this script could have created."""
    before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    _run(env=_clean_env())
    after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    assert before == after


# ---------------------------------------------------------------- item 3: role-awareness and the security contract
def test_evidence_snapshot_declares_its_own_security_contract():
    p = _run(env=_clean_env())
    doc = json.loads(p.stdout)
    sc = doc["security_contract"]
    assert sc["checks_that_inspect_actual_vault_key_bytes"] == ["role_preflight_owner (X25519 pair-matching step only)"]
    assert sc["checks_that_decode_and_validate_the_corpus_secret"] == ["role_preflight_generator", "role_preflight_owner"]
    assert sc["checks_that_never_touch_the_corpus_secret_at_all"] == ["role_preflight_verifier", "owner_preflight", "privacy_scan", "vault_isolation"]
    assert "role_preflight_generator" in " ".join(sc["checks_that_only_check_vault_key_shape"])
    assert "role_preflight_verifier" in " ".join(sc["checks_that_only_check_vault_key_shape"])
    assert "never a secret value itself" in sc["values_ever_emitted_in_this_report"]
    assert "NO part" in sc["values_ever_emitted_in_this_report"]


def test_evidence_snapshot_never_claims_cross_environment_separation_evidence():
    """The core item-3 correction: running all three role preflights in one invocation must never be presented as
    proof that two real deployments keep credentials apart."""
    p = _run(env=_clean_env())
    doc = json.loads(p.stdout)
    assert doc["cross_environment_separation_evidence"] == "NOT_ESTABLISHED_BY_THIS_TOOL"
    assert doc["role_scope_of_this_invocation"] == "all"
    assert "NOT proof" in doc["role_scope_note"] or "not proof" in doc["role_scope_note"].lower() or "NOT " in doc["role_scope_note"]


def test_evidence_snapshot_role_flag_runs_only_the_requested_role(tmp_path):
    _need_crypto()
    from orca.eval.genesis_v2 import store as ST
    priv, pub = ST.generate_vault_keypair()
    env = _clean_env(**{"ORNEUR_GENESIS_V2_PRIVATE_STORE": "ENCRYPTED_ARTIFACT:/fake/vault",
                         "ORNEUR_GENESIS_V2_CORPUS_SECRET": os.urandom(32).hex(),
                         "ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY": pub.hex()})
    p = _run("--role", "generator", env=env)
    assert p.returncode == 0
    doc = json.loads(p.stdout)
    assert "role_preflight_generator" in doc
    assert "role_preflight_owner" not in doc and "role_preflight_verifier" not in doc
    assert doc["role_scope_of_this_invocation"] == "generator"
    assert doc["role_preflight_generator"]["status"] == "GENERATOR_CONFIGURED_UNVERIFIED"


def test_evidence_snapshot_role_flag_for_verifier_with_synthetic_populated_environment(tmp_path):
    """Tests against a SYNTHETIC POPULATED environment, not only the unconfigured baseline -- required by item 3."""
    _need_crypto()
    from orca.eval.genesis_v2 import store as ST
    priv, pub = ST.generate_vault_keypair()
    env = _clean_env(**{"ORNEUR_GENESIS_V2_PRIVATE_STORE": "ENCRYPTED_ARTIFACT:/fake/vault",
                         "ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY": priv.hex()})
    p = _run("--role", "verifier", env=env)
    assert p.returncode == 0
    doc = json.loads(p.stdout)
    assert "role_preflight_verifier" in doc
    assert "role_preflight_owner" not in doc and "role_preflight_generator" not in doc
    assert doc["role_preflight_verifier"]["status"] == "VERIFIER_CONFIGURED_UNVERIFIED"
    # the private key hex value itself never appears in the report, even though it was genuinely read/used
    assert priv.hex() not in p.stdout


def test_evidence_snapshot_all_roles_against_a_shared_environment_flags_the_generator_violation(tmp_path):
    """The dangerous scenario item 3 exists to prevent misinterpreting: BOTH key halves present in ONE environment
    (e.g. an admin/setup machine). role_preflight_generator must report the violation, and the report must still
    never claim this proves or disproves real separation -- cross_environment_separation_evidence stays
    NOT_ESTABLISHED_BY_THIS_TOOL regardless."""
    _need_crypto()
    from orca.eval.genesis_v2 import store as ST
    priv, pub = ST.generate_vault_keypair()
    env = _clean_env(**{"ORNEUR_GENESIS_V2_PRIVATE_STORE": "ENCRYPTED_ARTIFACT:/fake/vault",
                         "ORNEUR_GENESIS_V2_CORPUS_SECRET": os.urandom(32).hex(),
                         "ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY": pub.hex(),
                         "ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY": priv.hex()})
    p = _run(env=env)
    assert p.returncode == 0
    doc = json.loads(p.stdout)
    assert any(v["item"] == "ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY" for v in doc["role_preflight_generator"]["violations"])
    assert doc["role_preflight_verifier"]["status"] == "VERIFIER_CONFIGURED_UNVERIFIED"   # verifier's own check still passes on its own terms
    assert doc["cross_environment_separation_evidence"] == "NOT_ESTABLISHED_BY_THIS_TOOL"   # never upgraded, even here
    assert priv.hex() not in p.stdout and pub.hex() not in p.stdout


def test_evidence_snapshot_owner_role_with_a_synthetic_matching_keypair(tmp_path):
    _need_crypto()
    from orca.eval.genesis_v2 import store as ST
    priv, pub = ST.generate_vault_keypair()
    env = _clean_env(**{"ORNEUR_GENESIS_V2_PRIVATE_STORE": "ENCRYPTED_ARTIFACT:/fake/vault",
                         "ORNEUR_GENESIS_V2_CORPUS_SECRET": os.urandom(32).hex(),
                         "ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY": pub.hex(),
                         "ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY": priv.hex()})
    p = _run("--role", "owner", env=env)
    assert p.returncode == 0
    doc = json.loads(p.stdout)
    assert doc["role_preflight_owner"]["status"] == "PRIVATE_STORAGE_CONFIGURED_UNVERIFIED"
    assert priv.hex() not in p.stdout and pub.hex() not in p.stdout


# ---------------------------------------------------------------- item 3: fixed, allowlisted error codes (never a
# regex-based scrub of exception message text) -- adversarial coverage across hex, base64, variable-length, and
# path-shaped secrets, plus ordinary and deliberately hostile exception strings.
def test_safe_wrapper_never_forwards_any_part_of_a_64_hex_secret_shaped_exception_message():
    mod = _load_module()
    fake_secret = "ab" * 32   # exactly the shape the OLD regex-based scrubber targeted

    def boom():
        raise RuntimeError(f"leaked {fake_secret} in a hypothetical bug")
    result = mod._safe("role_preflight_generator", boom)
    blob = json.dumps(result)
    assert fake_secret not in blob
    assert "leaked" not in blob and "hypothetical bug" not in blob
    assert result["error_code"] == "UNEXPECTED_EXCEPTION"
    assert result["exception_type"] == "RuntimeError"
    assert result["description"] == mod._CHECK_DESCRIPTIONS["role_preflight_generator"]


def test_safe_wrapper_never_forwards_a_base64_shaped_secret_the_old_hex_regex_would_have_missed():
    """The audit's core point: a 64-hex-char regex would never have caught THIS shape at all -- proving the fix
    does not merely widen the regex, it removes exception-text forwarding entirely."""
    import base64
    mod = _load_module()
    fake_secret_b64 = base64.b64encode(os.urandom(32)).decode()

    def boom():
        raise ValueError(f"corpus secret {fake_secret_b64} failed validation")
    result = mod._safe("role_preflight_owner", boom)
    blob = json.dumps(result)
    assert fake_secret_b64 not in blob
    assert "corpus secret" not in blob and "failed validation" not in blob


def test_safe_wrapper_never_forwards_a_variable_length_secret():
    mod = _load_module()
    for length in (16, 33, 47, 129):
        fake_secret = os.urandom(length).hex()

        def boom(s=fake_secret):
            raise RuntimeError(f"bad secret: {s}")
        result = mod._safe("role_preflight_verifier", boom)
        blob = json.dumps(result)
        assert fake_secret not in blob
        assert "bad secret" not in blob


def test_safe_wrapper_never_forwards_a_secret_embedded_in_a_filesystem_path():
    """A secret-shaped value embedded inside a path (e.g. a key file whose name or containing directory leaked into
    an exception message) is exactly the kind of thing a 64-hex regex might miss depending on surrounding
    punctuation -- proving the fix removes forwarding entirely, not just widening the pattern."""
    mod = _load_module()
    fake_secret = "ef" * 32
    hostile_path = f"/Users/owner/.secrets/vault_private_key_{fake_secret}.pem"

    def boom():
        raise FileNotFoundError(f"could not read key material at {hostile_path}")
    result = mod._safe("vault_isolation", boom)
    blob = json.dumps(result)
    assert fake_secret not in blob
    assert hostile_path not in blob
    assert "/Users/owner" not in blob


def test_safe_wrapper_never_forwards_an_adversarial_exception_string_even_one_crafted_to_look_safe():
    """An exception message deliberately crafted to look like harmless diagnostic text (no hex/base64 shape at all)
    must still never appear -- proving the guarantee does not depend on recognizing any particular shape."""
    mod = _load_module()

    class _AdversarialError(RuntimeError):
        pass

    def boom():
        raise _AdversarialError("this looks totally safe but actually embeds owner_password=hunter2 right here")
    result = mod._safe("owner_preflight", boom)
    blob = json.dumps(result)
    assert "hunter2" not in blob
    assert "totally safe" not in blob
    assert result["exception_type"] == "_AdversarialError"
    assert result["description"] == mod._CHECK_DESCRIPTIONS["owner_preflight"]


def test_safe_wrapper_uses_the_unknown_check_description_for_an_unrecognized_label():
    mod = _load_module()

    def boom():
        raise RuntimeError("some detail that must never appear")
    result = mod._safe("some_future_check_not_yet_allowlisted", boom)
    assert result["description"] == mod._UNKNOWN_CHECK_DESCRIPTION
    assert "some detail that must never appear" not in json.dumps(result)


def test_safe_wrapper_returns_the_underlying_value_unchanged_on_success():
    mod = _load_module()
    result = mod._safe("owner_preflight", lambda: {"status": "OK", "missing": []})
    assert result == {"status": "OK", "missing": []}
