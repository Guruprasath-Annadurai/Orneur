"""Cross-process revocation. In-process reset is not a substitute.

Worker A and Worker B are separate interpreters. A durable revoke in B
must stop A from returning passages, including a search that had already
passed the in-process cache before the revoke landed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path


MARKER = "archive key cobalt-77"
OTHER = "beta marker saffron-18"


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["ORCA_HOME"] = str(home)
    env["ORNEUR_HOME"] = str(home)
    return env


def _run(home: Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        env=_env(home),
        capture_output=True,
        text=True,
        check=False,
    )


def _admit(home: Path) -> None:
    completed = _run(
        home,
        """
        from orca.serve.authorized_product_index import admit_uploaded_document
        admit_uploaded_document("user-a", "sess-a", filename="a.txt", text="archive key cobalt-77", doc_id="doc-a")
        admit_uploaded_document("user-a", "sess-b", filename="b.txt", text="beta marker saffron-18", doc_id="doc-b")
        print("admitted")
        """,
    )
    assert completed.returncode == 0, completed.stderr
    assert "admitted" in completed.stdout


def _wait(path: Path, proc: subprocess.Popen[str], timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline and not path.exists():
        if proc.poll() is not None:
            break
        time.sleep(0.02)


def test_worker_a_cache_dies_when_worker_b_revokes(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    _admit(home)
    ready = home / "ready"
    go = home / "go"
    worker_a = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
        import os, time
        from pathlib import Path
        os.environ["ORCA_HOME"] = {str(home)!r}
        os.environ["ORNEUR_HOME"] = {str(home)!r}
        from orca.serve.authorized_product_index import retrieve_authorized, ProductRetrievalDenied
        first = retrieve_authorized("user-a", "sess-a", "archive")
        assert any({MARKER!r} in hit.text for hit in first.hits)
        Path({str(ready)!r}).write_text("cached")
        while not Path({str(go)!r}).exists():
            time.sleep(0.02)
        try:
            retrieve_authorized("user-a", "sess-a", "archive")
        except ProductRetrievalDenied as exc:
            sibling = retrieve_authorized("user-a", "sess-b", "beta")
            sibling_text = " ".join(hit.text for hit in sibling.hits)
            assert {OTHER!r} in sibling_text
            assert {MARKER!r} not in sibling_text
            print("DENIED", exc.code)
            raise SystemExit(0)
        print("SERVED")
        raise SystemExit(2)
        """)],
        env=_env(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait(ready, worker_a)
    assert ready.exists(), "worker A did not cache the conversation"
    revoked = _run(
        home,
        """
        from orca.serve.authorized_product_index import revoke
        revoke("user-a", "sess-a")
        print("revoked")
        """,
    )
    assert revoked.returncode == 0, revoked.stderr
    go.write_text("go")
    stdout, stderr = worker_a.communicate(timeout=20)
    assert worker_a.returncode == 0, stderr
    assert "DENIED revoked" in stdout
    assert MARKER not in stdout
    assert "SERVED" not in stdout


def test_in_flight_search_does_not_return_passages_after_revoke(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    _admit(home)
    entered = home / "entered"
    release = home / "release"
    worker_a = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
        import os, time
        from pathlib import Path
        os.environ["ORCA_HOME"] = {str(home)!r}
        os.environ["ORNEUR_HOME"] = {str(home)!r}
        import orca.serve.authorized_product_index as mod
        from orca.serve.authorized_product_index import ProductRetrievalDenied
        real = mod.run_authorized_retrieval
        def wrapped(session, index, query):
            Path({str(entered)!r}).write_text("in-search")
            while not Path({str(release)!r}).exists():
                time.sleep(0.02)
            return real(session, index, query)
        mod.run_authorized_retrieval = wrapped
        try:
            mod.retrieve_authorized("user-a", "sess-a", "archive")
        except ProductRetrievalDenied as exc:
            print("DENIED", exc.code)
            raise SystemExit(0)
        print("SERVED")
        raise SystemExit(2)
        """)],
        env=_env(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait(entered, worker_a)
    assert entered.exists(), "search did not reach the retrieval call"
    revoked = _run(
        home,
        """
        from orca.serve.authorized_product_index import revoke
        revoke("user-a", "sess-a")
        print("revoked")
        """,
    )
    assert revoked.returncode == 0, revoked.stderr
    release.write_text("go")
    stdout, stderr = worker_a.communicate(timeout=20)
    assert worker_a.returncode == 0, stderr
    assert "DENIED revoked" in stdout
    assert MARKER not in stdout
    assert "SERVED" not in stdout


def test_fresh_process_after_revoke_stays_denied(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    _admit(home)
    revoked = _run(
        home,
        """
        from orca.serve.authorized_product_index import revoke
        revoke("user-a", "sess-a")
        print("revoked")
        """,
    )
    assert revoked.returncode == 0, revoked.stderr
    later = _run(
        home,
        f"""
        from orca.serve.authorized_product_index import retrieve_authorized, ProductRetrievalDenied
        try:
            retrieve_authorized("user-a", "sess-a", "archive")
        except ProductRetrievalDenied as exc:
            print("DENIED", exc.code)
        else:
            print("SERVED")
            raise SystemExit(2)
        sibling = retrieve_authorized("user-a", "sess-b", "beta")
        text = " ".join(hit.text for hit in sibling.hits)
        assert {OTHER!r} in text and {MARKER!r} not in text
        print("sibling-ok")
        """,
    )
    assert later.returncode == 0, later.stderr
    assert "DENIED revoked" in later.stdout
    assert "sibling-ok" in later.stdout
    assert MARKER not in later.stdout
