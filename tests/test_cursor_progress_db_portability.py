"""Progress-database portability and symlink resistance.

Linux execution in this file is real. The Darwin branch is exercised by
supplying the directory path a `F_GETPATH` call would have returned; this
environment has not executed Darwin `fcntl`.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from orca.genesis.data.pipeline import (
    PROGRESS_DB_NAME,
    CorpusBoundaryError,
    _darwin_descriptor_path,
    _open_progress_db,
    iter_kept_records,
    process_corpus,
)


def _record(path, text: str) -> None:
    path.write_text(json.dumps({"text": text}) + "\n")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc descriptor URI only")
def test_linux_uri_is_anchored_to_the_directory_descriptor(tmp_path, monkeypatch):
    import orca.genesis.data.pipeline as pipeline

    out = tmp_path / "out"
    out.mkdir()
    uris: list[str] = []
    real_connect = pipeline.sqlite3.connect

    def wrapped(*args, **kwargs):
        uris.append(args[0] if args else kwargs.get("database"))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(pipeline.sqlite3, "connect", wrapped)
    conn = _open_progress_db(out)
    conn.close()
    assert len(uris) == 1
    assert uris[0].startswith("file:/proc/self/fd/")
    assert uris[0].endswith(f"/{PROGRESS_DB_NAME}?mode=rw")
    assert str(out) not in uris[0]


def test_progress_database_uses_wal_and_regular_sidecars(tmp_path):
    source = tmp_path / "in.jsonl"
    text = "a short synthetic sentence about rain"
    _record(source, text)
    out = tmp_path / "out"
    report, kept = process_corpus(source, out, num_shards=1)
    assert report.kept == 1
    assert kept == [text]
    conn = _open_progress_db(out)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        for suffix in ("", "-wal", "-shm"):
            path = out / f"{PROGRESS_DB_NAME}{suffix}"
            assert path.is_file()
            assert not path.is_symlink()
        row = conn.execute("PRAGMA database_list").fetchone()
        assert os.lstat(row[2]).st_ino == (out / PROGRESS_DB_NAME).stat().st_ino
    finally:
        conn.close()
    resumed, kept_again = process_corpus(source, out, num_shards=1)
    assert resumed.kept == 1
    assert kept_again == [text]


def test_progress_db_symlink_is_not_followed(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    secret = tmp_path / "secret.sqlite3"
    secret.write_bytes(b"ORIGINAL")
    os.symlink(secret, out / PROGRESS_DB_NAME)
    with pytest.raises(CorpusBoundaryError, match="symlink"):
        _open_progress_db(out)
    assert secret.read_bytes() == b"ORIGINAL"
    assert (out / PROGRESS_DB_NAME).is_symlink()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_progress_sidecar_symlink_is_not_followed(tmp_path, suffix):
    out = tmp_path / "out"
    out.mkdir()
    secret = tmp_path / "secret"
    secret.write_bytes(b"ORIGINAL")
    os.symlink(secret, out / f"{PROGRESS_DB_NAME}{suffix}")
    with pytest.raises(CorpusBoundaryError, match="symlink"):
        _open_progress_db(out)
    assert secret.read_bytes() == b"ORIGINAL"
    assert (out / f"{PROGRESS_DB_NAME}{suffix}").is_symlink()


def test_iter_kept_records_refuses_a_progress_symlink(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    secret = tmp_path / "secret.sqlite3"
    secret.write_bytes(b"ORIGINAL")
    os.symlink(secret, out / PROGRESS_DB_NAME)
    with pytest.raises(CorpusBoundaryError, match="symlink"):
        list(iter_kept_records(out))
    assert secret.read_bytes() == b"ORIGINAL"


def test_other_platforms_do_not_fall_back_to_a_pathname(tmp_path, monkeypatch):
    import orca.genesis.data.pipeline as pipeline

    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(pipeline.sys, "platform", "freebsd")

    def wrapped(*args, **kwargs):
        raise AssertionError(f"SQLite connect was called: {args!r}")

    monkeypatch.setattr(pipeline.sqlite3, "connect", wrapped)
    with pytest.raises(CorpusBoundaryError, match="freebsd"):
        _open_progress_db(out)
    assert not (out / PROGRESS_DB_NAME).exists()


_HOST_PLATFORM = sys.platform


def _linux_simulated_darwin_descriptor_path(fd: int) -> str:
    """Linux stand-in for Darwin `F_GETPATH`: the kernel path of this fd."""
    return os.readlink(f"/proc/self/fd/{fd}")


def test_darwin_branch_binds_sqlite_to_the_descriptor_directory(tmp_path, monkeypatch):
    """Darwin URI construction binds SQLite to the opened directory.

    On Linux this simulates `F_GETPATH` without using Darwin fcntl. On macOS
    the real descriptor lookup is used. Patching `pipeline.sys.platform`
    also mutates the process `sys.platform`, so the host is captured first.
    """
    import orca.genesis.data.pipeline as pipeline

    out = tmp_path / "out"
    out.mkdir()
    if _HOST_PLATFORM != "darwin":
        monkeypatch.setattr(pipeline.sys, "platform", "darwin")
        monkeypatch.setattr(
            pipeline, "_darwin_descriptor_path", _linux_simulated_darwin_descriptor_path,
        )
    conn = _open_progress_db(out)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        reported = conn.execute("PRAGMA database_list").fetchone()[2]
        assert os.lstat(reported).st_ino == (out / PROGRESS_DB_NAME).stat().st_ino
        assert os.lstat(reported).st_dev == (out / PROGRESS_DB_NAME).stat().st_dev
        assert not os.path.islink(reported)
    finally:
        conn.close()


def test_darwin_branch_rejects_a_different_directory(tmp_path, monkeypatch):
    import orca.genesis.data.pipeline as pipeline

    out = tmp_path / "out"
    out.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(pipeline.sys, "platform", "darwin")
    monkeypatch.setattr(pipeline, "_darwin_descriptor_path", lambda _fd: str(other))

    def wrapped(*args, **kwargs):
        raise AssertionError(f"SQLite connect was called: {args!r}")

    monkeypatch.setattr(pipeline.sqlite3, "connect", wrapped)
    with pytest.raises(CorpusBoundaryError, match="different directory"):
        _open_progress_db(out)
    assert list(other.iterdir()) == []


@pytest.mark.skipif(sys.platform != "linux", reason="Linux refuse path for Darwin F_GETPATH")
def test_darwin_fcntl_lookup_is_refused_on_linux():
    with pytest.raises(CorpusBoundaryError, match="Darwin descriptor path lookup"):
        _darwin_descriptor_path(0)
