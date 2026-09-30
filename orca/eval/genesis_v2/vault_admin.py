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
path, including when isolation verification fails, a write fails partway, or the backup fails partway. It claims
EXCLUSIVE ownership of a single, uniquely-named, freshly-created workspace directory BEFORE performing any write
(the `mkdir` call itself, with its default exclusive-creation semantics, IS the ownership claim), writes every
artifact this activation produces -- the test corpus AND the test backup -- ONLY inside that one workspace, and
removes ONLY that one workspace in its `finally` block. This means a failure at ANY point after the workspace is
claimed (mid-`write_corpus`, mid-`export_backup`, or anything else) still leaves cleanup with an unambiguous, single
target: the whole workspace, whatever partial state it holds, gone in one `rmtree` — never a traversal of
`vault_dir` itself, never a chance of reaching content this invocation did not create. See that function's own
docstring for the full guarantee, and `tests/test_genesis_v2_vault_ledger_activation.py`'s sentinel-preservation,
fault-injection (mid-write failure, partial-backup failure, cleanup failure) regression tests.

EVIDENCE, NOT ASSUMPTIONS: every field in the produced record depends on a genuinely executed check performed
during THIS invocation. In particular `backup_policy_result` is computed from an ACTUAL `export_backup()` call
verified byte-for-byte against the live ciphertext (never hardcoded), executed BEFORE the destructive
tamper/truncation tests below it so the backup reflects real, uncorrupted content. `cleanup_verified_result` reports
whether the workspace was genuinely, completely removed -- an incomplete cleanup is reported as an ACTIVATION
FAILURE (`pass: false`), never masked as a successful activation.
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
    test touches the vault's own copy), THEN checks tamper/truncation detection, then destroys the ENTIRE isolated
    workspace this invocation exclusively created (and nothing else), then destroys the keys. Returns
    {'pass': bool, 'checks': {...}, 'error': str|None}.

    OWNERSHIP AND CLEANUP: before writing a single byte, this function exclusively creates ONE workspace directory
    inside `vault_dir` (`Path.mkdir()`'s default exclusive-creation semantics -- it raises `FileExistsError` on any
    collision rather than silently reusing something already there -- IS the ownership claim, made before any write
    is attempted). Every artifact this invocation produces (the test corpus, the test backup) is written ONLY
    inside that one workspace; nothing this function does ever touches any other path under `vault_dir`. Cleanup in
    the `finally` block below removes that ONE workspace, whatever state it is in -- fully written, partially
    written after a mid-`write_corpus` or mid-`export_backup` failure, or anything else -- via a single `rmtree`
    that can never traverse into or delete unrelated pre-existing vault content, because it is never given any path
    other than the workspace it itself exclusively created. If isolation verification fails before the workspace is
    even created, nothing under `vault_dir` is touched at all.

    CLEANUP IS ITSELF A PASS/FAIL CONDITION: `checks["cleanup_complete"]` is genuinely computed (workspace removed
    AND confirmed gone afterward, not merely "no exception raised") and is included in the overall `pass`
    computation -- an activation whose test artifacts could not be fully cleaned up is reported as a FAILURE, never
    as a successful activation with a silently leftover workspace."""
    vault_dir = Path(vault_dir)
    checks: dict = {}
    workspace: Path | None = None
    error: str | None = None
    priv, pub = ST.generate_vault_keypair()   # TEST keypair only; never written to disk; discarded at the end of this function
    corpus_id = "gce2c-" + os.urandom(8).hex()   # a fresh, unique corpus id -- collision with any pre-existing content is not credible
    try:
        iso = VV.verify_vault_isolation(vault_dir, repo_root)
        checks["repository_isolation"] = iso["pass"]
        checks.update({f"isolation.{k}": v for k, v in iso.get("checks", {}).items()})
        if not iso["pass"]:
            error = "vault is not isolated from the repository"
        else:
            # EXCLUSIVE ownership claim, before any write: mkdir's default exist_ok=False raises FileExistsError on
            # collision (astronomically unlikely given os.urandom(8)) rather than silently adopting an existing
            # directory. Every subsequent write in this function stays INSIDE `workspace`.
            workspace = vault_dir / (".genesis-v2-vault-activation-test-" + os.urandom(8).hex())
            workspace.mkdir(mode=0o700)

            writer = ST.EncryptedVaultWriter(workspace, pub)
            checks["writer_exposes_no_read_method"] = not hasattr(writer, "read_split")
            checks["writer_holds_no_private_key_bytes"] = not any(v == priv for v in vars(writer).values())
            plain = {"SCREEN": _TEST_MARKER + b"-SCREEN", "QUALIFICATION_HOLDOUT": _TEST_MARKER + b"-HOLDOUT"}
            digest = writer.write_corpus(corpus_id, plain)   # any failure here leaves only partial content INSIDE workspace, still fully covered by cleanup below
            checks["round_trip_write"] = True

            reader = ST.EncryptedVaultReader(workspace, priv)
            got = {s: reader.read_split(corpus_id, s, expected_corpus_digest=digest) for s in plain}
            checks["round_trip_read_matches"] = got == plain

            wrong_priv, _ = ST.generate_vault_keypair()
            wrong_reader = ST.EncryptedVaultReader(workspace, wrong_priv)
            try:
                wrong_reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=digest)
                checks["wrong_key_fails"] = False
            except ST.PrivateStorageIntegrityError:
                checks["wrong_key_fails"] = True

            # GENUINE ciphertext-only backup verification -- BEFORE any destructive tamper/truncation test below, so
            # the backup is verified against the real, uncorrupted vault content, and the result is never hardcoded.
            # backup_dir lives INSIDE `workspace` too -- a partial `export_backup` failure is covered by the SAME
            # single cleanup as everything else, never separately tracked.
            backup_dir = workspace / "backup"
            try:
                names = reader.export_backup(corpus_id, backup_dir, expected_corpus_digest=digest)
                expected_names = {"SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"}
                names_match = set(names) == expected_names
                live_dir = workspace / corpus_id
                content_matches = names_match and all((backup_dir / n).read_bytes() == (live_dir / n).read_bytes() for n in expected_names)
                no_plaintext_leaked = names_match and not any(
                    _TEST_MARKER in (backup_dir / n).read_bytes() for n in expected_names)
                checks["backup_ciphertext_only"] = bool(names_match and content_matches and no_plaintext_leaked)
            except ST.PrivateStorageIntegrityError as e:
                checks["backup_ciphertext_only"] = False
                checks["backup_test_error"] = f"NOT_TESTED: export_backup raised {type(e).__name__} against a freshly-written, uncorrupted corpus"

            target = workspace / corpus_id / "SCREEN.enc"
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
            checks["seal_last_publication"] = (workspace / corpus_id / "SEAL.enc").exists()   # SEAL.enc is never touched by the SCREEN.enc-only tamper/truncation tests above
            checks["no_plaintext_temp_survives"] = not list((workspace / corpus_id).glob(".tmp-*"))
            vs = VV.P.scan_vault_dir(workspace)
            checks["permission_and_no_plaintext_siblings"] = vs["pass"]
    except Exception as e:
        checks["exception"] = False
        error = f"{type(e).__name__}: {str(e)[:160]}"
    finally:
        priv = b"\x00" * 32          # best-effort scrub of the local reference
        del priv
        cleanup_ok = True
        if workspace is not None:
            try:
                if workspace.exists():
                    shutil.rmtree(workspace)
            except Exception:
                cleanup_ok = False
            if workspace.exists():
                cleanup_ok = False
        checks["cleanup_complete"] = cleanup_ok

    if error is not None:
        return {"pass": False, "checks": checks, "error": error}
    return {"pass": all(bool(v) for v in checks.values() if not isinstance(v, str)), "checks": checks, "error": None}


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
        "cleanup_verified_result": bool(c.get("cleanup_complete")),
        "verifier_code_sha256": _verifier_code_sha(),
        "pass": bool(activation["pass"]),
        "evidence_digests": {k: hashlib.sha256(f"{k}={v}".encode()).hexdigest()[:16] for k, v in sorted(c.items())},
        "note": "TEST activation only: an ephemeral X25519 test keypair (public key for writing, private key for reading) and synthetic plaintext "
                "were used and destroyed immediately after verification. No real corpus secret, vault key, or benchmark content exists as a result "
                "of this record.",
    }
    return rec
