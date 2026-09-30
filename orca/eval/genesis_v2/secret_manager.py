"""Secret-manager boundary contract: the policy every V2 secret class must satisfy, plus a read-only probe for a locally available manager.

Nothing here ever handles, stores, prints or returns a real secret value: `probe_*` functions test only for PRESENCE/ABSENCE of an entry by name,
using the platform's own tool (macOS Keychain via `/usr/bin/security`), and every value in SECRET_CLASSES is policy metadata, not a secret.

CURRENT ARCHITECTURE: the vault uses an X25519 keypair split into two SEPARATELY scoped secret classes --
`vault_public_key` (generator-scoped) and `vault_private_key` (creation-time-verifier / qualification-runner-scoped)
-- never a single symmetric key usable by both roles. `corpus_secret` belongs to the GENERATOR role (it seeds
generation), not to any reader role -- an earlier draft of this policy had it backwards. `aes_encryption_key_LEGACY_RETIRED`
is kept ONLY for historical/audit continuity with the retired symmetric-key architecture; it is not read by any
code path and must never be presented as an active contract -- see `env_var` on each entry, which cross-references
the REAL environment-variable constants in `spec.py` (`None` for entries with no single ORNEUR env var, e.g. personal
signing keys) and is checked by `validate_env_var_cross_references()` below.
"""
from __future__ import annotations

import shutil
import subprocess

SECRET_CLASSES = {
    "corpus_secret": {"owner": "ORNEUR owner", "generation_method": "orca.eval.genesis_v2.secret.generate_secret() on a trusted, offline-capable machine",
                      "minimum_entropy_bytes": 32, "storage_location_class": "SECRET_MANAGER_ONLY", "access_scope": "generator process only",
                      "permitted_readers": ["generator identity"], "rotation_policy": "rotate by creating a fresh corpus version; never reuse across eval versions",
                      "revocation_policy": "delete from the secret manager; retire the eval version it was bound to", "backup_recovery_policy": "single secret-manager backup with access control; never a plaintext file",
                      "incident_response_rule": "any suspected exposure retires the eval version and requires a fresh secret + fresh corpus",
                      "env_var": "ORNEUR_GENESIS_V2_CORPUS_SECRET"},
    "vault_public_key": {"owner": "ORNEUR owner", "generation_method": "orca.eval.genesis_v2.store.generate_vault_keypair() on a trusted machine -- ONLY the public half is ever given to the generator",
                         "minimum_entropy_bytes": 32, "storage_location_class": "SECRET_MANAGER_ONLY", "access_scope": "generator process only",
                         "permitted_readers": ["generator identity"], "rotation_policy": "rotate by generating a fresh X25519 keypair and creating a fresh corpus version under it; never reuse across eval versions",
                         "revocation_policy": "delete from the secret manager once the corpus version it protects is retired", "backup_recovery_policy": "backed up separately from the private half AND from ciphertext, with two custodians",
                         "incident_response_rule": "public-key exposure alone cannot decrypt anything (see store.EncryptedVaultWriter's own docstring) -- still revoke and re-authorize the exposed generator identity",
                         "env_var": "ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY"},
    "vault_private_key": {"owner": "ORNEUR owner", "generation_method": "orca.eval.genesis_v2.store.generate_vault_keypair() on a trusted machine -- given ONLY to the creation-time-verifier / qualification-runner identity, NEVER the generator",
                          "minimum_entropy_bytes": 32, "storage_location_class": "SECRET_MANAGER_ONLY", "access_scope": "creation-time-verifier / qualification-runner process only",
                          "permitted_readers": ["creation-time-verifier identity", "qualification runner identity"], "rotation_policy": "rotate by generating a fresh X25519 keypair and creating a fresh corpus version under it; never reuse across eval versions",
                          "revocation_policy": "delete from the secret manager once the corpus version it protects is retired", "backup_recovery_policy": "backed up separately from the public half AND from ciphertext, with two custodians, never together",
                          "incident_response_rule": "private-key loss or compromise = corpus loss; issue a fresh corpus version under a fresh keypair",
                          "env_var": "ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY"},
    "aes_encryption_key_LEGACY_RETIRED": {"owner": "ORNEUR owner", "generation_method": "RETIRED -- os.urandom(32), a single symmetric key usable for both encrypt and decrypt. Superseded by vault_public_key/vault_private_key above.",
                          "minimum_entropy_bytes": 32, "storage_location_class": "SECRET_MANAGER_ONLY", "access_scope": "RETIRED -- kept for historical/audit continuity only; no code path reads this class",
                          "permitted_readers": ["RETIRED -- no active reader; see vault_public_key/vault_private_key"], "rotation_policy": "N/A -- retired",
                          "revocation_policy": "N/A -- retired; any remaining secret-manager entry under the legacy env var name should simply be deleted (see GENESIS_CAPABILITY_EVAL_V2_OWNER_VAULT_PROCEDURE.md's legacy-var warning)",
                          "backup_recovery_policy": "N/A -- retired", "incident_response_rule": "N/A -- retired; this class protects nothing currently in use",
                          "env_var": "ORNEUR_GENESIS_V2_ENCRYPTION_KEY (RETIRED -- unused by current code; store.owner_setup_preflight() warns if still set)"},
    "authority_signing_key": {"owner": "the registered authority identity (OWNER/DELEGATED_OWNER)", "generation_method": "Ed25519 keypair generated by that individual on their own trusted device; only the public half is ever transmitted",
                              "minimum_entropy_bytes": 32, "storage_location_class": "PERSONAL_SECRET_MANAGER_OR_HARDWARE_KEY", "access_scope": "that individual only",
                              "permitted_readers": ["the registered authority identity"], "rotation_policy": "rotate on a schedule set by the owner, or immediately on suspected compromise; publish the new public key, mark the old record revoked",
                              "revocation_policy": "set revoked=true on the AUTHORITY_REGISTRY.json record; a revoked key never verifies again",
                              "backup_recovery_policy": "personal responsibility of the authority identity; ORNEUR never holds this key", "incident_response_rule": "revoke immediately; treat every authorization signed after the suspected compromise window as void",
                              "env_var": None},
    "reviewer_signing_key": {"owner": "the registered reviewer identity", "generation_method": "Ed25519 keypair generated by that individual on their own trusted device",
                             "minimum_entropy_bytes": 32, "storage_location_class": "PERSONAL_SECRET_MANAGER_OR_HARDWARE_KEY", "access_scope": "that individual only",
                             "permitted_readers": ["the registered reviewer identity"], "rotation_policy": "same as authority_signing_key",
                             "revocation_policy": "set revoked=true on the REVIEWER_REGISTRY.json record", "backup_recovery_policy": "personal responsibility of the reviewer identity",
                             "incident_response_rule": "revoke immediately; treat every review signed after the suspected compromise window as INCONCLUSIVE pending re-review",
                             "env_var": None},
    "runner_credential": {"owner": "ORNEUR owner", "generation_method": "least-privilege credential minted by the private store / secret manager for the qualification runner identity only",
                          "minimum_entropy_bytes": 32, "storage_location_class": "SECRET_MANAGER_ONLY", "access_scope": "the qualification runner process only; never public CI",
                          "permitted_readers": ["qualification runner identity"], "rotation_policy": "rotate every 90 days or on personnel/runner change",
                          "revocation_policy": "revoke at the store/secret-manager side; deregister the runner identity", "backup_recovery_policy": "none required (reissue rather than restore)",
                          "incident_response_rule": "revoke immediately; audit every private-store access since the last known-good rotation",
                          "env_var": "ORNEUR_GENESIS_V2_STORE_TOKEN"},
}

REQUIRED_POLICY_FIELDS = ("owner", "generation_method", "minimum_entropy_bytes", "storage_location_class", "access_scope", "permitted_readers",
                          "rotation_policy", "revocation_policy", "backup_recovery_policy", "incident_response_rule", "env_var")


def validate_policy() -> list:
    """Structural (field-presence) AND semantic (role-scope correctness) validation. A policy that merely has the
    right FIELDS but assigns the wrong ROLE to a secret class (e.g. the corpus secret scoped to a reader role, or
    the vault private key scoped to the generator) is just as wrong as a missing field, so both are checked here."""
    p = []
    for name, pol in SECRET_CLASSES.items():
        if set(pol) != set(REQUIRED_POLICY_FIELDS):
            p.append(f"{name}: field mismatch")
            continue
        if pol["minimum_entropy_bytes"] < 32:
            p.append(f"{name}: entropy floor too low")

    # Semantic cross-checks against the CURRENT X25519 architecture and the identity-separation model this
    # program enforces in code (generator_registry.py, operational_boundary.py) -- not merely field presence.
    corpus = SECRET_CLASSES.get("corpus_secret")
    if corpus is not None:
        scope = corpus["access_scope"].lower()
        if "generator" not in scope:
            p.append("corpus_secret: access_scope must name the generator role -- it seeds generation, not a reader role")
        if "qualification" in scope or "verifier" in scope:
            p.append("corpus_secret: access_scope must NOT name a reader role (qualification runner / verifier)")

    pub = SECRET_CLASSES.get("vault_public_key")
    if pub is not None:
        scope = pub["access_scope"].lower()
        if "generator" not in scope:
            p.append("vault_public_key: access_scope must name the generator role")
        if "qualification" in scope or "verifier" in scope:
            p.append("vault_public_key: access_scope must NOT name a reader role -- it is the generator's own key")

    priv = SECRET_CLASSES.get("vault_private_key")
    if priv is not None:
        scope = priv["access_scope"].lower()
        if "generator" in scope:
            p.append("vault_private_key: access_scope must NEVER name the generator role")
        if "qualification" not in scope and "verifier" not in scope:
            p.append("vault_private_key: access_scope must name a reader role (creation-time-verifier / qualification runner)")

    if "aes_encryption_key_LEGACY_RETIRED" not in SECRET_CLASSES:
        p.append("the retired symmetric-key class must be kept (clearly marked RETIRED) for historical/audit continuity, not deleted")
    elif "retired" not in SECRET_CLASSES["aes_encryption_key_LEGACY_RETIRED"]["access_scope"].lower():
        p.append("aes_encryption_key_LEGACY_RETIRED: must be clearly marked as retired in its own access_scope, never presented as an active contract")

    return p


def validate_env_var_cross_references() -> list:
    """Confirms each policy entry's declared `env_var` genuinely matches the REAL constant in spec.py -- catches
    the class of drift where a policy document and the actual code silently disagree about which variable name
    protects which secret class."""
    from orca.eval.genesis_v2 import spec
    expect = {"corpus_secret": spec.SECRET_ENV, "vault_public_key": spec.VAULT_PUBLIC_KEY_ENV,
              "vault_private_key": spec.VAULT_PRIVATE_KEY_ENV, "runner_credential": spec.STORE_TOKEN_ENV}
    p = []
    for name, real_var in expect.items():
        pol = SECRET_CLASSES.get(name)
        if pol is None:
            p.append(f"{name}: missing from SECRET_CLASSES entirely")
            continue
        if pol.get("env_var") != real_var:
            p.append(f"{name}: env_var {pol.get('env_var')!r} does not match spec.py's real constant {real_var!r}")
    return p


def macos_keychain_available() -> bool:
    return shutil.which("security") is not None


def keychain_entry_present(service: str, account: str) -> bool:
    """PRESENCE-only probe: returns whether an entry exists, never its value. False on any error (fail closed, not 'assume present')."""
    if not macos_keychain_available():
        return False
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def probe_secret_manager() -> dict:
    """Read-only readiness probe. Never touches a real secret value; reports only mechanism availability."""
    return {"mechanism": "macos_keychain" if macos_keychain_available() else None, "available": macos_keychain_available(),
            "note": "presence-only probe; this function never reads or returns a secret value"}
