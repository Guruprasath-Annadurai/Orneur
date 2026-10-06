#!/usr/bin/env python3
"""Genesis V2 Tier0-S (Sequential Sovereign Isolation) -- phase gate v4. REDUCED-ASSURANCE, SOFTWARE-LEVEL, ONE-SHOT, ADVISORY.

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

FAIL-CLOSED RULE ("unknown state is unsafe state"): every security-relevant input must be supplied, every host query must succeed, and the gate passes only if
every check is PASS. TWO SEPARATE QUESTIONS ARE ANSWERED AND NEVER CONFLATED:
  (1) STRUCTURAL VALIDITY. Each command output goes through a parser that RAISES on any shape it does not recognise (newline termination, ASCII-only, exact column
      headers, no data after a blank line, terminated sections where one exists, loopback floors). A rejected source is FAIL_CLOSED with its reason. This shows only
      that the received text is structurally well-formed and properly terminated. It does NOT prove that well-formed telemetry is complete or true.
  (2) COMPLETENESS. Exit status 0 plus well-formed output does not establish it. macOS can return a REDUCED VIEW from its own trusted tools (observed: the Internet
      socket section, neighbour routes and every hardware address vanish, with exit status 0, when the process lineage includes a non-Apple executable such as a
      Homebrew or uv-managed Python). Completeness is therefore tested SEPARATELY, against sources the reduced view does not touch (see COMPLETENESS below). A view that
      is structurally valid but whose completeness cannot be shown is STRUCTURALLY_VALID_BUT_COMPLETENESS_UNPROVEN and becomes FAIL_CLOSED with the sanitized reason
      TELEMETRY_COMPLETENESS_UNPROVEN.

ENFORCED (checked once, at start, by this code):  the sixteen checks returned by evaluate(); telemetry shape and the completeness comparisons below; the hash-pinned role-code manifest;
descriptor-relative tree traversal; deny-list configuration validity; the advisory interlock's hash chain and exact file set; serialized interlock appends.
ADVISORY (forgeable by any same-user writer): the interlock log; volume matching by label (spoofable) or UUID (only as good as `diskutil`); the name/header scan
of the role state (WEAK). PROCEDURAL (owner, not checked): cold boot, physical detachment, keeping the network off for the whole phase, out-of-band transcription
of the manifest pin, every NOT_CHECKED / OWNER_PROCEDURE channel in the design doc's persistence table. UNPROVEN: that a real Tier0-S environment can pass, mutual
invisibility of the two roles, log hygiene, and anything involving a malicious owner, root or kernel.

MANDATORY HOST TELEMETRY (each is a distinct source; an unavailable source is FAIL_CLOSED and reported with its reason):
  processes (`ps -axo comm=`), cmdlines (`ps -axo command=`), env (this process's environment, must be a str->str mapping; EMPTY is a legitimately verified
  value; it describes only the gate process), home (the user's home directory from the PASSWORD DATABASE for the effective UID -- never $HOME -- which must be an
  existing, canonical, non-symlink directory owned by that user), ifconfig (`ifconfig -a`) cross-checked against ifnames (`ifconfig -l`) AND against the independent
  inventories ifaddrs (libc getifaddrs) and ifindex (libc if_nameindex) and linkstate (in-process SIOCGIFMEDIA), routes4/routes6 (`netstat -rn -f inet|inet6`), sockets (`netstat -an`) compared with
  pcbcounts (kernel PCB counters read before and after it), boot_id (`kern.bootsessionuuid`), and -- when any deny volume/UUID is supplied -- volumes (/Volumes,
  non-empty list of plain names) and disks (`diskutil list -plist`, validated records). Every tool is invoked by ABSOLUTE system path (/bin/ps, /sbin/ifconfig,
  /usr/sbin/netstat, /usr/sbin/sysctl, /usr/sbin/diskutil), never through PATH, in a clean locale/environment; the tool and its directories must be root-owned,
  not group/other-writable, and the tool a regular file. A verified-empty cmdline list is IMPOSSIBLE on a live system (it must contain launchd), so an empty or
  launchd-less cmdline set is treated as unavailable. Telemetry failure reasons are distinguished: UNAVAILABLE, PERMISSION_DENIED, UNSUPPORTED, MALFORMED, TELEMETRY_COMPLETENESS_UNPROVEN, and -- for an UNEXPECTED exception
  inside a collector or parser, i.e. a defect in the gate rather than a host condition -- PARSER_DEFECT:<ExceptionClass> / COLLECTOR_DEFECT:<ExceptionClass> (the class name only,
  never the message). Every one of them is FAIL_CLOSED; the defect forms make a gate defect distinguishable from a host condition.
  WHAT THE STRUCTURAL CHECKS PROVE AND DO NOT PROVE: ifconfig lists >= 2 interfaces including a loopback carrying 127/8 and exactly the names `ifconfig -l` reports; each
  route table has its own family section, the exact column header and at least one loopback-interface row; the socket output begins and is sectioned by `Active ...`
  headers, every examined section is followed by another section, and no row follows a blank line. They show that the output was not obviously truncated or cut inside
  those structures. They do NOT prove that no row was removed from within a well-formed table, and exit status 0 is never treated as completeness.

COMPLETENESS (independent of the command parsers; every comparison source is mandatory, and a missing, malformed or implausible one is FAIL_CLOSED):
  * interfaces: `ifconfig -a` must agree with libc getifaddrs() (read in-process through ctypes) and libc if_nameindex() on the name set, the UP and LOOPBACK flags and the
    IPv4/IPv6 address sets. In the reduced view both libc inventories were observed unfiltered. They are only PARTIALLY independent of ifconfig (the same kernel interface
    list). RUNNING and the other flags are NOT compared.
  * link state: every interface's `status:` line is cross-checked against the kernel's own answer, read IN-PROCESS with the SIOCGIFMEDIA ioctl (the answer `ifconfig` renders as
    `status:`). This is independent of the ifconfig TOOL, its output and its parsing, but it is the SAME KERNEL ANSWER, so a kernel that misreports link state is outside
    what this can detect. Per interface: active / inactive (valid media status), no_media (EOPNOTSUPP: loopback, tunnels), status_invalid (media exists, status not valid),
    vanished. EXPLICIT LINK POLICY (non-loopback interfaces): an independent 'active' link is a violation whatever ifconfig printed; ifconfig's `status:` must equal the
    independent state (active/inactive) or be absent for no_media/status_invalid, else the interface view is incomplete (FAIL_CLOSED); an UP, ADDRESSED interface whose
    independent state is status_invalid has a link state that cannot be established and is FAIL_CLOSED (availability is preferred over false isolation); an unavailable
    or unreadable link-state source is FAIL_CLOSED. Inactive and no_media interfaces are decided by their addresses. Whether a physical link is really up beyond what
    the kernel reports is not established.
  * sockets: parsed TCP and raw/ICMP rows are compared with the kernel PCB counters net.inet.tcp.pcbcount and net.inet.raw.pcbcount, read BEFORE and AFTER the socket
    query (the counters were observed unfiltered). Per class: rows >= max(1, floor(0.75 * lower counter)) and rows <= higher counter + 12. WHAT THAT ESTABLISHES, EXACTLY:
    the disappearance of the whole table is always detected whenever a counter is >= 1. It is a PLAUSIBILITY HEURISTIC, NOT row-by-row completeness: on a busy host
    roughly a quarter to a third of the rows can disappear and still be accepted, and on a host with only a handful of PCBs a MAJORITY of the rows can (for example 4 of 6
    at a counter of 3). A single listener can always be hidden inside the band. It says NOTHING about UDP: the kernel UDP counter equals the kernel pcblist record count, but
    `netstat` omits some UDP PCBs by design and the omitted number is not stable, so no trustworthy UDP relationship exists. UDP rows are therefore observation-only (they
    can add a failure, never a pass), UDP completeness is unproven and UDP absence is not claimed. Under heavy connection churn the counter exceeds the listed rows and the
    band fails closed (a false failure, never a false pass).
  * routes: NO independent route source exists (the raw kernel route dump is filtered identically to `netstat -rn`), so the route table's completeness is NEVER claimed.
    The network verdict rests on the interface ADDRESSES and the cross-checked LINK STATE; the route table can only add a failure, and it must contain a route for every
    UP, addressed, non-loopback interface of the independent inventory (otherwise COMPLETENESS is unproven).
  * reduced-view signature: any `ether` line equal to 02:00:00:00:00:00 (the value substituted for every hardware address in the reduced view; observed 12 of 12 reduced,
    0 of 12 full) is an INDICATOR, not proof. A host that really assigns that value fails closed, which is safe. When this signature, or a socket-counter inconsistency, is
    present, ifconfig, routes4, routes6 and sockets are ALL treated as TELEMETRY_COMPLETENESS_UNPROVEN, because they share the filtering layer. A violation still
    visible in a reduced view remains a violation (FAIL).
  * RUN THE GATE FROM AN UNFILTERED LINEAGE (for example the Apple-signed /usr/bin/python3 started from Terminal). Which ancestor property triggers the reduced view is NOT
    identified; every Apple-signed interpreter tested gave the full view and every non-Apple one tested (Homebrew node, uv, uv-managed Python, including their Apple-signed
    children) gave the reduced view. The gate does not guess the lineage; it tests the symptoms above.

MANDATORY CONFIGURATION: interlock state dir (--state-dir), the role's own state dir to scan (--role-state-dir), role code root (--code-root), a code manifest
(--code-manifest) AND its SHA-256 pinned out-of-band (--code-manifest-sha256), and at least one deny-listed path / volume / volume UUID naming the other
role's storage. Missing configuration is FAIL_CLOSED. Deny configuration is validated: UUIDs must be well-formed and non-duplicated, labels non-empty without
control/format characters or confusable-script letters, paths absolute and canonical. Volume matching by label alone is reported as LABEL_ONLY (weaker, advisory);
prefer --deny-volume-uuid. The check is named configured_other_role_storage_not_detected and is ADVISORY: PASS means only that the CONFIGURED identifiers were not observed. A well-formed UUID that is simply wrong matches nothing and cannot be detected.

PROCESS ABSENCE != EXPOSURE ABSENCE: a stopped sync/agent process does not satisfy the residual-exposure checks. Those look (existence and non-emptiness
only, never contents or names) at known synchronized paths and known agent transcript/index/session/recovery stores under the TRUSTED home. NO_RESIDUAL_EXPOSURE_DETECTED
means "none of the known locations has data", not a proof that no exposure exists.

CODE ALLOWLIST SEMANTICS: the role code root must equal a MANIFEST (relative path, SHA-256, size) exactly, every manifest path must be inside the fixed role
policy (ROLE_CODE_ALLOWLIST), and the manifest's own SHA-256 must match a value pinned out-of-band. This proves: the files under THIS root are byte-identical to
that manifest, nothing else is there, none is a symlink/hardlink/special file, none is group/other-writable, and no unlisted bytecode exists. It does NOT
prove the manifest is the reviewed one unless the pin was transcribed from a reviewed source, does not cover anything outside the root, and is not
cryptographic provenance. Path names alone are never treated as proof of Qualification absence. The tree is read descriptor-relative (O_DIRECTORY|O_NOFOLLOW at
every level, members opened relative to the open directory descriptor and compared with the listed device/inode), so a directory or file swapped after it was
listed is detected. RESIDUAL: the ancestors of the root are resolved normally; hashing is point-in-time; a same-authority attacker who can replace BOTH the
manifest and the pin passes.

MANIFEST WORKFLOW: `build-manifest` emits ONE canonical byte sequence (sorted keys, indent 1, one trailing newline). The pin is the SHA-256 of exactly those bytes.
Without --out they go to stdout (so `> M` produces a file whose digest is the pin; the pin is printed to stderr as `MANIFEST_SHA256 <hex>`); with --out they are
written to a new file and the pin is printed to stdout. --pin-out writes `<hex>` plus one newline. The verifier hashes the file bytes as they are and accepts only a 64-hex pin.

INTERLOCK (advisory, same-environment, operator-safety only -- NOT a security isolation boundary): lives INSIDE the currently booted environment's own state
directory (never shared across environments, so it creates no cross-role channel). Non-secret: role, per-boot UUID, sequence, hash chain, environment id.
Anyone who can write the directory can forge it. Appends are serialized with an exclusive flock() on the directory (verification takes a shared lock); a writer that
cannot get the lock fails closed, and the kernel drops the lock when its holder dies (no stale lock). If a writer crashes between the receipt append and the HEAD
replace, receipts and HEAD disagree and every later verification FAILS CLOSED until the owner creates a new interlock directory.

CLI:  init  --state-dir D
      build-manifest --code-root C [--out M] [--pin-out P]   (review the manifest before pinning its SHA-256 out-of-band)
      check --role forge|witness --state-dir D --role-state-dir R --code-root C --code-manifest M --code-manifest-sha256 H
            --deny-path P [--deny-path P ...] [--deny-volume NAME ...] [--deny-volume-uuid UUID ...] [--workspace W ...] [--process-allowlist FILE]
      begin (same as check; on GATE_PASSES appends an interlock entry)
EXIT CODES: 0 = GATE_PASSES; 1 = GATE_FAILS or an EXPECTED operational failure (printed as FAIL_CLOSED ..., no traceback); 3 = an unexpected internal defect (the traceback is
on stderr, the refusal on stdout). An unexpected exception is never swallowed or reported as an ordinary gate failure.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import ipaddress
import json
import os
import plistlib
import pwd
import re
import secrets
import socket
import stat
import struct
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

ROLES = ("forge", "witness")
PASS, FAIL, FAIL_CLOSED = "PASS", "FAIL", "FAIL_CLOSED"
UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\Z")      # \Z, never '$': '$' also matches before a trailing newline
ENV_ID_RE = re.compile(r"^[0-9a-f]{32}\Z")
SUM_RE = re.compile(r"^[0-9a-f]{64}\Z")
ZERO = "0" * 64
MAX_HASHED_BYTES = 16 * 1024 * 1024
STATE_FILES = frozenset({"INIT.json", "HEAD.json", "receipts.jsonl"})
LOCK_TIMEOUT = 5.0                      # seconds to wait for the interlock directory lock before failing closed
MAX_WALK_DEPTH = 64
# Host telemetry tools are NEVER resolved through the ambient PATH. Fixed macOS system locations; each must be a regular, root-owned, non-group/other-writable
# executable (not a symlink) inside root-owned, non-group/other-writable ancestor directories, or the source is not trusted.
SYSTEM_TOOLS = {"ps": "/bin/ps", "ifconfig": "/sbin/ifconfig", "netstat": "/usr/sbin/netstat", "sysctl": "/usr/sbin/sysctl", "diskutil": "/usr/sbin/diskutil"}
TOOL_ENV = {"LC_ALL": "C", "LANG": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}      # clean, locale-stable environment for every host query
_euid = os.geteuid                      # indirection so tests can simulate a different expected user
COMPLETENESS = "TELEMETRY_COMPLETENESS_UNPROVEN"     # sanitized reason: the output is structurally valid but cannot be shown complete => FAIL_CLOSED
MAC_REDACTED = "02:00:00:00:00:00"                   # value macOS substitutes for every hardware address in the reduced telemetry view (an INDICATOR, not proof)
PCB_COUNTERS = {"tcp": "net.inet.tcp.pcbcount", "raw": "net.inet.raw.pcbcount"}      # NO udp: see check_socket_plausibility
PCB_MAX = 10 ** 7                                    # a larger counter is implausible
# Per-class plausibility floors for "parsed socket rows >= ratio * counter": measured on macOS 27.0.1 in the UNFILTERED view as rows/counter = tcp ~0.89-1.12 at idle and light activity (rows
# usually slightly EXCEED the counter) and raw/ICMP exactly 1.00. The floors sit below those measurements; a host measuring lower FAILS CLOSED (availability), never open.
# UDP is deliberately EXCLUDED: the kernel UDP counter equals the kernel pcblist record count, but `netstat` omits some UDP PCBs by design and the omitted number is
# not stable (rows/counter measured 0.77, then 0.35 during a burst of 102 PCBs vs 36 rows), so NO trustworthy UDP relationship exists and none is invented.
PCB_MIN_RATIO = {"tcp": 0.75, "raw": 0.75}
# Upper bound: rows <= higher counter + PCB_MAX_EXCESS. Measured (macOS 27.0.1, ~300 samples, idle and light connection activity): `netstat` lists up to 5-8 MORE TCP
# rows than the counter and never more; under heavy connection churn rows fall far BELOW the counter (rows/counter 0.52 after 1000 short connections; lingering PCBs are
# counted but not all listed). The earlier multiplicative allowance (2x) had no support in any measurement and was removed; +12 leaves ~1.5x margin over the measured
# excess. A counter of 0 therefore still tolerates up to 12 rows: that is the measured constant excess, not an anomaly, and it cannot be tightened without false failures.
PCB_MAX_EXCESS = 12
# Link state: the kernel's SIOCGIFMEDIA answer (the source of `ifconfig`'s `status:` line), queried IN-PROCESS. Measured on macOS 27.0.1: the request is accepted with a
# 40- or 44-byte ifmediareq and rejected (EOPNOTSUPP) with 48 bytes; 40 is used. ifm_status sits at offset 24.
def _iowr(group: str, num: int, size: int) -> int:
    return 0xC0000000 | (size << 16) | (ord(group) << 8) | num


SIOCGIFMEDIA = _iowr("i", 56, 40)
IFM_AVALID, IFM_ACTIVE = 0x1, 0x2
LINK_STATES = ("active", "inactive", "no_media", "status_invalid", "vanished")
IFF_UP, IFF_LOOPBACK = 0x1, 0x8

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


def _defect(kind: str, exc: BaseException) -> str:
    """Sanitized diagnostic for an UNEXPECTED exception inside a collector or parser: the category and the exception CLASS NAME only (never the message, which could carry
    host data). `kind` is PARSER_DEFECT or COLLECTOR_DEFECT. The source still fails closed; the class name makes a gate defect distinguishable from a host condition."""
    name = type(exc).__name__
    return f"{kind}:{name}" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) else kind


# =============================================================================== host queries (fail closed)
def _resolve_tool(name: str) -> str:
    """Absolute path of a fixed system tool, or raises TelemetryError. Never consults PATH. The tool must be a regular file (a symlink is refused), owned by root,
    not group/other-writable and executable, and every ancestor directory must be root-owned and not group/other-writable."""
    path = SYSTEM_TOOLS.get(name)
    if path is None:
        raise TelemetryError("UNSUPPORTED", "tool not in the fixed system-tool table")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise TelemetryError("UNSUPPORTED", "system tool not present at its fixed location") from None
    except PermissionError:
        raise TelemetryError("PERMISSION_DENIED", "system tool not inspectable") from None
    except OSError:
        raise TelemetryError("UNAVAILABLE", "system tool not inspectable") from None
    if not stat.S_ISREG(st.st_mode):
        raise TelemetryError("MALFORMED", "system tool is not a regular file (symlink or other object)")
    if st.st_uid != 0 or (st.st_mode & 0o022) or not (st.st_mode & 0o111):
        raise TelemetryError("MALFORMED", "system tool has an unexpected owner or mode")
    for parent in Path(path).parents:
        try:
            pst = os.lstat(parent)
        except OSError:
            raise TelemetryError("UNAVAILABLE", "system tool directory not inspectable") from None
        if not stat.S_ISDIR(pst.st_mode) or pst.st_uid != 0 or (pst.st_mode & 0o022):
            raise TelemetryError("MALFORMED", "system tool directory has an unexpected type, owner or mode")
    return path


def _run(cmd: list):
    """Returns (status, stdout). status in OK | UNAVAILABLE | PERMISSION_DENIED | UNSUPPORTED | MALFORMED. cmd[0] is a tool NAME from SYSTEM_TOOLS."""
    try:
        argv = [_resolve_tool(cmd[0])] + list(cmd[1:])
    except TelemetryError as e:
        return e.reason, None
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=dict(TOOL_ENV))
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


_DEV_RE = re.compile(r"disk\d+(?:s\d+)*\Z")


def _text_field(d: dict, key: str) -> str:
    v = d.get(key, "")
    if not isinstance(v, str) or "\0" in v:
        raise TelemetryError("MALFORMED", f"disk record field {key}")
    return v


def _parse_disks(blob) -> list:
    """`diskutil list -plist` -> validated records. ANY structural surprise raises TelemetryError (never a bare TypeError/KeyError)."""
    try:
        d = plistlib.loads(blob.encode() if isinstance(blob, str) else blob)
    except Exception:
        raise TelemetryError("MALFORMED", "diskutil output is not a plist") from None
    if not isinstance(d, dict) or not isinstance(d.get("AllDisksAndPartitions"), list):
        raise TelemetryError("MALFORMED", "diskutil plist shape")
    out = []
    for disk in d["AllDisksAndPartitions"]:
        if not isinstance(disk, dict):
            raise TelemetryError("MALFORMED", "disk entry")
        subs = []
        for key in ("Partitions", "APFSVolumes"):
            v = disk.get(key, [])
            if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
                raise TelemetryError("MALFORMED", f"disk {key} shape")
            subs += v
        for item in [disk] + subs:
            if any(k in item for k in ("VolumeName", "VolumeUUID", "MountPoint")):
                out.append({"name": _text_field(item, "VolumeName"), "uuid": _text_field(item, "VolumeUUID"), "dev": _text_field(item, "DeviceIdentifier"),
                            "mount": _text_field(item, "MountPoint")})
    return parse_disk_records(out)


def parse_disk_records(recs) -> list:
    """Strict validation of the disk records handed to the gate (also applied to injected telemetry). A real host always has at least one volume record."""
    if not isinstance(recs, list) or not recs:
        raise TelemetryError("MALFORMED", "disk records must be a non-empty list")
    for r in recs:
        if not isinstance(r, dict) or set(r) != {"name", "uuid", "dev", "mount"} or not all(isinstance(r[k], str) for k in r):
            raise TelemetryError("MALFORMED", "disk record shape")
        if r["uuid"] and not UUID_RE.match(r["uuid"]):
            raise TelemetryError("MALFORMED", "disk record uuid")
        if not _DEV_RE.match(r["dev"]):
            raise TelemetryError("MALFORMED", "disk record device reference")
        if r["mount"] and (not os.path.isabs(r["mount"]) or "\0" in r["mount"] or "\0" in r["name"]):
            raise TelemetryError("MALFORMED", "disk record mount point")
    return recs


def parse_volumes(vols) -> list:
    """/Volumes listing: a non-empty list of plain entry names (macOS always lists the startup volume)."""
    if not isinstance(vols, list) or not vols:
        raise TelemetryError("MALFORMED", "volume list must be a non-empty list")
    for v in vols:
        if not isinstance(v, str) or not v or "/" in v or "\0" in v:
            raise TelemetryError("MALFORMED", "volume entry")
    return vols


def read_ifaddrs() -> list:
    """INDEPENDENT interface inventory straight from libc getifaddrs() (macOS/BSD sockaddr layout), not from the `ifconfig` tool. Returns
    [{'name', 'flags', 'v4': [str], 'v6': [str]}]. Observed unfiltered in the lineage where `netstat`/`ifconfig` return a reduced view. The libc handle is the
    already-loaded process image (ctypes.CDLL(None)); no library path is searched. Any surprise raises TelemetryError."""
    if sys.platform != "darwin":
        raise TelemetryError("UNSUPPORTED", "getifaddrs layout is implemented for macOS only")
    import ctypes

    class _Ifa(ctypes.Structure):
        pass
    _Ifa._fields_ = [("next", ctypes.POINTER(_Ifa)), ("name", ctypes.c_char_p), ("flags", ctypes.c_uint), ("addr", ctypes.c_void_p), ("mask", ctypes.c_void_p),
                     ("dst", ctypes.c_void_p), ("data", ctypes.c_void_p)]
    libc = ctypes.CDLL(None, use_errno=True)
    libc.getifaddrs.argtypes = [ctypes.POINTER(ctypes.POINTER(_Ifa))]
    libc.getifaddrs.restype = ctypes.c_int
    libc.freeifaddrs.argtypes = [ctypes.POINTER(_Ifa)]
    head = ctypes.POINTER(_Ifa)()
    if libc.getifaddrs(ctypes.byref(head)) != 0:
        raise TelemetryError("UNAVAILABLE", "getifaddrs failed")
    out, byname, node, n = [], {}, head, 0
    try:
        while node:
            n += 1
            if n > 100000:
                raise TelemetryError("MALFORMED", "getifaddrs list does not terminate")
            e = node.contents
            if not e.name:
                raise TelemetryError("MALFORMED", "interface without a name")
            rec = byname.get(e.name)
            if rec is None:
                rec = byname[e.name] = {"name": e.name.decode("ascii", "strict"), "flags": int(e.flags), "v4": [], "v6": []}
                out.append(rec)
            if e.addr:
                sa_len, fam = ctypes.string_at(e.addr, 2)
                if fam == 2 and sa_len >= 8:                                         # AF_INET
                    rec["v4"].append(str(ipaddress.IPv4Address(ctypes.string_at(e.addr + 4, 4))))
                elif fam == 30 and sa_len >= 24:                                     # AF_INET6
                    rec["v6"].append(str(ipaddress.IPv6Address(ctypes.string_at(e.addr + 8, 16))))
            node = e.next
    except UnicodeDecodeError:
        raise TelemetryError("MALFORMED", "interface name is not ASCII") from None
    finally:
        libc.freeifaddrs(head)
    return out


def read_linkstate(names: list) -> dict:
    """INDEPENDENT link state per interface, read IN-PROCESS from the kernel with the SIOCGIFMEDIA ioctl -- the same kernel answer `ifconfig` renders as `status:`, but
    obtained without the `ifconfig` tool, so a tool-level omission, rendering change or reduced `ifconfig` view cannot hide it. NOT independent of the kernel itself.
    Result per interface: 'active' | 'inactive' (media status valid) | 'status_invalid' (media present, status not valid) | 'no_media' (EOPNOTSUPP: no link-layer concept:
    loopback, tunnels) | 'vanished' (ENXIO/ENODEV: the interface disappeared). Permission failures and every other error raise TelemetryError (=> FAIL_CLOSED)."""
    if sys.platform != "darwin":
        raise TelemetryError("UNSUPPORTED", "SIOCGIFMEDIA layout is implemented for macOS only")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except PermissionError:
        raise TelemetryError("PERMISSION_DENIED", "cannot create the query socket") from None
    except OSError:
        raise TelemetryError("UNAVAILABLE", "cannot create the query socket") from None
    out = {}
    try:
        for name in names:
            try:
                raw = name.encode("ascii", "strict") if isinstance(name, str) else b""
            except UnicodeEncodeError:
                raw = b""
            if not raw or len(raw) > 15 or b"\0" in raw:
                raise TelemetryError("MALFORMED", "interface name unsuitable for the media query")
            buf = bytearray(40)
            buf[:len(raw)] = raw
            try:
                fcntl.ioctl(sock.fileno(), SIOCGIFMEDIA, buf, True)
            except OSError as e:
                if e.errno == errno.EOPNOTSUPP:
                    out[name] = "no_media"
                elif e.errno in (errno.ENXIO, errno.ENODEV):
                    out[name] = "vanished"
                elif e.errno in (errno.EPERM, errno.EACCES):
                    raise TelemetryError("PERMISSION_DENIED", "media query denied") from None
                else:
                    raise TelemetryError("UNAVAILABLE", "media query failed") from None
                continue
            (status,) = struct.unpack_from("<i", buf, 24)
            out[name] = "status_invalid" if not status & IFM_AVALID else ("active" if status & IFM_ACTIVE else "inactive")
    finally:
        sock.close()
    return out


def _read_counters() -> dict:
    """The kernel PCB counters (sysctl, read by the fixed absolute tool). Digits only, bounded; anything else raises."""
    out = {}
    for cls, key in PCB_COUNTERS.items():
        status, txt = _run(["sysctl", "-n", key])
        if status != "OK":
            raise TelemetryError(status, "pcb counter not readable")
        t = txt.strip()
        if not re.fullmatch(r"[0-9]{1,8}", t):
            raise TelemetryError("MALFORMED", "pcb counter is not a bounded non-negative integer")
        out[cls] = int(t)
    return out


def collect_host() -> dict:
    """Raw host telemetry. A source that failed has value None and a reason in host['telemetry'][source]; evaluate() turns that into FAIL_CLOSED.
    The home directory comes from the password database for the effective UID, NEVER from $HOME (which any same-user process can set)."""
    tele, host = {}, {}

    def get(key, cmd, post=None):
        status, out = _run(cmd)
        if status == "OK":
            try:
                host[key] = post(out) if post else out
                tele[key] = "OK"
                return
            except TelemetryError as e:
                status = e.reason
            except Exception as e:                                                       # a defect in the post-processing step, not a host condition: keep the class name
                status = _defect("PARSER_DEFECT", e)
        host[key], tele[key] = None, status
    get("processes", ["ps", "-axo", "comm="], lambda o: o.splitlines())
    get("cmdlines", ["ps", "-axo", "command="], lambda o: o.splitlines())
    get("ifconfig", ["ifconfig", "-a"])
    get("ifnames", ["ifconfig", "-l"])
    for key, fn in (("ifaddrs", read_ifaddrs), ("ifindex", lambda: [name for _, name in socket.if_nameindex()])):        # independent of the ifconfig tool
        try:
            host[key], tele[key] = fn(), "OK"
        except TelemetryError as e:
            host[key], tele[key] = None, e.reason
        except Exception as e:
            host[key], tele[key] = None, _defect("COLLECTOR_DEFECT", e)
    try:                                                                                 # independent LINK STATE for every interface name seen by the libc inventories
        names = host["ifindex"] or [r["name"] for r in (host["ifaddrs"] or [])]
        if not names:
            raise TelemetryError("UNAVAILABLE", "no interface names to query")
        host["linkstate"], tele["linkstate"] = read_linkstate(sorted(set(names))), "OK"
    except TelemetryError as e:
        host["linkstate"], tele["linkstate"] = None, e.reason
    except Exception as e:
        host["linkstate"], tele["linkstate"] = None, _defect("COLLECTOR_DEFECT", e)
    get("routes4", ["netstat", "-rn", "-f", "inet"])
    get("routes6", ["netstat", "-rn", "-f", "inet6"])
    try:                                                                              # counters BRACKET the socket query so natural churn cannot cause a mismatch
        before = _read_counters()
        get("sockets", ["netstat", "-an"])
        host["pcbcounts"], tele["pcbcounts"] = {"before": before, "after": _read_counters()}, "OK"
    except TelemetryError as e:
        host["pcbcounts"], tele["pcbcounts"] = None, e.reason
        if "sockets" not in host:
            get("sockets", ["netstat", "-an"])
    get("boot_id", ["sysctl", "-n", "kern.bootsessionuuid"], lambda o: o.strip())
    get("disks", ["diskutil", "list", "-plist"], _parse_disks)
    try:
        host["volumes"], tele["volumes"] = sorted(os.listdir("/Volumes")), "OK"
    except PermissionError:
        host["volumes"], tele["volumes"] = None, "PERMISSION_DENIED"
    except OSError:
        host["volumes"], tele["volumes"] = None, "UNAVAILABLE"
    try:
        host["home"], tele["home"] = Path(pwd.getpwuid(_euid()).pw_dir), "OK"
    except (KeyError, OSError, AttributeError, TypeError, ValueError):                   # no password-database entry / lookup error / malformed entry: no silent fallback
        host["home"], tele["home"] = None, "UNAVAILABLE"
    except Exception as e:
        host["home"], tele["home"] = None, _defect("COLLECTOR_DEFECT", e)
    host["env"], tele["env"] = dict(os.environ), "OK"
    host["telemetry"] = tele
    return host


# =============================================================================== strict parsers (raise TelemetryError => FAIL_CLOSED)
_BAD_CHAR = re.compile(r"[^\n\t\x20-\x7e]")


def _strict_lines(text, what: str) -> list:
    """Splits ONLY on '\\n'. Output must be newline-terminated (an unterminated tail means truncation) and contain nothing but printable ASCII, TAB and LF:
    CR, VT, FF, NUL, other controls and non-ASCII are rejected rather than interpreted (str.splitlines() would silently turn them into line breaks)."""
    if not isinstance(text, str) or not text:
        raise TelemetryError("MALFORMED", f"{what}: empty or not text")
    if not text.endswith("\n"):
        raise TelemetryError("MALFORMED", f"{what}: output is not newline-terminated (possible truncation)")
    if _BAD_CHAR.search(text):
        raise TelemetryError("MALFORMED", f"{what}: unexpected character (CR, NUL, control or non-ASCII)")
    return text[:-1].split("\n")


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
    out, cur = [], None
    for raw in _strict_lines(text, "ifconfig"):
        if not raw.strip():
            continue
        if not raw[0].isspace():
            m = _IF_HDR.match(raw)
            if not m:
                raise TelemetryError("MALFORMED", "interface header")
            cur = {"name": m.group(1), "up": "UP" in m.group(3).split(","), "loopback_flag": "LOOPBACK" in m.group(3).split(","), "status": None, "v4": [], "v6": [], "ether": []}
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
            if "\t" in raw.lstrip() or ": flags=" in raw:                      # a joined line (its successor starts with TAB, or is a header) must not swallow an address
                raise TelemetryError("MALFORMED", "interface line carries embedded line-joining artifacts")
            if tok == "ether":
                cur["ether"].append(raw.split()[1].lower() if len(raw.split()) > 1 else "")
            continue
        else:
            raise TelemetryError("MALFORMED", "unrecognized interface line")
    names = [i["name"] for i in out]
    if len(set(names)) != len(names):
        raise TelemetryError("MALFORMED", "duplicate interface name")
    if not any(i["name"].startswith("lo") and i["loopback_flag"] and any(a.is_loopback for a in i["v4"]) for i in out):
        raise TelemetryError("MALFORMED", "no loopback interface carrying a 127/8 address (plausibility floor)")
    if len(out) < 2:
        raise TelemetryError("MALFORMED", "fewer than two interface blocks (a real macOS host lists more than the loopback; plausibility floor)")
    return out


def parse_ifnames(text):
    """`ifconfig -l`: ONE line of unique interface names. Cross-checked against the names parsed from `ifconfig -a` so that a truncated `-a` listing cannot
    silently drop trailing interface blocks."""
    lines = _strict_lines(text, "ifconfig -l")
    if len(lines) != 1:
        raise TelemetryError("MALFORMED", "ifconfig -l must be exactly one line")
    toks = lines[0].split(" ")
    if not toks or not all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", t) for t in toks) or len(set(toks)) != len(toks):
        raise TelemetryError("MALFORMED", "ifconfig -l interface list")
    return toks


def parse_home(h):
    """The trusted user home: an absolute, canonical (no symlink anywhere in the path), existing directory owned by the expected user."""
    if not isinstance(h, (str, os.PathLike)) or not str(h) or "\0" in str(h):
        raise TelemetryError("MALFORMED", "home is not a path")
    p = str(h)
    if not os.path.isabs(p):
        raise TelemetryError("MALFORMED", "home is not absolute")
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        raise TelemetryError("UNAVAILABLE", "home directory does not exist") from None
    except PermissionError:
        raise TelemetryError("PERMISSION_DENIED", "home directory not inspectable") from None
    except OSError:
        raise TelemetryError("UNAVAILABLE", "home directory not inspectable") from None
    if stat.S_ISLNK(st.st_mode):
        raise TelemetryError("MALFORMED", "home is a symlink")
    if not stat.S_ISDIR(st.st_mode):
        raise TelemetryError("MALFORMED", "home is not a directory")
    if st.st_uid != _euid():
        raise TelemetryError("MALFORMED", "home is not owned by the expected user")
    if p != os.path.normpath(p) or os.path.realpath(p) != p:
        raise TelemetryError("MALFORMED", "home path is not canonical")
    return Path(p)


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


# =============================================================================== telemetry COMPLETENESS (independent of the command parsers)
# Parsers prove only that output is structurally well-formed and properly terminated. A reduced-but-well-formed view (observed on macOS when the process
# lineage includes a non-Apple executable: the Internet socket section, neighbour routes and hardware addresses vanish while every command exits 0) is
# "STRUCTURALLY_VALID_BUT_COMPLETENESS_UNPROVEN". The functions below compare that view with sources that the filter does not touch. Any discrepancy, and any
# missing or implausible comparison source, raises TelemetryError(COMPLETENESS) and the affected checks become FAIL_CLOSED. They establish bounded consistency
# between independently obtained facts; they are NOT a proof that every row is present.
_IFNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,31}\Z")


def _kame_fix(a: "ipaddress.IPv6Address") -> "ipaddress.IPv6Address":
    """getifaddrs returns link-local IPv6 with the scope id embedded in bytes 2-3 (KAME); ifconfig prints the bare address. Normalize to the bare form."""
    b = bytearray(a.packed)
    if b[0] == 0xFE and (b[1] & 0xC0) == 0x80:
        b[2:4] = b"\0\0"
    return ipaddress.IPv6Address(bytes(b))


def parse_ifaddrs(v) -> list:
    """Validates the getifaddrs inventory: non-empty list of {name, flags, v4, v6} with unique names, a loopback entry, and parseable addresses."""
    if not isinstance(v, list) or not v:
        raise TelemetryError("MALFORMED", "interface inventory must be a non-empty list")
    out, seen = [], set()
    for r in v:
        if not isinstance(r, dict) or set(r) != {"name", "flags", "v4", "v6"}:
            raise TelemetryError("MALFORMED", "interface record shape")
        name, flags = r["name"], r["flags"]
        if not isinstance(name, str) or not _IFNAME_RE.match(name) or name in seen:
            raise TelemetryError("MALFORMED", "interface name malformed or duplicated")
        if not isinstance(flags, int) or isinstance(flags, bool) or not 0 <= flags < 2 ** 32:
            raise TelemetryError("MALFORMED", "interface flags")
        if not isinstance(r["v4"], list) or not isinstance(r["v6"], list) or not all(isinstance(x, str) for x in r["v4"] + r["v6"]):
            raise TelemetryError("MALFORMED", "interface address lists")
        try:
            v4 = {ipaddress.IPv4Address(x) for x in r["v4"]}
            v6 = {_kame_fix(ipaddress.IPv6Address(x.split("%")[0])) for x in r["v6"]}
        except ValueError:
            raise TelemetryError("MALFORMED", "interface address") from None
        seen.add(name)
        out.append({"name": name, "up": bool(flags & IFF_UP), "loopback": bool(flags & IFF_LOOPBACK), "v4": v4, "v6": v6})
    if not any(i["loopback"] and i["name"].startswith("lo") for i in out):
        raise TelemetryError("MALFORMED", "no loopback interface in the independent inventory")
    return out


def parse_ifindex(v) -> list:
    if not isinstance(v, list) or not v or not all(isinstance(x, str) and _IFNAME_RE.match(x) for x in v) or len(set(v)) != len(v):
        raise TelemetryError("MALFORMED", "interface index list")
    return v


def check_interface_inventory(ifs: list, ifaddrs: list, ifindex: list) -> None:
    """`ifconfig -a` must agree with two inventories that do not come from the ifconfig tool (libc getifaddrs; libc if_nameindex): identical name sets,
    identical UP/LOOPBACK flags, identical IPv4 and IPv6 address sets. Raises COMPLETENESS on any discrepancy (an interface or address that silently
    disappeared from one view)."""
    a = {i["name"]: i for i in ifs}
    b = {i["name"]: i for i in ifaddrs}
    if set(a) != set(b) or set(a) != set(ifindex):
        raise TelemetryError(COMPLETENESS, "interface name sets differ between ifconfig, getifaddrs and if_nameindex")
    for n, i in a.items():
        j = b[n]
        if i["up"] != j["up"] or i["loopback_flag"] != j["loopback"] or set(i["v4"]) != j["v4"] or {_kame_fix(x) for x in i["v6"]} != j["v6"]:
            raise TelemetryError(COMPLETENESS, "interface flags or addresses differ between ifconfig and getifaddrs")


def redacted_hardware_addresses(ifs: list) -> int:
    """Number of `ether` lines carrying the macOS redaction constant (02:00:00:00:00:00). An INDICATOR of the reduced telemetry view, not proof: it was observed
    on 12 of 12 hardware addresses in the reduced view and 0 of 12 in the full view; the same value could in principle be assigned to a virtual NIC, which
    then fails closed (safe)."""
    return sum(1 for i in ifs for e in i.get("ether", []) if e == MAC_REDACTED)


def parse_pcbcounts(v) -> dict:
    if not isinstance(v, dict) or set(v) != {"before", "after"}:
        raise TelemetryError("MALFORMED", "pcb counter structure")
    for phase in v.values():
        if not isinstance(phase, dict) or set(phase) != set(PCB_COUNTERS):
            raise TelemetryError("MALFORMED", "pcb counter classes")
        for x in phase.values():
            if not isinstance(x, int) or isinstance(x, bool) or not 0 <= x <= PCB_MAX:
                raise TelemetryError(COMPLETENESS, "pcb counter value implausible")
    return v


def check_socket_plausibility(rows: list, pcb: dict) -> None:
    """Parsed TCP (tcp*) and raw/ICMP (icm*) socket rows against the kernel PCB counters (read before AND after the socket query). Required, per class:
    rows >= max(1, floor(ratio * min(bracket))) when the counter is >= 1, and rows <= max(bracket) + PCB_MAX_EXCESS. WHAT THIS ESTABLISHES, EXACTLY: the disappearance of the
    whole table whenever a counter is >= 1 is always detected. Up to about (1 - ratio) = 25% of the rows PLUS the measured listing excess (a few rows) can be removed while the
    band still accepts on a busy host, and on a host with only a handful of PCBs a MAJORITY of the rows can be removed (for example 4 of 6 at a counter of 3). It is a
    plausibility heuristic, NOT row-by-row completeness, and it says NOTHING about UDP rows (no stable relationship exists, so UDP
    completeness is unproven and UDP absence is not claimed). Raises COMPLETENESS on a violation."""
    have = {"tcp": 0, "raw": 0}
    for proto, _state, _ext in rows:
        if proto.startswith("tcp"):
            have["tcp"] += 1
        elif proto.startswith("icm"):
            have["raw"] += 1                                                    # UDP rows are intentionally not counted: see PCB_MIN_RATIO
    for cls, n in have.items():
        lo, hi = min(pcb["before"][cls], pcb["after"][cls]), max(pcb["before"][cls], pcb["after"][cls])
        need = max(1, int(PCB_MIN_RATIO[cls] * lo)) if lo >= 1 else 0
        if n < need or n > hi + PCB_MAX_EXCESS:
            raise TelemetryError(COMPLETENESS, f"{cls} socket rows are inconsistent with the kernel PCB counter")


def parse_linkstate(v) -> dict:
    """Validates the in-process link-state map: non-empty {interface name: state} with names in the interface-name grammar and states from LINK_STATES."""
    if not isinstance(v, dict) or not v:
        raise TelemetryError("MALFORMED", "link-state map must be a non-empty object")
    for name, state in v.items():
        if not isinstance(name, str) or not _IFNAME_RE.match(name) or state not in LINK_STATES or not isinstance(state, str):
            raise TelemetryError("MALFORMED", "link-state entry")
    return v


_EXPECTED_STATUS = {"active": "active", "inactive": "inactive", "no_media": None, "status_invalid": None}


def link_state_report(ifs: list, ifa: list, ls: dict) -> dict:
    """Cross-checks `ifconfig`'s `status:` against the independent kernel link state, per interface, and applies the explicit link policy. Returns
    {'active': [names whose INDEPENDENT link is active], 'unknown': [names], 'mismatch': int}. Raises COMPLETENESS if the interface sets differ.
    POLICY (non-loopback interfaces only):
      * independent 'active'            -> the link is up: a violation, whatever `ifconfig` printed. If `ifconfig` did not print `status: active` that is also a MISMATCH.
      * independent 'inactive'          -> `ifconfig` must print `status: inactive` (else MISMATCH); the addresses then decide.
      * independent 'no_media'          -> kernel says the interface has no link layer (tunnels): `ifconfig` must print NO status line (else MISMATCH); the addresses decide.
      * independent 'status_invalid'    -> media exists but its state is not valid (transition / driver): `ifconfig` must print no status line (else MISMATCH). For an UP,
                                           ADDRESSED interface the link state CANNOT be established => UNKNOWN => FAIL_CLOSED (availability is preferred over false isolation).
      * independent 'vanished'          -> the interface disappeared between queries: MISMATCH.
    A MISMATCH marks the interface view incomplete (FAIL_CLOSED). The independent source is the same kernel answer as `ifconfig`'s; it removes the dependency on the
    ifconfig tool and its output, not on the kernel."""
    names = {i["name"] for i in ifs}
    if set(ls) != names:
        raise TelemetryError(COMPLETENESS, "link-state and interface name sets differ")
    ia = {i["name"]: i for i in ifa}
    active, unknown, mismatch = [], [], 0
    for i in ifs:
        n = i["name"]
        state = ls[n]
        if i["loopback_flag"]:
            continue
        if state == "vanished" or i["status"] != _EXPECTED_STATUS[state]:
            mismatch += 1
        if state == "active":
            active.append(n)
        addressed = bool(i["v4"] or i["v6"] or (ia.get(n) and (ia[n]["v4"] or ia[n]["v6"])))
        if state == "status_invalid" and i["up"] and addressed:
            unknown.append(n)
    return {"active": active, "unknown": unknown, "mismatch": mismatch}


def check_route_interface_consistency(r4: list, r6: list, ifaddrs: list) -> None:
    """Every non-loopback interface that is UP and carries an address must appear as the interface of at least one route row of that family. This ties the
    route table to the independent interface inventory. It says nothing about neighbour (host) routes, which the reduced view omits and which no check uses."""
    n4, n6 = {r[3] for r in r4}, {r[3] for r in r6}
    for i in ifaddrs:
        if i["loopback"] or not i["up"]:
            continue
        if any(not a.is_loopback for a in i["v4"]) and i["name"] not in n4:
            raise TelemetryError(COMPLETENESS, "an addressed UP interface has no IPv4 route in the table")
        if i["v6"] and i["name"] not in n6:
            raise TelemetryError(COMPLETENESS, "an addressed UP interface has no IPv6 route in the table")


_ROUTE_DEST = re.compile(r"(?i:default)|\d{1,3}(?:\.\d{1,3}){0,3}(?:/\d{1,2})?|[0-9A-Fa-f:]*:[0-9A-Fa-f:]*(?:%[A-Za-z0-9]+)?(?:/\d{1,3})?")


def parse_routes(text, family=None):
    """Strict `netstat -rn -f inet|inet6` grammar. Returns data rows (destination, gateway, flags, netif). Malformed rows raise.
    Plausibility floors (all enforced): output newline-terminated; a recognized `Internet:`/`Internet6:` section header precedes a recognized column header;
    when `family` is given ('inet' | 'inet6') ONLY that section may appear; and at least one row must use a loopback interface (`lo<N>`; for IPv6 with an IPv6
    destination). A header-only table, or a table truncated before its loopback entries, therefore fails closed. Exit status 0 is never treated as proof of
    completeness."""
    if family not in (None, "inet", "inet6"):
        raise ValueError(family)
    rows, sections, sec, seen_header = [], [], None, False
    for raw in _strict_lines(text, "routes"):
        line = raw.strip()
        if not line or line == "Routing tables":
            continue
        if line in ("Internet:", "Internet6:"):
            sec = "inet" if line == "Internet:" else "inet6"
            sections.append(sec); seen_header = False
            continue
        tok = line.split()
        if tok[0] == "Destination":
            if sec is None or tok not in (["Destination", "Gateway", "Flags", "Netif"], ["Destination", "Gateway", "Flags", "Netif", "Expire"]):      # EXACT header: a joined line must not swallow a row
                raise TelemetryError("MALFORMED", "route table header")
            seen_header = True
            continue
        if not seen_header:
            raise TelemetryError("MALFORMED", "route row before header")
        if len(tok) not in (4, 5) or not re.fullmatch(r"[A-Za-z0-9]+", tok[2]) or not re.fullmatch(r"[A-Za-z0-9_.-]+", tok[3]) or not _ROUTE_DEST.fullmatch(tok[0]):
            raise TelemetryError("MALFORMED", "route row")
        rows.append((sec, *tok[:4]))
    if not sections or (family and sections != [family]) or (not family and len(set(sections)) != len(sections)):
        raise TelemetryError("MALFORMED", "route table sections missing, repeated or of the wrong address family")
    loop = [r for r in rows if re.fullmatch(r"lo\d+", r[4]) and (r[0] == "inet" or ":" in r[1])]
    if not loop:
        raise TelemetryError("MALFORMED", "no loopback route (plausibility floor; header-only or truncated table)")
    return [r[1:] for r in rows]


def parse_routes4(text):
    return parse_routes(text, "inet")


def parse_routes6(text):
    return parse_routes(text, "inet6")


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


_SOCK_HDR_INET = ["Proto", "Recv-Q", "Send-Q", "Local", "Address", "Foreign", "Address", "(state)"]
_SOCK_HDR_MPTCP = ["Proto/ID", "Flags", "Local", "Address", "Foreign", "Address", "(state)"]


def _sock_row(raw: str) -> tuple:
    f = raw.split()
    if not f or raw[0].isspace():
        raise TelemetryError("MALFORMED", "socket row")
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
    if not (f[1].isdigit() and f[2].isdigit()):
        raise TelemetryError("MALFORMED", "socket queue columns")
    local, foreign = _classify_sock_addr(f[3]), _classify_sock_addr(f[4])
    if proto.startswith("tcp"):
        external = local in ("wildcard", "external") or foreign == "external"      # any TCP listener/connection beyond loopback
    else:
        # UDP: a socket bound to a specific non-loopback address, or connected to a non-loopback peer, is live traffic. A WILDCARD-only UDP bind
        # (e.g. mDNSResponder `*.5353`) exists even with networking disabled and is inert without an addressed interface or route, which the interface
        # and route checks establish -- it is not counted, and UDP absence is NOT claimed.
        external = local == "external" or foreign == "external"
    return (proto, state, external)


def parse_sockets(text):
    """Strict `netstat -an` Internet-connections grammar. Returns [(proto, state, external_bool)].

    Structure (every rule is enforced; anything else raises MALFORMED):
      * the output is newline-terminated, printable ASCII/TAB/LF only (a CR, VT, FF, NUL or other control character is NOT a line break and is rejected);
      * it begins with an `Active ...` section header; sections are delimited ONLY by lines starting `Active `;
      * each `Active Internet connections` section has the exact column header, then data rows; a blank (or whitespace-only) line is accepted ONLY as the end
        of the table: after the first blank line every remaining line of the section must be blank, so a stray blank line can no longer hide later rows;
      * EVERY examined section must be followed by another `Active ...` section. A table that runs to the end of the output is treated as truncated;
      * an `Active Multipath Internet connections` section is parsed with the SAME row grammar and its rows are classified like any other (real macOS lists
        icm6 sockets there); a row in an unrecognised format is refused; it too must be terminated;
      * at least one Internet section must be present. A header-only table that IS terminated by a following section is structurally well-formed and is the
        only 'verified empty' representation; an unterminated one is refused.
    This establishes that the received text is STRUCTURALLY WELL-FORMED AND PROPERLY TERMINATED. It does NOT establish that every socket is listed: completeness is tested
    separately by check_socket_plausibility against the kernel PCB counters, and exit status 0 is not relied upon. It does not show that no socket opened afterwards."""
    lines = _strict_lines(text, "sockets")
    if not lines[0].startswith("Active "):
        raise TelemetryError("MALFORMED", "output does not begin with an Active section")
    rows, n, i, saw_inet = [], len(lines), 0, False
    while i < n:
        head = lines[i]
        i += 1
        body = []
        while i < n and not lines[i].startswith("Active "):
            body.append(lines[i]); i += 1
        terminated = i < n
        if head.startswith("Active Internet connections"):
            kind = "inet"
        elif head.startswith("Active Multipath Internet connections"):
            kind = "mptcp"
        else:
            continue                                                                    # unix-domain / kernel sockets: not network exposure
        if not terminated:
            raise TelemetryError("MALFORMED", "socket section not followed by another section (output may be truncated)")
        if not body:
            raise TelemetryError("MALFORMED", "socket section has no column header")
        if body[0].split() != (_SOCK_HDR_INET if kind == "inet" else _SOCK_HDR_MPTCP):
            raise TelemetryError("MALFORMED", "socket column header missing, partial or unrecognized")
        seen_blank = False
        for raw in body[1:]:
            if not raw.strip():
                seen_blank = True
                continue
            if seen_blank:
                raise TelemetryError("MALFORMED", "data after a blank line inside a socket section")
            rows.append(_sock_row(raw))                           # the multipath section also lists plain icm6/tcp/udp rows on real macOS: same grammar, same classification
        saw_inet = saw_inet or kind == "inet"
    if not saw_inet:
        raise TelemetryError("MALFORMED", "no Internet connections section")
    return rows


# =============================================================================== strict filesystem helpers
def _scandir(dfd: int, rel: str = ""):
    """Lists the directory behind the OPEN descriptor `dfd` (never a pathname). `rel` is informational (tests key fault injection on it)."""
    return os.scandir(dfd)
_openat = os.open              # indirection so tests can simulate a swap between listing and open
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _O_CLOEXEC


def _read_member(dfd: int, name: str, lst, mode: str):
    """Opens `name` RELATIVE TO the already-open directory descriptor `dfd` (never through a pathname), verifies that the open descriptor is the very object
    the listing saw, and returns ('hash': (sha256, size)) or ('head': first 256 bytes). None on any anomaly."""
    try:
        fd = _openat(name, _FILE_FLAGS, dir_fd=dfd)
    except Exception:
        return None
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode) or (fst.st_dev, fst.st_ino) != (lst.st_dev, lst.st_ino) or (fst.st_size, fst.st_mtime_ns) != (lst.st_size, lst.st_mtime_ns):
            return None                                            # not the object the listing saw, or modified in place since the listing
        if mode == "head":
            return os.read(fd, 256)
        if fst.st_nlink != 1 or fst.st_size > MAX_HASHED_BYTES:
            return None
        h = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = f.read(MAX_HASHED_BYTES + 1)
        after = os.fstat(fd)
        if len(data) != fst.st_size or (after.st_size, after.st_mtime_ns) != (fst.st_size, fst.st_mtime_ns):
            return None                                            # modified while being read
        h.update(data)
        return h.hexdigest(), fst.st_size
    except Exception:
        return None
    finally:
        os.close(fd)


def _walk(root, mode: str = "none", only=None) -> tuple:
    """DESCRIPTOR-RELATIVE traversal. The root is opened once with O_DIRECTORY|O_NOFOLLOW; every child directory is opened with O_DIRECTORY|O_NOFOLLOW relative
    to its parent's open descriptor and must be the very (device, inode) the listing reported; members are read relative to the open directory descriptor. A
    child is NEVER re-resolved through a mutable pathname after it was listed, so a directory swapped for a symlink (or another directory) is detected and
    counted as an error. Returns (entries[(rel, lstat)], error_count, results{rel: hash|head|None}). mode: 'none' | 'hash' (regular, single-link members whose rel
    is in `only` when given) | 'head' (first 256 bytes of every regular member).
    RESIDUAL: the ANCESTORS of `root` are resolved by the kernel in the ordinary way (only the final component is O_NOFOLLOW); a same-user attacker who can
    rewrite an ancestor symlink during the one-shot call is outside what this can detect, and the digest is point-in-time."""
    entries, results, errors = [], {}, [0]
    try:
        rfd = _openat(os.fspath(root), _DIR_FLAGS)
    except Exception:
        return entries, 1, results
    try:
        rst = os.fstat(rfd)
        try:
            pst = os.lstat(root)
        except Exception:
            return entries, 1, results
        if not stat.S_ISDIR(rst.st_mode) or (rst.st_dev, rst.st_ino) != (pst.st_dev, pst.st_ino):
            return entries, 1, results

        def scan(dfd: int, rel: str, depth: int):
            if depth > MAX_WALK_DEPTH:
                errors[0] += 1
                return
            try:
                with _scandir(dfd, rel) as it:
                    children = list(it)
            except Exception:                  # unknown state is unsafe state: any failure (not only OSError) counts
                errors[0] += 1
                return
            subdirs = []
            for e in children:
                r = f"{rel}/{e.name}" if rel else e.name
                try:
                    st = e.stat(follow_symlinks=False)
                except Exception:
                    errors[0] += 1
                    continue
                entries.append((r, st))
                if stat.S_ISDIR(st.st_mode):
                    subdirs.append((e.name, r, st))
                elif mode != "none" and stat.S_ISREG(st.st_mode) and (only is None or r in only) and (mode == "head" or st.st_nlink == 1):
                    results[r] = _read_member(dfd, e.name, st, mode)
            for name, r, lst in subdirs:
                try:
                    cfd = _openat(name, _DIR_FLAGS, dir_fd=dfd)
                except Exception:              # swapped for a symlink / removed / permission changed => unknown state
                    errors[0] += 1
                    continue
                try:
                    cst = os.fstat(cfd)
                    if not stat.S_ISDIR(cst.st_mode) or (cst.st_dev, cst.st_ino) != (lst.st_dev, lst.st_ino):
                        errors[0] += 1
                        continue
                    scan(cfd, r, depth + 1)
                finally:
                    os.close(cfd)
        scan(rfd, "", 0)
    finally:
        os.close(rfd)
    return entries, errors[0], results


def walk_strict(root: Path) -> tuple:
    """Descriptor-relative walk that NEVER silently skips: returns (entries[(rel, lstat)], error_count). Any listing/stat/open failure increments the count."""
    entries, errors, _ = _walk(root)
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


# =============================================================================== code manifest
def build_code_manifest(code_root: Path) -> dict:
    """Reads the tree strictly (descriptor-relative) and returns {'v':1,'files':{rel:{'sha256','size'}}}. Raises on any anomaly (symlink, special file, hardlink, error)."""
    entries, errors, hashed = _walk(Path(code_root), "hash")
    if errors:
        raise OSError("traversal errors; refusing to build a manifest")
    files = {}
    for rel, st in entries:
        k = _kind(st)
        if k == "dir":
            continue
        if k != "file" or st.st_nlink != 1:
            raise OSError("anomalous filesystem object; refusing to build a manifest")
        if hashed.get(rel) is None:
            raise OSError("a member could not be hashed; refusing to build a manifest")
        sha, size = hashed[rel]
        files[rel] = {"sha256": sha, "size": size}
    return {"v": 1, "files": dict(sorted(files.items()))}


def canonical_manifest_bytes(m: dict) -> bytes:
    """The ONE canonical serialization of a manifest: sorted keys, indent 1, exactly one trailing newline. The pin is the SHA-256 of THESE bytes, which are also
    exactly the bytes a shell redirect of `build-manifest` stdout produces."""
    return (json.dumps(m, sort_keys=True, indent=1) + "\n").encode()


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
    wanted = set(manifest["files"])
    entries, errors, hashed = _walk(Path(code_root), "hash", only=wanted)
    if errors:
        return FAIL_CLOSED, f"{errors} traversal error(s); the complete tree could not be established"
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
        if hashed.get(rel) is None:
            unreadable += 1
            continue
        sha, size = hashed[rel]
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
    entries, errors, heads = _walk(Path(role_state_dir), "head")
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
            head = heads.get(rel)
            if head is None:
                unreadable += 1
            else:
                hit = any(m in head for m in KEY_HEADER_MARKERS)
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


_CONFUSABLE_SCRIPTS = ("CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE", "COPTIC")


def canon_volume_name(s: str) -> str:
    """Comparison form of a volume LABEL: NFKC (folds full-width and compatibility forms, NBSP -> space), format/control characters (zero-width space/joiner, BOM,
    bidi marks, TAB/LF...) REMOVED, case-folded, whitespace collapsed and trimmed, and a trailing macOS collision suffix (' 2', ' (2)', '-2') removed. This is NOT
    a confusables mapper: a lookalike from another script is not folded -- `suspicious_label` flags those instead. Labels are advisory; UUIDs are the identifier."""
    s = unicodedata.normalize("NFKC", str(s))
    s = "".join(c for c in s if unicodedata.category(c) not in ("Cf", "Cc"))
    s = unicodedata.normalize("NFKC", s.casefold())
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"(?: \d+| \(\d+\)|-\d+)$", "", s)


def suspicious_label(s: str) -> bool:
    """True when a label cannot be compared reliably: it contains a script that has Latin lookalikes (Cyrillic, Greek, ...), or a control/format character. Such an
    OBSERVED label makes the volume check FAIL_CLOSED rather than being silently non-matching."""
    for c in str(s):
        if unicodedata.category(c) in ("Cf", "Cc"):
            return True
        if c.isalpha() and any(unicodedata.name(c, "").startswith(sc) for sc in _CONFUSABLE_SCRIPTS):
            return True
    return False


def validate_deny_config(deny_paths, deny_volumes, deny_volume_uuids, home) -> tuple:
    """Returns (cfg|None, problem|None). cfg = {'paths': [...], 'names': set, 'uuids': set, 'label_only': bool}. Anything malformed, empty, duplicated or ambiguous
    is a PROBLEM (=> FAIL_CLOSED): a typo'd or empty entry must not silently match nothing. Problems are reported as categories only (never the value)."""
    def as_list(x, what):
        if x is None:
            return []
        if isinstance(x, (str, bytes)) or not isinstance(x, (list, tuple)):
            raise ValueError(f"{what} must be a list")
        return list(x)
    try:
        paths, labels, uuids = as_list(deny_paths, "deny paths"), as_list(deny_volumes, "deny volumes"), as_list(deny_volume_uuids, "deny volume UUIDs")
    except ValueError as e:
        return None, str(e)
    norm = []
    for p in paths:
        n = normalize_deny_path(p, home)
        if n is None:
            return None, "a deny path is not an absolute canonical path (relative, '..', unresolved '~' or empty)"
        norm.append(n)
    if len(set(norm)) != len(norm):
        return None, "duplicate deny path"
    names = []
    for v in labels:
        if not isinstance(v, str) or not v.strip():
            return None, "a deny volume label is empty or not text"
        if suspicious_label(v) or v != v.strip():
            return None, "a deny volume label contains control/format characters, confusable-script letters or surrounding whitespace (use the volume UUID)"
        c = canon_volume_name(v)
        if not c:
            return None, "a deny volume label is empty after normalization"
        names.append(c)
    if len(set(names)) != len(names):
        return None, "duplicate deny volume label (after normalization)"
    ids = []
    for u in uuids:
        if not isinstance(u, str) or not UUID_RE.match(u):
            return None, "a deny volume UUID is empty or not a well-formed UUID"
        ids.append(u.casefold())
    if len(set(ids)) != len(ids):
        return None, "duplicate deny volume UUID"
    return {"paths": norm, "names": set(names), "uuids": set(ids), "label_only": bool(names) and not ids}, None


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


def _read_state_file(p, dir_fd: int | None = None) -> str:
    """Race-safe read: open without following symlinks or blocking (relative to the already-open, locked interlock directory when `dir_fd` is given), then check
    the OPEN descriptor (regular, single link, our owner, not group/other writable)."""
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
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


def _lock_dir(d: Path, *, exclusive: bool, timeout: float | None = None) -> int:
    """Advisory flock() on the interlock DIRECTORY itself (no extra file is created, so the exact-file-set check is unaffected). Returns the held descriptor; the
    caller closes it. Failure to obtain the lock within the timeout, or any lock error, raises PermissionError (=> fail closed). The kernel releases the lock when
    the holding process dies, so there is no stale-lock state to clean up. The lock coordinates cooperating writers; it does not stop a same-user process that
    ignores it."""
    timeout = LOCK_TIMEOUT if timeout is None else timeout
    try:
        fd = os.open(d, _DIR_FLAGS)
    except OSError as e:
        raise PermissionError("interlock directory cannot be opened for locking") from e
    op = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, op)
            return fd
        except OSError as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EINTR) or time.monotonic() >= deadline:
                os.close(fd)
                raise PermissionError("interlock lock not acquired (another writer is active, or locking is unsupported here)") from e
            time.sleep(0.02)


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


def verify_state(state_dir, *, _locked: bool = False, _dfd: int | None = None) -> tuple:
    """Returns (problems, receipts). ANY problem => the caller must treat the interlock as unverifiable (FAIL_CLOSED). Takes a SHARED lock on the directory (so it
    never observes a half-finished append); failure to obtain it is itself a problem. `_locked` is for the writer that already holds the exclusive lock."""
    if state_dir is None:
        return ["state directory not supplied"], []
    if _locked:
        return _verify_state(_dfd)
    try:
        fd = _lock_dir(Path(state_dir), exclusive=False)
    except PermissionError:
        return ["interlock lock not acquired (a writer is active, or the directory is missing or unusable; run `init` first)"], []
    try:
        return _verify_state(fd)
    finally:
        os.close(fd)


def _verify_state(dfd: int) -> tuple:
    """Verifies the interlock through the OPEN directory descriptor only (no pathname is re-resolved after the directory was opened O_NOFOLLOW and locked)."""
    problems, recs = [], []
    try:
        st = os.fstat(dfd)
    except OSError:
        return ["state directory missing or unreadable (run `init` first)"], recs
    if not stat.S_ISDIR(st.st_mode):
        return ["state path is not a directory"], recs
    if not stat_ok(st):
        return ["state directory has an unsafe owner or mode (must be owned by the current user and not group/other-writable)"], recs
    try:
        names = set(os.listdir(dfd))
    except OSError:
        return ["state directory cannot be listed"], recs
    if names != STATE_FILES:
        return [f"state directory must contain exactly the interlock files ({len(names - STATE_FILES)} unexpected, {len(STATE_FILES - names)} missing; "
                f"a stale or planted temporary file also fails here)"], recs
    try:
        init = _strict_loads(_read_state_file("INIT.json", dfd))
        head = _strict_loads(_read_state_file("HEAD.json", dfd))
        raw = _read_state_file("receipts.jsonl", dfd)
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
    """Serialized append. The whole verify -> append -> HEAD-replace sequence runs under an EXCLUSIVE lock on the interlock directory, so concurrent cooperating
    writers cannot interleave and corrupt the chain; a writer that cannot get the lock fails closed (PermissionError). CRASH BEHAVIOUR: if the process dies between the
    receipt append and the HEAD replace, receipts and HEAD disagree and every later verification FAILS CLOSED until the owner re-initializes a new interlock directory
    (history is advisory and is not recovered automatically). A stale lock cannot exist: the kernel drops it with the process."""
    d = Path(state_dir)
    lock = _lock_dir(d, exclusive=True)
    try:
        problems, recs = verify_state(state_dir, _locked=True, _dfd=lock)
        if problems:
            raise PermissionError("interlock state unverifiable: " + "; ".join(problems))
        if role not in ROLES or not UUID_RE.match(boot_id or ""):
            raise ValueError("role/boot id invalid")
        env_id = _strict_loads(_read_state_file("INIT.json", lock))["env_id"]
        rec = {"v": 2, "env_id": env_id, "seq": len(recs) + 1, "role": role, "boot": boot_id, "prev": recs[-1]["sum"] if recs else ZERO}
        rec["sum"] = _sum(rec)
        fd = os.open("receipts.jsonl", os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=lock)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or not stat_ok(st):
                raise PermissionError("receipts file is not a safe regular file")
            os.write(fd, (json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        tmp = f".HEAD.{secrets.token_hex(8)}.tmp"
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=lock)        # exclusive create; never follows a planted symlink
        try:
            os.write(fd, json.dumps({"v": 2, "env_id": env_id, "seq": rec["seq"], "sum": rec["sum"]}, sort_keys=True).encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, "HEAD.json", src_dir_fd=lock, dst_dir_fd=lock)                         # same-directory atomic replace
        return rec
    finally:
        os.close(lock)


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
    except Exception as e:                                                       # parsers only raise TelemetryError for host conditions; anything else is a gate defect
        return None, _defect("PARSER_DEFECT", e)


def evaluate(role, *, host: dict, state_dir=None, role_state_dir=None, code_root=None, code_manifest=None, code_manifest_sha256=None, deny_paths=None,
             deny_volumes=None, deny_volume_uuids=None, workspaces=None, process_allowlist=None) -> dict:
    """Pure given its inputs. {check: {"status": PASS|FAIL|FAIL_CLOSED, "ok": bool, "detail": str}}. Details are counts/categories only -- never paths,
    file names, process command lines or contents."""
    if role not in ROLES:
        raise ValueError(role)
    r = {}
    # -- telemetry sources (mandatory)
    names, why_names = _src(host, "processes", parse_processes)
    cmds, why_cmds = _src(host, "cmdlines", parse_cmdlines)
    env, why_env = _src(host, "env", parse_env)
    home, why_home = _src(host, "home", parse_home)
    ifs, why_if = _src(host, "ifconfig", parse_interfaces)
    ifn, why_ifn = _src(host, "ifnames", parse_ifnames)
    if ifs is not None and why_ifn is None and [i["name"] for i in ifs] != ifn:
        ifs, why_if = None, "MALFORMED"                                    # `ifconfig -a` lists different interfaces than `ifconfig -l`: truncated or tampered
    elif ifs is not None and why_ifn is not None:
        ifs, why_if = None, "UNVERIFIED"                                   # cannot cross-check the interface listing
    r4, why_r4 = _src(host, "routes4", parse_routes4)
    r6, why_r6 = _src(host, "routes6", parse_routes6)
    socks, why_sock = _src(host, "sockets", parse_sockets)
    ifa, why_ifa = _src(host, "ifaddrs", parse_ifaddrs)
    idx, why_idx = _src(host, "ifindex", parse_ifindex)
    ls, why_ls = _src(host, "linkstate", parse_linkstate)
    pcb, why_pcb = _src(host, "pcbcounts", parse_pcbcounts)
    # ---- COMPLETENESS: structurally valid is not complete. Compare the command views with sources the reduced-view filter does not touch.
    incomplete, signals = {}, 0
    if ifs is not None and ifa is not None and idx is not None:
        try:
            check_interface_inventory(ifs, ifa, idx)
        except TelemetryError as e:
            incomplete["ifconfig"] = e.reason
    elif ifs is not None:
        incomplete["ifconfig"] = COMPLETENESS                              # no independent inventory to compare with => completeness unproven
    link = None
    if ifs is not None and ifa is not None and ls is not None:
        try:
            link = link_state_report(ifs, ifa, ls)
            if link["mismatch"]:
                incomplete["ifconfig"] = COMPLETENESS                      # `ifconfig`'s status disagrees with the independent kernel link state
                signals += 1
        except TelemetryError as e:
            incomplete["ifconfig"] = e.reason
    elif ifs is not None:
        incomplete["ifconfig"] = COMPLETENESS                              # no independent link state => the interface view cannot be shown complete
    if ifs is not None:
        signals += 1 if redacted_hardware_addresses(ifs) else 0          # hardware addresses redacted: the reduced telemetry view
    if socks is not None and pcb is not None:
        try:
            check_socket_plausibility(socks, pcb)
        except TelemetryError as e:
            incomplete["sockets"] = e.reason
            signals += 1
    elif socks is not None:
        incomplete["sockets"] = COMPLETENESS                               # no counter to compare with
    elif pcb is not None and why_sock is not None and max(pcb["before"].values()) >= 1:
        incomplete["sockets"] = COMPLETENESS                               # sockets exist (kernel counter) but the table is unusable: reduced view, not a clean parse failure
        signals += 1
    if r4 is not None and r6 is not None and ifa is not None:
        try:
            check_route_interface_consistency(r4, r6, ifa)
        except TelemetryError as e:
            incomplete["routes4"] = incomplete["routes6"] = e.reason
    else:
        for k, v in (("routes4", r4), ("routes6", r6)):
            if v is not None:
                incomplete[k] = COMPLETENESS                              # no independent inventory to tie the route table to
    if signals:                                                            # a known reduced-view signature: every network command shares the filter => none is trusted
        for k, src in (("ifconfig", ifs), ("routes4", r4), ("routes6", r6), ("sockets", socks)):
            if src is not None:
                incomplete.setdefault(k, COMPLETENESS)
    boot, why_boot = _src(host, "boot_id")
    boot_ok = isinstance(boot, str) and bool(UUID_RE.match(boot))
    need_vol = bool(deny_volumes or deny_volume_uuids)
    vols, why_vols = _src(host, "volumes", parse_volumes) if need_vol else (None, None)
    disks, why_disks = _src(host, "disks", parse_disk_records) if need_vol else (None, None)
    failed = {k: w for k, w in (("processes", why_names), ("cmdlines", why_cmds), ("env", why_env), ("home", why_home), ("ifconfig", why_if), ("ifnames", why_ifn),
                                ("routes4", why_r4), ("routes6", why_r6), ("sockets", why_sock), ("ifaddrs", why_ifa), ("ifindex", why_idx), ("linkstate", why_ls), ("pcbcounts", why_pcb),
                                ("boot_id", why_boot)) if w}
    failed.update(incomplete)                                               # an explicit COMPLETENESS reason replaces a bare parse failure of the same source
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
    # -- network (one-shot; point-in-time). The PRIMARY facts are the interface ADDRESSES and FLAGS (cross-checked against independent libc inventories) and the LINK STATE (cross-checked against the in-process kernel ioctl);
    #    the route table and socket table are corroborating evidence that can only ADD failures: a violation seen in a reduced view is still a violation.
    if ifs is None:
        r["network_interfaces_disabled"] = _fc("ifconfig " + (why_if or "UNAVAILABLE"))
    else:
        bad = interface_violations(ifs)
        bad_names = {i["name"] for i in bad} | set(link["active"] if link else [])        # an active link seen by the INDEPENDENT source is a violation too
        kinds = sorted({re.sub(r"\d+$", "", n) for n in bad_names})
        if bad_names:
            r["network_interfaces_disabled"] = _res(FAIL, f"{len(bad_names)} interface(s) with a non-loopback address or an active link (kinds: {','.join(kinds) or 'none'})")
        elif "ifconfig" in incomplete:
            r["network_interfaces_disabled"] = _fc(f"{COMPLETENESS}: the interface view could not be shown complete")
        elif link and link["unknown"]:
            r["network_interfaces_disabled"] = _fc(f"LINK_STATE_UNESTABLISHED: {len(link['unknown'])} UP addressed interface(s) whose link state cannot be independently established "
                                                   f"(media status not valid); availability is preferred over false isolation")
        else:
            r["network_interfaces_disabled"] = _res(PASS, "0 interface(s) with a non-loopback address or an active link; names, UP/LOOPBACK flags and addresses agree with two independent libc inventories "
                                                    "and every interface's `status:` agrees with the independent kernel link state")
    if r4 is None or r6 is None:
        r["network_no_default_route"] = _fc("routing tables: " + unverified("routes4", "routes6"))
    else:
        d4, d6 = default_routes(r4), default_routes(r6)
        if d4 or d6:
            r["network_no_default_route"] = _res(FAIL, f"{len(d4)} IPv4 / {len(d6)} IPv6 default route(s) observed")
        elif "routes4" in incomplete or "routes6" in incomplete:
            r["network_no_default_route"] = _fc(f"{COMPLETENESS}: the route table could not be shown consistent with the interface inventory")
        else:
            r["network_no_default_route"] = _res(PASS, "ADVISORY: no default route observed; the route table's completeness is NOT claimed (the OS may omit rows) -- the network verdict rests on the interface addresses, which are cross-checked independently")
            r["network_no_default_route"]["advisory"] = True
    if socks is None:
        r["network_no_external_sockets"] = _fc("socket table " + (incomplete.get("sockets") or why_sock or "UNAVAILABLE"))
    else:
        ext = [s for s in socks if s[2]]
        udp = sum(1 for s in ext if s[0].startswith("udp"))
        if ext:
            r["network_no_external_sockets"] = _res(FAIL, f"{len(ext)} socket(s) bound or connected beyond loopback ({udp} UDP) observed; point-in-time only")
        elif "sockets" in incomplete:
            r["network_no_external_sockets"] = _fc(f"{COMPLETENESS}: the socket table is not consistent with the kernel PCB counters")
        else:
            r["network_no_external_sockets"] = _res(PASS, "0 external socket(s) observed, TCP and raw/ICMP rows are consistent with the kernel PCB counters within a bounded plausibility band (not a proof that every row is present); UDP rows are NOT cross-checked (no stable relationship exists) and UDP absence is NOT claimed; point-in-time only, not proof that nothing could communicate")
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
        r["configured_other_role_storage_not_detected"] = _fc("no deny-listed path, volume or volume UUID supplied (the other role's storage must be named explicitly)")
    else:
        dcfg, dproblem = validate_deny_config(deny_paths, deny_volumes, deny_volume_uuids, home)
        if dproblem:
            r["configured_other_role_storage_not_detected"] = _fc("malformed deny configuration: " + dproblem)
        elif need_vol and (vols is None or disks is None):
            r["configured_other_role_storage_not_detected"] = _fc("volume telemetry unverified: " + unverified("volumes", "disks"))
        else:
            present = sum(1 for n in dcfg["paths"] if os.path.lexists(n))
            if need_vol:
                observed = list(vols) + [d["name"] for d in disks if d["name"]] + [os.path.basename(d["mount"]) for d in disks if d["mount"]]
                if any(suspicious_label(o) for o in observed):
                    r["configured_other_role_storage_not_detected"] = _fc("an observed volume label contains confusable-script letters or control/format characters; labels cannot be compared reliably (use the volume UUID and physical detachment)")
                    dcfg = None
                else:
                    seen_names = {canon_volume_name(o) for o in observed}
                    seen_uuids = {d["uuid"].casefold() for d in disks if d["uuid"]}
                    present += len(dcfg["names"] & seen_names) + len(dcfg["uuids"] & seen_uuids)
            if dcfg is not None:
                total = len(dcfg["paths"]) + len(dcfg["names"]) + len(dcfg["uuids"])
                weak = " LABEL_ONLY: no volume UUID supplied, so volume matching rests on spoofable display labels (weaker, advisory)." if dcfg["label_only"] else ""
                note = ("The configured identifiers were not observed; this is NOT evidence that the other role's storage is physically absent (a renamed label, a wrong UUID or an "
                        "unconfigured drive would not be seen). " if not present else "") + "Physical detachment remains an owner procedure."
                r["configured_other_role_storage_not_detected"] = _res(FAIL if present else PASS, f"ADVISORY: {present} of {total} configured path(s)/volume(s)/UUID(s) observed present, attached or mounted. {note}{weak}")
                r["configured_other_role_storage_not_detected"]["advisory"] = True
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
    ap.add_argument("--out", type=Path, help="build-manifest: write the canonical manifest bytes to this NEW file (exclusive create) instead of stdout")
    ap.add_argument("--pin-out", type=Path, help="build-manifest: write the 64-hex pin followed by one newline to this NEW file")
    a = ap.parse_args(argv[1:])
    if a.cmd == "init":
        if not a.state_dir:
            print("FAIL_CLOSED --state-dir required"); return 1
        try:
            init_state(a.state_dir)
        except FileExistsError:
            print("FAIL_CLOSED interlock state directory already exists; refusing to re-initialize"); return 1
        except OSError as e:                                                    # permission denied, read-only filesystem, missing parent ...: expected operational failure
            print(f"FAIL_CLOSED interlock state directory could not be created ({type(e).__name__})"); return 1
        print("INITIALIZED"); return 0
    if a.cmd == "build-manifest":
        if not a.code_root:
            print("FAIL_CLOSED --code-root required"); return 1
        try:
            m = build_code_manifest(a.code_root)
        except OSError as e:
            print("FAIL_CLOSED", e); return 1
        raw = canonical_manifest_bytes(m)
        pin = hashlib.sha256(raw).hexdigest()
        try:
            for path, data in ((a.out, raw), (a.pin_out, (pin + "\n").encode())):
                if path is not None:
                    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(data)
        except OSError as e:
            print("FAIL_CLOSED cannot write output:", type(e).__name__); return 1
        if a.out is None:
            sys.stdout.buffer.write(raw); sys.stdout.buffer.flush()               # exactly the canonical bytes: `> M` yields a file whose SHA-256 is the pin
            print(f"MANIFEST_SHA256 {pin}", file=sys.stderr)
        else:
            print(f"MANIFEST_SHA256 {pin}")
        return 0
    if not a.role:
        print("FAIL_CLOSED --role required"); return 1
    allow = None
    if a.process_allowlist:
        try:
            allow = [l.strip() for l in a.process_allowlist.read_text().splitlines() if l.strip()]
        except OSError:
            print("FAIL_CLOSED process allowlist unreadable"); return 1
    try:
        host = collect_host()
        res = evaluate(a.role, host=host, state_dir=a.state_dir, role_state_dir=a.role_state_dir, code_root=a.code_root, code_manifest=a.code_manifest,
                       code_manifest_sha256=a.code_manifest_sha256, deny_paths=a.deny_path, deny_volumes=a.deny_volume, deny_volume_uuids=a.deny_volume_uuid,
                       workspaces=a.workspace, process_allowlist=allow)
    except Exception as e:
        # collect_host/evaluate are written never to raise for ANY host condition, so reaching this is a PROGRAMMING ERROR. It is not hidden: the full traceback goes to
        # stderr (visible during development), stdout carries the refusal, and the exit code (3) differs from an ordinary gate failure (1).
        import traceback
        traceback.print_exc()
        print(f"FAIL_CLOSED internal error ({type(e).__name__}); this is a defect in the gate, not a host condition")
        print("GATE_FAILS"); return 3
    for k, v in res.items():
        print(f"{v['status']:11} {k} -- {v['detail']}")
    ok = gate_passes(res)
    if a.cmd == "begin" and ok:
        try:
            begin(a.role, a.state_dir, host["boot_id"], res)
        except PermissionError as e:                                           # lock not acquired / interlock unverifiable: expected, fail closed, nothing recorded
            print(f"FAIL_CLOSED the phase start was NOT recorded: {str(e)[:160]}")
            print("GATE_FAILS"); return 1
        except OSError as e:
            print(f"FAIL_CLOSED the phase start was NOT recorded ({type(e).__name__})")
            print("GATE_FAILS"); return 1
    print("GATE_PASSES" if ok else "GATE_FAILS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
