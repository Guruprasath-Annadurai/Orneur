from __future__ import annotations

import os
import threading

import pytest

from orca.auth.store import User
from orca.serve.uploads import UploadError, delete, read, store, store_for


def _user(uid: str) -> User:
    return User(id=uid, email=f"{uid}@example.com", name=uid, tier="free", verified=True)


def test_store_for_requires_user_object(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)
    with pytest.raises(UploadError) as exc:
        store_for(object(), "note.txt", b"hello")  # type: ignore[arg-type]
    assert exc.value.code == "unauthenticated"
    with pytest.raises(UploadError) as exc:
        store_for("user-a", "note.txt", b"hello")  # type: ignore[arg-type]
    assert exc.value.code == "unauthenticated"
    stored = store_for(_user("user-a"), "note.txt", b"hello")
    assert stored["isolation"] == "directory_hash_not_os"
    assert read("user-a", "note.txt") == b"hello"

    class Reloaded:
        def __init__(self):
            self.id = "user-b"

    store_for(Reloaded(), "other.txt", b"hello")  # type: ignore[arg-type]
    assert read("user-b", "other.txt") == b"hello"


def test_symlink_destination_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)
    store("user-a", "ok.txt", b"one")
    root = tmp_path / "uploads"
    # hashed dir
    dirs = list(root.iterdir())
    assert dirs
    target = dirs[0] / "link.txt"
    os.symlink("/tmp/orneur-upload-escape", target)
    with pytest.raises(UploadError) as exc:
        store("user-a", "link.txt", b"two")
    assert exc.value.code in {"symlink_refused", "duplicate_name"}


def test_concurrent_same_name_one_winner(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)
    results = []

    def write():
        try:
            results.append(store("user-a", "race.txt", b"aaaa"))
        except UploadError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=write) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wins = [row for row in results if isinstance(row, dict)]
    losses = [row for row in results if row == "duplicate_name"]
    assert len(wins) == 1
    assert len(losses) == 7
    assert read("user-a", "race.txt") == b"aaaa"


def test_failed_write_leaves_no_object(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)

    def boom(fd, data):
        raise OSError("disk")

    monkeypatch.setattr("orca.serve.uploads.os.write", boom)
    with pytest.raises(UploadError) as exc:
        store("user-a", "gone.txt", b"payload")
    assert exc.value.code == "write_failed"
    with pytest.raises(UploadError):
        read("user-a", "gone.txt")
    leftovers = list(tmp_path.rglob("*.tmp")) + list(tmp_path.rglob("*.part"))
    assert leftovers == []


def test_delete_does_not_claim_replicas(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)
    store("user-a", "note.txt", b"hello")
    body = delete("user-a", "note.txt")
    assert body["deleted"] is True
    assert body["replicas_removed"] == "unknown"
    assert body["scope"] == "local_object"
