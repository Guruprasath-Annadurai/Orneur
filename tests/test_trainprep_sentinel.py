"""Workstream G #12: synthetic-only guarantee. The sentinel installs a permanent (inert-when-off) PEP 578 audit hook, so every behavioural proof runs
in a fresh SUBPROCESS and the pytest process stays untouched. Proven: forbidden trainer/tensor imports, sockets/DNS, GPU libs/devices, subprocesses
and out-of-sandbox reads/writes are blocked while a guard is active; a full synthetic run completes under the guard without loading any trainer
package; and the harness FAILS CLOSED whenever the guarantee cannot be established."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from orca.train.dryrun import sentinel as S

REPO = Path(__file__).resolve().parent.parent

PRELUDE = """
import json, os, sys, socket, subprocess, ctypes, tempfile, types
from pathlib import Path
import orca.train.dryrun.harness as H
from orca.train.dryrun import sentinel as S
from orca.train.dryrun.sentinel import SyntheticOnlyGuard, SyntheticGuaranteeViolation, SyntheticGuaranteeUnavailable
from orca.train.dryrun.toy import Plan
from orca.train.dryrun.budget import ResourceBudget
from orca.train.dryrun.binding import Binding
REPO = Path(os.getcwd())
BIND = Binding("a" * 40, True, "b" * 64, ("c" * 64,), None)
BUD = ResourceBudget(max_steps=50, max_tokens=10**6, max_wall_clock_s=100, max_spend_usd=10, sim_cost_usd_per_step=0.01)
sb = Path(tempfile.mkdtemp(prefix="sentinel-test-"))
res = {}
def attempt(name, fn):
    try:
        fn()
        res[name] = "ALLOWED"
    except SyntheticGuaranteeViolation:
        res[name] = "BLOCKED"
    except SyntheticGuaranteeUnavailable:
        res[name] = "UNAVAILABLE"
    except BaseException as e:
        res[name] = "OTHER:" + type(e).__name__
"""


def _child(body: str, tmp_path: Path) -> dict:
    script = PRELUDE + textwrap.dedent(body) + "\nprint('RESULT=' + json.dumps(res))\n"
    env = {"PATH": os.defpath, "ORNEUR_HOME": str(tmp_path / "home"), "HOME": str(tmp_path / "home"), "LANG": "C.UTF-8"}
    (tmp_path / "home").mkdir(exist_ok=True)
    p = subprocess.run([sys.executable, "-E", "-s", "-c", script], cwd=str(REPO), env=env, capture_output=True, text=True, timeout=240)
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("RESULT=")]
    assert line, f"child failed: rc={p.returncode}\nSTDOUT:{p.stdout[-2000:]}\nSTDERR:{p.stderr[-3000:]}"
    return json.loads(line[0][len("RESULT="):])


# ── pure policy (in-process, no hook) ───────────────────────────────────────────────────────────────────────────────────────────

def test_path_policy_is_deny_by_default(tmp_path):
    sb = str(tmp_path.resolve())
    roots = (os.path.realpath(sys.prefix),)
    assert S.path_decision(tmp_path / "a", write=True, sandbox=sb, read_roots=roots)
    assert S.path_decision(Path(sys.prefix) / "lib", write=False, sandbox=sb, read_roots=roots)
    assert not S.path_decision(Path(sys.prefix) / "lib", write=True, sandbox=sb, read_roots=roots)        # never write outside the sandbox
    assert not S.path_decision("/etc/passwd", write=False, sandbox=sb, read_roots=roots)
    assert not S.path_decision(REPO / "eval_private", write=False, sandbox=sb, read_roots=roots)
    assert not S.path_decision(tmp_path / ".." / "escape", write=True, sandbox=sb, read_roots=roots)      # '..' is resolved before the check
    link = tmp_path / "link"
    link.symlink_to("/etc")
    assert not S.path_decision(link / "passwd", write=False, sandbox=sb, read_roots=roots)                # symlink out of the sandbox is resolved


def test_forbidden_list_covers_every_trainer_package_named_in_the_task():
    for name in ("torch", "transformers", "unsloth", "trl", "peft", "bitsandbytes", "accelerate", "datasets"):
        assert name in S.FORBIDDEN_TOP_LEVEL


def test_the_pytest_process_has_no_trainer_packages_loaded_and_no_hook_active():
    assert S.forbidden_modules_loaded() == [] and S._State.active is False


# ── behaviour under the guard (subprocess) ──────────────────────────────────────────────────────────────────────────────────────

def test_guard_blocks_imports_network_gpu_processes_and_foreign_paths(tmp_path):
    out = _child("""
        os.environ["CUDA_VISIBLE_DEVICES"] = "0"
        g = SyntheticOnlyGuard(sb)
        with g as att:
            for name in S.FORBIDDEN_TOP_LEVEL:
                attempt("import_" + name, lambda n=name: __import__(n))
            attempt("socket_create", lambda: socket.socket())
            attempt("socket_connect", lambda: socket.create_connection(("127.0.0.1", 9), timeout=0.2))
            attempt("dns", lambda: socket.getaddrinfo("example.com", 80))
            attempt("read_etc_passwd", lambda: open("/etc/passwd").read())
            attempt("read_protected_dir", lambda: open(REPO / "eval_private" / "anything.jsonl"))
            attempt("read_orca_home", lambda: open(Path.home() / ".orca" / "x"))
            attempt("write_outside_sandbox", lambda: open("/tmp/orneur-sentinel-should-not-exist.txt", "w"))
            attempt("write_repo", lambda: open(REPO / "SENTINEL_SHOULD_NOT_EXIST", "w"))
            attempt("mkdir_outside", lambda: os.mkdir("/tmp/orneur-sentinel-dir-should-not-exist"))
            attempt("listdir_outside", lambda: os.listdir("/etc"))
            attempt("gpu_device_node", lambda: open("/dev/nvidia0", "rb"))
            attempt("cuda_library", lambda: ctypes.CDLL("libcuda.so.1"))
            attempt("subprocess", lambda: subprocess.run(["true"]))
            attempt("os_system", lambda: os.system("true"))
            attempt("fork", lambda: os.fork())
            attempt("sandbox_write_ok", lambda: (sb / "ok.txt").write_text("x"))
            attempt("sandbox_read_ok", lambda: (sb / "ok.txt").read_text())
            attempt("stdlib_read_ok", lambda: open(os.__file__).read())
            attempt("urandom_ok", lambda: os.urandom(8))
            res["cuda_inside"] = os.environ.get("CUDA_VISIBLE_DEVICES")
            res["violations_inside"] = len(g.violations)
            swallowed = []
            try:
                try:
                    __import__("torch")
                except Exception:
                    swallowed.append("Exception")        # a stray `except Exception` must NOT swallow the violation
            except SyntheticGuaranteeViolation:
                swallowed.append("propagated")
            try:
                try:
                    __import__("torch")
                except ImportError:
                    swallowed.append("ImportError")
            except SyntheticGuaranteeViolation:
                swallowed.append("propagated")
            res["swallow_probe"] = swallowed
        res["cuda_after"] = os.environ.get("CUDA_VISIBLE_DEVICES")
        s = socket.socket(); s.close(); res["after_exit_socket_ok"] = True
        res["after_exit_import_not_blocked"] = "torch" not in sys.modules
        res["forbidden_loaded"] = S.forbidden_modules_loaded()
        res["leftover_files"] = [p for p in ("/tmp/orneur-sentinel-should-not-exist.txt", "/tmp/orneur-sentinel-dir-should-not-exist", str(REPO / "SENTINEL_SHOULD_NOT_EXIST")) if os.path.exists(p)]
    """, tmp_path)
    for k, v in out.items():
        if k.startswith("import_") or k in ("socket_create", "socket_connect", "dns", "read_etc_passwd", "read_protected_dir", "read_orca_home",
                                             "write_outside_sandbox", "write_repo", "mkdir_outside", "listdir_outside", "gpu_device_node",
                                             "cuda_library", "subprocess", "os_system", "fork"):
            assert v == "BLOCKED", (k, v)
    assert out["sandbox_write_ok"] == out["sandbox_read_ok"] == out["stdlib_read_ok"] == out["urandom_ok"] == "ALLOWED"
    assert out["cuda_inside"] == "" and out["cuda_after"] == "0"                   # GPUs hidden inside, environment restored after
    assert out["violations_inside"] >= len(S.FORBIDDEN_TOP_LEVEL)
    assert out["swallow_probe"] == ["propagated", "propagated"]                    # neither `except Exception` nor `except ImportError` can hide it
    assert out["after_exit_socket_ok"] and out["forbidden_loaded"] == [] and out["leftover_files"] == []


def test_a_full_synthetic_run_completes_under_the_guard_without_loading_any_trainer_package(tmp_path):
    out = _child("""
        before = set(sys.modules)
        o = H.run_synthetic(Plan(), sb / "run", guard=SyntheticOnlyGuard(sb), run_id="sentinel-run", budget=BUD, binding=BIND, env_manifest_sha256="d" * 64)
        res["status"] = o.status
        res["steps"] = o.steps
        res["forbidden_loaded"] = S.forbidden_modules_loaded()
        res["new_forbidden"] = sorted(m for m in set(sys.modules) - before if m.partition(".")[0] in S.FORBIDDEN_TOP_LEVEL)
        res["network_modules_opened"] = False
        from orca.train.dryrun.ledger import RunLedger
        res["ledger_ok"] = RunLedger(sb / "run" / "ledger.jsonl").verify().ok
        res["wrote_only_in_sandbox"] = sorted(p.name for p in sb.iterdir())
        res["violations"] = len(S._State.violations)
    """, tmp_path)
    assert out["status"] == "FINISHED" and out["steps"] == 12 and out["forbidden_loaded"] == [] and out["new_forbidden"] == []
    assert out["ledger_ok"] and out["wrote_only_in_sandbox"] == ["run"] and out["violations"] == 0


def test_resume_also_runs_under_the_guard(tmp_path):
    out = _child("""
        b1 = ResourceBudget(max_steps=5, max_tokens=10**6, max_wall_clock_s=100, max_spend_usd=10, sim_cost_usd_per_step=0.01)
        kw = dict(run_id="r", binding=BIND, env_manifest_sha256="d" * 64)
        a = H.run_synthetic(Plan(), sb / "x", guard=SyntheticOnlyGuard(sb), budget=b1, **kw)
        b = H.run_synthetic(Plan(), sb / "x", guard=SyntheticOnlyGuard(sb), budget=BUD, resume=True, **kw)
        c = H.run_synthetic(Plan(), sb / "y", guard=SyntheticOnlyGuard(sb), budget=BUD, **kw)
        res["first"] = a.reason
        res["equal"] = b.state.sha256 == c.state.sha256
    """, tmp_path)
    assert out["first"] == "STEP_CAP" and out["equal"] is True


# ── fail closed ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_fails_closed_when_a_forbidden_package_is_already_imported(tmp_path):
    out = _child("""
        sys.modules["torch"] = types.ModuleType("torch")
        attempt("enter", lambda: SyntheticOnlyGuard(sb).__enter__())
        attempt("run", lambda: H.run_synthetic(Plan(), sb / "run", guard=SyntheticOnlyGuard(sb), run_id="r", budget=BUD, binding=BIND, env_manifest_sha256="d" * 64))
        res["run_dir_created"] = (sb / "run").exists()
        res["guard_active"] = S._State.active
    """, tmp_path)
    assert out["enter"] == out["run"] == "UNAVAILABLE" and out["run_dir_created"] is False and out["guard_active"] is False


def test_fails_closed_for_unsafe_sandboxes_and_nesting(tmp_path):
    out = _child("""
        attempt("repo_as_sandbox", lambda: SyntheticOnlyGuard(REPO).__enter__())
        attempt("tmp_root_as_sandbox", lambda: SyntheticOnlyGuard(Path(tempfile.gettempdir())).__enter__())
        attempt("missing_sandbox", lambda: SyntheticOnlyGuard(sb / "nope").__enter__())
        link = sb.parent / (sb.name + "-link")
        link.symlink_to(sb)
        attempt("symlink_sandbox", lambda: SyntheticOnlyGuard(link).__enter__())
        with SyntheticOnlyGuard(sb) as att:
            attempt("nested", lambda: SyntheticOnlyGuard(sb).__enter__())
        attempt("stale_attestation", att.assert_active)
        attempt("forged_attestation", lambda: S.GuardAttestation(object(), object()))
        res["guard_active_after"] = S._State.active
    """, tmp_path)
    assert {out[k] for k in ("repo_as_sandbox", "tmp_root_as_sandbox", "missing_sandbox", "symlink_sandbox", "nested", "stale_attestation",
                             "forged_attestation")} == {"UNAVAILABLE"}
    assert out["guard_active_after"] is False


def test_fails_closed_when_the_audit_hook_is_not_actually_enforcing(tmp_path):
    out = _child("""
        S._audit = lambda event, args: None          # simulate a broken/neutered hook BEFORE it is installed
        attempt("enter", lambda: SyntheticOnlyGuard(sb).__enter__())
        res["guard_active"] = S._State.active
        attempt("run", lambda: H.run_synthetic(Plan(), sb / "run", guard=SyntheticOnlyGuard(sb), run_id="r", budget=BUD, binding=BIND, env_manifest_sha256="d" * 64))
        res["run_dir_created"] = (sb / "run").exists()
    """, tmp_path)
    assert out["enter"] == "UNAVAILABLE" and out["run"] == "UNAVAILABLE" and out["guard_active"] is False and out["run_dir_created"] is False


def test_a_swallowed_violation_still_fails_the_run(tmp_path):
    out = _child("""
        with SyntheticOnlyGuard(sb) as att:
            try:
                __import__("torch")
            except BaseException:
                pass
            attempt("check", att.assert_no_violations)
    """, tmp_path)
    assert out["check"] == "BLOCKED"            # SyntheticGuaranteeViolation re-raised by the end-of-run check


@pytest.mark.parametrize("name", ["run_synthetic", "rehearse_with_grant"])
def test_harness_entry_points_require_a_guard_argument(name):
    import inspect
    import orca.train.dryrun.harness as H
    assert "guard" in inspect.signature(getattr(H, name)).parameters
