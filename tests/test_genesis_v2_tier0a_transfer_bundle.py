"""Tier0-A ciphertext-only transfer bundle validator -- SYNTHETIC. Runs on one machine, offline, no Docker. Proves the transfer-hygiene rules only;
it is not evidence of a second machine, of physical separation, or of any real transfer."""
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_s = importlib.util.spec_from_file_location("tier0a_bundle", ROOT / "scripts" / "genesis_v2_tier0a_transfer_bundle.py")
B = importlib.util.module_from_spec(_s)
_s.loader.exec_module(B)


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography  # noqa: F401
    else:
        pytest.importorskip("cryptography")


@pytest.fixture
def bundle(tmp_path):
    _need_crypto()
    from orca.eval.genesis_v2 import store as S, spec
    _priv, pub = S.generate_vault_keypair()          # ephemeral, never printed or persisted
    out = tmp_path / "out"
    cid = "gce2c-" + "ab" * 16
    S.EncryptedVaultWriter(out, pub, repo_root=ROOT).write_corpus(cid, {s: b"SYNTHETIC-TIER0A-" + s.encode() for s in spec.PRIVATE_SPLITS})
    b = tmp_path / "bundle"
    shutil.copytree(out, b)
    for p in b.rglob("*"):
        p.chmod(0o700 if p.is_dir() else 0o600)
    B.seal(b)
    return b, cid


def test_a_well_formed_ciphertext_bundle_validates(bundle):
    b, _ = bundle
    assert B.validate(b) == []


def test_plaintext_in_place_of_ciphertext_is_rejected(bundle):
    b, cid = bundle
    (b / cid / "SCREEN.enc").write_bytes(b"SYNTHETIC-TIER0A-plaintext")
    assert any("not ciphertext" in p or "implausible" in p for p in B.validate(b))


@pytest.mark.parametrize("extra", ["corpus_secret", "vault_private_key", "owner_signing_key.pem", "notes.txt", ".hidden"])
def test_any_extra_file_including_secret_shaped_names_is_rejected(bundle, extra):
    b, cid = bundle
    (b / cid / extra).write_bytes(b"x" * 64)
    assert any("unexpected entry" in p for p in B.validate(b))
    (b / extra).write_bytes(b"x" * 64)
    assert any("unexpected top-level entry" in p for p in B.validate(b))


def test_tampered_ciphertext_is_caught_by_the_manifest_digest(bundle):
    b, cid = bundle
    f = b / cid / "SEAL.enc"
    data = bytearray(f.read_bytes()); data[-1] ^= 1; f.write_bytes(bytes(data))
    assert any("does not match bundle contents" in p for p in B.validate(b))


def test_missing_split_or_missing_manifest_is_rejected(bundle):
    b, cid = bundle
    (b / cid / "QUALIFICATION_HOLDOUT.enc").unlink()
    assert any("exactly SCREEN" in p for p in B.validate(b))
    (b / MANIFEST_NAME()).unlink()
    assert any("MANIFEST.json missing" in p for p in B.validate(b))


def MANIFEST_NAME():
    return B.MANIFEST


def test_symlinks_are_rejected(bundle, tmp_path):
    b, cid = bundle
    (b / cid / "SCREEN.enc").unlink()
    (b / cid / "SCREEN.enc").symlink_to(tmp_path)
    assert any("unexpected entry" in p for p in B.validate(b))


def test_header_metadata_outside_the_allowlist_is_rejected(bundle):
    """A ciphertext whose plaintext header smuggles extra metadata fields must not pass, even with a matching manifest."""
    import struct
    b, cid = bundle
    f = b / cid / "SCREEN.enc"
    blob = f.read_bytes(); n = len(B.S.MAGIC_ASYM)
    (hlen,) = struct.unpack(">I", blob[n:n + 4]); h = json.loads(blob[n + 4:n + 4 + hlen]); h["note"] = "smuggled"
    hj = json.dumps(h, sort_keys=True, separators=(",", ":")).encode()
    f.write_bytes(blob[:n] + struct.pack(">I", len(hj)) + hj + blob[n + 4 + hlen:])
    (b / B.MANIFEST).unlink()
    with pytest.raises(ValueError):
        B.seal(b)


def test_header_must_match_its_path(bundle):
    b, cid = bundle
    other = b / ("gce2c-" + "cd" * 16)
    shutil.copytree(b / cid, other)
    assert any("header does not match its path" in p for p in B.validate(b))


def test_seal_is_write_once_and_empty_bundle_is_rejected(bundle, tmp_path):
    b, _ = bundle
    with pytest.raises(FileExistsError):
        B.seal(b)
    empty = tmp_path / "empty"; empty.mkdir()
    assert "bundle contains no corpus" in B.validate(empty)


def test_validator_never_prints_file_content(bundle, capsys):
    b, cid = bundle
    (b / cid / "SCREEN.enc").write_bytes(b"SYNTHETIC-TIER0A-LEAKME" + b"\0" * 64)
    B.main(["x", "validate", str(b)])
    assert "LEAKME" not in capsys.readouterr().out


def test_tier0a_readiness_doc_states_the_blocked_verdict_and_claims_no_second_machine():
    txt = (ROOT / "docs/orneur/phase-21/infrastructure/GENESIS_V2_TIER0A_READINESS_AND_MACHINE_REQUIREMENTS.md").read_text()
    assert "SECOND_MACHINE_NOT_CONFIGURED" in txt and "TIER0_A_BLOCKED_SECOND_MACHINE_REQUIRED" in txt
    assert "not evaluable" in txt and "INDEPENDENT_CONTROL_PLANES_CONFIRMED" in txt
    assert "no hardware is chosen" in txt
    # nothing may have been promoted: the Tier-0 acceptance table still has no PROVEN_REAL and item 20 is PARTIAL
    status = (ROOT / "docs/orneur/phase-21/infrastructure/GENESIS_V2_TIER0_ACCEPTANCE_STATUS.md").read_text()
    assert "`PROVEN_REAL` |" not in status and "| 20 | No real corpus content was used | `PARTIAL`" in status
