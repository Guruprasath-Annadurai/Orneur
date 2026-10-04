#!/usr/bin/env python3
"""Genesis V2 Tier0-S (Sequential Sovereign Isolation) -- phase gate v3. REDUCED-ASSURANCE, SOFTWARE-LEVEL, ONE-SHOT, ADVISORY.

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
  * NOT proof of network absence. The socket check sees only sockets that exist at this instant (TCP/UDP bound or connected to a non-loopback address); it
    does not establish that no process could communicate.

FAIL-CLOSED RULE ("unknown state is unsafe state"): every security-relevant input must be supplied, every host query must succeed, produce plausible
output, and parse STRICTLY. Anything missing, unavailable, unreadable, malformed, unsupported, permission-denied, or unverifiable yields FAIL_CLOSED.
Unrecognized syntax inside a security-relevant telemetry source is never ignored. The gate passes only if every check is PASS.

MANDATORY HOST TELEMETRY (each is a distinct source; an unavailable source is FAIL_CLOSED and reported with its reason):
  processes (`ps -axo comm=`), cmdlines (`ps -axo command=`), env (this process's environment, must be a str->str mapping; EMPTY is a legitimately verified
  value), home (the inspected home directory, no silent fallback), ifconfig (`ifconfig -a`), routes4/routes6 (`netstat -rn -f inet|inet6`), sockets
  (`netstat -an`, must contain the Internet-connections section), boot_id (`kern.bootsessionuuid`), and -- when any deny volume/UUID is supplied --
  volumes (/Volumes) and disks (`diskutil list -plist`). A verified-empty cmdline list is IMPOSSIBLE on a live system (it must contain launchd), so an empty
  or launchd-less cmdline set is treated as unavailable. Telemetry failure reasons are distinguished: UNAVAILABLE, PERMISSION_DENIED, UNSUPPORTED, MALFORMED.

MANDATORY CONFIGURATION: interlock state dir (--state-dir), the role's own state dir to scan (--role-state-dir), role code root (--code-root), a code manifest
(--code-manifest) AND its SHA-256 pinned out-of-band (--code-manifest-sha256), and at least one deny-listed path / volume / volume UUID naming the other
role's storage. Missing configuration is FAIL_CLOSED.

PROCESS ABSENCE != EXPOSURE ABSENCE: a stopped sync/agent process does not satisfy the residual-exposure checks. Those look (existence and non-emptiness
only, never contents or names) at known synchronized paths and known agent transcript/index/session/recovery stores. NO_RESIDUAL_EXPOSURE_DETECTED
means "none of the known locations has data", not a proof that no exposure exists.

CODE ALLOWLIST SEMANTICS: the role code root must equal a MANIFEST (relative path, SHA-256, size) exactly, every manifest path must be inside the fixed role
policy (ROLE_CODE_ALLOWLIST), and the manifest's own SHA-256 must match a value pinned out-of-band. This proves: the files under THIS root are byte-identical to
that manifest, nothing else is there, none is a symlink/hardlink/special file, none is group/other-writable, and no unlisted bytecode exists. It does NOT
prove the manifest is the reviewed one unless the pin was transcribed from a reviewed source, does not cover anything outside the root, and is not
cryptographic provenance. Path names alone are never treated as proof of Qualification absence.

INTERLOCK (advisory, same-environment, operator-safety only -- NOT a security isolation boundary): lives INSIDE the currently booted environment's own state
directory (never shared across environments, so it creates no cross-role channel). Non-secret: role, per-boot UUID, sequence, hash chain, environment id.
Anyone who can write the directory can forge it.

CLI:  init  --state-dir D
      build-manifest --code-root C                      (prints a manifest to stdout; review it before pinning its SHA-256)
      check --role forge|witness --state-dir D --role-state-dir R --code-root C --code-manifest M --code-manifest-sha256 H
            --deny-path P [--deny-path P ...] [--deny-volume NAME ...] [--deny-volume-uuid UUID ...] [--workspace W ...] [--process-allowlist FILE]
      begin (same as check; on GATE_PASSES appends an interlock entry)
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import plistlib
import re
import secrets
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path

ROLES = ("forge", "witness")
PASS, FAIL, FAIL_CLOSED = "PASS", "FAIL", "FAIL_CLOSED"
UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
ENV_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SUM_RE = re.compile(r"^[0-9a-f]{64}$")
ZERO = "0" * 64
MAX_HASHED_BYTES = 16 * 1024 * 1024
STATE_FILES = frozenset({"INIT.json", "HEAD.json", "receipts.jsonl"})

# ---- runtime / control-plane detection (NOT exhaustive; names, sockets, install dirs, env)
RUNTIME_TOKENS = {"docker", "dockerd", "containerd", "colima", "lima", "limactl", "podman", "gvproxy", "nerdctl", "buildkitd", "vfkit", "krunkit",
                  "orbstack", "rancher", "utm", "virtualization", "virtualmachine", "virtualbuddy", "multipass", "kubelet", "k3s", "minikube", "hyperkit",
                  "firecracker", "bhyve", "lxc", "crun", "runc"}
RUNTIME_PREFIXES = ("qemu", "vbox", "virtualbox", "vmware", "prl", "parallels")
RUNTIME_SOCKETS_ABS = ("/var/run/docker.sock", "/var/run/podman", "/run/podman/podman.sock", "/var/run/containerd/containerd.sock")
RUNTIME_SOCKETS_HOME = (".docker/run/docker.sock", ".orbstack/run/docker.sock", ".rd/docker.sock")
RUNTIME_INSTALL_DIRS_HOME = (".colima", ".lima", ".orbstack", ".rd", ".local/share/containers", ".config/containers", ".docker", ".kube", ".minikube",
                             "Library/Containers/com.docker.docker")
RUNTIME_ENV = ("DOCKER_HOST", "CONTAINER_HOST", "DOCKER_CONTEXT", "COLIMA_HOME", "LIMA_HOME", "PODMAN_HOST", "CONTAINERD_ADDRESS")

# ---- sync / agent: PROCESS indicators and RESIDUAL-EXPOSURE locations (relative to home). Lists are NOT exhaustive.
SYNC_PROC_TOKENS = {"dropbox", "onedrive", "googledrivefs", "megasync", "pcloud", "nextcloud", "syncthing", "rclone", "box", "resilio", "insync", "maestral"}
SYNC_ROOTS_HOME = ("Library/Mobile Documents", "Library/CloudStorage", "Library/Application Support/CloudDocs", "Dropbox", "OneDrive", "Google Drive", "Box",
                   "pCloud Drive", "Nextcloud", "Sync")
SYNC_WORKSPACE_FORBIDDEN_HOME = ("Desktop", "Documents")      # may be iCloud-synced; sync scope is not established by this gate
AGENT_PROC_TOKENS = {"claude", "codex", "cursor", "copilot", "aider", "windsurf", "gemini", "ollama", "context-mode", "continue", "cline", "roo", "opencode"}
AGENT_CMDLINE_MARKERS = ("claude-code", "@anthropic-ai", "@openai/codex", "context-mode", "copilot-language-server", "aider", "windsurf", "ollama", "gemini-cli",
                         "open-interpreter")
AGENT_STORES_HOME = (".claude", ".codex", ".cursor", ".windsurf", ".gemini", ".continue", ".cline", ".roo", ".aider", ".config/github-copilot", ".ollama",
                     ".local/share/opencode", ".config/Claude", "Library/Application Support/Claude", "Library/Application Support/Cursor",
                     "Library/Application Support/Code", "Library/Application Support/Windsurf", "Library/Application Support/Zed",
                     "Library/Application Support/Codex", "Library/Logs/Claude", "Library/Caches/Claude")

# ---- role material (weak, name+header evidence only)
OWNER_KEY_PATTERNS = (r"owner[_-]?signing", r"ed25519.*priv", r"\.pem$", r"id_(rsa|ed25519)$", r"\.p12$", r"\.key$")
FORBIDDEN_BY_ROLE = {"forge": (r"vault[_-]?private[_-]?key", r"x25519.*priv"), "witness": (r"corpus[_-]?secret", r"generator[_-]?credential")}
KEY_HEADER_MARKERS = (b"PRIVATE KEY", b"OPENSSH PRIVATE")

# ---- fixed role code POLICY: the only paths a role environment may ever contain. A manifest may not add to it.
ROLE_CODE_ALLOWLIST = frozenset({
    "orca/__init__.py", "orca/eval/__init__.py", "orca/eval/genesis_eval_v1.py", "orca/eval/genesis_v2/__init__.py",
    "orca/eval/genesis_v2/spec.py", "orca/eval/genesis_v2/store.py",
    "scripts/genesis_v2_tier0a_transfer_bundle.py", "scripts/genesis_v2_tier0s_phase_gate.py"})
ROLE_BYTECODE_ALLOWED = frozenset()       # generated runtime artifacts must be defined explicitly; none are. Run with PYTHONDONTWRITEBYTECODE=1.


class TelemetryError(Exception):
    """A telemetry source was unparsable. `reason` is one of the distinguished failure classes."""
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


# =============================================================================== host queries (fail closed)
def _run(cmd: list):
    """Returns (status, stdout). status in OK | UNAVAILABLE | PERMISSION_DENIED | UNSUPPORTED."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return "UNSUPPORTED", None
    except PermissionError:
        return "PERMISSION_DENIED", None
    except Exception:
        return "UNAVAILABLE", None
    if p.returncode != 0:
        denied = "permission denied" in (p.stderr or "").lower() or "operation not permitted" in (p.stderr or "").lower()
        return ("PERMISSION_DENIED" if denied else "UNAVAILABLE"), None
    return "OK", p.stdout


def _parse_disks(blob: str) -> list:
    d = plistlib.loads(blob.encode() if isinstance(blob, str) else blob)
    if not isinstance(d, dict) or not isinstance(d.get("AllDisksAndPartitions"), list):
        raise TelemetryError("MALFORMED", "diskutil plist shape")
    out = []
    for disk in d["AllDisksAndPartitions"]:
        if not isinstance(disk, dict):
            raise TelemetryError("MALFORMED", "disk entry")
        for item in [disk] + list(disk.get("Partitions", [])) + list(disk.get("APFSVolumes", [])):
            if isinstance(item, dict) and any(k in item for k in ("VolumeName", "VolumeUUID", "MountPoint")):
                out.append({"name": str(item.get("VolumeName", "")), "uuid": str(item.get("VolumeUUID", "")), "dev": str(item.get("DeviceIdentifier", "")),
                            "mount": str(item.get("MountPoint", ""))})
    return out


def collect_host(home: Path | None = None) -> dict:
    """Raw host telemetry. A source that failed has value None and a reason in host['telemetry'][source]; evaluate() turns that into FAIL_CLOSED."""
    tele, host = {}, {}

    def get(key, cmd, post=None):
        status, out = _run(cmd)
        if status == "OK":
            try:
                host[key] = post(out) if post else out
                tele[key] = "OK"
                return
            except Exception:
                status = "MALFORMED"
        host[key], tele[key] = None, status
    get("processes", ["ps", "-axo", "comm="], lambda o: o.splitlines())
    get("cmdlines", ["ps", "-axo", "command="], lambda o: o.splitlines())
    get("ifconfig", ["ifconfig", "-a"])
    get("routes4", ["netstat", "-rn", "-f", "inet"])
    get("routes6", ["netstat", "-rn", "-f", "inet6"])
    get("sockets", ["netstat", "-an"])
    get("boot_id", ["sysctl", "-n", "kern.bootsessionuuid"], lambda o: o.strip())
    get("disks", ["diskutil", "list", "-plist"], _parse_disks)
    try:
        host["volumes"], tele["volumes"] = sorted(os.listdir("/Volumes")), "OK"
    except PermissionError:
        host["volumes"], tele["volumes"] = None, "PERMISSION_DENIED"
    except OSError:
        host["volumes"], tele["volumes"] = None, "UNAVAILABLE"
    host["home"], tele["home"] = Path(home) if home else Path.home(), "OK"
    host["env"], tele["env"] = dict(os.environ), "OK"
    host["telemetry"] = tele
    return host


# =============================================================================== strict parsers (raise TelemetryError => FAIL_CLOSED)
def parse_processes(lines):
    if not isinstance(lines, list) or not all(isinstance(l, str) for l in lines) or len(lines) < 10:
        raise TelemetryError("MALFORMED", "process list shape/size")
    names = [os.path.basename(l.strip()) for l in lines if l.strip()]
    if "launchd" not in names:
        raise TelemetryError("MALFORMED", "no launchd in process list")        # a real macOS `ps` always lists launchd
    return names


def parse_cmdlines(lines):
    if not isinstance(lines, list) or not all(isinstance(l, str) for l in lines) or len(lines) < 10:
        raise TelemetryError("MALFORMED", "command-line list shape/size")
    if not any(os.path.basename(l.strip().split(" ")[0]) == "launchd" for l in lines if l.strip()):
        raise TelemetryError("MALFORMED", "no launchd in command-line list")
    return lines


def parse_env(env):
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise TelemetryError("MALFORMED", "environment must be a str->str mapping")
    return env                                                                  # an EMPTY mapping is a legitimately verified value


_IF_HDR = re.compile(r"^([A-Za-z][A-Za-z0-9_.-]*): flags=([0-9a-fA-F]+)<([A-Z0-9_,]*)>(?: mtu (\d+))?(?: index (\d+))?$")
_IF_INET = re.compile(r"^\s+inet (\S+)(?: --> (\S+))?(?: netmask (\S+))?(?: broadcast (\S+))?\s*$")
_IF_INET6 = re.compile(r"^\s+inet6 (\S+) prefixlen (\d+)(?: .*)?$")
_IF_STATUS = re.compile(r"^\s+status: ([A-Za-z][A-Za-z ]*)$")
_IF_HARMLESS = ("ether", "nd6", "media:", "member:", "ifmaxaddr", "root", "maxage", "ipfilter", "id", "Configuration:", "capabilities=", "tunnel", "agent",
                "hellotime", "fwddelay", "holdcnt", "proto", "priority", "desc:", "groups:", "bond", "link", "channel", "scheduler", "index", "ssid", "bssid")


def parse_interfaces(text):
    """Strict `ifconfig -a` grammar. Unrecognized security-relevant syntax raises MALFORMED instead of being skipped."""
    if not isinstance(text, str) or not text.strip():
        raise TelemetryError("MALFORMED", "ifconfig output empty")
    out, cur = [], None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if not raw[0].isspace():
            m = _IF_HDR.match(raw)
            if not m:
                raise TelemetryError("MALFORMED", "interface header")
            cur = {"name": m.group(1), "up": "UP" in m.group(3).split(","), "loopback_flag": "LOOPBACK" in m.group(3).split(","), "status": None, "v4": [], "v6": []}
            out.append(cur)
            continue
        if cur is None:
            raise TelemetryError("MALFORMED", "indented line before any interface")
        tok = raw.split()[0]
        if tok == "inet":
            m = _IF_INET.match(raw)
            if not m:
                raise TelemetryError("MALFORMED", "inet record")
            try:
                cur["v4"].append(ipaddress.IPv4Address(m.group(1)))
            except ValueError:
                raise TelemetryError("MALFORMED", "inet address") from None
        elif tok == "inet6":
            m = _IF_INET6.match(raw)
            if not m:
                raise TelemetryError("MALFORMED", "inet6 record")
            try:
                cur["v6"].append(ipaddress.IPv6Address(m.group(1).split("%")[0]))
            except ValueError:
                raise TelemetryError("MALFORMED", "inet6 address") from None
        elif tok == "status:":
            m = _IF_STATUS.match(raw)
            if not m:
                raise TelemetryError("MALFORMED", "status record")
            if m.group(1).strip() not in ("active", "inactive"):
                raise TelemetryError("MALFORMED", "unrecognized interface status value")        # e.g. a corrupted 'active' must not silently become 'not active'
            cur["status"] = m.group(1).strip()
        elif tok.startswith("options=") or tok in _IF_HARMLESS:
            continue
        else:
            raise TelemetryError("MALFORMED", "unrecognized interface line")
    if not any(i["name"].startswith("lo") and i["loopback_flag"] for i in out):
        raise TelemetryError("MALFORMED", "no loopback interface in ifconfig output")
    return out


def interface_violations(ifs: list) -> list:
    """An interface is tolerated only if every address on it is a true loopback address (127/8, ::1) -- by ADDRESS, never by name. Otherwise it violates if it
    has any IPv4 address, any non-link-local IPv6 address, or status active."""
    bad = []
    for i in ifs:
        v4_nonloop = [a for a in i["v4"] if not a.is_loopback]
        v6_nonloop = [a for a in i["v6"] if not a.is_loopback]
        has_addr_issue = bool(v4_nonloop) or any(not a.is_link_local for a in v6_nonloop)
        if has_addr_issue or i["status"] == "active":
            bad.append(i)
    return bad


_ROUTE_DEST = re.compile(r"(?i:default)|\d{1,3}(?:\.\d{1,3}){0,3}(?:/\d{1,2})?|[0-9A-Fa-f:]*:[0-9A-Fa-f:]*(?:%[A-Za-z0-9]+)?(?:/\d{1,3})?")


def parse_routes(text):
    """Strict `netstat -rn` grammar. Returns data rows (destination, gateway, flags, netif). Malformed rows raise."""
    if not isinstance(text, str) or not text.strip():
        raise TelemetryError("MALFORMED", "routing output empty")
    rows, seen_header = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line in ("Routing tables", "Internet:", "Internet6:"):
            continue
        tok = line.split()
        if tok[0] == "Destination":
            if tok[:4] != ["Destination", "Gateway", "Flags", "Netif"]:
                raise TelemetryError("MALFORMED", "route table header")
            seen_header = True
            continue
        if not seen_header:
            raise TelemetryError("MALFORMED", "route row before header")
        if len(tok) not in (4, 5) or not re.fullmatch(r"[A-Za-z0-9]+", tok[2]) or not re.fullmatch(r"[A-Za-z0-9_.-]+", tok[3]) or not _ROUTE_DEST.fullmatch(tok[0]):
            raise TelemetryError("MALFORMED", "route row")
        rows.append(tuple(tok[:4]))
    if not seen_header:
        raise TelemetryError("MALFORMED", "no route table header")
    return rows


def default_routes(rows: list) -> list:
    return [r for r in rows if r[0].lower() == "default"]


_ADDR_PORT = re.compile(r"^(.+)\.(\d+|\*)$")


def _classify_sock_addr(a: str) -> str:
    """'wildcard' | 'loopback' | 'external'. Raises on unparsable syntax."""
    m = _ADDR_PORT.match(a)
    if not m:
        raise TelemetryError("MALFORMED", "socket address")
    host = m.group(1)
    if host == "*":
        return "wildcard"
    if host == "localhost" or host == "::1":
        return "loopback"
    if ":" in host:
        if not re.fullmatch(r"[0-9A-Za-z:%_.-]+", host):
            raise TelemetryError("MALFORMED", "ipv6 socket address")
        return "external"                                                       # netstat truncates IPv6; anything but ::1 is treated as external
    try:
        return "loopback" if ipaddress.IPv4Address(host).is_loopback else "external"
    except ValueError:
        raise TelemetryError("MALFORMED", "ipv4 socket address") from None


def parse_sockets(text):
    """Strict `netstat -an` Internet-connections section. Returns [(proto, state, external_bool)]."""
    if not isinstance(text, str) or "Active Internet connections" not in text:
        raise TelemetryError("MALFORMED", "no Internet connections section")
    lines = text.splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith("Active Internet connections"))
    if i + 1 >= len(lines) or not lines[i + 1].lstrip().startswith("Proto"):
        raise TelemetryError("MALFORMED", "no column header")
    rows = []
    for raw in lines[i + 2:]:
        if not raw.strip() or raw.startswith("Active "):
            break
        f = raw.split()
        proto = f[0]
        if proto.startswith("tcp"):
            if len(f) != 6 or not re.fullmatch(r"[A-Z0-9_]+", f[5]):
                raise TelemetryError("MALFORMED", "tcp row")
            state = f[5]
        elif proto.startswith(("udp", "icm")):                     # udp4/udp6/udp46 and ICMP sockets (icm4/icm6): 5 columns, no state
            if len(f) != 5:
                raise TelemetryError("MALFORMED", "udp/icmp row")
            state = "UDP" if proto.startswith("udp") else "ICMP"
        else:
            raise TelemetryError("MALFORMED", "unrecognized protocol row")
        local, foreign = _classify_sock_addr(f[3]), _classify_sock_addr(f[4])
        if proto.startswith("tcp"):
            external = local in ("wildcard", "external") or foreign == "external"      # any TCP listener/connection beyond loopback
        else:
            # UDP: a socket bound to a specific non-loopback address, or connected to a non-loopback peer, is live traffic. A WILDCARD-only UDP bind
            # (e.g. mDNSResponder `*.5353`) exists even with networking disabled and is inert without an addressed interface or route, which the interface
            # and route checks establish -- it is not counted, and UDP absence is NOT claimed.
            external = local == "external" or foreign == "external"
        rows.append((proto, state, external))
    return rows


# =============================================================================== strict filesystem helpers
_scandir = os.scandir          # indirection so tests can simulate transient scan errors


def walk_strict(root: Path) -> tuple:
    """Iterative walk that NEVER silently skips: returns (entries[(rel, lstat)], error_count). Any listing/stat failure increments the error count."""
    entries, errors, stack = [], 0, [""]
    try:
        st = os.lstat(root)
        if not stat.S_ISDIR(st.st_mode):
            return entries, 1
    except Exception:
        return entries, 1
    while stack:
        rel = stack.pop()
        try:
            with _scandir(Path(root) / rel if rel else root) as it:
                children = list(it)
        except Exception:                      # unknown state is unsafe state: any failure (not only OSError) counts
            errors += 1
            continue
        for e in children:
            r = f"{rel}/{e.name}" if rel else e.name
            try:
                st = e.stat(follow_symlinks=False)
            except Exception:
                errors += 1
                continue
            entries.append((r, st))
            if stat.S_ISDIR(st.st_mode):
                stack.append(r)
    return entries, errors


def _kind(st) -> str:
    m = st.st_mode
    for name, fn in (("file", stat.S_ISREG), ("dir", stat.S_ISDIR), ("symlink", stat.S_ISLNK), ("fifo", stat.S_ISFIFO), ("socket", stat.S_ISSOCK),
                     ("blockdev", stat.S_ISBLK), ("chardev", stat.S_ISCHR)):
        if fn(m):
            return name
    return "other"


def stat_ok(st, *, allow_root: bool = False) -> bool:
    """Ownership/permission sanity (pure; tests pass mocked metadata): owned by the current user (optionally root), no group/other write, no setuid/setgid."""
    uid_ok = st.st_uid == os.geteuid() or (allow_root and st.st_uid == 0)
    return bool(uid_ok and not (st.st_mode & 0o022) and not (st.st_mode & (stat.S_ISUID | stat.S_ISGID)))


def _hash_fd(path: Path) -> tuple:
    """(sha256, size) of a regular file opened without following symlinks or blocking; raises OSError on anything unusual."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_HASHED_BYTES:
            raise OSError("not a single-link regular file within bounds")
        h = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as f:
            h.update(f.read(MAX_HASHED_BYTES + 1))
        return h.hexdigest(), st.st_size
    finally:
        os.close(fd)


# =============================================================================== code manifest
def build_code_manifest(code_root: Path) -> dict:
    """Reads the tree strictly and returns {'v':1,'files':{rel:{'sha256','size'}}}. Raises on any anomaly (symlink, special file, hardlink, error)."""
    entries, errors = walk_strict(Path(code_root))
    if errors:
        raise OSError("traversal errors; refusing to build a manifest")
    files = {}
    for rel, st in entries:
        k = _kind(st)
        if k == "dir":
            continue
        if k != "file" or st.st_nlink != 1:
            raise OSError("anomalous filesystem object; refusing to build a manifest")
        sha, size = _hash_fd(Path(code_root) / rel)
        files[rel] = {"sha256": sha, "size": size}
    return {"v": 1, "files": dict(sorted(files.items()))}


def _strict_loads(text: str):
    def hook(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate key")
        return dict(pairs)
    return json.loads(text, object_pairs_hook=hook)


def load_code_manifest(path, pinned_sha256) -> tuple:
    """Returns (manifest|None, problem|None). Digest must match the out-of-band pin; policy paths only; strict JSON."""
    if path is None or not pinned_sha256:
        return None, "code manifest and its pinned SHA-256 are both mandatory"
    if not isinstance(pinned_sha256, str) or not SUM_RE.match(pinned_sha256.lower()):
        return None, "pinned manifest digest malformed"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_HASHED_BYTES:
                return None, "code manifest is not a bounded regular file"
            with os.fdopen(fd, "rb", closefd=False) as f:
                raw = f.read()
        finally:
            os.close(fd)
    except OSError:
        return None, "code manifest unreadable"
    if hashlib.sha256(raw).hexdigest() != pinned_sha256.lower():
        return None, "code manifest digest does not match the pinned value"
    try:
        m = _strict_loads(raw.decode())
        if not isinstance(m, dict) or set(m) != {"v", "files"} or m["v"] != 1 or not isinstance(m["files"], dict) or not m["files"]:
            raise ValueError("shape")
        for rel, meta in m["files"].items():
            if not isinstance(rel, str) or not isinstance(meta, dict) or set(meta) != {"sha256", "size"} or not SUM_RE.match(str(meta["sha256"])) \
                    or not isinstance(meta["size"], int) or isinstance(meta["size"], bool):
                raise ValueError("entry")
    except Exception:
        return None, "code manifest malformed (strict JSON required)"
    outside = [r for r in m["files"] if r not in ROLE_CODE_ALLOWLIST and r not in ROLE_BYTECODE_ALLOWED]
    if outside:
        return None, f"code manifest lists {len(outside)} path(s) outside the fixed role policy"
    return m, None


def check_code_root(code_root, manifest) -> tuple:
    """Returns (status, detail). FAIL_CLOSED if the tree cannot be completely and safely read; FAIL if it differs from the manifest."""
    entries, errors = walk_strict(Path(code_root))
    if errors:
        return FAIL_CLOSED, f"{errors} traversal error(s); the complete tree could not be established"
    wanted = set(manifest["files"])
    all_parents = set()
    for r in wanted:
        p = Path(r).parent
        while str(p) not in (".", ""):
            all_parents.add(str(p)); p = p.parent
    odd = [k for k in (_kind(st) for _, st in entries) if k not in ("file", "dir")]
    if odd:
        return FAIL_CLOSED, f"{len(odd)} symlink/special filesystem object(s) in the code root"
    unknown_files = unknown_dirs = mismatch = hardlinks = badperm = bytecode = unreadable = 0
    seen = set()
    for rel, st in entries:
        k = _kind(st)
        if k == "dir":
            if rel not in all_parents:
                unknown_dirs += 1
            if not stat_ok(st, allow_root=True):
                badperm += 1
            continue
        seen.add(rel)
        if (rel.endswith((".pyc", ".pyo")) or "__pycache__" in rel.split("/")) and rel not in wanted:
            bytecode += 1
            continue
        if rel not in wanted:
            unknown_files += 1
            continue
        if st.st_nlink != 1:
            hardlinks += 1                      # a definite violation; do not hash (and do not let the hash refusal escalate it)
            continue
        if not stat_ok(st, allow_root=True):
            badperm += 1
        try:
            sha, size = _hash_fd(Path(code_root) / rel)
        except OSError:
            unreadable += 1
            continue
        if sha != manifest["files"][rel]["sha256"] or size != manifest["files"][rel]["size"]:
            mismatch += 1
    missing = len(wanted - seen)
    if unreadable:
        return FAIL_CLOSED, f"{unreadable} manifest file(s) could not be hashed"
    bad = unknown_files + unknown_dirs + mismatch + hardlinks + badperm + bytecode + missing
    return (FAIL if bad else PASS), (f"{unknown_files} unknown file(s), {unknown_dirs} unknown dir(s), {mismatch} hash/size mismatch(es), {missing} missing, "
                                     f"{hardlinks} hardlink(s), {badperm} unsafe owner/mode, {bytecode} unlisted bytecode (names only; matches manifest "
                                     f"{'exactly' if not bad else 'NOT'}; no provenance claim)")


def check_role_state(role: str, role_state_dir) -> tuple:
    entries, errors = walk_strict(Path(role_state_dir))
    if errors:
        return FAIL_CLOSED, f"{errors} traversal error(s); the complete state could not be established"
    odd = [k for k in (_kind(st) for _, st in entries) if k not in ("file", "dir")]
    if odd:
        return FAIL_CLOSED, f"{len(odd)} symlink/special filesystem object(s) in the role state"
    bad = unreadable = 0
    for rel, st in entries:
        if _kind(st) != "file":
            continue
        n = os.path.basename(rel).lower()
        hit = any(re.search(p, n) for p in OWNER_KEY_PATTERNS) or any(re.search(p, n) for p in FORBIDDEN_BY_ROLE[role])
        if not hit:
            try:
                fd = os.open(Path(role_state_dir) / rel, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        raise OSError("not regular")
                    head = os.read(fd, 256)
                finally:
                    os.close(fd)
                hit = any(m in head for m in KEY_HEADER_MARKERS)
            except OSError:
                unreadable += 1
        bad += 1 if hit else 0
    if unreadable:
        return FAIL_CLOSED, f"{unreadable} role-state file(s) could not be read"
    return (FAIL if bad else PASS), f"{bad} suspicious file(s) by name or first-256-byte key header; WEAK evidence only (a renamed, encoded or late-header key is not detected)"


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


def canon_volume_name(s: str) -> str:
    """Case-insensitive, NFC-normalized, collision-suffix-aware ('Name 1' == 'Name'). Display labels only; UUIDs are the stable identifier."""
    s = unicodedata.normalize("NFC", str(s)).casefold().strip()
    return re.sub(r"\s+\d+$", "", s)


def normalize_deny_path(p, home) -> str | None:
    """Absolute canonical path, or None. A leading '~/' is expanded against the supplied home; relative, '..'-bearing or empty paths are rejected."""
    if not isinstance(p, (str, os.PathLike)) or not str(p):
        return None
    s = str(p)
    if s == "~" or s.startswith("~/"):
        if home is None:
            return None
        s = str(Path(home)) + s[1:]
    if not os.path.isabs(s) or ".." in Path(s).parts or "~" in Path(s).parts:
        return None
    return os.path.normpath(s)


# =============================================================================== interlock (advisory, same-environment, NOT a security boundary)
def _canon(rec: dict) -> bytes:
    return json.dumps(rec, sort_keys=True, separators=(",", ":")).encode()


def _sum(rec: dict) -> str:
    return hashlib.sha256(_canon({k: v for k, v in rec.items() if k != "sum"})).hexdigest()


def _read_state_file(p: Path) -> str:
    """Race-safe read: open without following symlinks or blocking, then check the OPEN descriptor (regular, single link, our owner, not group/other
    writable)."""
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("not a regular file")
        if st.st_nlink != 1:
            raise ValueError("hard-linked")
        if not stat_ok(st):
            raise ValueError("unsafe owner or mode")
        with os.fdopen(fd, "rb", closefd=False) as f:           # bytes, then decode: text mode would silently translate \r\n and hide non-canonical input
            return f.read(MAX_HASHED_BYTES).decode("utf-8")
    finally:
        os.close(fd)


def init_state(state_dir: Path) -> str:
    """Explicit owner/operator action that creates a NEW interlock directory (0700) for this environment. Refuses to touch anything existing."""
    state_dir = Path(state_dir)
    if os.path.lexists(state_dir):
        raise FileExistsError("state directory already exists; refusing to re-initialize")
    state_dir.mkdir(parents=True, mode=0o700)
    env_id = secrets.token_hex(16)
    for name, body in (("INIT.json", {"v": 2, "env_id": env_id}), ("HEAD.json", {"v": 2, "env_id": env_id, "seq": 0, "sum": ZERO}), ("receipts.jsonl", None)):
        fd = os.open(state_dir / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
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
    if not stat_ok(st):
        return ["state directory has an unsafe owner or mode (must be owned by the current user and not group/other-writable)"], recs
    try:
        names = set(os.listdir(d))
    except OSError:
        return ["state directory cannot be listed"], recs
    if names != STATE_FILES:
        return [f"state directory must contain exactly the interlock files ({len(names - STATE_FILES)} unexpected, {len(STATE_FILES - names)} missing; "
                f"a stale or planted temporary file also fails here)"], recs
    try:
        init = _strict_loads(_read_state_file(d / "INIT.json"))
        head = _strict_loads(_read_state_file(d / "HEAD.json"))
        raw = _read_state_file(d / "receipts.jsonl")
    except Exception as e:
        return [f"INIT/HEAD/receipts unreadable, unsafe or malformed ({type(e).__name__})"], recs
    if set(init) != {"v", "env_id"} or init.get("v") != 2 or not ENV_ID_RE.match(str(init.get("env_id"))):
        problems.append("INIT malformed")
    if set(head) != {"v", "env_id", "seq", "sum"} or head.get("v") != 2 or not isinstance(head.get("seq"), int) or isinstance(head.get("seq"), bool) \
            or not SUM_RE.match(str(head.get("sum"))):
        problems.append("HEAD malformed")
    if problems:
        return problems, recs
    if head["env_id"] != init["env_id"]:
        return ["HEAD/INIT environment id mismatch"], recs
    if "\r" in raw:
        return ["receipts contain carriage returns (non-canonical)"], recs
    if raw and not raw.endswith("\n"):
        return ["receipts truncated (no final newline)"], recs
    prev = ZERO
    for i, line in enumerate(raw.split("\n")[:-1] if raw else [], 1):
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
    fd = os.open(d / "receipts.jsonl", os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or not stat_ok(st):
            raise PermissionError("receipts file is not a safe regular file")
        os.write(fd, (json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp = d / f".HEAD.{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)        # exclusive create; never follows a planted symlink
    try:
        os.write(fd, json.dumps({"v": 2, "env_id": env_id, "seq": rec["seq"], "sum": rec["sum"]}, sort_keys=True).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, d / "HEAD.json")                                                       # same-directory atomic replace
    return rec


# =============================================================================== the gate
def _src(host: dict, key: str, parser=None):
    """Returns (value, None) for a verified source or (None, reason) when it is unavailable/malformed. Missing key / None are UNAVAILABLE, never 'empty'."""
    tele = host.get("telemetry", {})
    if key not in host or host[key] is None:
        return None, tele.get(key, "UNAVAILABLE") if tele.get(key, "OK") != "OK" else "UNAVAILABLE"
    if tele.get(key, "OK") != "OK":
        return None, tele[key]
    if parser is None:
        return host[key], None
    try:
        return parser(host[key]), None
    except TelemetryError as e:
        return None, e.reason
    except Exception:
        return None, "MALFORMED"


def evaluate(role, *, host: dict, state_dir=None, role_state_dir=None, code_root=None, code_manifest=None, code_manifest_sha256=None, deny_paths=None,
             deny_volumes=None, deny_volume_uuids=None, workspaces=None, process_allowlist=None) -> dict:
    """Pure given its inputs. {check: {"status": PASS|FAIL|FAIL_CLOSED, "ok": bool, "detail": str}}. Details are counts/categories only -- never paths,
    file names, process command lines or contents."""
    if role not in ROLES:
        raise ValueError(role)
    r = {}
    deny_paths, deny_volumes, deny_volume_uuids = list(deny_paths or []), list(deny_volumes or []), list(deny_volume_uuids or [])
    # -- telemetry sources (mandatory)
    names, why_names = _src(host, "processes", parse_processes)
    cmds, why_cmds = _src(host, "cmdlines", parse_cmdlines)
    env, why_env = _src(host, "env", parse_env)
    home_v, why_home = _src(host, "home")
    home = Path(home_v) if home_v is not None else None
    ifs, why_if = _src(host, "ifconfig", parse_interfaces)
    r4, why_r4 = _src(host, "routes4", parse_routes)
    r6, why_r6 = _src(host, "routes6", parse_routes)
    socks, why_sock = _src(host, "sockets", parse_sockets)
    boot, why_boot = _src(host, "boot_id")
    boot_ok = isinstance(boot, str) and bool(UUID_RE.match(boot))
    need_vol = bool(deny_volumes or deny_volume_uuids)
    vols, why_vols = _src(host, "volumes") if need_vol else (None, None)
    disks, why_disks = _src(host, "disks") if need_vol else (None, None)
    failed = {k: w for k, w in (("processes", why_names), ("cmdlines", why_cmds), ("env", why_env), ("home", why_home), ("ifconfig", why_if),
                                ("routes4", why_r4), ("routes6", why_r6), ("sockets", why_sock), ("boot_id", why_boot)) if w}
    if not boot_ok and "boot_id" not in failed:
        failed["boot_id"] = "MALFORMED"
    if need_vol:
        failed.update({k: w for k, w in (("volumes", why_vols), ("disks", why_disks)) if w})
    r["telemetry_complete"] = _res(PASS, "all mandatory host telemetry sources verified") if not failed else \
        _fc(f"{len(failed)} mandatory source(s) not verified: " + ", ".join(f"{k}={w}" for k, w in sorted(failed.items())))

    def unverified(*keys):
        return ", ".join(f"{k}={failed[k]}" for k in keys if k in failed)
    # -- boot session
    r["boot_session_identified"] = _res(PASS, "per-boot UUID obtained") if boot_ok else _fc("kern.bootsessionuuid " + (failed.get("boot_id") or "MALFORMED"))
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
    if names is None or env is None or home is None:
        r["container_runtime_absent"] = _fc("cannot verify: " + unverified("processes", "env", "home"))
    else:
        hits = [n for n in names if _matches(n, RUNTIME_TOKENS, RUNTIME_PREFIXES)]
        socks_p = [p for p in host.get("runtime_sockets_abs", RUNTIME_SOCKETS_ABS) if os.path.lexists(p)] + [p for p in RUNTIME_SOCKETS_HOME if os.path.lexists(home / p)]
        dirs = [p for p in RUNTIME_INSTALL_DIRS_HOME if os.path.lexists(home / p)]
        envs = [e for e in RUNTIME_ENV if env.get(e)]
        bad = len(hits) + len(socks_p) + len(dirs) + len(envs)
        r["container_runtime_absent"] = _res(FAIL if bad else PASS, f"{len(hits)} runtime process(es), {len(socks_p)} runtime socket(s), {len(dirs)} runtime install dir(s), {len(envs)} runtime env var(s); NOT exhaustive")
    if process_allowlist is not None:
        if names is None:
            r["process_allowlist_respected"] = _fc("process list unverified")
        else:
            extra = sorted({n for n in names if n not in set(process_allowlist)})
            r["process_allowlist_respected"] = _res(FAIL if extra else PASS, f"{len(extra)} running process name(s) outside the supplied allowlist")
    # -- network (one-shot; point-in-time)
    if ifs is None:
        r["network_interfaces_disabled"] = _fc("ifconfig " + (why_if or "UNAVAILABLE"))
    else:
        bad = interface_violations(ifs)
        kinds = sorted({re.sub(r"\d+$", "", i["name"]) for i in bad})
        r["network_interfaces_disabled"] = _res(FAIL if bad else PASS, f"{len(bad)} interface(s) with a non-loopback address or active status (kinds: {','.join(kinds) or 'none'})")
    if r4 is None or r6 is None:
        r["network_no_default_route"] = _fc("routing tables: " + unverified("routes4", "routes6"))
    else:
        d4, d6 = default_routes(r4), default_routes(r6)
        r["network_no_default_route"] = _res(FAIL if (d4 or d6) else PASS, f"{len(d4)} IPv4 / {len(d6)} IPv6 default route(s)")
    if socks is None:
        r["network_no_external_sockets"] = _fc("socket table " + (why_sock or "UNAVAILABLE"))
    else:
        ext = [s for s in socks if s[2]]
        udp = sum(1 for s in ext if s[0].startswith("udp"))
        r["network_no_external_sockets"] = _res(FAIL if ext else PASS, f"{len(ext)} socket(s) bound or connected beyond loopback ({udp} UDP); point-in-time only, not proof that nothing could communicate")
    # -- cloud sync / agent: process vs exposure
    if names is None:
        r["cloud_sync_process_absent"] = _fc("process list unverified")
    else:
        sync = [n for n in names if _matches(n, SYNC_PROC_TOKENS)]
        r["cloud_sync_process_absent"] = _res(FAIL if sync else PASS, f"PROCESS_{'RUNNING' if sync else 'NOT_RUNNING'} ({len(sync)} third-party sync client process(es))")
    if names is None or cmds is None:
        r["agent_process_absent"] = _fc("cannot verify: " + unverified("processes", "cmdlines"))
    else:
        agent = [n for n in names if _matches(n, AGENT_PROC_TOKENS)]
        cmd_hits = [c for c in cmds if any(m in c.lower() for m in AGENT_CMDLINE_MARKERS)]
        r["agent_process_absent"] = _res(FAIL if (agent or cmd_hits) else PASS, f"PROCESS_{'RUNNING' if (agent or cmd_hits) else 'NOT_RUNNING'} ({len(agent)} name match(es), {len(cmd_hits)} command-line match(es))")
    if home is None:
        r["cloud_sync_residual_exposure_absent"] = _fc("home directory unverified")
        r["agent_residual_exposure_absent"] = _fc("home directory unverified")
    else:
        sync_present = [p for p in SYNC_ROOTS_HOME if _nonempty_dir(home / p)]
        r["cloud_sync_residual_exposure_absent"] = _res(FAIL if sync_present else PASS, ("RESIDUAL_EXPOSURE_PRESENT" if sync_present else "NO_RESIDUAL_EXPOSURE_DETECTED") + f" ({len(sync_present)} of {len(SYNC_ROOTS_HOME)} known synchronized location(s) hold data; sync scope not established)")
        agent_present = [p for p in AGENT_STORES_HOME if _nonempty_dir(home / p)]
        r["agent_residual_exposure_absent"] = _res(FAIL if agent_present else PASS, ("RESIDUAL_EXPOSURE_PRESENT" if agent_present else "NO_RESIDUAL_EXPOSURE_DETECTED") + f" ({len(agent_present)} of {len(AGENT_STORES_HOME)} known agent transcript/index/session/recovery location(s) hold data)")
    ws = [Path(w) for w in (workspaces or [])] + ([Path(role_state_dir)] if role_state_dir else []) + ([Path(state_dir)] if state_dir else [])
    if not ws or home is None:
        r["workspace_not_in_synced_or_user_documents_path"] = _fc("no workspace/state directory supplied" if not ws else "home directory unverified")
    else:
        roots = [(home / p) for p in SYNC_ROOTS_HOME + SYNC_WORKSPACE_FORBIDDEN_HOME]
        inside = 0
        for w in ws:
            rp = Path(os.path.realpath(w))
            if any(rp == Path(os.path.realpath(x)) or Path(os.path.realpath(x)) in rp.parents for x in roots):
                inside += 1
        r["workspace_not_in_synced_or_user_documents_path"] = _res(FAIL if inside else PASS, f"{inside} of {len(ws)} workspace/state dir(s) under a synchronized or Desktop/Documents location")
    # -- other role's storage unavailable (advisory evidence only; physical detachment is an owner procedure)
    if not (deny_paths or deny_volumes or deny_volume_uuids):
        r["other_role_storage_unavailable"] = _fc("no deny-listed path, volume or volume UUID supplied (the other role's storage must be named explicitly)")
    else:
        norm = [normalize_deny_path(p, home) for p in deny_paths]
        if any(n is None for n in norm):
            r["other_role_storage_unavailable"] = _fc(f"{sum(n is None for n in norm)} deny path(s) are not absolute canonical paths (relative, '..' or unresolved '~')")
        elif need_vol and (vols is None or disks is None):
            r["other_role_storage_unavailable"] = _fc("volume telemetry unverified: " + unverified("volumes", "disks"))
        else:
            present = sum(1 for n in norm if os.path.lexists(n))
            if need_vol:
                want_names = {canon_volume_name(v) for v in deny_volumes}
                want_uuids = {u.casefold() for u in deny_volume_uuids}
                seen_names = {canon_volume_name(v) for v in vols} | {canon_volume_name(d["name"]) for d in disks if d["name"]} | \
                             {canon_volume_name(os.path.basename(d["mount"])) for d in disks if d["mount"]}
                seen_uuids = {d["uuid"].casefold() for d in disks if d["uuid"]}
                present += len(want_names & seen_names) + len(want_uuids & seen_uuids)
            total = len(norm) + len(deny_volumes) + len(deny_volume_uuids)
            r["other_role_storage_unavailable"] = _res(FAIL if present else PASS, f"{present} of {total} deny-listed path(s)/volume(s)/UUID(s) present, attached or mounted (advisory name/UUID evidence; NOT proof of physical disconnection)")
    # -- role code root equals a hash-pinned manifest
    manifest, why_man = load_code_manifest(code_manifest, code_manifest_sha256)
    if code_root is None:
        r["role_code_root_matches_manifest"] = _fc("code root not supplied")
    elif why_man:
        r["role_code_root_matches_manifest"] = _fc(why_man)
    else:
        st_, detail = check_code_root(code_root, manifest)
        r["role_code_root_matches_manifest"] = _res(st_, detail)
    # -- weak owner-key / other-role material scan in the role's own state
    if role_state_dir is None or not Path(role_state_dir).is_dir() or Path(role_state_dir).is_symlink():
        r["role_state_forbidden_material_WEAK"] = _fc("role state directory not supplied, missing, or not a plain directory")
    else:
        st_, detail = check_role_state(role, role_state_dir)
        r["role_state_forbidden_material_WEAK"] = _res(st_, detail)
    return r


def gate_passes(results: dict) -> bool:
    return bool(results) and all(v["status"] == PASS for v in results.values())


def begin(role: str, state_dir: Path, boot_id: str, results: dict) -> dict:
    if not gate_passes(results):
        raise PermissionError("phase gate did not pass; refusing to record a phase start")
    return append_receipt(state_dir, role, boot_id)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("init", "build-manifest", "check", "begin"))
    ap.add_argument("--role", choices=ROLES)
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--role-state-dir", type=Path)
    ap.add_argument("--code-root", type=Path)
    ap.add_argument("--code-manifest", type=Path)
    ap.add_argument("--code-manifest-sha256")
    ap.add_argument("--deny-path", action="append", default=[])
    ap.add_argument("--deny-volume", action="append", default=[])
    ap.add_argument("--deny-volume-uuid", action="append", default=[])
    ap.add_argument("--workspace", action="append", default=[])
    ap.add_argument("--process-allowlist", type=Path)
    a = ap.parse_args(argv[1:])
    if a.cmd == "init":
        if not a.state_dir:
            print("FAIL_CLOSED --state-dir required"); return 1
        init_state(a.state_dir); print("INITIALIZED"); return 0
    if a.cmd == "build-manifest":
        if not a.code_root:
            print("FAIL_CLOSED --code-root required"); return 1
        try:
            m = build_code_manifest(a.code_root)
        except OSError as e:
            print("FAIL_CLOSED", e); return 1
        txt = json.dumps(m, sort_keys=True, indent=1)
        print(txt); print(f"# SHA-256 of the manifest bytes above (pin this out-of-band): {hashlib.sha256(txt.encode()).hexdigest()}", file=sys.stderr)
        return 0
    if not a.role:
        print("FAIL_CLOSED --role required"); return 1
    allow = None
    if a.process_allowlist:
        try:
            allow = [l.strip() for l in a.process_allowlist.read_text().splitlines() if l.strip()]
        except OSError:
            print("FAIL_CLOSED process allowlist unreadable"); return 1
    host = collect_host()
    res = evaluate(a.role, host=host, state_dir=a.state_dir, role_state_dir=a.role_state_dir, code_root=a.code_root, code_manifest=a.code_manifest,
                   code_manifest_sha256=a.code_manifest_sha256, deny_paths=a.deny_path, deny_volumes=a.deny_volume, deny_volume_uuids=a.deny_volume_uuid,
                   workspaces=a.workspace, process_allowlist=allow)
    for k, v in res.items():
        print(f"{v['status']:11} {k} -- {v['detail']}")
    ok = gate_passes(res)
    if a.cmd == "begin" and ok:
        begin(a.role, a.state_dir, host["boot_id"], res)
    print("GATE_PASSES" if ok else "GATE_FAILS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
