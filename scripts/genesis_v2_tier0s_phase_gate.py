#!/usr/bin/env python3
"""Genesis V2 Tier0-S (Sequential Sovereign Isolation) -- phase gate v2. REDUCED-ASSURANCE, SOFTWARE-LEVEL, ONE-SHOT, ADVISORY.

WHAT THIS IS: a fail-closed pre-flight run by the operator at the START of a Forge or Witness phase on the single physical machine. It checks what software
on that machine can check, then (only via `begin`) appends an entry to a local same-environment interlock log.

WHAT THIS IS NOT (read before relying on it):
  * NOT a hardware trust boundary. A malicious owner/root administrator, anyone able to write the files this script reads, or a compromised kernel/firmware
    can make it pass. It guards against ACCIDENTAL mixing and ordinary-process mistakes only.
  * NOT continuous. It is checked once, at phase start. It cannot prevent the network being re-enabled, a runtime being started, or a sync/agent
    process being launched after it exits. The OWNER PROCEDURE must independently keep networking disabled and the environment clean for the WHOLE phase.
  * NOT the cold-boot/detachment control. Cold boot between roles and PHYSICAL DETACHMENT of the other role's storage are owner-controlled physical
    procedures (see the Tier0-S design doc). The interlock below adds NO assurance against any adversary and earns NO acceptance credit.
  * NOT exhaustive. Process, socket and path checks use known names/locations; absence of a known indicator is not proof of absence.

FAIL-CLOSED RULE: every security-relevant input must be supplied and every host query must succeed, produce plausible output, and parse. Anything
missing, unreadable, malformed, or unverifiable yields FAIL_CLOSED. Missing telemetry is never interpreted as a secure host. The gate passes only if every
check is PASS.

PROCESS ABSENCE != EXPOSURE ABSENCE: a stopped sync/agent process does not satisfy the residual-exposure checks. Those look (existence and non-emptiness
only, never contents or names) at known synchronized paths and known agent transcript/index/session/recovery stores. NO_RESIDUAL_EXPOSURE_DETECTED
means "none of the known locations has data", not a proof that no exposure exists.

INTERLOCK (advisory, same-environment): lives INSIDE the currently booted environment's own state directory (never shared across environments, so it
creates no cross-role channel). Non-secret: role, per-boot UUID, sequence, hash chain, environment id. Anyone who can write the directory can forge it.

CLI:  init  --state-dir D
      check --role forge|witness --state-dir D --code-root C --deny-path P [--deny-path P ...] [--deny-volume NAME ...] [--workspace W ...] [--process-allowlist FILE]
      begin (same as check; on GATE_PASSES appends an interlock entry)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path

ROLES = ("forge", "witness")
PASS, FAIL, FAIL_CLOSED = "PASS", "FAIL", "FAIL_CLOSED"
UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
ENV_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SUM_RE = re.compile(r"^[0-9a-f]{64}$")
ZERO = "0" * 64

# ---- runtime / control-plane detection (NOT exhaustive; names, sockets, install dirs, env)
RUNTIME_TOKENS = {"docker", "dockerd", "containerd", "colima", "lima", "limactl", "podman", "gvproxy", "nerdctl", "buildkitd", "vfkit", "krunkit",
                  "orbstack", "rancher", "utm", "virtualization", "virtualmachine", "virtualbuddy", "multipass", "kubelet", "k3s", "minikube"}
RUNTIME_PREFIXES = ("qemu", "vbox", "virtualbox", "vmware", "prl", "parallels")
RUNTIME_SOCKETS_ABS = ("/var/run/docker.sock", "/var/run/podman", "/run/podman/podman.sock", "/var/run/containerd/containerd.sock")
RUNTIME_SOCKETS_HOME = (".docker/run/docker.sock", ".orbstack/run/docker.sock", ".rd/docker.sock")
RUNTIME_INSTALL_DIRS_HOME = (".colima", ".lima", ".orbstack", ".rd", ".local/share/containers", ".docker")
RUNTIME_ENV = ("DOCKER_HOST", "CONTAINER_HOST", "DOCKER_CONTEXT", "COLIMA_HOME", "LIMA_HOME")

# ---- sync / agent: PROCESS indicators and RESIDUAL-EXPOSURE locations (relative to home)
SYNC_PROC_TOKENS = {"dropbox", "onedrive", "googledrivefs", "megasync", "pcloud", "nextcloud", "syncthing", "rclone", "box", "resilio", "insync", "maestral"}
SYNC_ROOTS_HOME = ("Library/Mobile Documents", "Library/CloudStorage", "Library/Application Support/CloudDocs", "Dropbox", "OneDrive", "Google Drive", "Box", "pCloud Drive", "Nextcloud", "Sync")
SYNC_WORKSPACE_FORBIDDEN_HOME = ("Desktop", "Documents")      # may be iCloud-synced; sync scope is not established by this gate
AGENT_PROC_TOKENS = {"claude", "codex", "cursor", "copilot", "aider", "windsurf", "gemini", "ollama", "context-mode", "continue"}
AGENT_CMDLINE_MARKERS = ("claude-code", "@anthropic-ai", "@openai/codex", "context-mode", "copilot-language-server", "aider", "windsurf", "ollama")
AGENT_STORES_HOME = (".claude", ".codex", ".cursor", ".windsurf", ".gemini", ".continue", ".config/github-copilot", ".ollama",
                     "Library/Application Support/Claude", "Library/Application Support/Cursor", "Library/Application Support/Code",
                     "Library/Application Support/Windsurf", "Library/Application Support/Zed", "Library/Application Support/Codex")

# ---- role material (weak, name+header evidence only)
OWNER_KEY_PATTERNS = (r"owner[_-]?signing", r"ed25519.*priv", r"\.pem$", r"id_(rsa|ed25519)$", r"\.p12$", r"\.key$")
FORBIDDEN_BY_ROLE = {"forge": (r"vault[_-]?private[_-]?key", r"x25519.*priv"), "witness": (r"corpus[_-]?secret", r"generator[_-]?credential")}
KEY_HEADER_MARKERS = (b"PRIVATE KEY", b"OPENSSH PRIVATE")

# ---- allowlisted role code (everything else under the code root fails). Mirrors infra/tier0-local APP_FILES + the two transfer/gate scripts.
ROLE_CODE_ALLOWLIST = frozenset({
    "orca/__init__.py", "orca/eval/__init__.py", "orca/eval/genesis_eval_v1.py", "orca/eval/genesis_v2/__init__.py",
    "orca/eval/genesis_v2/spec.py", "orca/eval/genesis_v2/store.py",
    "scripts/genesis_v2_tier0a_transfer_bundle.py", "scripts/genesis_v2_tier0s_phase_gate.py"})


# =============================================================================== host queries (fail closed)
def _run(cmd: list):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return p.stdout if p.returncode == 0 else None


def collect_host(home: Path | None = None) -> dict:
    """Raw host telemetry. A value of None means the query failed (non-zero exit / exception); evaluate() turns that into FAIL_CLOSED."""
    boot = _run(["sysctl", "-n", "kern.bootsessionuuid"])
    try:
        volumes = sorted(os.listdir("/Volumes"))
    except OSError:
        volumes = None
    ps_comm, ps_cmd = _run(["ps", "-axo", "comm="]), _run(["ps", "-axo", "command="])
    return {"processes": ps_comm.splitlines() if ps_comm is not None else None, "cmdlines": ps_cmd.splitlines() if ps_cmd is not None else None,
            "ifconfig": _run(["ifconfig", "-a"]), "routes4": _run(["netstat", "-rn", "-f", "inet"]), "routes6": _run(["netstat", "-rn", "-f", "inet6"]),
            "listeners": _run(["netstat", "-an"]), "boot_id": boot.strip() if boot is not None else None, "volumes": volumes,
            "home": Path(home) if home else Path.home(), "env": dict(os.environ)}


# =============================================================================== parsers (None => unparsable => FAIL_CLOSED)
def parse_processes(lines):
    if not isinstance(lines, list) or len(lines) < 10:
        return None
    names = [os.path.basename(l.strip()) for l in lines if l.strip()]
    return names if "launchd" in names else None            # sanity: a real macOS `ps` always lists launchd


def parse_cmdlines(lines):
    return lines if isinstance(lines, list) and len(lines) >= 10 else None


def parse_interfaces(text):
    if not isinstance(text, str) or "lo0:" not in text:
        return None                                          # sanity: loopback must be present in a real `ifconfig -a`
    out = []
    for block in re.split(r"\n(?=\S)", text):
        m = re.match(r"^([A-Za-z0-9_.-]+):", block)
        if not m:
            continue
        fl = re.search(r"flags=[0-9a-fx]+<([^>]*)>", block)
        out.append({"name": m.group(1), "up": bool(fl and "UP" in fl.group(1).split(",")),
                    "status": (re.search(r"status:\s*(\w+)", block) or [None, None])[1],
                    "v4": re.findall(r"^\s+inet\s+(\S+)", block, re.M),
                    "v6": [a.split("%")[0] for a in re.findall(r"^\s+inet6\s+(\S+)", block, re.M)]})
    return out or None


def _link_local6(a: str) -> bool:
    return a.lower().startswith(("fe8", "fe9", "fea", "feb"))


def parse_default_routes(text):
    if not isinstance(text, str) or "Destination" not in text:
        return None
    return [l.split() for l in text.splitlines() if l.split()[:1] == ["default"]]


def parse_listeners(text):
    if not isinstance(text, str) or "Active Internet connections" not in text:
        return None
    out = []
    for l in text.splitlines():
        f = l.split()
        if len(f) >= 6 and f[0].startswith("tcp") and f[-1] == "LISTEN":
            out.append(f[3])
    return out


def _is_loopback_listener(addr: str) -> bool:
    return addr.startswith(("127.", "::1.", "localhost."))


# =============================================================================== helpers
def _tokens(name: str) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", name.lower()) if t}


def _matches(name: str, tokens: set, prefixes: tuple = ()) -> bool:
    ts = _tokens(name)
    return bool(ts & tokens) or any(t.startswith(prefixes) for t in ts if prefixes)


def _nonempty_dir(p: Path) -> bool:
    try:
        if p.is_symlink() or not p.is_dir():
            return p.exists() or p.is_symlink()
        with os.scandir(p) as it:
            return any(True for _ in it)
    except OSError:
        return True                                          # unreadable existing location: assume exposure


def _res(status, detail):
    return {"status": status, "ok": status == PASS, "detail": detail}


def _fc(detail):
    return _res(FAIL_CLOSED, detail)


# =============================================================================== interlock (advisory, same-environment, NOT a security boundary)
def _canon(rec: dict) -> bytes:
    return json.dumps(rec, sort_keys=True, separators=(",", ":")).encode()


def _sum(rec: dict) -> str:
    return hashlib.sha256(_canon({k: v for k, v in rec.items() if k != "sum"})).hexdigest()


def _strict_loads(text: str):
    def hook(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate key")
        return dict(pairs)
    return json.loads(text, object_pairs_hook=hook)


def _read_regular(p: Path) -> str:
    st = os.lstat(p)
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("not a regular file")
    return p.read_text()


def init_state(state_dir: Path) -> str:
    """Explicit owner/operator action that creates a NEW interlock directory (0700) for this environment. Refuses to touch anything existing."""
    state_dir = Path(state_dir)
    if state_dir.exists():
        raise FileExistsError("state directory already exists; refusing to re-initialize")
    state_dir.mkdir(parents=True, mode=0o700)
    env_id = secrets.token_hex(16)
    for name, body in (("INIT.json", {"v": 2, "env_id": env_id}), ("HEAD.json", {"v": 2, "env_id": env_id, "seq": 0, "sum": ZERO}), ("receipts.jsonl", None)):
        fd = os.open(state_dir / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            if body is not None:
                f.write(json.dumps(body, sort_keys=True))
    return env_id


def verify_state(state_dir) -> tuple:
    """Returns (problems, receipts). ANY problem => the caller must treat the interlock as unverifiable (FAIL_CLOSED)."""
    problems, recs = [], []
    if state_dir is None:
        return ["state directory not supplied"], recs
    d = Path(state_dir)
    try:
        st = os.lstat(d)
    except OSError:
        return ["state directory missing or unreadable (run `init` first)"], recs
    if not stat.S_ISDIR(st.st_mode):
        return ["state path is not a directory"], recs
    if st.st_mode & 0o022:
        problems.append("state directory is group/other-writable")
    try:
        init = _strict_loads(_read_regular(d / "INIT.json"))
        head = _strict_loads(_read_regular(d / "HEAD.json"))
        raw = _read_regular(d / "receipts.jsonl")
    except Exception as e:
        return problems + [f"INIT/HEAD/receipts missing, unreadable or malformed ({type(e).__name__})"], recs
    if set(init) != {"v", "env_id"} or init.get("v") != 2 or not ENV_ID_RE.match(str(init.get("env_id"))):
        problems.append("INIT malformed")
    if set(head) != {"v", "env_id", "seq", "sum"} or head.get("v") != 2 or not isinstance(head.get("seq"), int) or isinstance(head.get("seq"), bool) \
            or not SUM_RE.match(str(head.get("sum"))):
        problems.append("HEAD malformed")
    if problems:
        return problems, recs
    if head["env_id"] != init["env_id"]:
        return ["HEAD/INIT environment id mismatch"], recs
    if raw and not raw.endswith("\n"):
        return ["receipts truncated (no final newline)"], recs
    prev = ZERO
    for i, line in enumerate(raw.splitlines(), 1):
        try:
            r = _strict_loads(line)
        except Exception:
            return [f"receipt {i} is not strict JSON"], recs
        if not isinstance(r, dict) or set(r) != {"v", "env_id", "seq", "role", "boot", "prev", "sum"}:
            return [f"receipt {i} has missing or extra fields"], recs
        if r["v"] != 2 or not isinstance(r["seq"], int) or isinstance(r["seq"], bool) or r["role"] not in ROLES or not isinstance(r["boot"], str) or not UUID_RE.match(r["boot"]) \
                or not isinstance(r["prev"], str) or not isinstance(r["sum"], str) or not SUM_RE.match(r["sum"]) or not SUM_RE.match(r["prev"]):
            return [f"receipt {i} has malformed or unknown field values"], recs
        if r["env_id"] != init["env_id"]:
            return [f"receipt {i} belongs to a different environment (copied?)"], recs
        if r["seq"] != i:
            return [f"receipt {i} sequence inconsistent (replay, gap or reorder)"], recs
        if r["prev"] != prev:
            return [f"receipt {i} chain link broken"], recs
        if r["sum"] != _sum(r):
            return [f"receipt {i} checksum mismatch (edited)"], recs
        prev = r["sum"]
        recs.append(r)
    if head["seq"] != len(recs) or head["sum"] != prev:
        return ["HEAD does not match the receipt log (receipts deleted, truncated or HEAD edited)"], recs
    return [], recs


def append_receipt(state_dir: Path, role: str, boot_id: str) -> dict:
    problems, recs = verify_state(state_dir)
    if problems:
        raise PermissionError("interlock state unverifiable: " + "; ".join(problems))
    if role not in ROLES or not UUID_RE.match(boot_id or ""):
        raise ValueError("role/boot id invalid")
    d = Path(state_dir)
    env_id = _strict_loads((d / "INIT.json").read_text())["env_id"]
    rec = {"v": 2, "env_id": env_id, "seq": len(recs) + 1, "role": role, "boot": boot_id, "prev": recs[-1]["sum"] if recs else ZERO}
    rec["sum"] = _sum(rec)
    fd = os.open(d / "receipts.jsonl", os.O_APPEND | os.O_WRONLY)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n"); f.flush(); os.fsync(f.fileno())
    tmp = d / ".HEAD.tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps({"v": 2, "env_id": env_id, "seq": rec["seq"], "sum": rec["sum"]}, sort_keys=True)); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, d / "HEAD.json")
    return rec


# =============================================================================== the gate
def evaluate(role, *, host: dict, state_dir=None, code_root=None, deny_paths=None, deny_volumes=None, workspaces=None, process_allowlist=None) -> dict:
    """Pure given its inputs. {check: {"status": PASS|FAIL|FAIL_CLOSED, "ok": bool, "detail": str}}. Details are counts/categories only -- never paths,
    file names, process command lines or contents."""
    if role not in ROLES:
        raise ValueError(role)
    r = {}
    home = Path(host.get("home") or Path.home())
    # -- boot session
    boot = host.get("boot_id")
    boot_ok = isinstance(boot, str) and bool(UUID_RE.match(boot))
    r["boot_session_identified"] = _res(PASS, "per-boot UUID obtained") if boot_ok else _fc("kern.bootsessionuuid unavailable or not a UUID")
    # -- advisory interlock
    problems, recs = verify_state(state_dir)
    if problems:
        r["interlock_state_verified"] = _fc("; ".join(problems))
        r["interlock_other_role_not_this_boot"] = _fc("interlock state unverifiable")
    else:
        r["interlock_state_verified"] = _res(PASS, f"{len(recs)} chained receipt(s) verified (advisory; forgeable by any writer)")
        if not boot_ok:
            r["interlock_other_role_not_this_boot"] = _fc("no boot id to compare")
        else:
            clash = [x for x in recs if x["boot"].lower() == boot.lower() and x["role"] != role]
            r["interlock_other_role_not_this_boot"] = _res(FAIL if clash else PASS, f"{len(clash)} entry(ies) of the other role in this boot session")
    # -- container runtime / control plane
    names, cmds = parse_processes(host.get("processes")), parse_cmdlines(host.get("cmdlines"))
    if names is None:
        r["container_runtime_absent"] = _fc("process list unavailable or implausible")
    else:
        hits = [n for n in names if _matches(n, RUNTIME_TOKENS, RUNTIME_PREFIXES)]
        socks = [p for p in host.get("runtime_sockets_abs", RUNTIME_SOCKETS_ABS) if os.path.lexists(p)] + [str(home / p) for p in RUNTIME_SOCKETS_HOME if os.path.lexists(home / p)]
        dirs = [p for p in RUNTIME_INSTALL_DIRS_HOME if os.path.lexists(home / p)]
        envs = [e for e in RUNTIME_ENV if (host.get("env") or {}).get(e)]
        bad = len(hits) + len(socks) + len(dirs) + len(envs)
        r["container_runtime_absent"] = _res(FAIL if bad else PASS, f"{len(hits)} runtime process(es), {len(socks)} runtime socket(s), {len(dirs)} runtime install dir(s), {len(envs)} runtime env var(s); NOT exhaustive")
    if process_allowlist is not None:
        if names is None:
            r["process_allowlist_respected"] = _fc("process list unavailable")
        else:
            extra = sorted({n for n in names if n not in set(process_allowlist)})
            r["process_allowlist_respected"] = _res(FAIL if extra else PASS, f"{len(extra)} running process name(s) outside the supplied allowlist")
    # -- network
    ifs = parse_interfaces(host.get("ifconfig"))
    if ifs is None:
        r["network_interfaces_disabled"] = _fc("ifconfig output unavailable or implausible")
    else:
        bad = [i for i in ifs if not i["name"].startswith("lo") and (i["v4"] or [a for a in i["v6"] if not _link_local6(a)] or i["status"] == "active")]
        kinds = sorted({re.sub(r"\d+$", "", i["name"]) for i in bad})
        r["network_interfaces_disabled"] = _res(FAIL if bad else PASS, f"{len(bad)} non-loopback interface(s) with an address or active status (kinds: {','.join(kinds) or 'none'})")
    d4, d6 = parse_default_routes(host.get("routes4")), parse_default_routes(host.get("routes6"))
    if d4 is None or d6 is None:
        r["network_no_default_route"] = _fc("routing table unavailable or implausible")
    else:
        r["network_no_default_route"] = _res(FAIL if (d4 or d6) else PASS, f"{len(d4)} IPv4 / {len(d6)} IPv6 default route(s)")
    lis = parse_listeners(host.get("listeners"))
    if lis is None:
        r["network_no_external_listeners"] = _fc("listener table unavailable or implausible")
    else:
        ext = [a for a in lis if not _is_loopback_listener(a)]
        r["network_no_external_listeners"] = _res(FAIL if ext else PASS, f"{len(ext)} non-loopback TCP listener(s) ({len(lis) - len(ext)} loopback-only)")
    # -- cloud sync: process vs exposure
    if names is None:
        r["cloud_sync_process_absent"] = _fc("process list unavailable")
        r["agent_process_absent"] = _fc("process list unavailable")
    else:
        sync = [n for n in names if _matches(n, SYNC_PROC_TOKENS)]
        r["cloud_sync_process_absent"] = _res(FAIL if sync else PASS, f"PROCESS_{'RUNNING' if sync else 'NOT_RUNNING'} ({len(sync)} third-party sync client process(es))")
        agent = [n for n in names if _matches(n, AGENT_PROC_TOKENS)]
        cmd_hits = [c for c in (cmds or []) if any(m in c.lower() for m in AGENT_CMDLINE_MARKERS)]
        r["agent_process_absent"] = _res(FAIL if (agent or cmd_hits) else PASS, f"PROCESS_{'RUNNING' if (agent or cmd_hits) else 'NOT_RUNNING'} ({len(agent)} name match(es), {len(cmd_hits)} command-line match(es))")
    sync_present = [p for p in SYNC_ROOTS_HOME if _nonempty_dir(home / p)]
    r["cloud_sync_residual_exposure_absent"] = _res(FAIL if sync_present else PASS, ("RESIDUAL_EXPOSURE_PRESENT" if sync_present else "NO_RESIDUAL_EXPOSURE_DETECTED") + f" ({len(sync_present)} of {len(SYNC_ROOTS_HOME)} known synchronized location(s) hold data; sync scope not established)")
    agent_present = [p for p in AGENT_STORES_HOME if _nonempty_dir(home / p)]
    r["agent_residual_exposure_absent"] = _res(FAIL if agent_present else PASS, ("RESIDUAL_EXPOSURE_PRESENT" if agent_present else "NO_RESIDUAL_EXPOSURE_DETECTED") + f" ({len(agent_present)} of {len(AGENT_STORES_HOME)} known agent transcript/index/session/recovery location(s) hold data)")
    ws = [Path(w) for w in (workspaces or [])] + ([Path(state_dir)] if state_dir else [])
    if not ws:
        r["workspace_not_in_synced_or_user_documents_path"] = _fc("no workspace/state directory supplied")
    else:
        roots = [(home / p) for p in SYNC_ROOTS_HOME + SYNC_WORKSPACE_FORBIDDEN_HOME]
        inside = 0
        for w in ws:
            rp = Path(os.path.realpath(w))
            if any(rp == Path(os.path.realpath(x)) or Path(os.path.realpath(x)) in rp.parents for x in roots):
                inside += 1
        r["workspace_not_in_synced_or_user_documents_path"] = _res(FAIL if inside else PASS, f"{inside} of {len(ws)} workspace/state dir(s) under a synchronized or Desktop/Documents location")
    # -- other role's storage unavailable (physical detachment evidence)
    deny_paths, deny_volumes = list(deny_paths or []), list(deny_volumes or [])
    vols = host.get("volumes")
    if not deny_paths and not deny_volumes:
        r["other_role_storage_unavailable"] = _fc("no deny-listed path or volume supplied (the other role's storage must be named explicitly)")
    elif deny_volumes and vols is None:
        r["other_role_storage_unavailable"] = _fc("/Volumes listing unavailable")
    else:
        present = [str(p) for p in deny_paths if os.path.lexists(p)] + [v for v in deny_volumes if v in (vols or [])]
        r["other_role_storage_unavailable"] = _res(FAIL if present else PASS, f"{len(present)} of {len(deny_paths) + len(deny_volumes)} deny-listed path(s)/volume(s) present or mounted")
    # -- allowlisted code root (Qualification exclusion by construction, not by filename blacklist)
    if code_root is None or not Path(code_root).is_dir() or Path(code_root).is_symlink():
        r["role_code_root_allowlisted"] = _fc("code root not supplied, missing, or not a plain directory")
    else:
        cr, extra, links, seen = Path(code_root), 0, 0, 0
        for dp, dns, fns in os.walk(cr, followlinks=False):
            for n in dns + fns:
                full = Path(dp) / n
                if full.is_symlink():
                    links += 1
            for n in fns:
                rel = str((Path(dp) / n).relative_to(cr))
                seen += 1
                if rel not in ROLE_CODE_ALLOWLIST and not (rel.endswith(".pyc") and "__pycache__" in rel):
                    extra += 1
        r["role_code_root_allowlisted"] = _fc("code root is empty") if seen == 0 else _res(FAIL if (extra or links) else PASS, f"{extra} file(s) outside the role allowlist, {links} symlink(s) (Qualification code is excluded by allowlist only within THIS root)")
    # -- weak owner-key / other-role material scan in role state (names + first bytes only)
    if state_dir is None or not Path(state_dir).is_dir():
        r["role_state_forbidden_material_WEAK"] = _fc("state directory not supplied or missing")
    else:
        bad = 0
        for f in Path(state_dir).rglob("*"):
            if not f.is_file() or f.is_symlink():
                continue
            n = f.name.lower()
            hit = any(re.search(p, n) for p in OWNER_KEY_PATTERNS) or any(re.search(p, n) for p in FORBIDDEN_BY_ROLE[role])
            if not hit:
                try:
                    with open(f, "rb") as fh:
                        head = fh.read(256)
                    hit = any(m in head for m in KEY_HEADER_MARKERS)
                except OSError:
                    hit = True           # unreadable file in the role state: treat as suspicious (fail closed)
            bad += 1 if hit else 0
        r["role_state_forbidden_material_WEAK"] = _res(FAIL if bad else PASS, f"{bad} suspicious file(s) by name or key-header; WEAK evidence only (a renamed or encoded key is not detected)")
    return r


def gate_passes(results: dict) -> bool:
    return bool(results) and all(v["status"] == PASS for v in results.values())


def begin(role: str, state_dir: Path, boot_id: str, results: dict) -> dict:
    if not gate_passes(results):
        raise PermissionError("phase gate did not pass; refusing to record a phase start")
    return append_receipt(state_dir, role, boot_id)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("init", "check", "begin"))
    ap.add_argument("--role", choices=ROLES)
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--code-root", type=Path)
    ap.add_argument("--deny-path", action="append", default=[])
    ap.add_argument("--deny-volume", action="append", default=[])
    ap.add_argument("--workspace", action="append", default=[])
    ap.add_argument("--process-allowlist", type=Path)
    a = ap.parse_args(argv[1:])
    if a.cmd == "init":
        if not a.state_dir:
            print("FAIL_CLOSED --state-dir required"); return 1
        init_state(a.state_dir); print("INITIALIZED"); return 0
    if not a.role:
        print("FAIL_CLOSED --role required"); return 1
    allow = None
    if a.process_allowlist:
        try:
            allow = [l.strip() for l in a.process_allowlist.read_text().splitlines() if l.strip()]
        except OSError:
            print("FAIL_CLOSED process allowlist unreadable"); return 1
    host = collect_host()
    res = evaluate(a.role, host=host, state_dir=a.state_dir, code_root=a.code_root, deny_paths=a.deny_path, deny_volumes=a.deny_volume, workspaces=a.workspace, process_allowlist=allow)
    for k, v in res.items():
        print(f"{v['status']:11} {k} -- {v['detail']}")
    ok = gate_passes(res)
    if a.cmd == "begin" and ok:
        begin(a.role, a.state_dir, host["boot_id"], res)
    print("GATE_PASSES" if ok else "GATE_FAILS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
