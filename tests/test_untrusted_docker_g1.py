"""Real Docker G1 tests. Skipped when the daemon is not usable — never a fake pass."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orca.auth.db import init_db
from orca.auth.store import User, create_user
from orca.code.untrusted import (
    ALLOWED_IMAGE,
    UntrustedError,
    daemon_usable,
    execute,
    get_job,
    inspect_isolation_flags,
    isolator,
    list_jobs,
    reset_for_tests,
    set_job_path,
    spawn_probe_container,
    _stop_container,
)
from orca.code.untrusted_routes import router
from orca.sovereign_mission.service import SovereignMission

pytestmark = pytest.mark.skipif(
    not daemon_usable(),
    reason="BLOCKED: Docker daemon is not usable — real container tests cannot run",
)


def _user(uid: str) -> User:
    return User(id=uid, email=f"{uid}@example.com", name=uid, tier="free", verified=True)


@pytest.fixture()
def jobs(tmp_path):
    set_job_path(tmp_path / "jobs.sqlite")
    reset_for_tests()
    yield tmp_path
    set_job_path(None)


def test_authorized_python_executes(jobs):
    result = execute("print('g1-ok')", user=_user("owner"), task_id="harmless")
    assert result["status"] == "succeeded"
    assert "g1-ok" in result["stdout"]
    assert result["verified"] is True
    assert result["image"] == ALLOWED_IMAGE
    assert result["isolator"] == "docker"
    assert result["native_family"] is None
    assert result["handlers_forcibly_stopped"] is False
    assert result["container_confirmed_stopped"] is True


def test_unauthenticated_rejected(jobs):
    with pytest.raises(UntrustedError) as exc:
        execute("print(1)", user="owner")
    assert exc.value.code == "unauthenticated"


def test_cross_tenant_job_access_rejected(jobs):
    result = execute("print('owned')", user=_user("owner"), task_id="t1")
    with pytest.raises(UntrustedError) as exc:
        get_job(user=_user("intruder"), job_id=result["job_id"])
    assert exc.value.code == "access_denied"
    assert list_jobs(user=_user("intruder")) == []


def test_root_filesystem_is_read_only(jobs):
    source = (
        "import os\n"
        "try:\n"
        "    open('/g1-should-fail','w').write('x')\n"
        "    print('WROTE')\n"
        "except OSError as e:\n"
        "    print('DENIED')\n"
    )
    result = execute(source, user=_user("owner"))
    assert "WROTE" not in result["stdout"]
    assert "DENIED" in result["stdout"]


def test_host_filesystem_secret_is_absent(jobs, tmp_path):
    secret = tmp_path / "host-secret.txt"
    secret.write_text("HOST-SECRET-TOKEN")
    source = (
        "import os\n"
        f"print('SEEN' if os.path.exists({str(secret)!r}) else 'ABSENT')\n"
        "print('SOCK' if os.path.exists('/var/run/docker.sock') else 'NOSOCK')\n"
        "print('CREDS' if os.environ.get('ORNEUR_AUTH_SECRET') else 'NOCREDS')\n"
    )
    os.environ["ORNEUR_AUTH_SECRET"] = "must-not-leak"
    try:
        result = execute(source, user=_user("owner"))
    finally:
        os.environ.pop("ORNEUR_AUTH_SECRET", None)
    assert "ABSENT" in result["stdout"]
    assert "SEEN" not in result["stdout"]
    assert "NOSOCK" in result["stdout"]
    assert "NOCREDS" in result["stdout"]
    assert "must-not-leak" not in result["stdout"]
    assert "must-not-leak" not in result["stderr"]


def test_default_network_denied(jobs):
    source = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=2)\n"
        "    print('NET_OK')\n"
        "except Exception as e:\n"
        "    print('NET_DENIED')\n"
        "try:\n"
        "    socket.create_connection(('169.254.169.254', 80), timeout=2)\n"
        "    print('META_OK')\n"
        "except Exception:\n"
        "    print('META_DENIED')\n"
    )
    result = execute(source, user=_user("owner"), timeout_s=8)
    assert "NET_OK" not in result["stdout"]
    assert "META_OK" not in result["stdout"]
    assert "NET_DENIED" in result["stdout"]
    assert "META_DENIED" in result["stdout"]


def test_pid_limit_blocks_fork_bomb(jobs):
    source = (
        "import os\n"
        "failed=False\n"
        "for i in range(80):\n"
        "    try:\n"
        "        pid=os.fork()\n"
        "        if pid==0:\n"
        "            import time; time.sleep(20); os._exit(0)\n"
        "    except OSError:\n"
        "        failed=True\n"
        "        break\n"
        "print('FORK_FAILED' if failed else 'FORK_ALL_OK')\n"
    )
    result = execute(source, user=_user("owner"), timeout_s=8)
    assert "FORK_ALL_OK" not in result["stdout"]
    assert result["status"] in {"succeeded", "failed", "timed_out"}
    if result["status"] == "succeeded":
        assert "FORK_FAILED" in result["stdout"]


def test_infinite_loop_hits_deadline(jobs):
    result = execute("while True: pass", user=_user("owner"), timeout_s=2)
    assert result["status"] == "timed_out"
    assert result["verified"] is False
    assert result["handlers_forcibly_stopped"] is False
    assert result["container_confirmed_stopped"] is True


def test_cancellation_stops_container(jobs):
    stop = threading.Event()

    def arm():
        time.sleep(0.4)
        stop.set()

    threading.Thread(target=arm, daemon=True).start()
    result = execute("import time\ntime.sleep(20)", user=_user("owner"), cancel=stop, timeout_s=12)
    assert result["status"] == "cancelled"
    assert result["verified"] is False
    assert result["container_confirmed_stopped"] is True
    assert result["handlers_forcibly_stopped"] is False


def test_crash_is_failed_not_verified(jobs):
    result = execute("import os\nos._exit(7)", user=_user("owner"))
    assert result["status"] == "failed"
    assert result["exit_code"] == 7
    assert result["verified"] is False


def test_concurrent_jobs_do_not_share_workspace(jobs):
    a = execute(
        "open('/workspace/a.txt','w').write('alpha')\nprint(open('/workspace/a.txt').read())\n",
        user=_user("user-a"),
    )
    assert a["status"] == "succeeded", a
    assert "alpha" in a["stdout"]
    b = execute(
        "import os\nprint('HAS_A' if os.path.exists('/workspace/a.txt') else 'NO_A')\n",
        user=_user("user-b"),
    )
    assert b["status"] == "succeeded", b
    assert "HAS_A" not in b["stdout"]
    assert "NO_A" in b["stdout"]


def test_caller_security_flags_rejected(jobs):
    with pytest.raises(UntrustedError) as exc:
        execute("print(1)", user=_user("owner"), privileged=True)
    assert exc.value.code == "caller_flags_refused"
    with pytest.raises(UntrustedError):
        execute("print(1)", user=_user("owner"), image="evil:latest")
    with pytest.raises(UntrustedError):
        execute("print(1)", user=_user("owner"), network="host")
    with pytest.raises(UntrustedError):
        execute("print(1)", user=_user("owner"), mounts=["/:/host"])
    with pytest.raises(UntrustedError):
        execute("print(1)", user=_user("owner"), extra_args=["--privileged"])


def test_applied_docker_flags(jobs):
    name = spawn_probe_container()
    try:
        flags = inspect_isolation_flags(name)
        assert flags["privileged"] is False
        assert flags["network_mode"] == "none"
        assert flags["readonly_rootfs"] is True
        assert flags["pids_limit"] == 32 or flags["pids_limit"] == 32.0
        assert flags["memory"] and int(flags["memory"]) > 0
        assert flags["nano_cpus"] and int(flags["nano_cpus"]) > 0
        assert any(str(c).upper() == "ALL" for c in flags["cap_drop"])
        assert flags["pid_mode"] in ("", None)
        assert flags["user"] in ("65534:65534", "65534")
        assert not any("docker.sock" in str(b) for b in flags["binds"])
    finally:
        _stop_container(name)


def test_http_stays_disabled_without_development_flag(jobs, tmp_path, monkeypatch):
    monkeypatch.setattr("orca.auth.db.AUTH_DB", tmp_path / "auth.db")
    monkeypatch.delenv("ORNEUR_UNTRUSTED_EXECUTION", raising=False)
    monkeypatch.delenv("ORCA_UNTRUSTED_EXECUTION", raising=False)
    init_db()
    create_user("owner@example.com", "correct-horse", "owner")
    token = SovereignMission().login("owner@example.com", "correct-horse")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    anon = client.post("/api/untrusted/execute", json={"source": "print(1)"})
    assert anon.status_code == 401
    denied = client.post(
        "/api/untrusted/execute",
        headers={"Authorization": f"Bearer {token}"},
        json={"source": "print(1)"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "capability_disabled"


def test_http_development_path_authenticates_and_isolates(jobs, tmp_path, monkeypatch):
    monkeypatch.setattr("orca.auth.db.AUTH_DB", tmp_path / "auth.db")
    monkeypatch.setenv("ORNEUR_UNTRUSTED_EXECUTION", "development")
    init_db()
    create_user("owner@example.com", "correct-horse", "owner")
    create_user("other@example.com", "correct-horse", "other")
    owner = SovereignMission().login("owner@example.com", "correct-horse")
    other = SovereignMission().login("other@example.com", "correct-horse")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    ok = client.post(
        "/api/untrusted/execute",
        headers={"Authorization": f"Bearer {owner}"},
        json={"source": "print('http-g1')", "task_id": "http1"},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "succeeded"
    assert "http-g1" in body["stdout"]
    job_id = body["job_id"]
    stolen = client.get(f"/api/untrusted/jobs/{job_id}", headers={"Authorization": f"Bearer {other}"})
    assert stolen.status_code == 403
    owned = client.get(f"/api/untrusted/jobs/{job_id}", headers={"Authorization": f"Bearer {owner}"})
    assert owned.status_code == 200
    flags = client.post(
        "/api/untrusted/execute",
        headers={"Authorization": f"Bearer {owner}"},
        json={"source": "print(1)", "privileged": True},
    )
    assert flags.status_code == 400


def test_memory_limit_is_configured_and_large_alloc_does_not_succeed_as_verified(jobs):
    source = "x = bytearray(200 * 1024 * 1024)\nprint('ALLOC_OK')\n"
    result = execute(source, user=_user("owner"), timeout_s=8)
    assert "ALLOC_OK" not in result["stdout"]
    assert result["verified"] is False
    assert result["status"] in {"failed", "timed_out", "unknown"}
