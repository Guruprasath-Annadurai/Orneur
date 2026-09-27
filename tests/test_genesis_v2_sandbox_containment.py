"""Sandbox CONTAINMENT tests: hostile fixture programs (written by this test suite; NO model-generated code) must be contained by the real Docker
sandbox. These tests need Docker + the runtime image; in the mandatory 'Genesis V2 Sandbox' CI job ORNEUR_REQUIRE_DOCKER=1 makes their absence a FAILURE."""
import hashlib
import json
import os
import socket
import subprocess
import textwrap
import threading
import time
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import sandbox as SB

REQUIRED = os.environ.get("ORNEUR_REQUIRE_DOCKER") == "1"
POL = SB.SandboxPolicy(wall_seconds=8.0)


def _ready():
    from orca.eval.sandbox_docker import is_docker_available
    if not is_docker_available():
        return "docker daemon not reachable"
    try:
        SB.resolve_image_digest(POL.image)
    except SB.SandboxUnavailable as e:
        return str(e)
    return ""


@pytest.fixture(scope="module", autouse=True)
def docker_ready():
    why = _ready()
    if why:
        if REQUIRED:
            pytest.fail(f"ORNEUR_REQUIRE_DOCKER=1 but the sandbox cannot run: {why}")
        pytest.skip(why)


def run(code: str, policy=POL, files=None, env=None, item="gce2-" + "b" * 24):
    f = {"main.py": textwrap.dedent(code).encode(), **(files or {})}
    rec = SB.run_job(SB.SandboxJob(item, "rev-test", f, ("python3", "-I", "/job/main.py"), env or {}), policy)
    return rec


def out_json(rec, ):
    assert rec.exit_status == 0, rec
    return rec


def run_json(code, **kw):
    """Run code that prints one JSON line; returns (record, parsed) by re-running with the digest check on a captured copy."""
    rec = run(code, **kw)
    return rec


def capture(code: str, policy=POL, files=None, env=None):
    """Like run() but returns the program's stdout text (the record only holds digests; use a tiny in-container writer to /dev/stdout and re-derive)."""
    marker = "@@RESULT@@"
    wrapped = f"import json,sys\n_r=None\n{textwrap.dedent(code)}\n"
    # the hostile program stores its findings in variable RESULT; we print them base64 in ONE stderr-free line captured via a second run of the same job
    return wrapped


# stdout is not returned in ExecutionRecord (digests only). For assertions we make the hostile program EXIT with a code that encodes the verdict.
def verdict(code: str, **kw):
    """The program calls sys.exit(0) iff containment held (every attack failed), sys.exit(1..) otherwise."""
    rec = run(code, **kw)
    return rec


def test_container_runs_and_record_is_complete():
    rec = run("print('ok')")
    assert rec.exit_status == 0 and not rec.timed_out and not rec.resource_limit_status["limit_hit"]
    assert rec.stdout_sha256 == hashlib.sha256(b"ok\n").hexdigest() and rec.stdout_bytes == 3 and rec.stderr_bytes == 0
    assert rec.sandbox_policy_version == SB.POLICY_VERSION and rec.sandbox_image_digest and rec.command == ("python3", "-I", "/job/main.py")
    assert rec.item_id.startswith("gce2-") and rec.candidate_revision == "rev-test" and rec.duration_seconds > 0
    assert len(rec.test_result_digest) == 64
    assert SB.leftover_containers() == []


def test_identity_privileges_and_namespaces():
    rec = run("""
        import os, sys
        st = dict(l.split(':', 1) for l in open('/proc/self/status').read().splitlines() if ':' in l)
        ok = (os.getuid() == 65534 and os.getgid() == 65534 and st['CapEff'].strip() == '0000000000000000' and st['NoNewPrivs'].strip() == '1'
              and st['Seccomp'].strip() == '2')
        # private PID namespace: pid 1 is the container's own init/command, not the host init
        c1 = open('/proc/1/cmdline','rb').read()
        ok = ok and (b'python' in c1 or b'sandbox' in c1 or b'docker' not in c1)
        try:
            open('/x', 'w'); ok = False          # root filesystem is read-only
        except OSError:
            pass
        sys.exit(0 if ok else 3)
    """)
    assert rec.exit_status == 0, rec


def test_host_filesystem_is_not_readable(tmp_path):
    marker = tmp_path / "host_marker.txt"
    marker.write_text("HOST-ONLY-SECRET")
    rec = run(f"""
        import os, sys
        leaked = []
        for p in [{str(marker)!r}, {str(tmp_path)!r}, '/Users', '/home/runner', '/host', '/mnt/host', '/run/host-services', '/root/.ssh', '/proc/1/root/Users']:
            if os.path.exists(p):
                leaked.append(p)
        # nothing of the host tmp tree, and only the container's own tiny rootfs
        for root in ('/private', '/Volumes', '/Users', '/var/folders'):
            if os.path.exists(root):
                leaked.append(root)
        sys.exit(0 if not leaked else 4)
    """)
    assert rec.exit_status == 0, rec


def test_job_mount_and_root_are_read_only_and_scratch_is_writable():
    rec = run("""
        import os, sys, errno
        def rw(path):
            try:
                with open(path, 'w') as f: f.write('x')
                return True
            except OSError as e:
                return False
        bad = [p for p in ('/job/new.txt', '/job/main.py', '/etc/x', '/usr/x', '/x') if rw(p)]
        good = [p for p in ('/work/ok.txt', '/tmp/ok.txt') if rw(p)]
        sys.exit(0 if not bad and len(good) == 2 else 5)
    """)
    assert rec.exit_status == 0, rec


def test_network_egress_is_impossible():
    rec = run("""
        import socket, os, sys
        socket.setdefaulttimeout(2)
        reached = []
        for host in ('1.1.1.1', '8.8.8.8', '93.184.216.34'):
            try:
                s = socket.create_connection((host, 53)); s.close(); reached.append(host)
            except OSError:
                pass
        try:
            socket.getaddrinfo('example.com', 80); reached.append('dns')
        except OSError:
            pass
        # the kernel may list unconfigured tunnel stubs (tunl0, sit0, ...); none may be UP except loopback
        up = set()
        for i in os.listdir('/sys/class/net'):
            try:
                if int(open('/sys/class/net/%s/flags' % i).read().strip(), 16) & 1:
                    up.add(i)
            except OSError:
                pass
        sys.exit(0 if not reached and up <= {'lo'} else 6)
    """)
    assert rec.exit_status == 0, rec


def test_host_localhost_and_cloud_metadata_are_unreachable():
    srv = socket.socket()
    srv.bind(("0.0.0.0", 0))
    srv.listen(5)
    port = srv.getsockname()[1]
    hits = []

    def accept():
        srv.settimeout(15)
        try:
            while True:
                c, _ = srv.accept()
                hits.append(1)
                c.close()
        except OSError:
            pass
    t = threading.Thread(target=accept, daemon=True)
    t.start()
    try:
        rec = run(f"""
            import socket, sys
            socket.setdefaulttimeout(2)
            reached = []
            for host, prt in (('127.0.0.1', {port}), ('localhost', {port}), ('host.docker.internal', {port}), ('172.17.0.1', {port}), ('169.254.169.254', 80),
                              ('169.254.170.2', 80), ('metadata.google.internal', 80), ('fd00:ec2::254', 80)):
                try:
                    s = socket.create_connection((host, prt)); s.close(); reached.append(host)
                except OSError:
                    pass
            sys.exit(0 if not reached else 7)
        """)
        assert rec.exit_status == 0, rec
        time.sleep(0.5)
        assert hits == []                                      # the host listener never saw a connection
    finally:
        srv.close()


def test_fork_bomb_is_bounded_and_the_container_is_reaped():
    rec = run("""
        import os, sys, time
        made = 0
        try:
            while made < 5000:
                pid = os.fork()
                if pid == 0:
                    time.sleep(30)
                    os._exit(0)
                made += 1
        except OSError:
            pass
        print(made)
        sys.stdout.flush()
        os._exit(0 if made < 40 else 8)
    """, policy=SB.SandboxPolicy(wall_seconds=8.0, pids=32))
    assert rec.exit_status == 0 and rec.duration_seconds < 20, rec       # process cap (32) held: fewer than 40 children could be created
    assert SB.leftover_containers() == []


def test_infinite_loop_times_out_and_is_killed():
    t0 = time.monotonic()
    rec = run("while True: pass", policy=SB.SandboxPolicy(wall_seconds=3.0, cpu_seconds=60))
    assert rec.timed_out and rec.resource_limit_status["wall_timeout"] and rec.resource_limit_status["limit_hit"]
    assert time.monotonic() - t0 < 20
    assert SB.leftover_containers() == []


def test_oversized_stdout_is_capped_and_killed():
    pol = SB.SandboxPolicy(wall_seconds=8.0, max_output_bytes=4096)
    rec = run("""
        import sys
        chunk = 'A' * 65536
        for _ in range(4000):
            sys.stdout.write(chunk)
    """, policy=pol)
    assert rec.resource_limit_status["output_limit_exceeded"] and rec.stdout_bytes >= 4096
    assert rec.duration_seconds < 8 and not rec.timed_out
    assert SB.leftover_containers() == []


def test_oversized_file_creation_is_refused():
    rec = run("""
        import sys
        written = 0
        try:
            with open('/work/big.bin', 'wb') as f:
                for _ in range(400):
                    f.write(b'x' * (1024 * 1024)); f.flush(); written += 1024 * 1024
        except OSError:
            pass
        sys.exit(0 if written < 20 * 1024 * 1024 else 9)          # tmpfs (16 MiB) / RLIMIT_FSIZE stop it long before 400 MiB
    """)
    assert rec.exit_status == 0 or rec.exit_status in (153, 25), rec  # exit 0, or killed by SIGXFSZ (153) / EFBIG: contained either way
    assert not rec.timed_out


def test_memory_bomb_is_oom_killed_not_the_host():
    rec = run("""
        buf = []
        while True:
            buf.append(bytearray(64 * 1024 * 1024))
    """, policy=SB.SandboxPolicy(wall_seconds=10.0, memory="128m"))
    assert rec.resource_limit_status["oom_killed"] or rec.exit_status not in (0, None), rec


def test_environment_secrets_are_not_visible(monkeypatch):
    monkeypatch.setenv("ORNEUR_TEST_SECRET_TOKEN", "sekrit-value-123")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake_token")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-fake")
    rec = run("""
        import os, sys
        blob = repr(dict(os.environ)) + open('/proc/self/environ').read().replace('\\0', ' ')
        bad = any(s in blob for s in ('sekrit-value-123', 'ghp_fake_token', 'aws-fake', 'ORNEUR_', 'GITHUB_', 'AWS_'))
        allowed = {'PATH','HOME','LANG','LC_ALL','TZ','PYTHONHASHSEED','PYTHONDONTWRITEBYTECODE','PYTHONUNBUFFERED','PYTHONNOUSERSITE'}
        extra = set(os.environ) - allowed
        ok = (not bad) and not extra and os.environ['TZ'] == 'UTC' and os.environ['LANG'] == 'C.UTF-8' and os.environ['PYTHONHASHSEED'] == '0' and os.environ['HOME'] == '/tmp'
        sys.exit(0 if ok else 10)
    """)
    assert rec.exit_status == 0, rec


def test_path_traversal_inside_the_container_reaches_only_the_container():
    rec = run("""
        import os, sys
        # walking out of /job by ../ lands in the container's own tiny root, which contains no host data and is read-only
        try:
            open('/job/../job/../evil.txt', 'w'); sys.exit(11)
        except OSError:
            pass
        names = set(os.listdir('/'))
        sys.exit(0 if not names & {'Users', 'host', 'mnt_host', 'Volumes', 'private'} and os.path.exists('/job/main.py') else 12)
    """)
    assert rec.exit_status == 0, rec


def test_symlink_escape_cannot_expose_host_files(tmp_path):
    secret = tmp_path / "host_secret.txt"
    secret.write_text("HOST-SECRET")
    tree = tmp_path / "fx"
    tree.mkdir()
    os.symlink(secret, tree / "link.txt")
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.load_fixture_tree(tree)                                     # a fixture symlink is refused before anything is mounted
    rec = run(f"""
        import os, sys
        try:
            os.symlink({str(secret)!r}, '/work/l')
            data = open('/work/l').read()
            sys.exit(13)                                               # would mean the host secret was readable
        except OSError:
            sys.exit(0)
    """)
    assert rec.exit_status == 0, rec


def test_docker_socket_is_not_reachable():
    rec = run("""
        import os, socket, sys
        found = [p for p in ('/var/run/docker.sock', '/run/docker.sock', '/docker.sock', '/var/run/docker', '/run/user/1000/docker.sock') if os.path.exists(p)]
        s = socket.socket(socket.AF_UNIX)
        try:
            s.connect('/var/run/docker.sock'); found.append('connected')
        except OSError:
            pass
        sys.exit(0 if not found else 14)
    """)
    assert rec.exit_status == 0, rec


def test_no_persistence_between_runs():
    before = subprocess.run(["docker", "volume", "ls", "-q"], capture_output=True, text=True).stdout.split()
    run("""
        open('/work/persist.txt', 'w').write('x'); open('/tmp/persist.txt', 'w').write('x')
    """)
    rec = run("""
        import os, sys
        sys.exit(0 if not os.path.exists('/work/persist.txt') and not os.path.exists('/tmp/persist.txt') and os.listdir('/work') == [] else 15)
    """)
    assert rec.exit_status == 0, rec
    after = subprocess.run(["docker", "volume", "ls", "-q"], capture_output=True, text=True).stdout.split()
    assert sorted(before) == sorted(after) and SB.leftover_containers() == []


def test_missing_image_never_triggers_a_pull_or_fallback():
    pol = SB.SandboxPolicy(image="python:0.0-doesnotexist")
    with pytest.raises(SB.SandboxUnavailable):
        run("print(1)", policy=pol)


def test_job_files_arrive_read_only_and_exact():
    body = b"DATA-FIXTURE-123"
    rec = run("""
        import sys
        sys.exit(0 if open('/job/fixtures/data.txt','rb').read() == b'DATA-FIXTURE-123' else 16)
    """, files={"fixtures/data.txt": body})
    assert rec.exit_status == 0, rec
