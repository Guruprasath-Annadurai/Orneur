"""Private-storage interface: ONE conformance suite run against the real fail-closed NoStore, the real EncryptedFileStore (ephemeral test key, tempdir) and
the SYNTHETIC backends. The unconfigured case must refuse every operation."""
import os
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import store as ST
from orca.evalinfra import private_store as PS
from tests.evalinfra_helpers import ROOT

CID = "gce2c-" + "cd" * 16
SPLITS = {"SCREEN": b"synthetic screen bytes", "QUALIFICATION_HOLDOUT": b"synthetic holdout bytes"}


def _encrypted(tmp_path):
    pytest.importorskip("cryptography")
    return ST.EncryptedFileStore(tmp_path / "enc", os.urandom(32))        # ephemeral key, outside the repo, test only


BACKENDS = {
    "synthetic-memory": lambda tp: PS.SyntheticMemoryStore(configured=True),
    "synthetic-dir": lambda tp: PS.SyntheticDirStore(tp / "dir"),
    "real-encrypted-file-store": _encrypted,
}
UNCONFIGURED = {
    "real-nostore": lambda tp: ST.NoStore(),
    "synthetic-memory-unconfigured": lambda tp: PS.SyntheticMemoryStore(configured=False),
    "synthetic-dir-unconfigured": lambda tp: PS.SyntheticDirStore(None),
}


@pytest.mark.parametrize("name", sorted(UNCONFIGURED))
def test_unconfigured_backend_refuses_every_operation(name, tmp_path):
    s = UNCONFIGURED[name](tmp_path)
    assert s.describe()["configured"] is False
    with pytest.raises(ST.PrivateStorageNotConfigured):
        s.write_corpus(CID, SPLITS)
    with pytest.raises(ST.PrivateStorageNotConfigured):
        s.read_split(CID, "SCREEN", expected_corpus_digest="0" * 64)
    assert PS.is_private_grade(s) is False


@pytest.mark.parametrize("name", sorted(BACKENDS))
def test_conformance_roundtrip_write_once_and_digest_binding(name, tmp_path):
    s = BACKENDS[name](tmp_path)
    digest = s.write_corpus(CID, SPLITS)
    assert len(digest) == 64
    for k, v in SPLITS.items():
        assert s.read_split(CID, k, expected_corpus_digest=digest) == v
    with pytest.raises(Exception):                                    # write-once: a corpus id can be used once
        s.write_corpus(CID, SPLITS)
    with pytest.raises(ST.PrivateStorageIntegrityError):              # wrong expected digest
        s.read_split(CID, "SCREEN", expected_corpus_digest="1" * 64)
    with pytest.raises(ST.PrivateStorageViolation):                   # only the private splits exist
        s.read_split(CID, "DEV", expected_corpus_digest=digest)
    with pytest.raises(ST.PrivateStorageIntegrityError):              # unknown corpus
        s.read_split("gce2c-" + "ef" * 16, "SCREEN", expected_corpus_digest=digest)


@pytest.mark.parametrize("name", sorted(BACKENDS))
def test_conformance_requires_both_private_splits_and_bytes(name, tmp_path):
    s = BACKENDS[name](tmp_path)
    with pytest.raises(ST.PrivateStorageViolation):
        s.write_corpus(CID, {"SCREEN": b"only one"})
    with pytest.raises(ST.PrivateStorageViolation):
        s.write_corpus(CID, {"SCREEN": "text", "QUALIFICATION_HOLDOUT": b"x"})
    with pytest.raises(ST.PrivateStorageViolation):
        s.write_corpus("not-a-corpus-id", SPLITS)


def test_synthetic_memory_tamper_is_detected_on_read():
    s = PS.SyntheticMemoryStore(configured=True)
    d = s.write_corpus(CID, SPLITS)
    s.tamper_for_test(CID, "SCREEN", b"corrupted")
    with pytest.raises(ST.PrivateStorageIntegrityError):
        s.read_split(CID, "SCREEN", expected_corpus_digest=d)


def test_synthetic_dir_tamper_partial_write_and_seal_edit_detected(tmp_path):
    s = PS.SyntheticDirStore(tmp_path / "d")
    d = s.write_corpus(CID, SPLITS)
    f = tmp_path / "d" / CID / "SCREEN.bin"
    f.write_bytes(b"x" * 10)
    with pytest.raises(ST.PrivateStorageIntegrityError):
        s.read_split(CID, "SCREEN", expected_corpus_digest=d)
    assert s.read_split(CID, "QUALIFICATION_HOLDOUT", expected_corpus_digest=d) == SPLITS["QUALIFICATION_HOLDOUT"]
    (tmp_path / "d" / CID / "SEAL.json").unlink()                      # a corpus without its SEAL is a partial write
    with pytest.raises(ST.PrivateStorageIntegrityError):
        s.read_split(CID, "QUALIFICATION_HOLDOUT", expected_corpus_digest=d)
    (tmp_path / "d" / CID / "SEAL.json").write_text("{not json")
    with pytest.raises(ST.PrivateStorageIntegrityError):
        s.read_split(CID, "QUALIFICATION_HOLDOUT", expected_corpus_digest=d)


def test_synthetic_dir_refuses_a_location_inside_the_repository():
    with pytest.raises(ST.PrivateStorageViolation):
        PS.SyntheticDirStore(ROOT / "eval_private" / "never_created_by_tests")
    assert not (ROOT / "eval_private" / "never_created_by_tests").exists()


def test_synthetic_backends_are_never_private_grade_or_confidential():
    for s in (PS.SyntheticMemoryStore(configured=True), PS.SyntheticDirStore(Path("/tmp") / "evalinfra-pg-check")):
        d = s.describe()
        assert d["kind"] == PS.SYNTHETIC_KIND and d["private_grade"] is False and d["confidential"] is False
        assert PS.is_private_grade(s) is False


def test_real_encrypted_store_is_the_only_one_reported_private_grade(tmp_path):
    assert PS.is_private_grade(_encrypted(tmp_path)) is True
    assert PS.is_private_grade(ST.NoStore()) is False


def test_guarded_reader_never_touches_the_store_without_a_valid_grant():
    class Boom:
        def read_split(self, *a, **k):
            raise AssertionError("store must not be touched")
    from orca.evalinfra.errors import AccessDeniedError
    r = PS.GuardedReader(Boom(), grant_checker=lambda g, **k: ["NO_GRANT"])
    with pytest.raises(AccessDeniedError):
        r.read_split(None, CID, "SCREEN", expected_corpus_digest="0" * 64)
