#!/usr/bin/env python3
"""Genesis V2 Tier-0 (Strategy A, Sovereign Local) -- reversible, SYNTHETIC-ONLY local isolation harness.

WHAT THIS IS: a harness that builds minimal Forge / Witness / harness container images and runs a full synthetic
write -> transfer -> decrypt -> backup -> restore scenario with ephemeral keys generated INSIDE a root provisioner container (the host
process never sees a key byte), then collects evidence about the isolation that was actually in force.

WHAT THIS IS NOT: real deployment acceptance. Tier0-B (single physical machine, container separation). Containers share one Linux VM
kernel and are all controlled by the same host user and Docker daemon; there are NO distinct host OS users (needs sudo, owner action) and
NO host firewall rules (pf needs root). Nothing here creates a real key/secret, touches a protected corpus/benchmark, calls a model,
uses a GPU/cloud/paid service, or flips any authorization. Every resource it creates carries the label orneur.tier0.run=<id> and is the
ONLY thing teardown ever removes.

CLI:  discover | build | verify | teardown <run_id>
"""
from __future__ import annotations

import json
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIER0 = ROOT / "infra" / "tier0-local"
RUN_LABEL = "orneur.tier0.run"
FORGE_UID, WITNESS_UID, COURIER_UID = 10001, 10002, 10003
IMAGES = {"forge": "orneur-tier0-forge:local", "witness": "orneur-tier0-witness:local", "harness": "orneur-tier0-harness:local"}
APP_FILES = ["orca/__init__.py", "orca/eval/__init__.py", "orca/eval/genesis_eval_v1.py", "orca/eval/genesis_v2/__init__.py",
             "orca/eval/genesis_v2/spec.py", "orca/eval/genesis_v2/store.py"]
SENTINEL = "SYNTHETIC-TIER0-"
# Allowlist (stronger than a deny-list): the ONLY env var names a role container may carry.
ALLOWED_ENV = {"PATH", "HOME", "HOSTNAME", "LANG", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "TERM"}
FORBIDDEN_ENV_FRAGMENTS = ("VAULT_PRIVATE", "CORPUS_SECRET", "OWNER", "QUALIFICATION", "GITHUB", "AWS_", "ANTHROPIC", "OPENAI", "NVIDIA", "GENESIS_V2")


class Tier0Error(RuntimeError):
    pass


def docker(*args, check=True, timeout=180) -> str:
    p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise Tier0Error(f"docker {' '.join(args[:3])} failed: {p.stderr.strip()[:400]}")
    return p.stdout


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def images_present() -> bool:
    return all(subprocess.run(["docker", "image", "inspect", i], capture_output=True).returncode == 0 for i in IMAGES.values())


# ------------------------------------------------------------------ capability discovery (sanitized: facts, no identifiers)
def discover_capabilities() -> dict:
    def sh(*cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:
            return ""
    caps = {"os": platform.system(), "os_version": platform.mac_ver()[0] or platform.release(), "arch": platform.machine(),
            "docker_cli": bool(shutil.which("docker")), "docker_daemon_reachable": docker_available()}
    if platform.system() == "Darwin":
        caps["ram_gb"] = round(int(sh("sysctl", "-n", "hw.memsize") or 0) / 2**30)
        caps["filevault"] = "On" in sh("fdesetup", "status")
        caps["app_firewall_enabled"] = "enabled" in sh("/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate").lower() and "disabled" not in sh("/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate").lower()
        caps["passwordless_sudo"] = subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0
    caps["disk_free_gb"] = round(shutil.disk_usage("/").free / 2**30)
    if caps["docker_daemon_reachable"]:
        info = json.loads(docker("info", "--format", "{{json .}}"))
        caps["docker"] = {"server_version": info.get("ServerVersion"), "cgroup_version": info.get("CgroupVersion"), "rootless": "rootless" in str(info.get("SecurityOptions")),
                          "security_options": [s.split(",")[0] for s in info.get("SecurityOptions", [])], "vm_cpus": info.get("NCPU"), "vm_mem_gb": round(info.get("MemTotal", 0) / 2**30, 1)}
    return caps


# ------------------------------------------------------------------ container construction (pure: unit-testable without docker)
def hardened_run_args(*, name: str, image: str, run_id: str, user: str, volumes: list, caps: tuple = (), detach: bool = False, cmd: list | None = None) -> list:
    """Every container this harness starts: no network, no caps beyond an explicit tiny list, read-only rootfs, no privilege escalation, no published ports,
    bounded resources, explicit env (none), and exactly the listed volumes (no docker.sock, no host paths)."""
    a = ["run", "--rm" if not detach else "-d", "--name", name, "--label", f"{RUN_LABEL}={run_id}", "--network", "none", "--cap-drop", "ALL"]
    for c in caps:
        a += ["--cap-add", c]
    a += ["--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m", "--pids-limit", "64", "--memory", "256m",
          "--cpus", "1", "--user", user]
    for vol, dest, mode in volumes:
        if mode not in ("ro", "rw"):
            raise ValueError(mode)
        a += ["-v", f"{vol}:{dest}:{mode}"]
    a.append(image)
    return a + (cmd or [])


class Tier0Run:
    def __init__(self):
        self.run_id = secrets.token_hex(4)
        self.p = f"orneur-tier0-{self.run_id}"
        self.vols = {n: f"{self.p}-{n}" for n in ("forge-secrets", "witness-secrets", "ingest", "vault", "vault-restored", "evidence", "reliquary", "owner")}
        self.evidence: dict = {}
        self._containers: list = []

    # -------- lifecycle
    def _vol(self, n):
        return self.vols[n]

    def _harness(self, role, image_key, user, vol_specs, caps, cmd) -> str:
        args = hardened_run_args(name=f"{self.p}-{role}", image=IMAGES[image_key], run_id=self.run_id, user=user,
                                 volumes=[(self._vol(v), d, m) for v, d, m in vol_specs], caps=caps, cmd=cmd)
        return docker(*args)

    def setup(self):
        for full in self.vols.values():
            docker("volume", "create", "--label", f"{RUN_LABEL}={self.run_id}", full)
        all_rw = [(n, f"/v/{n}", "rw") for n in self.vols]
        self._harness("provision", "harness", "0:0", all_rw, ("CHOWN", "FOWNER", "DAC_OVERRIDE"), ["python", "/roles/provision.py"])

    def start_roles(self):
        forge_vols = [("forge-secrets", "/secrets", "ro"), ("ingest", "/ingest", "rw")]
        witness_vols = [("witness-secrets", "/secrets", "ro"), ("vault", "/vault", "ro"), ("evidence", "/evidence", "rw")]
        for role, key, uid, vols in (("forge", "forge", FORGE_UID, forge_vols), ("witness", "witness", WITNESS_UID, witness_vols)):
            args = hardened_run_args(name=f"{self.p}-{role}", image=IMAGES[key], run_id=self.run_id, user=f"{uid}:{uid}", detach=True,
                                     volumes=[(self._vol(v), d, m) for v, d, m in vols], cmd=["sleep", "900"])
            docker(*args)
            self._containers.append(f"{self.p}-{role}")

    def exec(self, role, *cmd) -> str:
        uid = FORGE_UID if role == "forge" else WITNESS_UID
        return docker("exec", "-u", f"{uid}:{uid}", f"{self.p}-{role}", *cmd)

    def inspect(self, role) -> dict:
        return json.loads(docker("inspect", f"{self.p}-{role}"))[0]

    def audit(self, *args, vols) -> object:
        out = self._harness("audit", "harness", "0:0", [(v, f"/v/{v}", "ro") for v in vols], ("DAC_READ_SEARCH",), ["python", "/roles/audit.py", *args])
        return json.loads(out)

    def courier(self, src, dst, uid, manifest):
        out = self._harness("courier", "harness", "0:0", [(src, "/src", "ro"), (dst, "/dst", "rw")],
                            ("CHOWN", "FOWNER", "DAC_OVERRIDE"), ["python", "/roles/courier.py", "/src", "/dst", str(uid), "1" if manifest else "0"])
        return json.loads(out.strip().splitlines()[-1])

    def restored_verify(self, cid, dig) -> dict:
        """Item 14: decrypt FROM the restored copy with the correct witness identity (one-shot witness-image container, no network)."""
        out = self._harness("restored-verify", "witness", f"{WITNESS_UID}:{WITNESS_UID}",
                            [("witness-secrets", "/secrets", "ro"), ("vault-restored", "/vault", "ro"), ("evidence", "/evidence", "rw")], (),
                            ["python", "/roles/witness_verify.py", cid, dig])
        return json.loads(out.strip().splitlines()[-1])

    def teardown(self):
        for c in self._containers:
            docker("rm", "-f", c, check=False)
        for full in self.vols.values():
            docker("volume", "rm", "-f", full, check=False)
        self._containers = []

    # -------- the synthetic scenario
    def execute(self) -> dict:
        ev = self.evidence
        self.setup()
        self.start_roles()
        ev["forge_probe"] = json.loads(self.exec("forge", "python", "/roles/probe.py", "/secrets/vault_private_key", "/vault", "/evidence", "/owner", "/v", "/var/run/docker.sock"))
        ev["witness_probe"] = json.loads(self.exec("witness", "python", "/roles/probe.py", "/secrets/corpus_secret", "/ingest", "/owner", "/v", "/var/run/docker.sock"))
        ev["forge_inspect"], ev["witness_inspect"] = self.inspect("forge"), self.inspect("witness")
        ev["forge_write"] = json.loads(self.exec("forge", "python", "/roles/forge_write.py"))
        ev["forge_secret_files"] = json.loads(self.exec("forge", "python", "-c", "import os,json;print(json.dumps(sorted(os.listdir('/secrets'))))"))
        ev["witness_secret_files"] = json.loads(self.exec("witness", "python", "-c", "import os,json;print(json.dumps(sorted(os.listdir('/secrets'))))"))
        ev["witness_before_transfer_vault_empty"] = json.loads(self.exec("witness", "python", "-c", "import os,json;print(json.dumps(os.listdir('/vault')))")) == []
        cid, dig = ev["forge_write"]["corpus_id"], ev["forge_write"]["corpus_digest"]
        ev["transfer"] = self.courier("ingest", "vault", WITNESS_UID, False)
        ev["witness_verify"] = json.loads(self.exec("witness", "python", "/roles/witness_verify.py", cid, dig))
        ev["backup"] = self.courier("vault", "reliquary", COURIER_UID, True)
        ev["restore"] = self.courier("reliquary", "vault-restored", WITNESS_UID, False)
        ev["restore_equals_backup"] = {k: v for k, v in ev["restore"].items()} == {k: v for k, v in ev["backup"].items() if k != "MANIFEST.json"}
        ev["restored_verify"] = self.restored_verify(cid, dig)
        ev["app_tree"] = {r: json.loads(self.exec(r, "python", "-c", "import os,json;print(json.dumps(sorted(os.path.relpath(os.path.join(d,f),'/app') for d,_,fs in os.walk('/app') for f in fs)))")) for r in ("forge", "witness")}
        ev["vault_perms"] = self.audit("perms", "/v/vault", vols=["vault"])
        ev["ingest_perms"] = self.audit("perms", "/v/ingest", vols=["ingest"])
        ev["forge_secret_perms"] = self.audit("perms", "/v/forge-secrets", vols=["forge-secrets"])
        ev["witness_secret_perms"] = self.audit("perms", "/v/witness-secrets", vols=["witness-secrets"])
        ev["owner_perms"] = self.audit("perms", "/v/owner", vols=["owner"])
        scan_vols = [n for n in self.vols if n not in ("owner", "forge-secrets", "witness-secrets")]
        ev["plaintext_sentinel_hits"] = self.audit("scan", SENTINEL, *[f"/v/{n}" for n in scan_vols], vols=scan_vols)
        ev["reliquary_files"] = self.audit("list", "/v/reliquary", vols=["reliquary"])
        ev["evidence_files"] = self.audit("list", "/v/evidence", vols=["evidence"])
        ev["roles_concurrently_running"] = [self.inspect(r)["State"]["Running"] for r in ("forge", "witness")]
        # courier negative: a plaintext/foreign file must be refused at the transfer boundary
        ev["courier_refuses_plaintext"] = self._courier_refusal()
        return ev

    def _courier_refusal(self) -> bool:
        probe = f"{self.p}-refuse"
        docker("volume", "create", "--label", f"{RUN_LABEL}={self.run_id}", f"{probe}-src")
        docker("volume", "create", "--label", f"{RUN_LABEL}={self.run_id}", f"{probe}-dst")
        self.vols["refuse-src"], self.vols["refuse-dst"] = f"{probe}-src", f"{probe}-dst"
        docker("run", "--rm", "--network", "none", "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE", "--user", "0:0", "--label", f"{RUN_LABEL}={self.run_id}",
               "-v", f"{probe}-src:/s:rw", IMAGES["harness"], "python", "-c",
               f"import os;os.makedirs('/s/gce2c-{'ab'*8}');open('/s/gce2c-{'ab'*8}/SCREEN.enc','wb').write(b'{SENTINEL}plaintext-not-ciphertext')")
        args = hardened_run_args(name=f"{self.p}-refusal", image=IMAGES["harness"], run_id=self.run_id, user="0:0",
                                 volumes=[(f"{probe}-src", "/src", "ro"), (f"{probe}-dst", "/dst", "rw")], caps=("CHOWN", "FOWNER", "DAC_OVERRIDE"),
                                 cmd=["python", "/roles/courier.py", "/src", "/dst", "0", "0"])
        p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)
        return p.returncode != 0 and "REFUSED" in (p.stdout + p.stderr)


# ------------------------------------------------------------------ build
def stage_context(dest: Path) -> Path:
    for rel in APP_FILES:
        t = dest / "app" / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, t)
    shutil.copy2(TIER0 / "requirements-tier0.txt", dest / "requirements-tier0.txt")
    shutil.copytree(TIER0 / "roles", dest / "roles")
    return dest


def build_images(*, force: bool = False) -> dict:
    out = {}
    with tempfile.TemporaryDirectory(prefix="orneur-tier0-ctx-") as td:
        ctx = stage_context(Path(td))
        for role, tag in IMAGES.items():
            if not force and subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0:
                out[role] = "present"
                continue
            docker("build", "--pull=false", "-f", str(TIER0 / "docker" / f"Dockerfile.{role}"), "-t", tag, str(ctx), timeout=900)
            out[role] = "built"
    return out


def stale_run_ids() -> list:
    names = docker("ps", "-a", "--filter", f"label={RUN_LABEL}", "--format", "{{.Label \"" + RUN_LABEL + "\"}}").split()
    vols = docker("volume", "ls", "--filter", f"label={RUN_LABEL}", "--format", "{{.Label \"" + RUN_LABEL + "\"}}").split()
    return sorted(set(names) | set(vols))


def teardown_run(run_id: str) -> None:
    """Removes ONLY containers/volumes carrying label orneur.tier0.run=<run_id>. Never prunes, never touches unlabeled resources."""
    for c in docker("ps", "-aq", "--filter", f"label={RUN_LABEL}={run_id}").split():
        docker("rm", "-f", c, check=False)
    for v in docker("volume", "ls", "-q", "--filter", f"label={RUN_LABEL}={run_id}").split():
        docker("volume", "rm", "-f", v, check=False)


def main(argv: list) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "discover":
        print(json.dumps(discover_capabilities(), indent=2, sort_keys=True)); return 0
    if cmd == "build":
        print(json.dumps(build_images(force="--force" in argv))); return 0
    if cmd == "verify":
        r = Tier0Run()
        try:
            r.execute(); print(json.dumps({"run_id": r.run_id, "completed": True, "claim": "SYNTHETIC_TIER0B_CONTAINER_EVIDENCE_ONLY"}))
        finally:
            r.teardown()
        return 0
    if cmd == "teardown" and len(argv) > 2:
        teardown_run(argv[2]); return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
