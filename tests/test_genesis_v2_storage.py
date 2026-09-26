"""Genesis V2 private storage: the AES-256-GCM encrypted artifact backend. Keys/corpora here are ephemeral test values only."""
import hashlib
import json
import os
import pickle
import re
import stat
import tomllib
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import privacy_scan as P
from orca.eval.genesis_v2 import spec
from orca.eval.genesis_v2 import store as ST

ROOT = Path(__file__).resolve().parents[1]


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401  (hard failure, never a skip, in the security CI job)
    else:
        pytest.importorskip("cryptography")


CID = "gce2c-" + "ab" * 16
PLAIN = {"SCREEN": b'{"marker":"UNIT-TEST-PLAINTEXT-SCREEN-7f3a"}', "QUALIFICATION_HOLDOUT": b'{"marker":"UNIT-TEST-PLAINTEXT-HOLDOUT-91bc"}'}


@pytest.fixture
def vault(tmp_path):
    _need_crypto()
    key = os.urandom(32)
    st = ST.EncryptedFileStore(tmp_path / "vault", key)
    cdig = st.write_corpus(CID, dict(PLAIN))
    return st, key, tmp_path / "vault" / CID, cdig


# ------------------------------------------------------------- unconfigured / preflight
def test_no_store_fails_closed():
    s = ST.NoStore()
    assert s.describe()["configured"] is False
    with pytest.raises(ST.PrivateStorageNotConfigured):
        s.read_split(CID, "QUALIFICATION_HOLDOUT", expected_corpus_digest="0" * 64)
    with pytest.raises(ST.PrivateStorageNotConfigured):
        s.write_corpus(CID, dict(PLAIN))


def test_preflight_reports_exact_owner_setup_when_unconfigured():
    r = ST.owner_setup_preflight({})
    assert r["status"] == "PRIVATE_STORAGE_NOT_CONFIGURED"
    assert {m["item"] for m in r["missing"]} >= {spec.STORE_ENV, spec.SECRET_ENV}
    r2 = ST.owner_setup_preflight({spec.STORE_ENV: f"PRIVATE_GITHUB_REPO:{ST.PUBLIC_REPO_SLUG}", spec.STORE_TOKEN_ENV: "x", spec.SECRET_ENV: "00" * 32})
    assert any("must NOT be the public" in m["need"] for m in r2["missing"])
    assert any("invalid" in m["need"] for m in r2["missing"])
    ok = ST.owner_setup_preflight({spec.STORE_ENV: "PRIVATE_OBJECT_STORE:s3://bucket/p", spec.STORE_TOKEN_ENV: "t", spec.SECRET_ENV: os.urandom(32).hex()})
    assert ok["missing"] == [] and "not proof" in ok["note"]
    assert ok["status"] == "PRIVATE_STORAGE_CONFIGURED_UNVERIFIED"          # presence of variables is never 'genuinely configured'


def test_descriptor_backends_are_not_operational_and_status_says_so():
    st = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    assert st["freeze_prerequisites"]["private_storage_genuinely_configured"] is False
    assert st["operational_storage_backend"] == "ENCRYPTED_ARTIFACT"
    assert st["infrastructure_subchecks"]["encrypted_store_backend_qualified_by_tests"] is True
    assert "PRIVATE_GITHUB_REPO" in st["descriptor_only_backends_not_operational"] and "PRIVATE_OBJECT_STORE" in st["descriptor_only_backends_not_operational"]
    assert not hasattr(ST, "PrivateGithubStore") and not hasattr(ST, "PrivateObjectStore")


# ------------------------------------------------------------- construction rules
def test_repo_local_path_low_entropy_key_and_bad_key_length_are_refused(tmp_path):
    _need_crypto()
    with pytest.raises(ST.PrivateStorageViolation):
        ST.EncryptedFileStore(ROOT / "eval_private" / "v2vault", os.urandom(32))
    with pytest.raises(ST.PrivateStorageViolation):
        ST.EncryptedFileStore(ROOT / "tmp_vault_under_repo", os.urandom(32))
    with pytest.raises(ST.PrivateStorageViolation):
        ST.EncryptedFileStore(tmp_path, b"\x01" * 32)
    for bad in (os.urandom(31), os.urandom(33), b"", "string-key-not-bytes-0123456789abcdef"):
        with pytest.raises(ST.PrivateStorageViolation):
            ST.EncryptedFileStore(tmp_path, bad)
    assert not (ROOT / "eval_private" / "v2vault").exists() and not (ROOT / "tmp_vault_under_repo").exists()


def test_missing_cryptography_raises_not_configured(monkeypatch, tmp_path):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("cryptography"):
            raise ImportError("blocked for test")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(ST.PrivateStorageNotConfigured):
        ST.EncryptedFileStore(tmp_path / "v", os.urandom(32))


# ------------------------------------------------------------- happy path + posture
def test_roundtrip_digest_binding_and_permissions(vault):
    st, key, cdir, cdig = vault
    for s, p in PLAIN.items():
        assert st.read_split(CID, s, expected_corpus_digest=cdig) == p
    assert cdig == ST.corpus_digest_of({s: hashlib.sha256(p).hexdigest() for s, p in PLAIN.items()})
    assert stat.S_IMODE(cdir.stat().st_mode) == 0o700 and stat.S_IMODE(cdir.parent.stat().st_mode) == 0o700
    names = sorted(p.name for p in cdir.iterdir())
    assert names == ["QUALIFICATION_HOLDOUT.enc", "SCREEN.enc", "SEAL.enc"]
    for p in cdir.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o400
    assert P.scan_vault_dir(cdir.parent)["pass"], P.scan_vault_dir(cdir.parent)


def test_plaintext_and_key_are_never_written_anywhere(vault):
    st, key, cdir, cdig = vault
    for f in cdir.parent.rglob("*"):
        if f.is_file():
            blob = f.read_bytes()
            assert b"UNIT-TEST-PLAINTEXT" not in blob and key not in blob and key.hex().encode() not in blob, f.name
    assert not list(cdir.parent.rglob(".tmp-*"))                       # temp files (ciphertext-only) removed after publish


def test_no_plaintext_ever_reaches_a_file_handle(tmp_path, monkeypatch):
    """Instrument every file object the store opens for writing: buffers must be non-empty ciphertext and never contain plaintext."""
    _need_crypto()
    st = ST.EncryptedFileStore(tmp_path / "v", os.urandom(32))
    seen = []
    real_fdopen = os.fdopen

    class Spy:
        def __init__(self, f):
            self._f = f

        def write(self, data):
            seen.append(bytes(data))
            return self._f.write(data)

        def __getattr__(self, n):
            return getattr(self._f, n)

        def __enter__(self):
            self._f.__enter__()
            return self

        def __exit__(self, *a):
            return self._f.__exit__(*a)
    monkeypatch.setattr(os, "fdopen", lambda fd, mode="r", *a, **k: Spy(real_fdopen(fd, mode, *a, **k)))
    st.write_corpus(CID, dict(PLAIN))
    assert len(seen) == 3 and all(len(b) > 40 for b in seen)                # non-vacuous: three ciphertext blobs
    assert all(b"UNIT-TEST-PLAINTEXT" not in b for b in seen)


def test_key_and_plaintext_never_serialized_or_printed(vault):
    st, key, cdir, cdig = vault
    assert key.hex() not in repr(st) and "<redacted>" in repr(st) and key.hex() not in str(st.describe())
    with pytest.raises(TypeError):
        pickle.dumps(st)
    import copy
    with pytest.raises(TypeError):
        copy.deepcopy(st)
    with pytest.raises(ST.PrivateStorageIntegrityError) as e:
        ST.EncryptedFileStore(cdir.parent, os.urandom(32)).read_split(CID, "SCREEN", expected_corpus_digest=cdig)
    msg = str(e.value) + repr(e.value)
    assert key.hex() not in msg and "UNIT-TEST-PLAINTEXT" not in msg


# ------------------------------------------------------------- write-once
def test_corpus_id_and_files_are_write_once(vault):
    st, key, cdir, cdig = vault
    with pytest.raises(FileExistsError):
        st.write_corpus(CID, {"SCREEN": b"other-1", "QUALIFICATION_HOLDOUT": b"other-2"})     # same corpus id: refused, nothing changed
    assert st.read_split(CID, "SCREEN", expected_corpus_digest=cdig) == PLAIN["SCREEN"]
    with pytest.raises(FileExistsError):
        st._publish(cdir / "SCREEN.enc", b"overwrite")                                      # publish never overwrites an existing artifact
    assert st.read_split(CID, "SCREEN", expected_corpus_digest=cdig) == PLAIN["SCREEN"]
    with pytest.raises(ST.PrivateStorageViolation):
        st.write_corpus("gce2c-" + "cd" * 16, {"SCREEN": b"x"})                              # both private splits required
    with pytest.raises(ST.PrivateStorageViolation):
        st.write_corpus("not-a-corpus-id", dict(PLAIN))


# ------------------------------------------------------------- integrity: wrong key / tamper / truncation / nonce / metadata / partial
def _reader(vault_dir, key):
    return ST.EncryptedFileStore(vault_dir, key)


def _rewrite(path, data):
    os.chmod(path, 0o600)
    path.write_bytes(data)
    os.chmod(path, 0o400)


def test_wrong_key_fails_closed(vault):
    st, key, cdir, cdig = vault
    with pytest.raises(ST.PrivateStorageIntegrityError):
        _reader(cdir.parent, os.urandom(32)).read_split(CID, "QUALIFICATION_HOLDOUT", expected_corpus_digest=cdig)


@pytest.mark.parametrize("target", ["SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"])
def test_bitflip_in_ciphertext_fails_closed(vault, target):
    st, key, cdir, cdig = vault
    b = bytearray((cdir / target).read_bytes())
    b[-5] ^= 0x01
    _rewrite(cdir / target, bytes(b))
    with pytest.raises(ST.PrivateStorageIntegrityError):
        st.read_split(CID, "SCREEN", expected_corpus_digest=cdig)
        st.read_split(CID, "QUALIFICATION_HOLDOUT", expected_corpus_digest=cdig)


@pytest.mark.parametrize("cut", [1, 16, 40, 100])
def test_truncation_fails_closed(vault, cut):
    st, key, cdir, cdig = vault
    b = (cdir / "QUALIFICATION_HOLDOUT.enc").read_bytes()
    _rewrite(cdir / "QUALIFICATION_HOLDOUT.enc", b[:-cut] if cut < len(b) else b"")
    with pytest.raises(ST.PrivateStorageIntegrityError):
        st.read_split(CID, "QUALIFICATION_HOLDOUT", expected_corpus_digest=cdig)


def test_empty_and_garbage_files_fail_closed(vault):
    st, key, cdir, cdig = vault
    _rewrite(cdir / "SCREEN.enc", b"")
    with pytest.raises(ST.PrivateStorageIntegrityError):
        st.read_split(CID, "SCREEN", expected_corpus_digest=cdig)
    _rewrite(cdir / "SCREEN.enc", os.urandom(300))
    with pytest.raises(ST.PrivateStorageIntegrityError):
        st.read_split(CID, "SCREEN", expected_corpus_digest=cdig)


def test_nonce_corruption_fails_closed(vault):
    st, key, cdir, cdig = vault
    b = bytearray((cdir / "SCREEN.enc").read_bytes())
    (hl,) = __import__("struct").unpack(">I", bytes(b[8:12]))
    b[12 + hl] ^= 0xFF                                                     # first nonce byte
    _rewrite(cdir / "SCREEN.enc", bytes(b))
    with pytest.raises(ST.PrivateStorageIntegrityError):
        st.read_split(CID, "SCREEN", expected_corpus_digest=cdig)


def test_header_metadata_edits_fail_authentication(vault):
    """The header is AEAD associated data: editing eval_version / corpus_id / split / digest fails even with a consistent-looking header."""
    st, key, cdir, cdig = vault
    orig = (cdir / "SCREEN.enc").read_bytes()
    (hl,) = __import__("struct").unpack(">I", orig[8:12])
    hdr = json.loads(orig[12:12 + hl])
    for field, val in (("eval_version", "genesis-capability-eval/1.0.0"), ("corpus_id", "gce2c-" + "ee" * 16), ("split", "QUALIFICATION_HOLDOUT"),
                       ("split_sha256", "0" * 64)):
        h2 = json.dumps({**hdr, field: val}, sort_keys=True, separators=(",", ":")).encode()
        forged = orig[:8] + __import__("struct").pack(">I", len(h2)) + h2 + orig[12 + hl:]
        _rewrite(cdir / "SCREEN.enc", forged)
        with pytest.raises(ST.PrivateStorageIntegrityError):
            st.read_split(CID, "SCREEN", expected_corpus_digest=cdig)
    _rewrite(cdir / "SCREEN.enc", orig)
    assert st.read_split(CID, "SCREEN", expected_corpus_digest=cdig) == PLAIN["SCREEN"]


def test_split_files_swapped_or_moved_to_another_corpus_fail(vault, tmp_path):
    st, key, cdir, cdig = vault
    a, b = (cdir / "SCREEN.enc").read_bytes(), (cdir / "QUALIFICATION_HOLDOUT.enc").read_bytes()
    _rewrite(cdir / "SCREEN.enc", b)
    _rewrite(cdir / "QUALIFICATION_HOLDOUT.enc", a)
    for s in spec.PRIVATE_SPLITS:
        with pytest.raises(ST.PrivateStorageIntegrityError):
            st.read_split(CID, s, expected_corpus_digest=cdig)
    _rewrite(cdir / "SCREEN.enc", a)
    _rewrite(cdir / "QUALIFICATION_HOLDOUT.enc", b)
    other = "gce2c-" + "99" * 16
    import shutil
    shutil.copytree(cdir, cdir.parent / other)                              # the same ciphertext under a different corpus identity
    with pytest.raises(ST.PrivateStorageIntegrityError):
        st.read_split(other, "SCREEN", expected_corpus_digest=cdig)


def test_wrong_expected_corpus_digest_fails(vault):
    st, key, cdir, cdig = vault
    with pytest.raises(ST.PrivateStorageIntegrityError):
        st.read_split(CID, "SCREEN", expected_corpus_digest="0" * 64)


def test_partial_write_is_never_readable_and_leaves_no_valid_corpus(tmp_path, monkeypatch):
    _need_crypto()
    st = ST.EncryptedFileStore(tmp_path / "v", os.urandom(32))
    real, calls = st._publish, {"n": 0}

    def flaky(path, blob):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated crash between artifacts")
        return real(path, blob)
    monkeypatch.setattr(st, "_publish", flaky)
    with pytest.raises(OSError):
        st.write_corpus(CID, dict(PLAIN))
    # SCREEN.enc exists (valid ciphertext) but there is NO SEAL: the corpus is a partial write and must not be readable
    with pytest.raises(ST.PrivateStorageIntegrityError):
        st.read_split(CID, "SCREEN", expected_corpus_digest=ST.corpus_digest_of({s: hashlib.sha256(p).hexdigest() for s, p in PLAIN.items()}))


def test_crash_after_temp_write_leaves_only_ciphertext_temp_that_is_ignored(tmp_path):
    _need_crypto()
    st = ST.EncryptedFileStore(tmp_path / "v", os.urandom(32))
    (tmp_path / "v" / CID).mkdir()
    t = tmp_path / "v" / CID / ".tmp-deadbeef"
    t.write_bytes(os.urandom(64))
    assert st.stray_temp_files(CID) == [".tmp-deadbeef"]
    with pytest.raises(ST.PrivateStorageIntegrityError):
        st.read_split(CID, "SCREEN", expected_corpus_digest="0" * 64)
    assert not P.scan_vault_dir(tmp_path / "v")["pass"]                  # the vault scanner flags the interrupted write


def test_backup_is_verbatim_ciphertext_outside_repo(vault, tmp_path):
    st, key, cdir, cdig = vault
    names = st.export_backup(CID, tmp_path / "backup", expected_corpus_digest=cdig)
    assert sorted(names) == ["QUALIFICATION_HOLDOUT.enc", "SCREEN.enc", "SEAL.enc"]
    for n in names:
        assert (tmp_path / "backup" / n).read_bytes() == (cdir / n).read_bytes()
        assert b"UNIT-TEST-PLAINTEXT" not in (tmp_path / "backup" / n).read_bytes()
    restored = ST.EncryptedFileStore(tmp_path / "restored", key)
    (tmp_path / "restored" / CID).mkdir(mode=0o700)
    for n in names:
        (tmp_path / "restored" / CID / n).write_bytes((tmp_path / "backup" / n).read_bytes())
    assert restored.read_split(CID, "QUALIFICATION_HOLDOUT", expected_corpus_digest=cdig) == PLAIN["QUALIFICATION_HOLDOUT"]
    with pytest.raises(ST.PrivateStorageViolation):
        st.export_backup(CID, ROOT / "backup_inside_repo", expected_corpus_digest=cdig)
    assert not (ROOT / "backup_inside_repo").exists()
    with pytest.raises(ST.PrivateStorageIntegrityError):
        st.export_backup(CID, tmp_path / "b2", expected_corpus_digest="0" * 64)          # only a verified corpus is backed up


def test_public_split_is_not_a_storable_private_split(vault):
    st, key, cdir, cdig = vault
    with pytest.raises(ST.PrivateStorageViolation):
        st.read_split(CID, "DEV", expected_corpus_digest=cdig)


# ------------------------------------------------------------- dependency + CI declaration
def test_cryptography_is_a_declared_extra_and_a_mandatory_ci_job_exists():
    pp = tomllib.loads((ROOT / "pyproject.toml").read_text())
    reqs = pp["project"]["optional-dependencies"]["qualification"]
    assert len(reqs) == 1 and re.match(r"^cryptography>=\d+\.\d+\.\d+,<\d+\.\d+\.\d+$", reqs[0]), reqs
    wf = (ROOT / ".github/workflows/test.yml").read_text()
    assert "genesis-v2-security:" in wf and '.[dev,qualification]' in wf and 'ORNEUR_REQUIRE_CRYPTOGRAPHY: "1"' in wf
    sh = (ROOT / "scripts/ci/run_genesis_v2_security_tests.sh").read_text()
    assert "skipped|xfailed|deselected" in sh and "set -euo pipefail" in sh


def test_storage_policy_document_covers_backup_and_recovery():
    t = (ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STORAGE_POLICY.md").read_text()
    low = t.lower()
    for s in ("ciphertext-only", "key loss", "fresh corpus version", "two custodians", "no plaintext backup", "0700", "aes-256-gcm"):
        assert s in low, s
