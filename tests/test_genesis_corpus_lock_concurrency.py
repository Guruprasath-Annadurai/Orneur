"""Adversarial coverage for Genesis corpus lock acquisition.

The Darwin failure is FileNotFoundError(ENOENT) from
`_open_regular_at()` on `.process_corpus.lock` before `fcntl.flock()`.
Linux is not Darwin/APFS. Native 100-round tests skip here and must not
be reported as PASS. SQLite and shard bytes are checked, not only
process exit codes.
"""
from __future__ import annotations

import errno
import json
import os
import sqlite3
import stat
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pytest

import orca.genesis.data.pipeline as pipeline
from orca.genesis.data.pipeline import (
    PROGRESS_DB_NAME,
    CorpusBoundaryError,
    _OPEN_REGULAR_TRANSIENT_ENOENT_ATTEMPTS,
    _open_directory_leaf,
    _open_regular_at,
    iter_kept_records,
    process_corpus,
)


def _write_jsonl(path: Path, texts: list[str]) -> None:
    path.write_text("".join(json.dumps({"text": t}) + "\n" for t in texts))


def _shard_texts(output_dir: Path) -> list[str]:
    texts: list[str] = []
    for shard in sorted(output_dir.glob("shard-*.jsonl")):
        for line in shard.read_text().splitlines():
            if line.strip():
                texts.append(json.loads(line)["text"])
    return texts


def _sqlite_kept(output_dir: Path) -> list[str]:
    db = output_dir / PROGRESS_DB_NAME
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT normalized_text FROM kept_records ORDER BY seq").fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def _assert_durable_once(output_dir: Path, expected: list[str]) -> None:
    sqlite_kept = _sqlite_kept(output_dir)
    shard_kept = _shard_texts(output_dir)
    iterated = list(iter_kept_records(output_dir))
    assert sqlite_kept == iterated
    assert sorted(sqlite_kept) == sorted(expected)
    assert sorted(shard_kept) == sorted(expected)
    assert len(sqlite_kept) == len(expected)
    assert len(shard_kept) == len(expected)
    lock = output_dir / ".process_corpus.lock"
    assert lock.is_file()
    assert not lock.is_symlink()


def _run_process_corpus(payload: tuple[str, str, int]) -> tuple[int, str | None]:
    in_path, out_path, shards = payload
    try:
        report, _kept = process_corpus(
            in_path,
            out_path,
            num_shards=shards,
            commit_batch_size=5,
            return_kept_records=False,
        )
        return report.kept, None
    except BaseException as exc:  # noqa: BLE001
        return -1, f"{type(exc).__name__}: {exc}"


def test_transient_enoent_on_creat_is_retried_and_preserves_directory_identity(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    dir_fd = os.open(str(out), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    real_open = os.open
    hits = {"n": 0}

    def wrapped(path, flags, *args, **kwargs):
        if path == "leaf" and flags & os.O_CREAT:
            hits["n"] += 1
            if hits["n"] <= 3:
                raise FileNotFoundError(errno.ENOENT, "transient create visibility")
            assert flags & os.O_NOFOLLOW
            assert not (flags & os.O_TRUNC)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(pipeline.os, "open", wrapped)
    try:
        fd = _open_regular_at(dir_fd, "leaf", os.O_RDWR | os.O_CREAT)
        try:
            st = os.fstat(fd)
            assert stat.S_ISREG(st.st_mode)
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)
    assert hits["n"] == 4
    assert (out / "leaf").is_file()
    assert not (out / "leaf").is_symlink()


def test_persistent_enoent_on_creat_is_not_converted_into_success(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    dir_fd = os.open(str(out), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    real_open = os.open
    hits = {"n": 0}

    def wrapped(path, flags, *args, **kwargs):
        if path == "leaf":
            hits["n"] += 1
            raise FileNotFoundError(errno.ENOENT, "persistent")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(pipeline.os, "open", wrapped)
    try:
        with pytest.raises(FileNotFoundError):
            _open_regular_at(dir_fd, "leaf", os.O_RDWR | os.O_CREAT)
    finally:
        os.close(dir_fd)
    assert hits["n"] == _OPEN_REGULAR_TRANSIENT_ENOENT_ATTEMPTS
    assert not (out / "leaf").exists()


def test_enoent_without_creat_is_not_retried(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    dir_fd = os.open(str(out), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    hits = {"n": 0}
    real_open = os.open

    def wrapped(path, flags, *args, **kwargs):
        if path == "missing":
            hits["n"] += 1
            raise FileNotFoundError(errno.ENOENT, "missing")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(pipeline.os, "open", wrapped)
    try:
        with pytest.raises(FileNotFoundError):
            _open_regular_at(dir_fd, "missing", os.O_RDONLY)
    finally:
        os.close(dir_fd)
    assert hits["n"] == 1


def test_permission_and_disk_exhaustion_are_not_swallowed(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    dir_fd = os.open(str(out), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    real_open = os.open

    def eacces(path, flags, *args, **kwargs):
        if path == "leaf":
            raise OSError(errno.EACCES, "permission denied")
        return real_open(path, flags, *args, **kwargs)

    def enospc(path, flags, *args, **kwargs):
        if path == "leaf":
            raise OSError(errno.ENOSPC, "no space")
        return real_open(path, flags, *args, **kwargs)

    try:
        monkeypatch.setattr(pipeline.os, "open", eacces)
        with pytest.raises(OSError) as denied:
            _open_regular_at(dir_fd, "leaf", os.O_RDWR | os.O_CREAT)
        assert denied.value.errno == errno.EACCES

        monkeypatch.setattr(pipeline.os, "open", enospc)
        with pytest.raises(OSError) as full:
            _open_regular_at(dir_fd, "leaf", os.O_RDWR | os.O_CREAT)
        assert full.value.errno == errno.ENOSPC
    finally:
        os.close(dir_fd)
    assert not (out / "leaf").exists()


def test_lock_symlink_is_refused_and_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"ORIGINAL")
    out = tmp_path / "out"
    out.mkdir()
    os.symlink(outside, out / ".process_corpus.lock")
    source = tmp_path / "in.jsonl"
    _write_jsonl(source, ["a short synthetic sentence about rain"])
    with pytest.raises(CorpusBoundaryError, match="symlink"):
        process_corpus(source, out, num_shards=1)
    assert outside.read_bytes() == b"ORIGINAL"
    assert (out / ".process_corpus.lock").is_symlink()
    assert list(out.glob("shard-*.jsonl")) == []


def test_open_regular_at_refuses_truncation_and_path_separators(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "leaf"
    existing.write_bytes(b"KEEP")
    dir_fd = os.open(str(out), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with pytest.raises(CorpusBoundaryError, match="truncate"):
            _open_regular_at(dir_fd, "leaf", os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        with pytest.raises(CorpusBoundaryError, match="filesystem name"):
            _open_regular_at(dir_fd, "../escape", os.O_RDWR | os.O_CREAT)
        with pytest.raises(CorpusBoundaryError, match="filesystem name"):
            _open_regular_at(dir_fd, "a/b", os.O_RDWR | os.O_CREAT)
    finally:
        os.close(dir_fd)
    assert existing.read_bytes() == b"KEEP"


def test_invalid_and_non_directory_descriptors_are_not_converted_into_success(tmp_path):
    with pytest.raises(CorpusBoundaryError, match="directory descriptor is invalid"):
        _open_regular_at(-1, "leaf", os.O_RDWR | os.O_CREAT)

    regular = tmp_path / "file"
    regular.write_bytes(b"x")
    fd = os.open(regular, os.O_RDONLY | os.O_CLOEXEC)
    try:
        with pytest.raises(CorpusBoundaryError, match="not a directory"):
            _open_regular_at(fd, "leaf", os.O_RDWR | os.O_CREAT)
    finally:
        os.close(fd)

    live = tmp_path / "live"
    live.mkdir()
    dir_fd = os.open(str(live), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    os.close(dir_fd)
    with pytest.raises(CorpusBoundaryError, match="directory descriptor is invalid"):
        _open_regular_at(dir_fd, "leaf", os.O_RDWR | os.O_CREAT)


def test_lock_is_created_on_the_opened_directory_not_a_replaced_path(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    dir_fd = os.open(str(live), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    replaced = tmp_path / "replaced"
    os.rename(live, replaced)
    live.mkdir()
    try:
        fd = _open_regular_at(dir_fd, ".process_corpus.lock", os.O_RDWR | os.O_CREAT)
        os.close(fd)
    finally:
        os.close(dir_fd)
    assert (replaced / ".process_corpus.lock").is_file()
    assert not (live / ".process_corpus.lock").exists()


def test_replaced_directory_descriptor_identity_is_rejected(tmp_path, monkeypatch):
    live = tmp_path / "live"
    live.mkdir()
    dir_fd = os.open(str(live), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    other = tmp_path / "other"
    other.mkdir()
    other_fd = os.open(str(other), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    real_fstat = os.fstat
    calls = {"n": 0}

    def wrapped(fd):
        if fd == dir_fd:
            calls["n"] += 1
            if calls["n"] >= 2:
                return real_fstat(other_fd)
        return real_fstat(fd)

    monkeypatch.setattr(pipeline.os, "fstat", wrapped)
    try:
        with pytest.raises(CorpusBoundaryError, match="no longer refers to the same directory"):
            _open_regular_at(dir_fd, "leaf", os.O_RDWR | os.O_CREAT)
    finally:
        os.close(dir_fd)
        os.close(other_fd)
    assert not (live / "leaf").exists()
    assert not (other / "leaf").exists()


def test_lock_file_permission_error_does_not_report_success(tmp_path):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root bypasses mode bits on the lock file")
    out = tmp_path / "out"
    out.mkdir()
    lock = out / ".process_corpus.lock"
    lock.write_bytes(b"")
    lock.chmod(0)
    source = tmp_path / "in.jsonl"
    _write_jsonl(source, ["a short synthetic sentence about rain"])
    try:
        with pytest.raises(OSError) as excinfo:
            process_corpus(source, out, num_shards=1)
        assert excinfo.value.errno in {errno.EACCES, errno.EPERM}
    finally:
        lock.chmod(0o600)
    assert list(out.glob("shard-*.jsonl")) == []
    assert not (out / PROGRESS_DB_NAME).exists()


@pytest.mark.parametrize("writers", [4, 8])
def test_concurrent_writers_new_directory_are_serialized(tmp_path, writers):
    n = 40
    texts = [f"concurrent-new-dir record {i} about topic {i}" for i in range(n)]
    source = tmp_path / "in.jsonl"
    _write_jsonl(source, texts)
    out = tmp_path / "out"
    errors: list[BaseException] = []
    results: list[int] = []
    barrier = threading.Barrier(writers)

    def _run():
        try:
            barrier.wait(timeout=10)
            report, _kept = process_corpus(
                source, out, num_shards=2, commit_batch_size=7, return_kept_records=False
            )
            results.append(report.kept)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_run) for _ in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    assert results == [n] * writers
    _assert_durable_once(out, texts)


def test_concurrent_lock_create_on_existing_directory(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    dir_fd = _open_directory_leaf(out, create=True)
    errors: list[BaseException] = []
    fds: list[int] = []
    barrier = threading.Barrier(8)

    def _run():
        try:
            barrier.wait(timeout=10)
            fd = _open_regular_at(dir_fd, ".process_corpus.lock", os.O_RDWR | os.O_CREAT)
            fds.append(fd)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    try:
        assert not errors, errors
        assert len(fds) == 8
        inodes = {os.fstat(fd).st_ino for fd in fds}
        assert len(inodes) == 1
        lock = out / ".process_corpus.lock"
        assert lock.is_file()
        assert not lock.is_symlink()
    finally:
        for fd in fds:
            os.close(fd)
        os.close(dir_fd)


def test_repeated_processing_against_an_existing_directory(tmp_path):
    texts = [f"resume-existing record {i} about topic {i}" for i in range(25)]
    source = tmp_path / "in.jsonl"
    _write_jsonl(source, texts)
    out = tmp_path / "out"
    first, _ = process_corpus(source, out, num_shards=2, return_kept_records=False)
    second, _ = process_corpus(source, out, num_shards=2, return_kept_records=False)
    third, _ = process_corpus(source, out, num_shards=2, return_kept_records=False)
    assert first.kept == second.kept == third.kept == 25
    _assert_durable_once(out, texts)

    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def _run():
        try:
            barrier.wait(timeout=10)
            report, _kept = process_corpus(source, out, num_shards=2, return_kept_records=False)
            assert report.kept == 25
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    _assert_durable_once(out, texts)


def test_concurrent_independent_processes(tmp_path):
    texts = [f"multiprocess record {i} about topic {i}" for i in range(30)]
    source = tmp_path / "in.jsonl"
    _write_jsonl(source, texts)
    out = tmp_path / "out"
    payload = (str(source), str(out), 2)
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_run_process_corpus, payload) for _ in range(4)]
        outcomes = [future.result() for future in as_completed(futures)]
    errors = [err for kept, err in outcomes if err]
    assert not errors, errors
    assert {kept for kept, _err in outcomes} == {30}
    _assert_durable_once(out, texts)


def test_crash_during_processing_then_durable_resume(tmp_path, monkeypatch):
    texts = [f"crash-resume record {i} about a distinct topic {i}" for i in range(20)]
    source = tmp_path / "in.jsonl"
    _write_jsonl(source, texts)
    out = tmp_path / "out"
    real_flush = pipeline._flush_pending_shard_rows
    calls = {"n": 0}

    def crash_once(output_dir, conn):
        calls["n"] += 1
        if calls["n"] == 1:
            real_flush(output_dir, conn)
            raise OSError("simulated crash after a durable batch")
        return real_flush(output_dir, conn)

    monkeypatch.setattr(pipeline, "_flush_pending_shard_rows", crash_once)
    with pytest.raises(OSError, match="simulated crash"):
        process_corpus(source, out, num_shards=2, commit_batch_size=4, return_kept_records=False)

    monkeypatch.setattr(pipeline, "_flush_pending_shard_rows", real_flush)
    report, _kept = process_corpus(source, out, num_shards=2, commit_batch_size=4, return_kept_records=False)
    assert report.kept == 20
    _assert_durable_once(out, texts)
    assert calls["n"] >= 1


def test_synchronized_lock_open_stress_rounds(tmp_path):
    """Cross-platform lock-create stress. This is not Darwin APFS evidence."""
    rounds = 20
    writers = 8
    for round_i in range(rounds):
        out = tmp_path / f"round-{round_i}"
        out.mkdir()
        dir_fd = _open_directory_leaf(out, create=True)
        errors: list[BaseException] = []
        fds: list[int] = []
        barrier = threading.Barrier(writers)

        def _run():
            try:
                barrier.wait(timeout=10)
                fd = _open_regular_at(dir_fd, ".process_corpus.lock", os.O_RDWR | os.O_CREAT)
                fds.append(fd)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_run) for _ in range(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        try:
            assert not errors, (round_i, errors)
            assert len({os.fstat(fd).st_ino for fd in fds}) == 1
        finally:
            for fd in fds:
                os.close(fd)
            os.close(dir_fd)


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="requires authorized Darwin hardware; Linux CI is not this qualification",
)
def test_native_darwin_synchronized_corpus_lock_stress_100_rounds(tmp_path):
    texts = [f"darwin-stress record {i} about topic {i}" for i in range(12)]
    source = tmp_path / "in.jsonl"
    _write_jsonl(source, texts)
    writers = 4
    for round_i in range(100):
        out = tmp_path / f"out-{round_i}"
        errors: list[BaseException] = []
        results: list[int] = []
        barrier = threading.Barrier(writers)

        def _run():
            try:
                barrier.wait(timeout=30)
                report, _kept = process_corpus(
                    source, out, num_shards=2, commit_batch_size=4, return_kept_records=False
                )
                results.append(report.kept)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_run) for _ in range(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors, (round_i, errors)
        assert results == [12] * writers, (round_i, results)
        _assert_durable_once(out, texts)
