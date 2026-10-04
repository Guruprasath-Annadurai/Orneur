"""Ciphertext transfer bundle validator -- SYNTHETIC, offline, no Docker. Machine-independent: proves transfer-hygiene rules and the claim levels
(EXPECTED_ENCRYPTED_ARTIFACT_FORMAT_VALIDATED vs CRYPTOGRAPHICALLY_VERIFIED). It is not evidence of a second machine, physical separation, or any real transfer."""
import importlib.util
import json
import os
import shutil
import struct
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
    """(bundle_dir, corpus_id, ephemeral_private_key, corpus_digest). The key is ephemeral, in memory only, never printed."""
    _need_crypto()
    from orca.eval.genesis_v2 import store as S, spec
    priv, pub = S.generate_vault_keypair()
    out = tmp_path / "out"
    cid = "gce2c-" + "ab" * 16
    digest = S.EncryptedVaultWriter(out, pub, repo_root=ROOT).write_corpus(cid, {s: b"SYNTHETIC-TIER0A-" + s.encode() for s in spec.PRIVATE_SPLITS})
    b = tmp_path / "bundle"
    shutil.copytree(out, b)
    for p in b.rglob("*"):
        p.chmod(0o700 if p.is_dir() else 0o600)
    B.seal(b)
    return b, cid, priv, digest


def _reseal(b):
    (b / B.MANIFEST).unlink()
    return B.seal(b)


# ---------------------------------------------------------------- original coverage (format level)
def test_a_well_formed_bundle_passes_the_format_check(bundle):
    assert B.validate(bundle[0]) == []


def test_missing_magic_prefix_is_rejected(bundle):
    b, cid, *_ = bundle
    (b / cid / "SCREEN.enc").write_bytes(b"SYNTHETIC-TIER0A-plaintext")
    assert any("magic prefix missing" in p for p in B.validate(b))


@pytest.mark.parametrize("extra", ["corpus_secret", "vault_private_key", "owner_signing_key.pem", "notes.txt", ".hidden"])
def test_any_extra_file_including_secret_shaped_names_is_rejected(bundle, extra):
    b, cid, *_ = bundle
    (b / cid / extra).write_bytes(b"x" * 64)
    assert any("unexpected entry" in p for p in B.validate(b))
    (b / extra).write_bytes(b"x" * 64)
    assert any("unexpected top-level entry" in p for p in B.validate(b))


def test_tampered_ciphertext_is_caught_by_the_manifest_digest(bundle):
    b, cid, *_ = bundle
    f = b / cid / "SEAL.enc"
    data = bytearray(f.read_bytes()); data[-1] ^= 1; f.write_bytes(bytes(data))
    assert any("does not match bundle contents" in p for p in B.validate(b))


def test_missing_split_or_missing_manifest_is_rejected(bundle):
    b, cid, *_ = bundle
    (b / cid / "QUALIFICATION_HOLDOUT.enc").unlink()
    assert any("exactly SCREEN" in p for p in B.validate(b))
    (b / B.MANIFEST).unlink()
    assert any("MANIFEST.json" in p for p in B.validate(b))


def test_symlinks_are_rejected(bundle, tmp_path):
    b, cid, *_ = bundle
    (b / cid / "SCREEN.enc").unlink()
    (b / cid / "SCREEN.enc").symlink_to(tmp_path)
    assert any("SCREEN.enc" in p for p in B.validate(b))


def test_header_metadata_outside_the_allowlist_is_rejected(bundle):
    b, cid, *_ = bundle
    f = b / cid / "SCREEN.enc"
    blob = f.read_bytes(); n = len(B.S.MAGIC_ASYM)
    (hlen,) = struct.unpack(">I", blob[n:n + 4]); h = json.loads(blob[n + 4:n + 4 + hlen]); h["note"] = "smuggled"
    hj = json.dumps(h, sort_keys=True, separators=(",", ":")).encode()
    f.write_bytes(blob[:n] + struct.pack(">I", len(hj)) + hj + blob[n + 4 + hlen:])
    (b / B.MANIFEST).unlink()
    with pytest.raises(ValueError):
        B.seal(b)


def test_header_must_match_its_path(bundle):
    b, cid, *_ = bundle
    shutil.copytree(b / cid, b / ("gce2c-" + "cd" * 16))
    assert any("header does not match its path" in p for p in B.validate(b))


def test_seal_is_write_once_and_empty_bundle_is_rejected(bundle, tmp_path):
    with pytest.raises(FileExistsError):
        B.seal(bundle[0])
    empty = tmp_path / "empty"; empty.mkdir()
    assert "bundle contains no corpus" in B.validate(empty)


def test_validator_never_prints_file_content(bundle, capsys):
    b, cid, *_ = bundle
    (b / cid / "SCREEN.enc").write_bytes(b"SYNTHETIC-TIER0A-LEAKME" + b"\0" * 64)
    B.main(["x", "validate", str(b)])
    assert "LEAKME" not in capsys.readouterr().out


# ---------------------------------------------------------------- audit remediation: claim honesty
def test_AUDIT8_format_check_does_not_prove_encryption_valid_header_plus_plaintext_passes_it(bundle):
    """Documents the limit rather than hiding it: shape-only. The keyless validator accepts magic+header+PLAINTEXT payload."""
    b, cid, *_ = bundle
    f = b / cid / "SCREEN.enc"
    blob = f.read_bytes(); n = len(B.S.MAGIC_ASYM); (hl,) = struct.unpack(">I", blob[n:n + 4])
    f.write_bytes(blob[:n + 4 + hl] + b"SYNTHETIC-TIER0A-this is plaintext, not ciphertext" * 3)
    _reseal(b)
    assert B.validate(b) == [], "format-level check cannot tell; that is exactly why it must not be called proof of encryption"


def test_AUDIT8_cryptographic_verify_rejects_the_same_plaintext_payload(bundle):
    b, cid, priv, digest = bundle
    f = b / cid / "SCREEN.enc"
    blob = f.read_bytes(); n = len(B.S.MAGIC_ASYM); (hl,) = struct.unpack(">I", blob[n:n + 4])
    f.write_bytes(blob[:n + 4 + hl] + b"SYNTHETIC-TIER0A-this is plaintext, not ciphertext" * 3)
    _reseal(b)
    problems = B.cryptographic_verify(b, priv, digest)
    assert any("SCREEN" in p and "cryptographic verification failed" in p for p in problems)


def test_AUDIT8_cryptographic_verify_passes_genuine_ciphertext_and_fails_wrong_key_or_digest(bundle):
    from orca.eval.genesis_v2 import store as S
    b, cid, priv, digest = bundle
    assert B.cryptographic_verify(b, priv, digest) == []
    wrong_priv, _ = S.generate_vault_keypair()
    assert B.cryptographic_verify(b, wrong_priv, digest)
    assert B.cryptographic_verify(b, priv, "0" * 64)


def test_AUDIT8_cryptographic_verify_never_returns_or_prints_plaintext(bundle, capsys):
    b, cid, priv, digest = bundle
    out = B.cryptographic_verify(b, priv, digest)
    assert out == [] and "SYNTHETIC-TIER0A" not in capsys.readouterr().out


def test_AUDIT8_cli_reports_the_format_claim_not_proof_of_encryption(bundle, capsys):
    b, *_ = bundle
    assert B.main(["x", "validate", str(b)]) == 0
    out = capsys.readouterr().out
    assert B.FORMAT_CLAIM in out and "CLEAN" not in out and B.FORMAT_CLAIM == "EXPECTED_ENCRYPTED_ARTIFACT_FORMAT_VALIDATED"


# ---------------------------------------------------------------- audit remediation: parsing, links, TOCTOU
def test_AUDIT13_duplicate_manifest_keys_are_rejected(bundle):
    b, cid, *_ = bundle
    m = (b / B.MANIFEST).read_text(); k = list(json.loads(m))[0]
    (b / B.MANIFEST).write_text('{"%s":"%s",' % (k, "0" * 64) + m[1:])
    assert any("strict JSON" in p for p in B.validate(b))


def test_AUDIT13_hardlinked_members_are_rejected(bundle, tmp_path):
    b, cid, *_ = bundle
    outside = tmp_path / "outside.enc"
    shutil.copy(b / cid / "SEAL.enc", outside)
    (b / cid / "SEAL.enc").unlink()
    os.link(outside, b / cid / "SEAL.enc")
    assert any("hard-linked" in p for p in B.validate(b))


def test_AUDIT13_traversal_keys_oversize_and_nested_dirs_stay_rejected(bundle):
    b, cid, *_ = bundle
    m = json.loads((b / B.MANIFEST).read_text())
    (b / B.MANIFEST).write_text(json.dumps({**m, "../x": "0" * 64}))
    assert B.validate(b)
    (b / B.MANIFEST).write_text(json.dumps(m))
    d = b / cid / "nested"; d.mkdir(); (d / "x.enc").write_bytes(b"x")
    assert any("unexpected entry" in p for p in B.validate(b))


def test_AUDIT13_appledouble_and_dsstore_are_rejected_fail_closed(bundle):
    b, *_ = bundle
    (b / "._SCREEN.enc").write_bytes(b"x")
    assert B.validate(b)
    (b / "._SCREEN.enc").unlink(); (b / ".DS_Store").write_bytes(b"x")
    assert B.validate(b)


def test_AUDIT13_stage_hands_off_a_read_only_copy_independent_of_later_source_changes(bundle, tmp_path):
    b, cid, priv, digest = bundle
    parent = tmp_path / "staging"; parent.mkdir(mode=0o700)
    staged = B.validate_and_stage(b, parent)
    assert B.validate(staged) == [] and B.cryptographic_verify(staged, priv, digest) == []
    assert (staged / cid / "SCREEN.enc").stat().st_mode & 0o777 == 0o400 and staged.stat().st_mode & 0o777 == 0o500
    before = (staged / cid / "SCREEN.enc").read_bytes()
    (b / cid / "SCREEN.enc").write_bytes(b"tampered after staging")
    assert (staged / cid / "SCREEN.enc").read_bytes() == before, "import must read only from the staged copy"


def test_AUDIT13_stage_refuses_a_bad_bundle_and_creates_nothing(bundle, tmp_path):
    b, cid, *_ = bundle
    (b / cid / "extra.bin").write_bytes(b"x")
    parent = tmp_path / "staging"; parent.mkdir(mode=0o700)
    with pytest.raises(ValueError):
        B.validate_and_stage(b, parent)
    assert list(parent.iterdir()) == []


def test_validator_imports_nothing_that_could_authorize_anything():
    src = (ROOT / "scripts" / "genesis_v2_tier0a_transfer_bundle.py").read_text()
    imports = {l.split()[1] for l in src.splitlines() if l.startswith(("import ", "from "))}
    assert imports <= {"__future__", "hashlib", "json", "os", "re", "stat", "struct", "sys", "tempfile", "pathlib", "orca.eval.genesis_v2"}


def test_tier0a_readiness_doc_still_states_the_blocked_verdict_and_claims_no_second_machine():
    txt = (ROOT / "docs/orneur/phase-21/infrastructure/GENESIS_V2_TIER0A_READINESS_AND_MACHINE_REQUIREMENTS.md").read_text()
    assert "SECOND_MACHINE_NOT_CONFIGURED" in txt and "TIER0_A_BLOCKED_SECOND_MACHINE_REQUIRED" in txt
    assert "not evaluable" in txt and "INDEPENDENT_CONTROL_PLANES_CONFIRMED" in txt and "no hardware is chosen" in txt
    status = (ROOT / "docs/orneur/phase-21/infrastructure/GENESIS_V2_TIER0_ACCEPTANCE_STATUS.md").read_text()
    assert "`PROVEN_REAL` |" not in status and "| 20 | No real corpus content was used | `PARTIAL`" in status


# ---------------------------------------------------------------- Q7: special files can never hang or be opened
import socket as _socket
import stat as _stat
import time as _time


def _replace_member_with(b, cid, maker):
    p = b / cid / "SCREEN.enc"
    p.unlink(missing_ok=True)
    maker(p)
    return p


def _validate_in_subprocess(b, timeout=15):
    t0 = _time.time()
    p = subprocess.run([sys.executable, str(ROOT / "scripts/genesis_v2_tier0a_transfer_bundle.py"), "validate", str(b)], capture_output=True, text=True, timeout=timeout)
    return p, _time.time() - t0


import subprocess
import sys


def test_Q7_a_fifo_named_like_a_member_is_rejected_immediately_and_never_hangs(bundle):
    b, cid, *_ = bundle
    _replace_member_with(b, cid, os.mkfifo)
    p, elapsed = _validate_in_subprocess(b)
    assert p.returncode == 1 and elapsed < 10 and "not a regular file (fifo)" in p.stdout


def test_Q7_a_fifo_as_the_manifest_or_a_top_level_entry_never_hangs(bundle):
    b, cid, *_ = bundle
    (b / B.MANIFEST).unlink(); os.mkfifo(b / B.MANIFEST)
    p, elapsed = _validate_in_subprocess(b)
    assert p.returncode == 1 and elapsed < 10
    (b / B.MANIFEST).unlink(); os.mkfifo(b / "stray_fifo")
    p, elapsed = _validate_in_subprocess(b)
    assert p.returncode == 1 and elapsed < 10


def test_Q7_a_unix_socket_named_like_a_member_is_rejected(bundle, monkeypatch):
    b, cid, *_ = bundle
    monkeypatch.chdir(b / cid)
    (b / cid / "SCREEN.enc").unlink()
    s = _socket.socket(_socket.AF_UNIX); s.bind("SCREEN.enc")
    try:
        assert any("not a regular file (socket)" in p for p in B.validate(b))
    finally:
        s.close()


def test_Q7_a_directory_or_symlink_named_like_a_member_is_rejected(bundle, tmp_path):
    b, cid, *_ = bundle
    _replace_member_with(b, cid, lambda p: p.mkdir())
    assert any("not a regular file (directory)" in p for p in B.validate(b))
    (b / cid / "SCREEN.enc").rmdir()
    _replace_member_with(b, cid, lambda p: p.symlink_to(tmp_path))
    assert any("not a regular file (symlink)" in p for p in B.validate(b))


def test_Q7_a_hardlinked_member_is_rejected_before_it_is_opened(bundle, tmp_path, monkeypatch):
    b, cid, *_ = bundle
    outside = tmp_path / "ext.enc"; outside.write_bytes((b / cid / "SEAL.enc").read_bytes())
    (b / cid / "SEAL.enc").unlink(); os.link(outside, b / cid / "SEAL.enc")
    opened = []
    real_open = os.open
    monkeypatch.setattr(B.os, "open", lambda p, *a, **k: (opened.append(str(p)), real_open(p, *a, **k))[1])
    assert any("hard-linked" in p for p in B.validate(b))
    assert not any(x.endswith("SEAL.enc") for x in opened), "a hardlinked member must be rejected on lstat, without opening"


@pytest.mark.parametrize("mode,label", [(_stat.S_IFBLK, "block device"), (_stat.S_IFCHR, "character device")])
def test_Q7_device_like_members_are_rejected_without_ever_being_opened(bundle, monkeypatch, mode, label):
    """Platform-safe: devices cannot be created without privilege, so lstat is mocked for exactly one member and os.open is made to fail the test if reached."""
    b, cid, *_ = bundle
    target = str(b / cid / "SCREEN.enc")
    real_lstat, real_open = os.lstat, os.open

    def fake_lstat(path, *a, **k):
        if str(path) == target:
            return os.stat_result((mode | 0o600, 1, 1, 1, 0, 0, 10, 0, 0, 0))
        return real_lstat(path, *a, **k)

    def guarded_open(path, *a, **k):
        assert str(path) != target, "a device-like member must never be opened"
        return real_open(path, *a, **k)
    monkeypatch.setattr(B.os, "lstat", fake_lstat); monkeypatch.setattr(B.os, "open", guarded_open)
    assert any(f"not a regular file ({label})" in p for p in B.validate(b))


def test_Q7_a_member_swapped_for_a_symlink_between_the_lstat_and_the_open_is_refused_by_NOFOLLOW(bundle, monkeypatch, tmp_path):
    """Deterministic on every filesystem (unlike an inode swap, whose detection depends on inode reuse): O_NOFOLLOW refuses a symlink that appears after the lstat."""
    b, cid, *_ = bundle
    target = str(b / cid / "SCREEN.enc"); other = tmp_path / "other.enc"; other.write_bytes((b / cid / "SCREEN.enc").read_bytes())
    real_open = os.open

    def swap_then_open(path, flags, *a, **k):
        if str(path) == target:
            os.unlink(target); os.symlink(other, target)             # type change after the lstat
        return real_open(path, flags, *a, **k)
    monkeypatch.setattr(B.os, "open", swap_then_open)
    assert any("SCREEN.enc" in p and ("symlink" in p or "unreadable" in p) for p in B.validate(b))


def test_Q7_a_descriptor_whose_inode_differs_from_the_lstat_is_rejected(bundle, monkeypatch):
    """Deterministic via mocked fstat (a real swap would not reliably change the inode: filesystems such as ext4 reuse freed inode numbers, so the inode
    comparison is best-effort; O_NOFOLLOW, the regular-file and link-count checks and the manifest digests are the real guards)."""
    b, cid, *_ = bundle
    target = str(b / cid / "SCREEN.enc"); fds = set(); real_open, real_fstat = os.open, os.fstat

    def open_rec(path, flags, *a, **k):
        fd = real_open(path, flags, *a, **k)
        if str(path) == target:
            fds.add(fd)
        return fd

    def fstat_other_inode(fd):
        st = real_fstat(fd)
        if fd in fds:
            vals = list(st); vals[1] = st.st_ino + 1                 # st_ino
            return os.stat_result(tuple(vals))
        return st
    monkeypatch.setattr(B.os, "open", open_rec); monkeypatch.setattr(B.os, "fstat", fstat_other_inode)
    assert any("changed between check and open" in p for p in B.validate(b))


def test_Q7_the_inode_comparison_is_documented_as_best_effort():
    doc = " ".join(B.__doc__.split()).lower()
    assert "best-effort" in doc and "reuses" in doc


def test_Q7_stage_and_crypto_verify_inherit_the_special_file_rejection(bundle, tmp_path):
    b, cid, priv, digest = bundle
    _replace_member_with(b, cid, os.mkfifo)
    par = tmp_path / "stg"; par.mkdir(mode=0o700)
    with pytest.raises(ValueError):
        B.validate_and_stage(b, par)
    assert B.cryptographic_verify(b, priv, digest)
    assert list(par.iterdir()) == []
