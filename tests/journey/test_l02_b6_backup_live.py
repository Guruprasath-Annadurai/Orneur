"""L02-B6 -- backup, deletion and restore against a REAL ``orca serve`` process and the real CLI (evidence class: LIVE+FIX; fixture provider, synthetic customer data, test-only key).

Sequence: two conversations exist -> the server is stopped and an ENCRYPTED backup is taken through the CLI -> the server restarts and the customer deletes one conversation ->
the server is stopped and the OLDER backup is restored over the live directory through the CLI -> the server restarts. The deleted conversation must still be gone and the
other must be intact. Also: a wrong key is refused and changes nothing; no plaintext in the archive.
Run:  pytest tests/journey/test_l02_b6_backup_live.py -p no:cacheprovider -v
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, REPO, LiveServer, User

EVIDENCE = Path(os.environ.get("ORNEUR_L02_EVIDENCE_DIR", "/tmp/orneur-l02-evidence"))
SECRET_A = "CANARY-CONVERSATION-ALPHA-4471"
SECRET_B = "CANARY-CONVERSATION-BRAVO-9023"


def _cli(home, *args, extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(REPO), **(extra or {})})
    return subprocess.run([sys.executable, "-m", "orca.cli", *args], env=env, capture_output=True, text=True, timeout=180, cwd=REPO)


def _tree(home):
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(home.rglob("*"))
            if p.is_file() and not p.name.endswith(("-wal", "-shm")) and "server.log" not in p.name}


def test_older_backup_restore_does_not_resurrect_a_deleted_conversation(tmp_path):
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply="FIXTURE-ANSWER")
    fake.__enter__()
    home = tmp_path / "home"
    home.mkdir()
    env = {"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host, "ORNEUR_DELETION_SWEEP_S": "2"}
    keys = tmp_path / "keys"
    keys.mkdir()
    kf, wrong = keys / "k.key", keys / "wrong.key"
    assert _cli(home, "data-backup", "keygen", str(kf)).returncode == 0 and _cli(home, "data-backup", "keygen", str(wrong)).returncode == 0
    out = {}
    try:
        s1 = LiveServer(home, extra_env=env)
        s1.wait_ready()
        user = User(s1.base, "b6")
        _, ev = user.stream(SECRET_A)
        sid_a = next(e["session_id"] for e in ev if e.get("type") == "session")
        _, ev = user.stream(SECRET_B)
        sid_b = next(e["session_id"] for e in ev if e.get("type") == "session")
        s1.stop()

        archive = tmp_path / "bk" / "older.orbk"
        made = _cli(home, "data-backup", "create", str(archive), "--key-file", str(kf))
        assert made.returncode == 0, made.stdout + made.stderr
        blob = archive.read_bytes()
        out["archive_bytes"] = len(blob)
        out["plaintext_found_in_archive"] = [t for t in (SECRET_A, SECRET_B, user.email, "SQLite format 3") if t.encode() in blob]
        assert out["plaintext_found_in_archive"] == []
        assert _cli(home, "data-backup", "verify", str(archive), "--key-file", str(kf)).returncode == 0

        s2 = LiveServer(home, extra_env=env)
        s2.wait_ready()
        user.base = s2.base
        user.http = httpx.Client(base_url=s2.base, timeout=180)
        user.login()
        d = user.http.delete(f"/api/session/{sid_a}", headers=user.headers)
        out["delete_status"] = d.status_code
        assert d.status_code == 200
        s2.stop()

        before = _tree(home)
        bad = _cli(home, "data-backup", "restore", str(archive), "--key-file", str(wrong), "--overwrite")
        out["wrong_key_exit"] = bad.returncode
        assert bad.returncode == 1 and _tree(home) == before, "a wrong key is refused and changes nothing"

        r = _cli(home, "data-backup", "restore", str(archive), "--key-file", str(kf), "--overwrite")
        out["restore_output"] = (r.stdout + r.stderr)[-400:]
        assert r.returncode == 0, r.stdout + r.stderr

        s3 = LiveServer(home, extra_env=env)
        s3.wait_ready()
        try:
            h = {"Authorization": f"Bearer {httpx.post(f'{s3.base}/api/auth/login', json={'email': user.email, 'password': 'Journey-Pass-91x'}, timeout=30).json()['token']}"}
            ra = httpx.get(f"{s3.base}/api/session/{sid_a}/export", headers=h, timeout=30)
            rb = httpx.get(f"{s3.base}/api/session/{sid_b}/export", headers=h, timeout=30)
            out["deleted_conversation_http"] = ra.status_code
            out["kept_conversation_http"] = rb.status_code
            assert ra.status_code in (404, 410) and SECRET_A not in ra.text
            assert rb.status_code == 200 and SECRET_B in rb.text
            listed = httpx.get(f"{s3.base}/api/sessions", headers=h, timeout=30)
            out["deleted_listed"] = sid_a in listed.text
            assert sid_a not in listed.text
            assert httpx.get(f"{s3.base}/readyz", timeout=30).status_code == 200
        finally:
            s3.stop()
        raw = b"".join(p.read_bytes() for p in home.rglob("*") if p.is_file() and p.suffix in (".db", ".sqlite", ".jsonl", ".json") and ".pre-restore" not in str(p))
        out["alpha_text_left_in_live_files"] = SECRET_A.encode() in raw
        out["alpha_text_found_in"] = sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file() and ".pre-restore" not in str(p) and SECRET_A.encode() in p.read_bytes())
        assert not out["alpha_text_left_in_live_files"], "the deleted conversation's text is not on disk in the live directory after the sweep"
    finally:
        fake.__exit__(None, None, None)
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "b6_backup_live_restore_vs_deletion.json").write_text(json.dumps(out, indent=1))
