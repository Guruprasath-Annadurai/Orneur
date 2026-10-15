#!/usr/bin/env bash
# ORNEUR RSE Synthetic Integration Test Harness.
#
# SYNTHETIC ONLY. Read-only proof that the frozen IMP-1 authorization locks
# (orca/rse/imp1/locks.py) behave correctly in this container image. Creates
# no secret, authorizes nothing, never touches a protected benchmark, never
# writes to the real authorization manifests (mounted read-only below).
#
# Verified bash (not /bin/sh) is present with `pipefail` support in the base
# image this runs against (python:3.12-slim / Debian, bash 5.2) before this
# script relied on it.
#
# Every check below either passes or the script aborts immediately with a
# nonzero exit code via `set -e` -- there is no accumulate-then-report step
# that could itself hide a failure. The one prior bug class this replaces
# (a long `&&`/`||` one-liner where a `||` fallback silently "resumed" the
# chain past an earlier failure) cannot recur: there is no `||` anywhere in
# this script except inside explicit, self-contained `if` conditionals,
# which `set -e` does not trigger on and which each end their own branch in
# an explicit `exit 1` on the failing path.
set -euo pipefail

FIXTURE_ROOT="$(mktemp -d /tmp/rse-harness-fixtures.XXXXXX)"
trap 'rm -rf "$FIXTURE_ROOT"' EXIT

echo "=== RSE SYNTHETIC INTEGRATION TEST HARNESS ==="
echo "Image: ${HARNESS_IMAGE_LABEL:-unknown}"
echo "Python version:"
python3 --version
echo

echo "--- Import sanity ---"
python3 -c 'from orca.rse.imp1 import locks'
echo "OK IMP-1 locks module imported"
echo

echo "--- Positive: real authorization-lock evidence (/app/docs/orneur/authorization, read-only) => CHECKS_PASSED ---"
python3 <<'PY'
from orca.rse.imp1.locks import prove_authorization_locks

r = prove_authorization_locks()
assert r.ok, f"expected CHECKS_PASSED against the real frozen evidence, got {r.decision} ({r.reason})"
assert r.executable is False, "Result.executable must be False"
posture = dict(r.posture)
assert posture.get("training") is False, "training must be False"
assert posture.get("gpu") is False, "gpu must be False"
assert posture.get("corpus_generation") == "NOT_AUTHORIZED", "corpus_generation must be NOT_AUTHORIZED"
print(f"OK Authorization locks: {r.decision} ({r.reason}), executable={r.executable}, "
      f"training={posture.get('training')}, gpu={posture.get('gpu')}, "
      f"corpus_generation={posture.get('corpus_generation')}")
PY
echo

echo "--- Negative: missing manifests => FAIL_CLOSED ---"
python3 <<PY
from pathlib import Path
from orca.rse.imp1.locks import prove_authorization_locks

# An empty temp directory -- no docs/orneur/authorization/*.json at all.
# Never reads or writes anything under the real, mounted evidence path.
empty_root = Path("$FIXTURE_ROOT") / "empty"
empty_root.mkdir(parents=True)
r = prove_authorization_locks(root=empty_root)
assert not r.ok, f"expected FAIL_CLOSED for missing manifests, got {r.decision}"
assert r.decision == "FAIL_CLOSED"
assert r.executable is False
print(f"OK Missing manifests correctly refused: {r.decision} ({r.reason})")
PY
echo

echo "--- Negative: tampered synthetic manifest => FAIL_CLOSED with the specific reason ---"
python3 <<PY
import json
from pathlib import Path
from orca.rse.imp1.locks import prove_authorization_locks

# Fully synthetic fixtures, constructed in-script to match the schema
# orca/rse/imp1/locks.py reads -- independent of the real manifests'
# current contents, and written only under this process's own temp
# directory (tmpfs), never to the read-only mounted evidence path.
root = Path("$FIXTURE_ROOT") / "tampered"
auth_dir = root / "docs" / "orneur" / "authorization"
auth_dir.mkdir(parents=True)

valid_corpus = {"status": "NOT_AUTHORIZED"}
valid_model = {"status": "NOT_AUTHORIZED", "gpu_allowed": False,
               "network_provider_inference_allowed": False, "max_spend_usd": 0}
valid_runners = {"records": [{"state": "REGISTERED_NOT_AUTHORIZED"}]}


def write(root_dir, corpus, model, runners):
    (root_dir / "docs" / "orneur" / "authorization" / "CORPUS_GENERATION_AUTHORIZATION.json").write_text(json.dumps(corpus))
    (root_dir / "docs" / "orneur" / "authorization" / "MODEL_EVAL_AUTHORIZATION.json").write_text(json.dumps(model))
    (root_dir / "docs" / "orneur" / "authorization" / "QUALIFICATION_RUNNER_REGISTRY.json").write_text(json.dumps(runners))


# 1. Sanity: the synthetic baseline itself must be valid (proves the
#    tampering below is what trips the check, not a fixture mistake).
write(root, valid_corpus, valid_model, valid_runners)
baseline = prove_authorization_locks(root=root)
assert baseline.ok, f"synthetic baseline fixture is not valid: {baseline.decision} ({baseline.reason})"

# 2. Tamper the corpus lock status -- the one field locks.py checks first.
write(root, {**valid_corpus, "status": "AUTHORIZED"}, valid_model, valid_runners)
r = prove_authorization_locks(root=root)
assert not r.ok, f"expected FAIL_CLOSED for a tampered corpus lock, got {r.decision}"
assert r.reason == "CORPUS_LOCK", f"expected reason CORPUS_LOCK, got {r.reason}"
print(f"OK Tampered corpus manifest correctly refused: {r.decision} ({r.reason})")

# 3. Tamper the GPU posture -- a different field, different expected reason.
write(root, valid_corpus, {**valid_model, "gpu_allowed": True}, valid_runners)
r = prove_authorization_locks(root=root)
assert not r.ok and r.reason == "PROVIDER_LOCK", f"expected FAIL_CLOSED/PROVIDER_LOCK, got {r.decision} ({r.reason})"
print(f"OK Tampered GPU-allowed manifest correctly refused: {r.decision} ({r.reason})")

# 4. Qualification/model status -- a third, distinct branch (checked before
#    the provider/spend checks in locks.py, so this value alone must trip it
#    even though gpu_allowed/network_provider_inference_allowed stay valid).
write(root, valid_corpus, {**valid_model, "status": "AUTHORIZED"}, valid_runners)
r = prove_authorization_locks(root=root)
assert not r.ok and r.reason == "QUALIFICATION_LOCK", f"expected FAIL_CLOSED/QUALIFICATION_LOCK, got {r.decision} ({r.reason})"
print(f"OK Tampered qualification-status manifest correctly refused: {r.decision} ({r.reason})")

# 5. Provider lock's OTHER field -- network_provider_inference_allowed, not
#    just gpu_allowed (same reason, a genuinely different tampered field).
write(root, valid_corpus, {**valid_model, "network_provider_inference_allowed": True}, valid_runners)
r = prove_authorization_locks(root=root)
assert not r.ok and r.reason == "PROVIDER_LOCK", f"expected FAIL_CLOSED/PROVIDER_LOCK, got {r.decision} ({r.reason})"
print(f"OK Tampered network-provider-inference-allowed manifest correctly refused: {r.decision} ({r.reason})")

# 6. Spend lock -- a nonzero, non-None max_spend_usd.
write(root, valid_corpus, {**valid_model, "max_spend_usd": 1}, valid_runners)
r = prove_authorization_locks(root=root)
assert not r.ok and r.reason == "SPEND_LOCK", f"expected FAIL_CLOSED/SPEND_LOCK, got {r.decision} ({r.reason})"
print(f"OK Tampered max-spend-usd manifest correctly refused: {r.decision} ({r.reason})")

# 7. Runner lock, empty-records branch.
write(root, valid_corpus, valid_model, {"records": []})
r = prove_authorization_locks(root=root)
assert not r.ok and r.reason == "RUNNER_LOCK", f"expected FAIL_CLOSED/RUNNER_LOCK (empty records), got {r.decision} ({r.reason})"
print(f"OK Empty runner-registry manifest correctly refused: {r.decision} ({r.reason})")

# 8. Runner lock, not-a-list branch (records present but malformed shape).
write(root, valid_corpus, valid_model, {"records": "not-a-list"})
r = prove_authorization_locks(root=root)
assert not r.ok and r.reason == "RUNNER_LOCK", f"expected FAIL_CLOSED/RUNNER_LOCK (non-list records), got {r.decision} ({r.reason})"
print(f"OK Non-list runner-registry manifest correctly refused: {r.decision} ({r.reason})")

# 9. Runner lock, a registered runner whose state isn't REGISTERED_NOT_AUTHORIZED.
write(root, valid_corpus, valid_model, {"records": [{"state": "REGISTERED_NOT_AUTHORIZED"}, {"state": "AUTHORIZED"}]})
r = prove_authorization_locks(root=root)
assert not r.ok and r.reason == "RUNNER_LOCK", f"expected FAIL_CLOSED/RUNNER_LOCK (bad runner state), got {r.decision} ({r.reason})"
print(f"OK Runner-registry manifest with one non-REGISTERED_NOT_AUTHORIZED row correctly refused: {r.decision} ({r.reason})")

# 10. Malformed JSON -- not even valid JSON syntax, as opposed to valid JSON
#     with a tampered value (cases 2-9 above). A distinct failure mode: this
#     must fail inside json.loads itself, caught by @guard's generic
#     exception handler, same reason as the "missing manifests" case above.
syntax_root = Path("$FIXTURE_ROOT") / "malformed-json"
syntax_dir = syntax_root / "docs" / "orneur" / "authorization"
syntax_dir.mkdir(parents=True)
(syntax_dir / "CORPUS_GENERATION_AUTHORIZATION.json").write_text("{not valid json: ,,,")
(syntax_dir / "MODEL_EVAL_AUTHORIZATION.json").write_text(json.dumps(valid_model))
(syntax_dir / "QUALIFICATION_RUNNER_REGISTRY.json").write_text(json.dumps(valid_runners))
r = prove_authorization_locks(root=syntax_root)
assert not r.ok, f"expected FAIL_CLOSED for syntactically invalid JSON, got {r.decision}"
assert r.decision == "FAIL_CLOSED"
print(f"OK Syntactically invalid JSON correctly refused: {r.decision} ({r.reason})")

# 11. Valid JSON, wrong top-level shape -- a JSON array instead of an
#     object. _read_json() explicitly rejects any non-dict top level; this
#     is a different code path from "doesn't parse at all" (case 10).
shape_root = Path("$FIXTURE_ROOT") / "wrong-shape"
shape_dir = shape_root / "docs" / "orneur" / "authorization"
shape_dir.mkdir(parents=True)
(shape_dir / "CORPUS_GENERATION_AUTHORIZATION.json").write_text(json.dumps(["not", "an", "object"]))
(shape_dir / "MODEL_EVAL_AUTHORIZATION.json").write_text(json.dumps(valid_model))
(shape_dir / "QUALIFICATION_RUNNER_REGISTRY.json").write_text(json.dumps(valid_runners))
r = prove_authorization_locks(root=shape_root)
assert not r.ok, f"expected FAIL_CLOSED for a non-object top-level JSON value, got {r.decision}"
assert r.decision == "FAIL_CLOSED"
print(f"OK Non-object top-level JSON correctly refused: {r.decision} ({r.reason})")
PY
echo
echo "NOTE on branch coverage: orca/rse/imp1/locks.py has one more FAIL_CLOSED"
echo "branch, \"POSTURE\" -- it checks orca.rse.imp1.verdict.POSTURE, a fixed"
echo "code-level constant tuple, not a value read from any of these JSON"
echo "files. It cannot be exercised by tampering with a mounted/synthetic"
echo "manifest (that would require editing orca/rse/imp1/verdict.py itself,"
echo "which this harness must not do -- frozen RSE kernel). Documented here"
echo "as a known, structurally-unreachable-from-this-harness gap, not"
echo "silently skipped."
echo

echo "--- Control: a deliberately failed required assertion must abort this harness with a nonzero exit ---"
if [[ "${RSE_HARNESS_SELFTEST_CONTROL:-0}" == "1" ]]; then
  echo "RSE_HARNESS_SELFTEST_CONTROL=1: intentionally failing now to prove failures cannot be masked."
  python3 -c 'assert False, "deliberate control failure -- this line proves set -e propagates a real failure"'
  echo "UNREACHABLE: if this line ever prints, failure masking has regressed." >&2
  exit 1
else
  echo "SKIPPED (set RSE_HARNESS_SELFTEST_CONTROL=1 in a separate run to exercise this; the main run stays a true positive/negative suite, not a self-failing one)"
fi
echo

echo "--- Network isolation (network_mode: none) ---"
python3 <<'PY'
import errno
import socket
import sys

# NOT an interface-name check: every Linux network namespace -- including
# one created by `--network none`, which has no veth/eth0 at all -- still
# auto-creates several stock kernel tunnel pseudo-devices (erspan0, gre0,
# sit0, ip6_vti0, ...) whenever the corresponding kernel modules are loaded
# on the host, regardless of container network isolation. An earlier
# version of this check asserted `socket.if_nameindex() == ["lo"]`, which is
# true on some hosts and false on others for reasons that have nothing to do
# with whether THIS container can actually reach the network -- a
# non-deterministic, misleading signal. The property that actually matters
# is whether there is any route at all: with no route, there is no gateway
# to address a packet to, independent of how many unused pseudo-interfaces
# exist. `--network none` leaves /proc/net/route with a header and zero
# rows (verified empirically against this exact image: a bridge-networked
# run of the same image shows a default route via eth0; a
# --network none run shows none).
with open("/proc/net/route") as f:
    rows = [line for line in f.read().splitlines()[1:] if line.strip()]
if rows:
    print(f"FAIL: expected an empty IPv4 routing table (network_mode: none), found {len(rows)} route(s): {rows}",
          file=sys.stderr)
    sys.exit(1)
print("OK IPv4 routing table is empty -- no gateway exists for any address to be reachable through")

# "Do not classify every network error as proof of isolation": only the
# specific errno a missing route actually produces counts. ECONNREFUSED
# (a packet reached somewhere and got rejected -- the OPPOSITE of
# isolation), a timeout (ambiguous -- could mean a slow/filtered path
# rather than no route at all), or any other OSError are each treated as a
# DISTINCT, unexpected outcome and fail the check, rather than being folded
# into "egress refused, so isolation must be working."
EXPECTED_NO_ROUTE_ERRNOS = {errno.ENETUNREACH, errno.EHOSTUNREACH}

def probe(family, host, port, label):
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect((host, port))
    except OSError as exc:
        if exc.errno in EXPECTED_NO_ROUTE_ERRNOS:
            print(f"OK Egress to {label} refused with the expected no-route errno "
                  f"({errno.errorcode.get(exc.errno, exc.errno)}: {exc})")
        else:
            print(f"FAIL: egress to {label} failed, but NOT with a no-route errno -- "
                  f"got {errno.errorcode.get(exc.errno, exc.errno)}: {exc}. This is not "
                  f"classified as proof of isolation.", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"FAIL: egress to {label} succeeded -- network isolation is not in effect", file=sys.stderr)
        sys.exit(1)
    finally:
        s.close()

for host, port, label in (("8.8.8.8", 53, "8.8.8.8:53 (IPv4)"), ("1.1.1.1", 53, "1.1.1.1:53 (IPv4)")):
    probe(socket.AF_INET, host, port, label)

# IPv6. HONEST LIMITATION, not glossed over: on this Docker Desktop setup,
# the host's Docker daemon does not provision IPv6 for ANY container
# network, isolated or not -- a normal bridge-networked container shows the
# IDENTICAL /proc/net/if_inet6 (loopback only) and /proc/net/ipv6_route
# (three loopback-scoped rows, same as below) as a --network none one, and
# gets the SAME ENETUNREACH on an IPv6 connect attempt (verified empirically
# against this exact image before writing this check). So neither of these
# IPv6 signals, on their own, discriminates "network_mode: none" from
# "Docker on this host just doesn't do IPv6". They are still real, genuine
# IPv6 egress-denial evidence (worth having), but the AUTHORITATIVE
# confirmation of the effective Docker network mode is the external,
# host-side `docker inspect --format '{{.HostConfig.NetworkMode}}'` check in
# scripts/rse_docker_lab_verify.sh, run from outside the container (this
# entrypoint deliberately has no docker.sock mount -- that would be a far
# larger privilege-escalation surface than the property it would verify).
with open("/proc/net/ipv6_route") as f:
    v6_rows = [line for line in f.read().splitlines() if line.strip()]
non_loopback_v6 = [row for row in v6_rows if not row.rstrip().endswith(" lo")]
if non_loopback_v6:
    print(f"FAIL: found a non-loopback IPv6 route: {non_loopback_v6}", file=sys.stderr)
    sys.exit(1)
print(f"OK IPv6 routing table has only loopback-scoped entries ({len(v6_rows)} row(s), all via 'lo'). "
      f"NOTE: on this host this is also true under a normal (non-isolated) network -- see comment above.")

for host, port, label in (("2001:4860:4860::8888", 53, "2001:4860:4860::8888:53 (IPv6)"),
                          ("2606:4700:4700::1111", 53, "2606:4700:4700::1111:53 (IPv6)")):
    probe(socket.AF_INET6, host, port, label)
PY
echo

echo "=== RSE TEST HARNESS COMPLETE ==="
echo "OK all positive, negative and isolation checks passed"
