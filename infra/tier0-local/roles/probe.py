"""In-container capability probe (stdlib only). Prints one JSON object of FACTS about the container it runs in; never prints secret values.
Usage: probe.py <forbidden_path> ..."""
import json, os, socket, sys

def _status(key):
    for line in open("/proc/self/status"):
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()

def _mounts():
    out = []
    for line in open("/proc/self/mountinfo"):
        f = line.split()
        dest, opts = f[4], f[5].split(",")
        if dest.startswith(("/proc", "/sys", "/dev")) or dest in ("/etc/hosts", "/etc/hostname", "/etc/resolv.conf"):
            continue
        out.append({"dest": dest, "ro": "ro" in opts})
    return out

def _can(path, mode):
    try:
        if mode == "write":
            fd = os.open(os.path.join(path, ".probe-%d" % os.getpid()), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            os.close(fd); os.unlink(os.path.join(path, ".probe-%d" % os.getpid()))
        else:
            os.listdir(path) if os.path.isdir(path) else open(path, "rb").close()
        return True
    except Exception:
        return False

def _net():
    res = {}
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2).close(); res["tcp_egress"] = True
    except Exception:
        res["tcp_egress"] = False
    try:
        socket.getaddrinfo("example.com", 443); res["dns"] = True
    except Exception:
        res["dns"] = False
    ifaces = [l.split(":")[0].strip() for l in open("/proc/net/dev").read().splitlines()[2:]]
    res["interfaces"] = ifaces
    return res

forbidden = sys.argv[1:]
facts = {
    "uid": os.getuid(), "gid": os.getgid(), "pid_in_ns": os.getpid(),
    "cap_eff": _status("CapEff"), "no_new_privs": _status("NoNewPrivs"),
    "ns": {n: os.readlink("/proc/self/ns/" + n) for n in ("pid", "net", "mnt", "ipc", "uts")},
    "env_names": sorted(os.environ),
    "mounts": _mounts(),
    "rootfs_writable": _can("/", "write"),
    "app_writable": _can("/app", "write"),
    "docker_sock_present": os.path.exists("/var/run/docker.sock"),
    "forbidden_path_accessible": {p: _can(p, "read") for p in forbidden},
    "net": _net(),
}
mods = {}
for m in ("orca.eval.genesis_v2.runner_qualification", "orca.eval.genesis_v2.operational_boundary", "orca.eval.genesis_v2.ledger",
          "orca.eval.genesis_v2.authority_registry", "orca.eval.genesis_v2.secret_manager"):
    try:
        __import__(m); mods[m] = True
    except ImportError:
        mods[m] = False
facts["importable_privileged_modules"] = mods
print(json.dumps(facts, sort_keys=True))
