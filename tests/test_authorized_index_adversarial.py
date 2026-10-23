"""Adversarial confinement, integrity, crash recovery, and encoder identity."""
from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from orca.docs.authorized_index import (
    PRODUCTION_ENCODER_ID,
    AuthorizedIndex,
    LocalEncoder,
    TrustedOllamaEncoder,
)
from orca.truth.access import AccessDenied, SessionAuthority
from orca.truth.indexed_query import scan_conflicts


def _index(tmp_path, encoder=None):
    authority = SessionAuthority()
    session = authority.issue("tenant-a", "principal-a")
    index = AuthorizedIndex(authority, session, tmp_path, encoder=encoder)
    return authority, session, index


def test_symlinked_parent_directory_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    authority = SessionAuthority()
    session = authority.issue("tenant-a", "principal-a")
    with pytest.raises(AccessDenied, match="symlink|not a directory"):
        AuthorizedIndex(authority, session, link)


def test_world_writable_nonsticky_parent_is_refused(tmp_path):
    root = tmp_path / "open"
    root.mkdir()
    os.chmod(root, 0o777)
    mode = stat.S_IMODE(root.stat().st_mode)
    if not (mode & 0o022) or (mode & stat.S_ISVTX):
        pytest.skip("filesystem did not retain world-write without sticky")
    authority = SessionAuthority()
    session = authority.issue("tenant-a", "principal-a")
    with pytest.raises(AccessDenied, match="permissions"):
        AuthorizedIndex(authority, session, root)


def test_directory_replacement_does_not_follow_a_new_symlink(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    authority, session, index = _index(root)
    digest = index.admit(session, "kept", "kept fact is visible")
    session_dir = root / session.session_id
    backup = tmp_path / "backup"
    os.rename(session_dir, backup)
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (decoy / "chunks.jsonl").write_text('{"text":"OUTSIDE"}\n')
    os.symlink(decoy, session_dir)
    report = index.search(session, "kept")
    assert report.hits and report.hits[0].text.startswith("kept fact")
    assert index.replay(session, digest, "kept fact is visible") is True
    index.close()


def test_coordinated_text_and_digest_edit_is_integrity_mismatch(tmp_path):
    _authority, session, index = _index(tmp_path)
    original = index.admit(session, "kept", "kept fact is visible")
    leaf = tmp_path / session.session_id / "chunks.jsonl"
    rows = [json.loads(line) for line in leaf.read_text().splitlines()]
    rows[0]["text"] = "kept fact is substituted"
    rows[0]["content_sha256"] = __import__("hashlib").sha256(rows[0]["text"].encode()).hexdigest()
    leaf.write_text(json.dumps(rows[0]) + "\n")
    report = index.search(session, "kept")
    assert report.hits == ()
    assert any(reason.startswith("integrity mismatch") for reason in report.partial_reasons)
    assert index.replay(session, original, "kept fact is visible") is False
    assert index.replay(session, rows[0]["content_sha256"], rows[0]["text"]) is False


def test_stale_temporary_files_are_swept_without_dropping_committed_rows(tmp_path):
    _authority, session, index = _index(tmp_path)
    digest = index.admit(session, "harbor", "harbor depth is charted")
    session_dir = tmp_path / session.session_id
    stale = session_dir / f".chunks.jsonl.{os.getpid()}.{threading.get_ident()}.{'ab' * 16}.tmp"
    stale.write_text("partial")
    index.close()
    authority = SessionAuthority()
    # reopen with a new session would be a different directory; reopen same path via new object
    # The original session object remains valid for the same authority only if we keep it.
    # Reconstruct from the same files by opening a second index on a sibling session, then
    # reopen using the original session through a second AuthorizedIndex with a cloned authority
    # is not possible. Sweep is on init of a new index for the same session id: use the
    # original session with a second constructor after close.
    # SessionAuthority tokens are unique; instead sweep via a new index on the same session
    # directory by constructing AuthorizedIndex with the still-current session.
    second = AuthorizedIndex(_authority, session, tmp_path)
    assert not stale.exists()
    assert second.replay(session, digest, "harbor depth is charted") is True
    second.close()


def test_truncated_replace_leaves_the_committed_leaf(tmp_path):
    _authority, session, index = _index(tmp_path)
    digest = index.admit(session, "bridge", "bridge length is four hundred meters")
    real_write = os.write

    def once(fd, data):
        if isinstance(data, memoryview) and len(data) > 8:
            raise OSError("disk full")
        return real_write(fd, data)

    with patch("os.write", side_effect=once):
        with pytest.raises(OSError, match="disk full"):
            index.admit(session, "extra", "extra document text is here")
    assert index.replay(session, digest, "bridge length is four hundred meters") is True
    leftover = [name for name in os.listdir(tmp_path / session.session_id) if name.endswith(".tmp")]
    assert leftover == []


def test_index_lock_serializes_a_second_process(tmp_path):
    _authority, session, index = _index(tmp_path)
    lock_path = tmp_path / session.session_id / ".index.lock"
    holder = os.open(lock_path, os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)
    script = (
        "import fcntl, os, sys\n"
        f"fd = os.open({str(lock_path)!r}, os.O_RDWR)\n"
        "try:\n"
        "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except BlockingIOError:\n"
        "    sys.exit(2)\n"
        "sys.exit(0)\n"
    )
    blocked = subprocess.run([sys.executable, "-c", script], check=False)
    assert blocked.returncode == 2
    fcntl.flock(holder, fcntl.LOCK_UN)
    os.close(holder)
    free = subprocess.run([sys.executable, "-c", script], check=False)
    assert free.returncode == 0
    index.close()


def test_concurrent_thread_admits_serialize(tmp_path):
    _authority, session, index = _index(tmp_path)
    errors: list[BaseException] = []

    def admit(name: str) -> None:
        try:
            index.admit(session, name, f"{name} token is unique")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=admit, args=(f"doc{i}",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert index.count() == 8


def test_spoofed_nomic_callable_is_not_production_neural(tmp_path):
    def embed(text: str):
        return (1.0, 0.0) if "zephyr" in text else (0.0, 1.0)

    _authority, session, index = _index(
        tmp_path,
        encoder=LocalEncoder("neural", PRODUCTION_ENCODER_ID, embed),
    )
    index.admit(session, "zephyr", "zephyr lattice calibration")
    report = index.search(session, "zephyr")
    assert report.production_neural is False
    assert report.dense_backend == "unqualified"
    assert report.method == "hybrid-rrf"


def test_probe_does_not_qualify_a_trusted_adapter(tmp_path):
    class _Resp:
        def read(self):
            return json.dumps({"embedding": [0.1] * 8, "model": "nomic-embed-text"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    encoder = TrustedOllamaEncoder("http://127.0.0.1:9")
    with patch("urllib.request.urlopen", return_value=_Resp()):
        assert encoder.probe() is True
    assert encoder.qualified() is False
    _authority, session, index = _index(tmp_path, encoder=encoder)
    index.admit(session, "zephyr", "zephyr lattice calibration")
    with patch("urllib.request.urlopen", return_value=_Resp()):
        report = index.search(session, "zephyr")
    assert report.production_neural is True
    assert encoder.qualified() is True
    assert report.dense_backend == PRODUCTION_ENCODER_ID


def test_trusted_adapter_without_model_field_is_unqualified(tmp_path):
    class _Resp:
        def read(self):
            return json.dumps({"embedding": [0.2, 0.1]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    encoder = TrustedOllamaEncoder("http://127.0.0.1:9")
    _authority, session, index = _index(tmp_path, encoder=encoder)
    index.admit(session, "zephyr", "zephyr lattice calibration")
    with patch("urllib.request.urlopen", return_value=_Resp()):
        report = index.search(session, "zephyr")
    assert report.production_neural is False
    assert report.dense_backend == "unqualified"
    assert encoder.qualified() is False


def test_key_rotation_rebinds_existing_rows(tmp_path):
    _authority, session, index = _index(tmp_path)
    digest = index.admit(session, "beacon", "beacon interval is hourly")
    index.rotate_integrity_key(session)
    assert index.replay(session, digest, "beacon interval is hourly") is True
    report = index.search(session, "beacon")
    assert report.hits[0].content_sha256 == digest


def test_natural_language_conflicts_and_uncertain_without_a_model():
    scan = scan_conflicts(["The lamp is on", "The lamp is off"])
    assert scan.conflicts
    assert scan.model_backed is False
    assert "lamp=" in scan.conflicts[0]
    keyed = scan_conflicts(["lamp state = on", "lamp state = off"])
    assert keyed.conflicts
    uncertain = scan_conflicts([
        "the first report says the beacon works; however the second insists it failed overnight",
    ])
    assert uncertain.conflicts == ()
    assert uncertain.uncertain
    assert uncertain.model_backed is False
