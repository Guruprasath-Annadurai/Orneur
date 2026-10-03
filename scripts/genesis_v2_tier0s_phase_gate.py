#!/usr/bin/env python3
"""Genesis V2 Tier0-S (Sequential Sovereign Isolation) -- phase gate. REDUCED-ASSURANCE, PROCEDURAL + SOFTWARE-LEVEL control.

Runs at the START of a Forge or Witness phase on the single physical machine. It checks the invariants that software on that machine can check:
  no container daemon alive, network disabled, no cloud-sync / AI-agent tooling running, the OTHER role's secret store not visible, role-forbidden
  material absent from this role's state directory, Qualification code absent, and -- the key sequential rule -- that the OTHER role has not run in
  this same boot session (a full shutdown/reboot is required between phases).

HONEST LIMITS: this is a guard against ACCIDENTAL mixing and ordinary-process compromise, enforced by software running on the machine it guards. It does
not defend against a malicious owner/root administrator (who can edit the receipt, the gate, or the machine), firmware/boot-chain compromise, or a
privileged attacker with access to both environments over time. It is NOT Tier0-A-equivalent and creates/reads no secret value (only file NAMES and
process names). Receipts hold a role name and an opaque hash of the boot session -- no secrets, no hostnames.

CLI:  check --role forge|witness --state-dir DIR [--deny-path P ...] [--code-root DIR]   (read-only; exit 0 = gate passes)
      begin --role ... --state-dir DIR ...                                              (check, then append a phase-start receipt if clean)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROLES = ("forge", "witness")
DAEMON_PROCS = ("com.docker.backend", "dockerd", "containerd", "Docker Desktop", "com.docker.virtualization")
SYNC_PROCS = ("bird", "cloudd", "fileproviderd", "Dropbox", "OneDrive", "Google Drive", "GoogleDriveFS", "MEGAsync")
AGENT_PROCS = ("claude", "codex", "cursor", "copilot", "aider", "context-mode")
OWNER_KEY_PATTERNS = (r"owner[_-]?signing", r"ed25519.*priv", r"\.pem$", r"id_(rsa|ed25519)$")
FORBIDDEN_BY_ROLE = {"forge": (r"vault[_-]?private[_-]?key", r"x25519.*priv"), "witness": (r"corpus[_-]?secret", r"generator[_-]?credential")}
QUALIFICATION_MODULES = ("runner_qualification.py", "sandbox_qualification.py", "semantic_calibration.py")


def boot_session_id(boottime_raw: str) -> str:
    """Opaque id of the current boot session (hash of kern.boottime). Changes on every full boot; unchanged by sleep/wake or process restarts."""
    return hashlib.sha256(boottime_raw.encode()).hexdigest()[:16]


def _read_receipts(state_dir: Path) -> list:
    p = state_dir / "phase_receipts.jsonl"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({"role": "CORRUPT", "boot": "CORRUPT"})
    return out


def active_interfaces(ifconfig_text: str) -> list:
    active = []
    for block in re.split(r"\n(?=\S)", ifconfig_text):
        name = block.split(":", 1)[0].strip()
        if name and not name.startswith("lo") and re.search(r"status:\s*active", block):
            active.append(name)
    return active


def evaluate(role: str, *, processes: list, ifconfig_text: str, boot_id: str, state_dir: Path, deny_paths: list, code_root: Path | None) -> dict:
    """Pure given its inputs. Returns {check: {"ok": bool, "detail": str}}; never includes secret values (only names/counts)."""
    if role not in ROLES:
        raise ValueError(role)
    other = "witness" if role == "forge" else "forge"
    res = {}
    names = {os.path.basename(p) for p in processes}
    hit = sorted(n for n in names if any(d.lower() in n.lower() for d in DAEMON_PROCS))
    res["no_container_daemon_alive"] = {"ok": not hit, "detail": f"{len(hit)} matching process name(s)"}
    ifs = active_interfaces(ifconfig_text)
    res["network_disabled"] = {"ok": not ifs, "detail": f"{len(ifs)} active non-loopback interface(s)"}
    sync = sorted(n for n in names if any(s.lower() == n.lower() for s in SYNC_PROCS))
    res["no_cloud_sync_processes"] = {"ok": not sync, "detail": f"{len(sync)} matching process name(s)"}
    agent = sorted(n for n in names if any(a.lower() in n.lower() for a in AGENT_PROCS))
    res["no_ai_agent_tooling_running"] = {"ok": not agent, "detail": f"{len(agent)} matching process name(s)"}
    visible = [str(p) for p in deny_paths if Path(p).exists()]
    res["other_role_secret_store_not_visible"] = {"ok": not visible, "detail": f"{len(visible)} of {len(deny_paths)} deny-listed path(s) visible"}
    receipts = _read_receipts(state_dir)
    clash = [r for r in receipts if r.get("boot") == boot_id and r.get("role") != role]
    res["full_reboot_since_other_role"] = {"ok": not clash, "detail": f"{len(clash)} receipt(s) of another role in this boot session (a full shutdown/reboot is required between phases)"}
    bad = []
    if state_dir.is_dir():
        for f in state_dir.rglob("*"):
            n = f.name.lower()
            if f.is_file() and (any(re.search(p, n) for p in OWNER_KEY_PATTERNS) or any(re.search(p, n) for p in FORBIDDEN_BY_ROLE[role])):
                bad.append(f.name)
    res["no_forbidden_material_in_role_state"] = {"ok": not bad, "detail": f"{len(bad)} forbidden-name file(s) (owner key / other role's secret)"}
    q = []
    if code_root is not None and code_root.is_dir():
        q = sorted(m for m in QUALIFICATION_MODULES if any(code_root.rglob(m)))
    res["qualification_code_absent"] = {"ok": not q, "detail": f"{len(q)} qualification module(s) present under the role code root"}
    return res


def gate_passes(results: dict) -> bool:
    return all(v["ok"] for v in results.values())


def begin(role: str, state_dir: Path, boot_id: str, results: dict) -> None:
    if not gate_passes(results):
        raise PermissionError("phase gate failed; refusing to record a phase start")
    state_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(state_dir / "phase_receipts.jsonl", os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps({"role": role, "boot": boot_id}) + "\n")


def _live_inputs():
    ps = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, timeout=20).stdout.splitlines()
    ifc = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=20).stdout
    bt = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=20).stdout.strip()
    return ps, ifc, boot_session_id(bt)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("check", "begin"))
    ap.add_argument("--role", required=True, choices=ROLES)
    ap.add_argument("--state-dir", required=True, type=Path)
    ap.add_argument("--deny-path", action="append", default=[])
    ap.add_argument("--code-root", type=Path)
    a = ap.parse_args(argv[1:])
    ps, ifc, boot = _live_inputs()
    res = evaluate(a.role, processes=ps, ifconfig_text=ifc, boot_id=boot, state_dir=a.state_dir, deny_paths=a.deny_path, code_root=a.code_root)
    for k, v in res.items():
        print(("PASS " if v["ok"] else "FAIL ") + k + " -- " + v["detail"])
    ok = gate_passes(res)
    if a.cmd == "begin" and ok:
        begin(a.role, a.state_dir, boot, res)
    print("GATE_PASSES" if ok else "GATE_FAILS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
