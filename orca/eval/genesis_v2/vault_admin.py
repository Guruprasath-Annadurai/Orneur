"""Vault ACTIVATION mechanics (owner-side, local). Proves the encrypted-artifact backend genuinely works at a real, isolated, on-machine path,
using an EPHEMERAL TEST X25519 keypair (store.generate_vault_keypair()) and TEST plaintext that are both destroyed immediately after — never the
real corpus secret or vault key, never real benchmark content. Exercises the SAME production classes operational_boundary.py uses
(store.EncryptedVaultWriter to write, store.EncryptedVaultReader to read) — never the legacy symmetric store.EncryptedFileStore, which exists only
for backward-compatible reference and is not part of this activation path. Produces a PUBLIC-SAFE verification record: no path, no key, no
plaintext, only hashes/results.

Schema (`GENESIS_V2_VAULT_VERIFICATION.json`): store_type, verification_timestamp, schema_version, store_descriptor_digest (one-way hash of the
resolved path — cannot be used to reconstruct the location), permission_policy_result, repository_isolation_result, encryption_policy_result,
key_isolation_result (the writer object holds no private-key material and exposes no read method), backup_policy_result, verifier_code_sha, pass,
evidence_digests.

SAFETY: `activate_test_vault()` NEVER deletes pre-existing contents of the `vault_dir` it is given, in any code
path, including when isolation verification fails. It tracks exactly the paths it itself created during THIS
invocation and removes only those — see that function's own docstring for the full guarantee, and
`tests/test_genesis_v2_vault_ledger_activation.py`'s sentinel-preservation and failure-path regression tests.

EVIDENCE, NOT ASSUMPTIONS: every field in the produced record depends on a genuinely executed check performed
during THIS invocation. In particular `backup_policy_result` is computed from an ACTUAL `export_backup()` call
verified byte-for-byte against the live ciphertext (never hardcoded), executed BEFORE the destructive
tamper/truncation tests below it so the backup reflects real, uncorrupted content.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from orca.eval.genesis_v2 import store as ST
from orca.eval.genesis_v2 import vault_verify as VV

SCHEMA_VERSION = "genesis-v2-vault-verification/1"
RECORD_PATH = "docs/orneur/phase-21/GENESIS_V2_VAULT_VERIFICATION.json"
_TEST_MARKER = b"GENESIS-V2-VAULT-ACTIVATION-TEST-PLAINTEXT-DO-NOT-USE-AS-REAL-CORPUS"


def _verifier_code_sha() -> str:
    src = Path(__file__).read_text() + Path(inspect.getfile(VV)).read_text() + Path(inspect.getfile(ST)).read_text()
    return hashlib.sha256(src.encode()).hexdigest()


def _descriptor_digest(vault_dir: Path) -> str:
    """One-way: proves later that the SAME vault was checked, without letting a reader recover the path from the record."""
    return hashlib.sha256(("genesis-v2-vault-descriptor|" + str(Path(vault_dir).resolve())).encode()).hexdigest()


def activate_test_vault(vault_dir: Path, repo_root: Path) -> dict:
    """Round-trips a TEST corpus through the REAL production architecture -- store.EncryptedVaultWriter (public key
    only) to write, store.EncryptedVaultReader (private key) to read -- using an EPHEMERAL X25519 test keypair,
    checks wrong-key failure, confirms the WRITER itself holds no private-key material (genuine key isolation, not
    just a round-trip check), GENUINELY verifies the ciphertext-only backup (byte-for-byte, before any destructive
    test touches the vault's own copy), THEN checks tamper/truncation detection, then destroys ONLY the specific
    artifacts THIS invocation created, then destroys the keys. Returns {'pass': bool, 'checks': {...}, 'error': str|None}.

    SAFETY: this function NEVER removes pre-existing contents of `vault_dir`. It tracks exactly which paths it
    itself created (the one `corpus_id` subdirectory it wrote, and the one backup directory it created) and, in its
    `finally` block, removes ONLY those tracked paths -- never `vault_dir.iterdir()`. If `vault_dir` already
    contained other files or directories before this call (a real vault the owner is checking, a directory reused
    by mistake), they are left completely untouched, whether this call succeeds, fails, or raises. If isolation
    verification fails before anything is created, the tracked-paths list stays empty and nothing is removed at
    all -- the early-failure path performs NO filesystem writes to `vault_dir` in the first place."""
    vault_dir = Path(vault_dir)
    checks: dict = {}
    created_paths: list = []          # exactly what THIS invocation created; the only things ever removed below
    priv, pub = ST.generate_vault_keypair()   # TEST keypair only; never written to disk; discarded at the end of this function
    corpus_id = "gce2c-" + os.urandom(8).hex()   # a fresh, unique corpus id -- collision with any pre-existing content is not credible
    try:
        iso = VV.verify_vault_isolation(vault_dir, repo_root)
        checks["repository_isolation"] = iso["pass"]
        checks.update({f"isolation.{k}": v for k, v in iso.get("checks", {}).items()})
        if not iso["pass"]:
            return {"pass": False, "checks": checks, "error": "vault is not isolated from the repository"}

        writer = ST.EncryptedVaultWriter(vault_dir, pub)
        checks["writer_exposes_no_read_method"] = not hasattr(writer, "read_split")
        checks["writer_holds_no_private_key_bytes"] = not any(v == priv for v in vars(writer).values())
        plain = {"SCREEN": _TEST_MARKER + b"-SCREEN", "QUALIFICATION_HOLDOUT": _TEST_MARKER + b"-HOLDOUT"}
        digest = writer.write_corpus(corpus_id, plain)
        created_paths.append(vault_dir / corpus_id)   # the ONLY thing write_corpus created; track it for cleanup
        checks["round_trip_write"] = True

        reader = ST.EncryptedVaultReader(vault_dir, priv)
        got = {s: reader.read_split(corpus_id, s, expected_corpus_digest=digest) for s in plain}
        checks["round_trip_read_matches"] = got == plain

        wrong_priv, _ = ST.generate_vault_keypair()
        wrong_reader = ST.EncryptedVaultReader(vault_dir, wrong_priv)
        try:
            wrong_reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=digest)
            checks["wrong_key_fails"] = False
        except ST.PrivateStorageIntegrityError:
            checks["wrong_key_fails"] = True

        # GENUINE ciphertext-only backup verification -- BEFORE any destructive tamper/truncation test below, so the
        # backup is verified against the real, uncorrupted vault content, and the result is never hardcoded.
        backup_dir = vault_dir.parent / (vault_dir.name + "-backup-test-" + os.urandom(4).hex())   # uniquely named per invocation
        try:
            names = reader.export_backup(corpus_id, backup_dir, expected_corpus_digest=digest)
            created_paths.append(backup_dir)
            expected_names = {"SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"}
            names_match = set(names) == expected_names
            live_dir = vault_dir / corpus_id
            content_matches = names_match and all((backup_dir / n).read_bytes() == (live_dir / n).read_bytes() for n in expected_names)
            no_plaintext_leaked = names_match and not any(
                _TEST_MARKER in (backup_dir / n).read_bytes() for n in expected_names)
            checks["backup_ciphertext_only"] = bool(names_match and content_matches and no_plaintext_leaked)
        except ST.PrivateStorageIntegrityError as e:
            checks["backup_ciphertext_only"] = False
            checks["backup_test_error"] = f"NOT_TESTED: export_backup raised {type(e).__name__} against a freshly-written, uncorrupted corpus"

        target = vault_dir / corpus_id / "SCREEN.enc"
        blob = bytearray(target.read_bytes())
        blob[-3] ^= 0xFF
        os.chmod(target, 0o600)
        target.write_bytes(bytes(blob))
        os.chmod(target, 0o400)
        try:
            reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=digest)
            checks["tamper_detected"] = False
        except ST.PrivateStorageIntegrityError:
            checks["tamper_detected"] = True
        os.chmod(target, 0o600)
        target.write_bytes(bytes(blob)[:-40])
        os.chmod(target, 0o400)
        try:
            reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=digest)
            checks["truncation_detected"] = False
        except ST.PrivateStorageIntegrityError:
            checks["truncation_detected"] = True

        checks["encryption_algorithm_is_x25519_hkdf_aes_256_gcm"] = writer.describe()["cipher"] == "X25519+HKDF-SHA256+AES-256-GCM"
        try:
            writer.write_corpus(corpus_id, plain)   # a genuine second write attempt against the SAME corpus_id, executed right here
            checks["write_once_publication"] = False
        except FileExistsError:
            checks["write_once_publication"] = True
        checks["seal_last_publication"] = (vault_dir / corpus_id / "SEAL.enc").exists()   # SEAL.enc is never touched by the SCREEN.enc-only tamper/truncation tests above
        checks["no_plaintext_temp_survives"] = not list((vault_dir / corpus_id).glob(".tmp-*"))
        vs = VV.P.scan_vault_dir(vault_dir)
        checks["permission_and_no_plaintext_siblings"] = vs["pass"]
        return {"pass": all(bool(v) for v in checks.values() if not isinstance(v, str)), "checks": checks, "error": None}
    except Exception as e:
        checks["exception"] = False
        return {"pass": False, "checks": checks, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    finally:
        priv = b"\x00" * 32          # best-effort scrub of the local reference
        del priv
        for p in created_paths:      # remove ONLY what this invocation created -- never touch anything else in vault_dir
            if p.exists():
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)


def build_storage_verification_record(activation: dict, *, vault_dir: Path) -> dict:
    c = activation["checks"]
    rec = {
        "document": "GENESIS_V2_VAULT_VERIFICATION", "schema_version": SCHEMA_VERSION, "store_type": "ENCRYPTED_ARTIFACT",
        "verification_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "store_descriptor_digest": _descriptor_digest(vault_dir),
        "permission_policy_result": bool(c.get("permission_and_no_plaintext_siblings") and c.get("isolation.vault_permissions_and_no_plaintext_siblings")),
        "repository_isolation_result": bool(c.get("repository_isolation")),
        "encryption_policy_result": bool(c.get("encryption_algorithm_is_x25519_hkdf_aes_256_gcm") and c.get("wrong_key_fails") and c.get("tamper_detected")
                                         and c.get("truncation_detected") and c.get("seal_last_publication") and c.get("no_plaintext_temp_survives")),
        "key_isolation_result": bool(c.get("writer_exposes_no_read_method") and c.get("writer_holds_no_private_key_bytes")),
        "backup_policy_result": bool(c.get("backup_ciphertext_only")),
        "verifier_code_sha256": _verifier_code_sha(),
        "pass": bool(activation["pass"]),
        "evidence_digests": {k: hashlib.sha256(f"{k}={v}".encode()).hexdigest()[:16] for k, v in sorted(c.items())},
        "note": "TEST activation only: an ephemeral X25519 test keypair (public key for writing, private key for reading) and synthetic plaintext "
                "were used and destroyed immediately after verification. No real corpus secret, vault key, or benchmark content exists as a result "
                "of this record.",
    }
    return rec
