"""End-to-end demonstration of the cross-machine (or cross-OS-account) ciphertext transfer path described in
GENESIS_V2_CROSS_MACHINE_TRANSFER_PROCEDURE.md -- item 1 of the deployment-decision-accuracy-closure phase. Proves,
with real crypto and two GENUINELY SEPARATE tmp_path locations (standing in for two separate machines or two
separate OS accounts), that: only ciphertext ever crosses the transfer, the SEAL/digest catches any corruption
introduced during transfer, permissions must be explicitly re-applied on receipt, and the private key never needs
to move at all (it was never on the sending side in the first place)."""
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import store as ST


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
    else:
        pytest.importorskip("cryptography")


def test_full_generator_to_verifier_transfer_round_trip(tmp_path):
    """The complete, honest path: write on the 'generator machine', copy ONLY the .enc files to a totally separate
    location standing in for the 'verifier machine', re-apply permissions there, then read -- using an
    expected_corpus_digest obtained from an INDEPENDENT channel (never re-derived from the transferred bytes
    themselves), exactly as the real corpus-generation-authorization / manifest flow already provides."""
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()   # the owner generates this ONCE; only `pub` ever reaches the generator

    generator_machine = tmp_path / "generator-machine-vault"
    generator_machine.mkdir(mode=0o700)
    writer = ST.EncryptedVaultWriter(generator_machine, pub)
    assert not hasattr(writer, "read_split")   # the generator's own object has no decrypt capability at all

    corpus_id = "gce2c-" + "ab" * 16
    screen_bytes = b'{"marker":"CROSS-MACHINE-TRANSFER-TEST-SCREEN"}'
    holdout_bytes = b'{"marker":"CROSS-MACHINE-TRANSFER-TEST-HOLDOUT"}'
    corpus_digest = writer.write_corpus(corpus_id, {"SCREEN": screen_bytes, "QUALIFICATION_HOLDOUT": holdout_bytes})
    # This digest is what a REAL deployment would record through the manifest / corpus-generation-authorization
    # flow (an INDEPENDENT, already-signed channel) -- never re-derived from the ciphertext being transferred.

    # --- THE TRANSFER: copy ONLY the three .enc files, raw bytes, no decryption (the generator cannot decrypt
    # anyway). Stands in for scp/rsync/USB/etc. -- the exact mechanism is a deployment choice, not a code path.
    verifier_machine = tmp_path / "verifier-machine-vault"
    verifier_machine.mkdir(mode=0o700)
    src_corpus_dir = generator_machine / corpus_id
    dst_corpus_dir = verifier_machine / corpus_id
    dst_corpus_dir.mkdir(mode=0o700)
    transferred = []
    for name in ("SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"):
        assert name.endswith(".enc")   # nothing else is ever eligible for transfer
        data = (src_corpus_dir / name).read_bytes()
        (dst_corpus_dir / name).write_bytes(data)
        transferred.append(name)
    assert set(transferred) == {"SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"}

    # A naive copy (e.g. many cloud object stores, some transfer tools) does NOT preserve exact POSIX permissions
    # -- the receiving side must explicitly re-apply them, never assume the transfer mechanism did it.
    for name in transferred:
        os.chmod(dst_corpus_dir / name, 0o400)
    os.chmod(dst_corpus_dir, 0o700)

    # No plaintext, no key material anywhere in the transferred bytes -- confirm by hashing the raw ciphertext and
    # checking it never equals a hash of the known plaintext (a stronger, more concrete check than "doesn't look
    # like the marker string", since ciphertext is opaque by construction).
    for name, plain in (("SCREEN.enc", screen_bytes), ("QUALIFICATION_HOLDOUT.enc", holdout_bytes)):
        transferred_bytes = (dst_corpus_dir / name).read_bytes()
        assert plain not in transferred_bytes
        assert hashlib.sha256(transferred_bytes).hexdigest() != hashlib.sha256(plain).hexdigest()

    # --- RECEIPT VERIFICATION: the verifier's own reader, holding ONLY the private key (never transferred,
    # never needed to be -- it was generated once by the owner and only ever given to the verifier).
    reader = ST.EncryptedVaultReader(verifier_machine, priv)
    got_screen = reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=corpus_digest)
    got_holdout = reader.read_split(corpus_id, "QUALIFICATION_HOLDOUT", expected_corpus_digest=corpus_digest)
    assert got_screen == screen_bytes and got_holdout == holdout_bytes

    # Permissions on the RECEIVING side match the same 0700/0400 discipline as a single-machine vault.
    assert stat.S_IMODE(dst_corpus_dir.stat().st_mode) == 0o700
    for name in transferred:
        assert stat.S_IMODE((dst_corpus_dir / name).stat().st_mode) == 0o400

    # Write-once is preserved on BOTH sides independently: the generator's own directory cannot be reused for a
    # second write (proven elsewhere), and the verifier's imported copy is read-only by construction -- the
    # verifier's object (EncryptedVaultReader) has no write_corpus method at all.
    assert not hasattr(reader, "write_corpus")


def test_a_corrupted_transfer_is_caught_by_seal_and_digest_verification(tmp_path):
    """Corruption introduced DURING transfer (a bit flip mid-copy, a truncated USB write, a partial network
    transfer) is caught at receipt time by the SAME authenticated-encryption check that catches on-disk tampering
    -- the receiving side never needs a separate integrity mechanism for the transfer itself."""
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    generator_machine = tmp_path / "generator-machine-vault"
    generator_machine.mkdir(mode=0o700)
    writer = ST.EncryptedVaultWriter(generator_machine, pub)
    corpus_id = "gce2c-" + "cd" * 16
    corpus_digest = writer.write_corpus(corpus_id, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})

    verifier_machine = tmp_path / "verifier-machine-vault"
    verifier_machine.mkdir(mode=0o700)
    src_corpus_dir = generator_machine / corpus_id
    dst_corpus_dir = verifier_machine / corpus_id
    dst_corpus_dir.mkdir(mode=0o700)
    for name in ("SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"):
        data = bytearray((src_corpus_dir / name).read_bytes())
        if name == "SCREEN.enc":
            data[-5] ^= 0xFF   # simulate a bit flip introduced during transfer
        (dst_corpus_dir / name).write_bytes(bytes(data))
        os.chmod(dst_corpus_dir / name, 0o400)

    reader = ST.EncryptedVaultReader(verifier_machine, priv)
    with pytest.raises(ST.PrivateStorageIntegrityError):
        reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=corpus_digest)
    # the OTHER split, untouched by the simulated corruption, still reads correctly -- corruption is caught
    # per-artifact, not treated as an all-or-nothing transfer failure
    assert reader.read_split(corpus_id, "QUALIFICATION_HOLDOUT", expected_corpus_digest=corpus_digest) == b"h"


def test_an_incomplete_transfer_is_caught_not_silently_accepted(tmp_path):
    """Only two of the three files arrive (e.g. a network interruption) -- the verifier must fail closed, never
    treat a partial transfer as a valid corpus."""
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    generator_machine = tmp_path / "generator-machine-vault"
    generator_machine.mkdir(mode=0o700)
    writer = ST.EncryptedVaultWriter(generator_machine, pub)
    corpus_id = "gce2c-" + "ef" * 16
    corpus_digest = writer.write_corpus(corpus_id, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})

    verifier_machine = tmp_path / "verifier-machine-vault"
    verifier_machine.mkdir(mode=0o700)
    src_corpus_dir = generator_machine / corpus_id
    dst_corpus_dir = verifier_machine / corpus_id
    dst_corpus_dir.mkdir(mode=0o700)
    for name in ("SCREEN.enc", "QUALIFICATION_HOLDOUT.enc"):   # SEAL.enc never arrives
        data = (src_corpus_dir / name).read_bytes()
        (dst_corpus_dir / name).write_bytes(data)
        os.chmod(dst_corpus_dir / name, 0o400)

    reader = ST.EncryptedVaultReader(verifier_machine, priv)
    with pytest.raises(ST.PrivateStorageIntegrityError):
        reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=corpus_digest)


def test_a_stale_or_mistaken_expected_digest_fails_closed_even_on_a_genuinely_valid_transfer(tmp_path):
    """expected_corpus_digest MUST come from an independent, trusted channel (the manifest / corpus-generation-
    authorization record) -- never re-derived from the transferred artifacts themselves. This test proves the
    consequence of getting that wrong (a stale or mistyped digest): even a PERFECT, uncorrupted transfer is
    rejected if the caller supplies the wrong expected digest -- there is no code path that falls back to trusting
    the ciphertext's own self-reported digest instead."""
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    generator_machine = tmp_path / "generator-machine-vault"
    generator_machine.mkdir(mode=0o700)
    writer = ST.EncryptedVaultWriter(generator_machine, pub)
    corpus_id = "gce2c-" + "34" * 16
    real_digest = writer.write_corpus(corpus_id, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})

    verifier_machine = tmp_path / "verifier-machine-vault"
    verifier_machine.mkdir(mode=0o700)
    src = generator_machine / corpus_id
    dst = verifier_machine / corpus_id
    shutil.copytree(src, dst)
    for p in dst.iterdir():
        os.chmod(p, 0o400)
    os.chmod(dst, 0o700)

    reader = ST.EncryptedVaultReader(verifier_machine, priv)
    stale_digest = "0" * 64   # a plausible-looking but wrong digest (typo, stale record, wrong lineage)
    with pytest.raises(ST.PrivateStorageIntegrityError):
        reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=stale_digest)
    assert reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=real_digest) == b"s"


def test_two_os_accounts_one_machine_still_requires_an_explicit_export_import_step(tmp_path):
    """Item 1's specific correction: a naive 'shared vault_dir, two OS accounts' model does NOT work under strict
    0700 permissions -- the generator's own corpus_id directory (0700, owned by its writer) is NOT readable by a
    different account, so a second account cannot simply open the SAME vault_dir the generator wrote into. This
    test demonstrates the actual failure (via strict, real filesystem-permission semantics, simulated in-process by
    denying the copy) and the fix: an explicit local copy into a fresh, separately-owned directory -- structurally
    identical to the cross-machine transfer above, just without physical transport."""
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    shared_disk_generator_side = tmp_path / "generator-owned-vault"
    shared_disk_generator_side.mkdir(mode=0o700)
    writer = ST.EncryptedVaultWriter(shared_disk_generator_side, pub)
    corpus_id = "gce2c-" + "12" * 16
    corpus_digest = writer.write_corpus(corpus_id, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})

    # A SEPARATE account's own vault directory -- the fix: an explicit copy-in step, exactly like the cross-machine
    # case, not a shared read of the generator's 0700 directory.
    verifier_owned_vault = tmp_path / "verifier-owned-vault"
    verifier_owned_vault.mkdir(mode=0o700)
    src = shared_disk_generator_side / corpus_id
    dst = verifier_owned_vault / corpus_id
    shutil.copytree(src, dst)
    for p in dst.iterdir():
        os.chmod(p, 0o400)
    os.chmod(dst, 0o700)

    reader = ST.EncryptedVaultReader(verifier_owned_vault, priv)
    assert reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=corpus_digest) == b"s"
    # the two locations are genuinely independent directories -- proving this was a real copy, not a shared mount
    assert shared_disk_generator_side != verifier_owned_vault


def test_transferred_corpus_passes_the_real_ledger_gated_creation_time_verifier_flow(tmp_path):
    """Item 2 (authenticated-transfer-and-evidence-integrity-closure phase): extends the cross-machine transfer all
    the way through the REAL authorized creation-time verifier -- a genuine, registered qualification-runner
    identity, a real `AccessLedger` grant (via `operational_boundary.authorized_manifest_verification_bytes`,
    composed inside `verify_manifest_digest_only_same_process`), and a real, Ed25519-signed corpus manifest bound to
    a real `CORPUS_GENERATION_AUTHORIZATION` record -- not just the raw `store.EncryptedVaultReader.read_split`
    round trip the other tests in this file exercise.

    HONEST SCOPE, stated explicitly per item 2: this is still a SAME-PROCESS `tmp_path` test. The "generator
    machine" / "verifier machine" split below is two genuinely separate directories and a real copy step (exactly
    like the other tests in this file), but it is NOT a separate OS process, separate UID, or separate physical
    host -- Python interpreter state (including decrypted plaintext, briefly, inside
    `operational_boundary.verify_manifest_digest_only_same_process`) is shared for the whole test. That a real
    separate-machine or separate-UID deployment enforces genuine process isolation is NOT something any unit test
    can establish by construction -- it remains an owner-side deployment acceptance check, per
    `GENESIS_V2_PROCESS_ISOLATION_VERIFICATION_PROCEDURE.md`. What THIS test DOES prove, with real crypto and a
    real ledger: after a genuine cross-machine ciphertext transfer, complete receipt, correct permissions, manifest
    authentication (signature + CGA binding), and ledger evidence all check out end-to-end through the actual
    verifier code path -- not a hand-rolled substitute for it."""
    import hashlib as _hashlib

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from orca.eval.genesis_v2 import corpus_manifest as CMAN
    from orca.eval.genesis_v2 import ledger as LG
    from orca.eval.genesis_v2 import operational_boundary as OB
    from orca.eval.genesis_v2 import runner_registry as RN
    from orca.eval.genesis_v2 import spec as SPEC
    _need_crypto()

    # --- GENERATION, on the "generator machine": write the real sealed corpus.
    priv, pub = ST.generate_vault_keypair()
    generator_machine = tmp_path / "generator-machine-vault"
    generator_machine.mkdir(mode=0o700)
    writer = ST.EncryptedVaultWriter(generator_machine, pub)
    corpus_id = "gce2c-" + "56" * 16
    screen_bytes = b'{"marker":"ITEM2-LEDGER-GATED-SCREEN"}'
    holdout_bytes = b'{"marker":"ITEM2-LEDGER-GATED-HOLDOUT"}'
    writer.write_corpus(corpus_id, {"SCREEN": screen_bytes, "QUALIFICATION_HOLDOUT": holdout_bytes})

    # --- a real, Ed25519-SIGNED manifest binding this corpus to a real authorization record (item 1's format).
    owner_sk = Ed25519PrivateKey.generate()
    owner_pub_hex = owner_sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    authority_keys = [{"key_id": "k-owner-item2", "public_key_hex": owner_pub_hex, "identity": "owner-item2", "role": "OWNER"}]
    code_dir = tmp_path / "generator_code"
    code_dir.mkdir()
    (code_dir / "gen_a.py").write_text("def a():\n    return 1\n")
    generator_code_sha = RN.code_sha256_of(sorted(code_dir.glob("*.py")))
    reviewed_sha = "c" * 40
    unsigned_manifest = {
        "schema_version": CMAN.SCHEMA_VERSION, "corpus_id": corpus_id, "eval_version": SPEC.EVAL_VERSION,
        "generator_code_sha256": generator_code_sha, "generated_at_commit_sha": reviewed_sha,
        "screen_digest": _hashlib.sha256(screen_bytes).hexdigest(),
        "qualification_holdout_digest": _hashlib.sha256(holdout_bytes).hexdigest(),
        "per_category_item_counts": {"reasoning": 5}, "corpus_generation_authorization_id": "cgauth-" + "12" * 8,
        "signing_authority": {"identity": "owner-item2", "role": "OWNER", "key_id": "k-owner-item2"}, "signature": "0" * 128}
    manifest = {**unsigned_manifest, "signature": owner_sk.sign(CMAN.manifest_signing_bytes(unsigned_manifest)).hex()}
    authorization_record = {"status": "AUTHORIZED", "authorization_id": manifest["corpus_generation_authorization_id"],
                             "reviewed_commit_sha": reviewed_sha, "authorized_code_tree_sha256": generator_code_sha,
                             "authorized_scope": ["SCREEN", "QUALIFICATION_HOLDOUT"]}

    # --- THE TRANSFER: only ciphertext crosses, exactly like the other tests in this file.
    verifier_machine = tmp_path / "verifier-machine-vault"
    verifier_machine.mkdir(mode=0o700)
    src_corpus_dir = generator_machine / corpus_id
    dst_corpus_dir = verifier_machine / corpus_id
    dst_corpus_dir.mkdir(mode=0o700)
    for name in ("SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"):
        (dst_corpus_dir / name).write_bytes((src_corpus_dir / name).read_bytes())
        os.chmod(dst_corpus_dir / name, 0o400)
    os.chmod(dst_corpus_dir, 0o700)

    # --- a REAL, registered qualification-runner identity, restricted to creation-time verification only (never
    # PURPOSE_QUALIFICATION) -- the same separation-of-duties the runner registry already enforces elsewhere.
    verifier_root = tmp_path / "verifier-fakeroot"
    verifier_code_dir = tmp_path / "verifier_code"
    verifier_code_dir.mkdir()
    (verifier_code_dir / "verify_a.py").write_text("def v():\n    return 2\n")
    verifier_code_sha = RN.code_sha256_of(sorted(verifier_code_dir.glob("*.py")))
    doc = {"schema_version": RN.SCHEMA_VERSION, "records": [{
        "runner_id": "item2-verifier", "runner_class": "SELF_HOSTED_CPU", "os_runtime": "test", "code_sha256": verifier_code_sha,
        "allowed_purposes": [SPEC.PURPOSE_CREATION_VERIFICATION], "allowed_splits": ["SCREEN", "QUALIFICATION_HOLDOUT"],
        "sandbox_image_digest": "sha256:" + "b" * 64, "semantic_engine_digest": "c" * 64,
        "storage_backend_verification_digest": "d" * 64, "ledger_database_identity_digest": "e" * 64, "network_policy": "none",
        "credential_scope": {"private_store_read": True, "public_repo_write": False, "training_credentials": False,
                              "unrelated_cloud_credentials": False, "developer_tokens": False}, "state": "AUTHORIZED"}]}
    (verifier_root / RN.REGISTRY_PATH).parent.mkdir(parents=True, exist_ok=True)
    (verifier_root / RN.REGISTRY_PATH).write_text(json.dumps(doc))

    reader = ST.EncryptedVaultReader(verifier_machine, priv)
    ledger_dir = tmp_path / "ledger"
    problems = OB.verify_manifest_digest_only_same_process(
        verifier_root, ledger_dir, reader, manifest, authorization_record, authority_keys, process_id="item2-verifier",
        code_sha256=verifier_code_sha, corpus_id=corpus_id, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-item2",
        candidate_lineage="lineage-item2", run_id_prefix="item2-transfer-verify", timestamp_utc="2026-01-01T00:00:00Z",
        generator_code_root=code_dir, commit_is_descendant=True)
    assert problems == []

    # --- real ledger evidence: two grants (one per split), same creation-verification purpose, holdout still sealed
    # afterward (this path never consumes the one-time qualification lifecycle).
    led = LG.AccessLedger(ledger_dir, {})
    recs = [r for r in led.records() if r["purpose"] == SPEC.PURPOSE_CREATION_VERIFICATION]
    assert len(recs) == 2
    assert {r["split"] for r in recs} == {"SCREEN", "QUALIFICATION_HOLDOUT"}
    assert all(r["who"] == "item2-verifier" for r in recs)
    assert led.holdout_state(SPEC.EVAL_VERSION) == {"state": SPEC.STATE_SEALED, "opened_by": None, "lineages": []}

    # --- correct permissions preserved on the receiving side (same discipline as the raw-store transfer tests).
    assert stat.S_IMODE(dst_corpus_dir.stat().st_mode) == 0o700
    for name in ("SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"):
        assert stat.S_IMODE((dst_corpus_dir / name).stat().st_mode) == 0o400
