"""Native Darwin F_GETPATH qualification.

Linux executes the refuse path and the source-contract checks. Darwin
executes the real `fcntl.fcntl` lookup. A crash is a failure, not a skip.
Linux mocks of a successful F_GETPATH are not Darwin qualification.
"""
from __future__ import annotations

import inspect
import os
import sys

import pytest

from orca.genesis.data.pipeline import CorpusBoundaryError, _darwin_descriptor_path, _require_descriptor_directory
import orca.genesis.data.pipeline as pipeline


def test_pipeline_does_not_call_variadic_ctypes_fcntl():
    source = inspect.getsource(pipeline._darwin_descriptor_path)
    assert "fcntl.fcntl" in source
    assert 'b"\\x00" * _DARWIN_MAXPATHLEN' in source or "b'\\x00' * _DARWIN_MAXPATHLEN" in source
    assert "bytearray(" not in source
    assert "ctypes.CDLL" not in source
    assert "CDLL" not in source
    assert "ctypes.CDLL" not in inspect.getsource(pipeline)


def test_darwin_lookup_is_refused_on_non_darwin():
    if sys.platform == "darwin":
        pytest.skip("this assertion is the Linux/other refuse path")
    with pytest.raises(CorpusBoundaryError, match="Darwin descriptor path lookup"):
        _darwin_descriptor_path(0)


def test_invalid_descriptor_is_rejected_before_fcntl(monkeypatch):
    monkeypatch.setattr(pipeline.sys, "platform", "darwin")

    def boom(*_args, **_kwargs):
        raise AssertionError("fcntl must not be invoked for an invalid descriptor")

    monkeypatch.setattr(pipeline.fcntl, "fcntl", boom)
    with pytest.raises(CorpusBoundaryError, match="descriptor is invalid"):
        _darwin_descriptor_path(-1)
    with pytest.raises(CorpusBoundaryError, match="descriptor is invalid"):
        _darwin_descriptor_path("not-an-fd")  # type: ignore[arg-type]


def test_failed_f_getpath_is_a_boundary_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(pipeline.sys, "platform", "darwin")

    def fail(_fd, _cmd, _buf):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(pipeline.fcntl, "fcntl", fail)
    with pytest.raises(CorpusBoundaryError, match="F_GETPATH failed"):
        _darwin_descriptor_path(0)


def test_fcntl_uses_returned_bytes_not_a_mutated_input(monkeypatch):
    monkeypatch.setattr(pipeline.sys, "platform", "darwin")
    seen: dict[str, object] = {}

    def fake(_fd, _cmd, buf):
        seen["type"] = type(buf)
        assert isinstance(buf, (bytes, bytearray)) is True
        assert type(buf) is bytes
        return b"/private/tmp/orneur-fd\x00"

    monkeypatch.setattr(pipeline.fcntl, "fcntl", fake)
    assert _darwin_descriptor_path(0) == "/private/tmp/orneur-fd"
    assert seen["type"] is bytes


def test_unsupported_buffer_typeerror_is_fail_closed(monkeypatch):
    monkeypatch.setattr(pipeline.sys, "platform", "darwin")

    def fail(_fd, _cmd, _buf):
        raise TypeError("can't use a bytearray")

    monkeypatch.setattr(pipeline.fcntl, "fcntl", fail)
    with pytest.raises(CorpusBoundaryError, match="buffer type is unsupported"):
        _darwin_descriptor_path(0)


def test_unterminated_and_empty_buffers_are_rejected(monkeypatch):
    monkeypatch.setattr(pipeline.sys, "platform", "darwin")

    monkeypatch.setattr(pipeline.fcntl, "fcntl", lambda *_a, **_k: b"A" * pipeline._DARWIN_MAXPATHLEN)
    with pytest.raises(CorpusBoundaryError, match="empty or unterminated"):
        _darwin_descriptor_path(0)

    monkeypatch.setattr(pipeline.fcntl, "fcntl", lambda *_a, **_k: b"\x00")
    with pytest.raises(CorpusBoundaryError, match="empty or unterminated"):
        _darwin_descriptor_path(0)

    monkeypatch.setattr(pipeline.fcntl, "fcntl", lambda *_a, **_k: b"/tmp/gone (deleted)\x00")
    with pytest.raises(CorpusBoundaryError, match="malformed"):
        _darwin_descriptor_path(0)

    monkeypatch.setattr(pipeline.fcntl, "fcntl", lambda *_a, **_k: 0)
    with pytest.raises(CorpusBoundaryError, match="did not return a path buffer"):
        _darwin_descriptor_path(0)


@pytest.mark.skipif(sys.platform != "darwin", reason="requires authorized Darwin hardware; Linux CI is not this qualification")
def test_native_darwin_f_getpath_returns_the_open_directory(tmp_path):
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        reported = _darwin_descriptor_path(fd)
        assert reported.startswith("/")
        pinned = _require_descriptor_directory(fd, reported)
        assert os.path.samefile(pinned, tmp_path)
    finally:
        os.close(fd)


@pytest.mark.skipif(sys.platform != "darwin", reason="requires authorized Darwin hardware; Linux CI is not this qualification")
def test_native_darwin_rejects_invalid_closed_and_replaced_directories(tmp_path):
    with pytest.raises(CorpusBoundaryError, match="invalid"):
        _darwin_descriptor_path(-1)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    os.close(fd)
    with pytest.raises(CorpusBoundaryError, match="F_GETPATH failed"):
        _darwin_descriptor_path(fd)

    live = tmp_path / "live"
    live.mkdir()
    replaced = tmp_path / "replaced"
    live_fd = os.open(live, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.rename(live, replaced)
        other = tmp_path / "other"
        other.mkdir()
        os.rename(other, live)
        reported = _darwin_descriptor_path(live_fd)
        with pytest.raises(CorpusBoundaryError, match="different directory"):
            _require_descriptor_directory(live_fd, str(live))
        _require_descriptor_directory(live_fd, reported)
    finally:
        os.close(live_fd)


@pytest.mark.skipif(sys.platform != "darwin", reason="requires authorized Darwin hardware; Linux CI is not this qualification")
def test_native_darwin_process_corpus_uses_f_getpath_sqlite(tmp_path):
    from orca.genesis.data.pipeline import process_corpus

    source = tmp_path / "in.jsonl"
    source.write_text('{"text":"a short synthetic sentence about rain"}\n')
    out = tmp_path / "out"
    report, kept = process_corpus(source, out, num_shards=1)
    assert report.kept == 1
    assert kept == ["a short synthetic sentence about rain"]


@pytest.mark.skipif(sys.platform != "darwin", reason="requires authorized Darwin hardware; Linux CI is not this qualification")
def test_native_darwin_symlink_path_is_not_the_descriptor_identity(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    fd = os.open(real, os.O_RDONLY | os.O_DIRECTORY)
    try:
        reported = _darwin_descriptor_path(fd)
        assert not reported.endswith("/link")
        with pytest.raises(CorpusBoundaryError, match="different directory"):
            _require_descriptor_directory(fd, str(link))
    finally:
        os.close(fd)
