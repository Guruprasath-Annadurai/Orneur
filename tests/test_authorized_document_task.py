from __future__ import annotations

import pytest

from orca.auth.store import User
from orca.code.untrusted import UntrustedError, execute, isolator
from orca.docs.authorized_task import DocumentTaskError, remove, run
from orca.serve.uploads import UploadError, read


def _user(uid: str) -> User:
    return User(id=uid, email=f"{uid}@example.com", name=uid, tier="free", verified=True)


def test_authenticated_document_task_splits_claims(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)
    data = b"The indigo widget torque is 12 newton metres when calibrated."
    result = run(user=_user("user-a"), filename="note.txt", data=data, question="indigo widget torque")
    claims = result["claims"]
    assert claims["upload_integrity"] == "verified"
    assert claims["citation_excerpt_consistency"] == "verified"
    assert claims["answer_grounding"] == "not_performed"
    assert claims["independent_external"] == "not_performed"
    assert claims["source_provenance"] == "local_upload"
    assert "verified" not in result
    assert result["deep_rag"] is False
    assert all(item["match"] for item in result["evidence"])
    with pytest.raises(UploadError):
        read("user-b", "note.txt")
    gone = remove(user=_user("user-a"), filename="note.txt")
    assert gone["deleted"] is True
    assert gone["local_absent"] is True
    assert gone["replicas_claimed"] is False
    assert gone["replicas_removed"] == "unknown"


def test_extract_failure_does_not_persist(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)

    def boom(filename, data):
        raise ValueError("bad pdf")

    monkeypatch.setattr("orca.docs.authorized_task.extract", boom)
    with pytest.raises(DocumentTaskError) as exc:
        run(user=_user("user-a"), filename="note.txt", data=b"not-a-pdf", question="x")
    assert exc.value.code == "extract_failed"
    with pytest.raises(UploadError):
        read("user-a", "note.txt")


def test_caller_id_string_is_not_a_user(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)
    with pytest.raises(DocumentTaskError) as exc:
        run(user="user-a", filename="note.txt", data=b"hello world text", question="hello")  # type: ignore[arg-type]
    assert exc.value.code == "unauthenticated"


def test_untrusted_code_stays_disabled_without_isolator(monkeypatch):
    monkeypatch.setattr("orca.code.untrusted.daemon_usable", lambda: False)
    assert isolator() is None
    with pytest.raises(UntrustedError) as exc:
        execute("print(1)", user=_user("user-a"))
    assert exc.value.code == "isolation_unavailable"
