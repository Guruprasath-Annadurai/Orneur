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

import hashlib

from orca.docs.authorized_index import (
    PRODUCTION_ENCODER_ID,
    AuthorizedIndex,
    LocalEncoder,
    TrustedOllamaEncoder,
    _chunks_name,
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


def _pointer(tmp_path, session):
    return tmp_path / session.session_id / ".generation"


def _rewrite_pointer_hashes(tmp_path, session, index):
    session_dir = tmp_path / session.session_id
    gen = index._generation
    record = json.loads(_pointer(tmp_path, session).read_text())
    record["key_sha256"] = hashlib.sha256((session_dir / f"g{gen}.mac.key").read_bytes()).hexdigest()
    record["chunks_sha256"] = hashlib.sha256((session_dir / _chunks_name(gen)).read_bytes()).hexdigest()
    record["revoked_sha256"] = hashlib.sha256((session_dir / f"g{gen}.revoked.txt").read_bytes()).hexdigest()
    _pointer(tmp_path, session).write_text(json.dumps(record, sort_keys=True, separators=(",", ":")))


def test_coordinated_text_and_digest_edit_is_integrity_mismatch(tmp_path):
    _authority, session, index = _index(tmp_path)
    original = index.admit(session, "kept", "kept fact is visible")
    leaf = tmp_path / session.session_id / _chunks_name(index._generation)
    rows = [json.loads(line) for line in leaf.read_text().splitlines()]
    rows[0]["text"] = "kept fact is substituted"
    rows[0]["content_sha256"] = hashlib.sha256(rows[0]["text"].encode()).hexdigest()
    leaf.write_text(json.dumps(rows[0]) + "\n")
    _rewrite_pointer_hashes(tmp_path, session, index)
    report = index.search(session, "kept")
    assert report.hits == ()
    assert any(reason.startswith("integrity mismatch") for reason in report.partial_reasons)
    assert index.replay(session, original, "kept fact is visible") is False
    assert index.replay(session, rows[0]["content_sha256"], rows[0]["text"]) is False


def test_tampered_chunks_without_pointer_update_fail_closed(tmp_path):
    _authority, session, index = _index(tmp_path)
    index.admit(session, "kept", "kept fact is visible")
    leaf = tmp_path / session.session_id / _chunks_name(index._generation)
    leaf.write_text('{"text":"substituted"}\n')
    with pytest.raises(AccessDenied, match="does not match the generation pointer"):
        index.search(session, "kept")


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


class _Injected(RuntimeError):
    pass


def _stop_at(target: str):
    def hook(stage: str) -> None:
        if stage == target:
            raise _Injected(stage)
    return hook


@pytest.mark.parametrize(
    "stage",
    [
        "before-key",
        "after-key",
        "after-chunks",
        "after-revoked",
        "after-dirsync",
        "after-publish",
        "after-commit-dirsync",
        "after-cleanup",
    ],
)
def test_rotation_interruption_preserves_or_commits_one_generation(tmp_path, stage):
    authority, session, index = _index(tmp_path)
    digest = index.admit(session, "beacon", "beacon interval is hourly")
    before = index._generation
    index._inject_fault = _stop_at(stage)
    try:
        index.rotate_integrity_key(session)
    except _Injected:
        pass
    index.close()
    recovered = AuthorizedIndex(authority, session, tmp_path)
    assert recovered.replay(session, digest, "beacon interval is hourly") is True
    assert recovered.search(session, "beacon").hits[0].content_sha256 == digest
    if stage in {"before-key", "after-key", "after-chunks", "after-revoked", "after-dirsync"}:
        assert recovered._generation == before
    else:
        assert recovered._generation == before + 1
    recovered.close()


def test_second_handle_sees_delete_and_cannot_readmit(tmp_path):
    authority, session, first = _index(tmp_path)
    digest = first.admit(session, "manual", "manual code = secret")
    second = AuthorizedIndex(authority, session, tmp_path)
    warmed = first.search(session, "manual")
    assert warmed.hits
    assert second.delete(session, "manual") == 1
    stale = first.search(session, "manual")
    assert stale.hits == ()
    assert stale.cache_hit is False
    assert first.replay(session, digest, "manual code = secret") is False
    with pytest.raises(AccessDenied, match="revoked"):
        first.admit(session, "manual", "manual code = secret")
    first.close()
    second.close()


def test_rotation_is_visible_to_the_other_open_handle(tmp_path):
    authority, session, first = _index(tmp_path)
    digest = first.admit(session, "beacon", "beacon interval is hourly")
    second = AuthorizedIndex(authority, session, tmp_path)
    second.rotate_integrity_key(session)
    assert first.replay(session, digest, "beacon interval is hourly") is True
    assert first.search(session, "beacon").hits[0].content_sha256 == digest
    first.close()
    second.close()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_forked_process_delete_is_visible_after_reopen(tmp_path):
    authority, session, index = _index(tmp_path)
    digest = index.admit(session, "kept", "kept fact is visible")
    index.close()
    pid = os.fork()
    if pid == 0:
        try:
            child = AuthorizedIndex(authority, session, tmp_path)
            child.delete(session, "kept")
            child.close()
            os._exit(0)
        except Exception:
            os._exit(1)
    _pid, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
    parent = AuthorizedIndex(authority, session, tmp_path)
    assert parent.search(session, "kept").hits == ()
    assert parent.replay(session, digest, "kept fact is visible") is False
    parent.close()


def test_revocation_file_tamper_without_pointer_fails_closed(tmp_path):
    _authority, session, index = _index(tmp_path)
    digest = index.admit(session, "kept", "kept fact is visible")
    index.delete(session, "kept")
    revoked = tmp_path / session.session_id / f"g{index._generation}.revoked.txt"
    revoked.write_text("")
    with pytest.raises(AccessDenied, match="revocation state"):
        index.search(session, "kept")
    index.close()
    with pytest.raises(AccessDenied, match="revocation state"):
        AuthorizedIndex(_authority, session, tmp_path)
    assert digest


def test_missing_generation_pointer_does_not_wipe_an_existing_store(tmp_path):
    authority, session, index = _index(tmp_path)
    digest = index.admit(session, "kept", "kept fact is visible")
    index.delete(session, "kept")
    session_dir = tmp_path / session.session_id
    gen = index._generation
    pointer = session_dir / ".generation"
    pointer.unlink()
    before = {path.name: path.read_bytes() for path in session_dir.iterdir() if path.name.startswith("g")}
    assert before
    index.close()
    with pytest.raises(AccessDenied, match="generation pointer is missing"):
        AuthorizedIndex(authority, session, tmp_path)
    after = {path.name: path.read_bytes() for path in session_dir.iterdir() if path.name.startswith("g")}
    assert after == before
    assert digest.encode() in after[f"g{gen}.revoked.txt"] or digest in after[f"g{gen}.revoked.txt"].decode()
    with pytest.raises(AccessDenied, match="generation pointer is missing"):
        AuthorizedIndex(authority, session, tmp_path)


def test_malformed_generation_pointer_preserves_generation_files(tmp_path):
    authority, session, index = _index(tmp_path)
    index.admit(session, "kept", "kept fact is visible")
    session_dir = tmp_path / session.session_id
    (session_dir / ".generation").write_text("{not-json")
    before = sorted(p.name for p in session_dir.iterdir() if p.name.startswith("g"))
    index.close()
    with pytest.raises(AccessDenied, match="unreadable|malformed"):
        AuthorizedIndex(authority, session, tmp_path)
    after = sorted(p.name for p in session_dir.iterdir() if p.name.startswith("g"))
    assert after == before


def test_partial_integrity_failure_does_not_discard_rows_on_admit(tmp_path):
    authority, session, index = _index(tmp_path)
    first = index.admit(session, "alpha", "alpha fact is one")
    second = index.admit(session, "beta", "beta fact is two")
    leaf = tmp_path / session.session_id / _chunks_name(index._generation)
    rows = [json.loads(line) for line in leaf.read_text().splitlines()]
    rows[0]["mac"] = "00" * 32
    leaf.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    _rewrite_pointer_hashes(tmp_path, session, index)
    with pytest.raises(AccessDenied, match="unrecoverable index"):
        index.admit(session, "gamma", "gamma fact is three")
    report = index.search(session, "beta")
    assert any(hit.content_sha256 == second for hit in report.hits)
    assert any(reason.startswith("integrity mismatch") for reason in report.partial_reasons)
    with pytest.raises(AccessDenied, match="unrecoverable index"):
        index.delete(session, "beta")
    assert first and second


def test_empty_session_directory_still_bootstraps(tmp_path):
    authority, session, index = _index(tmp_path)
    assert index.count() == 0
    digest = index.admit(session, "kept", "kept fact is visible")
    assert index.replay(session, digest, "kept fact is visible") is True
    index.close()


def test_same_directory_hmac_is_not_a_same_uid_authenticity_boundary(tmp_path):
    """An attacker who can rewrite records, key, and the generation pointer
    can mint a valid MAC. The HMAC is not a claim against that attacker.
    """
    _authority, session, index = _index(tmp_path)
    index.admit(session, "kept", "kept fact is visible")
    session_dir = tmp_path / session.session_id
    gen = index._generation
    key = (session_dir / f"g{gen}.mac.key").read_bytes()
    row = {
        "doc_id": "kept",
        "filename": "kept",
        "chunk_idx": 0,
        "text": "kept fact is forged",
        "version": 9,
        "content_sha256": hashlib.sha256(b"kept fact is forged").hexdigest(),
        "tenant_id": "tenant-a",
        "session_id": session.session_id,
    }
    row["mac"] = index._mac(row, key)
    payload = json.dumps(row, sort_keys=True) + "\n"
    (session_dir / _chunks_name(gen)).write_text(payload)
    _rewrite_pointer_hashes(tmp_path, session, index)
    forged = index.search(session, "forged")
    assert forged.hits and forged.hits[0].text == "kept fact is forged"
