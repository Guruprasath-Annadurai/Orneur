"""L02-B6 corrective -- the production image installs only the BASE dependencies (no `cryptography`). Server start-up, /readyz and every deletion path must work without it; only the
backup/restore tooling needs it, and it must say so clearly. Found by CI (Production Container Build + Boot Smoke) after the serving lock imported the backup module.
Each scenario runs in a fresh interpreter in which importing `cryptography` fails exactly as it does in the image."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_BLOCK = "import sys\nsys.modules['cryptography'] = None\nfor m in list(sys.modules):\n    if m.startswith('cryptography.'):\n        sys.modules[m] = None\n"


def _run(code: str, home: Path, extra_env=None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(ROOT), **(extra_env or {})})
    return subprocess.run([sys.executable, "-c", _BLOCK + textwrap.dedent(code)], env=env, capture_output=True, text=True, timeout=120, cwd=ROOT)


def test_the_server_starts_reports_ready_and_deletes_without_the_cryptography_package(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    p = _run('''
        import asyncio, json, uuid
        from fastapi.testclient import TestClient
        from orca.serve import streaming
        streaming.shutdown_streaming_pool = lambda wait=False: None
        from orca.serve.api import app
        out = {}
        with TestClient(app) as c:                       # lifespan: takes the serving lock
            out["readyz"] = c.get("/readyz").status_code
            out["livez"] = c.get("/livez").status_code
            from orca.serve import deletions, deletion_ledger
            sid = str(uuid.uuid4())
            deletions.begin(sid, "u1")                   # conversation deletion path -> ledger
            from orca.docs import store as ds
            out["ledger_entries"] = len(deletion_ledger.read())
        print(json.dumps(out))
    ''', home)
    assert p.returncode == 0, p.stderr[-1500:]
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert out["livez"] == 200 and out["readyz"] in (200, 503) and out["ledger_entries"] == 1


def test_the_backup_commands_say_what_is_missing_instead_of_a_traceback(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    p = _run('''
        from typer.testing import CliRunner
        from orca.cli import app
        r = CliRunner().invoke(app, ["data-backup", "create", "/tmp/never.orbk", "--key-file", "/nonexistent"])
        print(r.exit_code)
        print(r.output)
    ''', home)
    assert p.returncode == 0, p.stderr[-1500:]
    code, *msg = p.stdout.strip().splitlines()
    text = " ".join(msg).lower()
    assert code == "2" and "cryptography" in text and "backup" in text and "traceback" not in text


def test_recover_works_without_the_cryptography_package_so_an_interrupted_restore_can_always_be_rolled_back(tmp_path):
    home = tmp_path / "home"
    aside = home / ".pre-restore-aaaaaaaaaa"
    aside.mkdir(parents=True)
    (aside / "auth.db").write_text("previous")
    (home / "auth.db").write_text("half-restored")
    (home / ".restore-journal.json").write_text(json.dumps({"aside": ".pre-restore-aaaaaaaaaa", "moved": ["auth.db"], "placed": ["auth.db"]}))
    (home / ".restore-journal.json").chmod(0o600)
    p = _run("""
        from typer.testing import CliRunner
        from orca.cli import app
        r = CliRunner().invoke(app, ["data-backup", "recover"])
        print(r.exit_code)
    """, home)
    assert p.returncode == 0 and p.stdout.strip().splitlines()[-1] == "0", p.stderr[-800:]
    assert (home / "auth.db").read_text() == "previous" and not (home / ".restore-journal.json").exists()
