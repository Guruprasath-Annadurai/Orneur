from __future__ import annotations

import pytest

from orca.code.untrusted import UntrustedError, execute, isolator
from orca.docs.authorized_task import remove, run


def test_authenticated_document_task_cites_only_owner_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)
    data = b"The indigo widget torque is 12 newton metres when calibrated."
    result = run(user_id="user-a", filename="note.txt", data=data, question="indigo widget torque")
    assert result["verified"] is True
    assert result["deep_rag"] is False
    assert result["sources"]
    assert all(row["filename"] == "note.txt" for row in result["sources"])
    assert all(item["match"] for item in result["evidence"])
    assert all(item["synthetic"] is False for item in result["evidence"])
    from orca.serve.uploads import UploadError, read

    with pytest.raises(UploadError):
        read("user-b", "note.txt")
    gone = remove(user_id="user-a", filename="note.txt")
    assert gone["deleted"] is True
    assert gone["local_absent"] is True
    assert gone["replicas_claimed"] is False


def test_untrusted_code_stays_disabled_without_isolator(monkeypatch):
    monkeypatch.setattr("orca.code.untrusted.shutil.which", lambda name: None)
    assert isolator() is None
    with pytest.raises(UntrustedError) as exc:
        execute("print(1)", user_id="user-a")
    assert exc.value.code == "isolation_unavailable"
