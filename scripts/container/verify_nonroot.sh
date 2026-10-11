#!/usr/bin/env bash
# Verify the non-root container contract (PR #27 / #28) against a locally built image.
#
#   docker build -t orneur-verify -f Dockerfile .          # or a build with the same user/ownership layout
#   IMAGE=orneur-verify bash scripts/container/verify_nonroot.sh
#
# Needs a Docker daemon. Uses throw-away volumes and temp directories with synthetic files only; it never touches a real volume or production data.
# Prints one PASS/FAIL line per check; exit status is the number of FAIL lines.
set -u
IMAGE="${IMAGE:-orneur-verify}"
WORK="$(mktemp -d)"
chmod 777 "$WORK"          # root in a container can then create and re-own entries here even when the host user is unprivileged
FAILS=0
PFX="orneur-verify-$$"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENTRYPOINT_SH="$ROOT_DIR/docker/entrypoint-nonroot.sh"
# rootsh DIR 'script': run a shell script as root inside the image with DIR mounted at /w. The host user may be unprivileged (as on CI), so ALL
# ownership changes and reads of 10001-owned files happen here, never on the host.
rootsh() { docker run --rm --network=none --user 0 -v "$1:/w" "$IMAGE" sh -c "$2"; }
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1  -- $2"; FAILS=$((FAILS+1)); }
check() { local name="$1"; shift; local out; if out="$("$@" 2>&1)"; then pass "$name"; else fail "$name" "$(echo "$out" | tail -2 | tr '\n' ' ' | cut -c1-200)"; fi; }
expect_fail_with() { local name="$1" needle="$2"; shift 2; local out; if out="$("$@" 2>&1)"; then fail "$name" "expected refusal but it started"; elif echo "$out" | grep -q "$needle"; then pass "$name"; else fail "$name" "refused, but not with '$needle': $(echo "$out" | tail -1 | cut -c1-160)"; fi; }
run() { docker run --rm --network=none "$@"; }
IMPORT='import orca.config as c; print(c.ORCA_HOME)'

# C1 -- runs as UID 10001, not root
check "C1 default user is 10001" bash -c "[ \"\$(docker run --rm --network=none $IMAGE id -u)\" = 10001 ]"

# C2 -- first install on a NEW named volume (Docker copies the image's 10001/0700 ownership into it)
docker volume create "$PFX-new" >/dev/null
check "C2a new volume: app starts and creates its state" run -v "$PFX-new:/home/orneur/.orca" "$IMAGE" python -c "$IMPORT"
check "C2b new volume: root dir and subdirs are 10001 and 0700" bash -c "[ \"\$(docker run --rm --network=none -v $PFX-new:/home/orneur/.orca $IMAGE sh -c 'stat -c \"%u %a\" /home/orneur/.orca /home/orneur/.orca/* | sort -u')\" = '10001 700' ]"

# C3 -- EXISTING root-owned data (written by an older root-running image) is refused with a clear reason, not served
mkdir -p "$WORK/rootvol"; chmod 777 "$WORK/rootvol"
rootsh "$WORK/rootvol" 'echo synthetic-data > /w/marker.txt && chown 0:0 /w /w/marker.txt && chmod 755 /w' >/dev/null
expect_fail_with "C3 root-owned existing volume is refused (UntrustedStoreDirectory)" "UntrustedStoreDirectory\|not owned\|Untrusted" run -v "$WORK/rootvol:/home/orneur/.orca" "$IMAGE" python -c "$IMPORT"

# C4 -- the documented one-time migration (chown as root), then it starts and the data survived
check "C4a migration: chown as root" docker run --rm --network=none --user 0 -v "$WORK/rootvol:/home/orneur/.orca" "$IMAGE" sh -c 'chown -R 10001:10001 /home/orneur/.orca && chmod 700 /home/orneur/.orca'
check "C4b migration: starts after re-own" run -v "$WORK/rootvol:/home/orneur/.orca" "$IMAGE" python -c "$IMPORT"
check "C4c migration: existing data preserved" bash -c "[ \"\$(docker run --rm --network=none --user 0 -v $WORK/rootvol:/w $IMAGE cat /w/marker.txt)\" = synthetic-data ]"

# C5 -- Fly path: the checkout's docker/entrypoint-nonroot.sh (mounted, since only Dockerfile.fly bakes it in) starts as root, re-owns /data once, drops to 10001
EP="-v $ENTRYPOINT_SH:/usr/local/bin/entrypoint-nonroot.sh:ro"
mkdir -p "$WORK/flydata"; chmod 777 "$WORK/flydata"; rootsh "$WORK/flydata" 'echo fly-synthetic > /w/marker.txt && chown 0:0 /w /w/marker.txt'
check "C5a fly entrypoint: re-owns and runs as 10001" bash -c "[ \"\$(docker run --rm --network=none --user 0 -e ORNEUR_HOME=/data -v $WORK/flydata:/data $EP $IMAGE /usr/local/bin/entrypoint-nonroot.sh sh -c 'id -u; stat -c %u:%a /data')\" = \"\$(printf '10001\n10001:700')\" ]"
check "C5b fly entrypoint: data preserved" bash -c "[ \"\$(docker run --rm --network=none --user 0 -v $WORK/flydata:/w $IMAGE cat /w/marker.txt)\" = fly-synthetic ]"
check "C5c fly entrypoint: app can start on the re-owned volume" docker run --rm --network=none --user 0 -e ORNEUR_HOME=/data -v "$WORK/flydata:/data" $EP "$IMAGE" /usr/local/bin/entrypoint-nonroot.sh python -c "$IMPORT"

# C6 -- interrupted/partial migration: top level already 10001 but a subtree still root-owned (the entrypoint must not wave it through)
mkdir -p "$WORK/partial"; chmod 777 "$WORK/partial"
rootsh "$WORK/partial" 'mkdir -p /w/sub && echo x > /w/sub/f && chown 10001:10001 /w && chmod 700 /w'
check "C6 partial migration is repaired on start" docker run --rm --network=none --user 0 -e ORNEUR_HOME=/data -v "$WORK/partial:/data" $EP "$IMAGE" /usr/local/bin/entrypoint-nonroot.sh sh -c '[ "$(stat -c %u /data/sub/f)" = 10001 ]'

# C7 -- Kubernetes init container: the command is read FROM k8s/deployment.yaml (so the deployed text is what gets tested) and run with its capability set
K8S_INIT="$(python3 - <<'PY'
import re, sys
text = open("k8s/deployment.yaml").read()
m = re.search(r"name: fix-data-ownership.*?command:\n\s+- sh\n\s+- -c\n\s+- \|\n((?:\s{10}.*\n)+)", text, re.S)
print("\n".join(l.strip() for l in m.group(1).splitlines()))
PY
)"
[ -n "$K8S_INIT" ] && pass "C7a init command extracted from k8s/deployment.yaml" || fail "C7a init command extracted from k8s/deployment.yaml" "pattern not found"
mkdir -p "$WORK/k8s"; chmod 777 "$WORK/k8s"; rootsh "$WORK/k8s" 'echo k > /w/m && chown 0:0 /w /w/m'

check "C7b k8s init (drop ALL + CHOWN,FOWNER,DAC_OVERRIDE, no-new-privileges) migrates a root-owned volume" docker run --rm --network=none --user 0 --cap-drop ALL --cap-add CHOWN --cap-add FOWNER --cap-add DAC_OVERRIDE --security-opt no-new-privileges:true -v "$WORK/k8s:/data" "$IMAGE" sh -c "$K8S_INIT; [ \"\$(stat -c %u:%a /data)\" = 10001:700 ]"
mkdir -p "$WORK/k8sp"; chmod 777 "$WORK/k8sp"; rootsh "$WORK/k8sp" 'mkdir -p /w/sub && echo p > /w/sub/f && chown 10001:10001 /w && chmod 700 /w'
check "C7c k8s init repairs a partially migrated volume" docker run --rm --network=none --user 0 --cap-drop ALL --cap-add CHOWN --cap-add FOWNER --cap-add DAC_OVERRIDE --security-opt no-new-privileges:true -v "$WORK/k8sp:/data" "$IMAGE" sh -c "$K8S_INIT; [ \"\$(stat -c %u /data/sub/f)\" = 10001 ]"
mkdir -p "$WORK/k8s2"; chmod 777 "$WORK/k8s2"
expect_fail_with "C7d without CHOWN the same step cannot migrate (proves the capability is needed)" "Operation not permitted" docker run --rm --network=none --user 0 --cap-drop ALL --security-opt no-new-privileges:true -v "$WORK/k8s2:/data" "$IMAGE" sh -c 'chown -R 10001:10001 /data'

# C8 -- app container under the k8s main-container security context: no capabilities, no new privileges, read-only root filesystem
docker volume create "$PFX-ro" >/dev/null
check "C8a drop ALL + no-new-privileges + read-only rootfs: app imports and starts state" run --cap-drop ALL --security-opt no-new-privileges:true --read-only --tmpfs /tmp -v "$PFX-ro:/home/orneur/.orca" "$IMAGE" python -c "from orca.serve.api import app; import orca.config as c; print(len(app.routes), c.ORCA_HOME)"
check "C8b process holds no capabilities" bash -c "docker run --rm --network=none --cap-drop ALL $IMAGE sh -c 'grep CapEff /proc/self/status' | grep -q 0000000000000000"
check "C8c cannot write the application tree or become root" bash -c "docker run --rm --network=none $IMAGE sh -c '! touch /app/x 2>/dev/null && ! su -c id 2>/dev/null'"

# C9 -- execute-only (0711) ancestor owned by another user (PR #28): traversal must not need read permission
mkdir -p "$WORK/xo"; chmod 777 "$WORK/xo"
rootsh "$WORK/xo" 'mkdir -p /w/inner/state && chown 10001:10001 /w/inner/state && chmod 700 /w/inner/state && chown 0:0 /w/inner /w && chmod 711 /w/inner /w'
check "C9 execute-only ancestors: starts" run -e ORNEUR_HOME=/mnt/xo/inner/state -v "$WORK/xo:/mnt/xo" "$IMAGE" python -c "$IMPORT"

# C10 -- symlink / TOCTOU regressions inside the volume
docker volume create "$PFX-sym" >/dev/null
docker run --rm --network=none --user 0 -v "$PFX-sym:/home/orneur/.orca" "$IMAGE" sh -c 'chown 10001:10001 /home/orneur/.orca && chmod 700 /home/orneur/.orca && mkdir -p /elsewhere && ln -s /elsewhere /home/orneur/.orca/cache && chown -h 10001:10001 /home/orneur/.orca/cache' >/dev/null
expect_fail_with "C10a a symlinked state subdirectory is refused" "ymlink\|ntrusted\|not owned\|ELOOP\|Too many" run -v "$PFX-sym:/home/orneur/.orca" "$IMAGE" python -c "$IMPORT"

# C11 -- boot smoke as 10001: the server answers /livez and its process runs as 10001
docker volume create "$PFX-boot" >/dev/null
CID="$(docker run -d --network=host -e ORNEUR_HOME=/home/orneur/.orca -v "$PFX-boot:/home/orneur/.orca" "$IMAGE" orca serve --host 127.0.0.1 --port 17337 --no-open 2>/dev/null)"
ok=0; for i in $(seq 1 30); do sleep 2; if curl -fsS http://127.0.0.1:17337/livez >/dev/null 2>&1; then ok=1; break; fi; done
[ "$ok" = 1 ] && pass "C11a boot smoke: /livez answers" || fail "C11a boot smoke: /livez answers" "$(docker logs "$CID" 2>&1 | tail -2 | tr '\n' ' ' | cut -c1-200)"
uids="$(docker exec "$CID" python -c "import glob; print(' '.join(sorted({l.split()[1] for p in glob.glob('/proc/[0-9]*/status') for l in open(p) if l.startswith('Uid:')})))" 2>/dev/null)"
[ "$uids" = "10001" ] && pass "C11b every process in the container runs as uid 10001" || fail "C11b every process in the container runs as uid 10001" "uids: $uids"
docker rm -f "$CID" >/dev/null 2>&1

# cleanup of what THIS script created (named volumes with our unique prefix and our own mktemp dir; contents re-owned/removed from inside a root container)
for v in new ro sym boot; do docker volume rm "$PFX-$v" >/dev/null 2>&1; done
rootsh "$WORK" 'rm -rf /w/* /w/.[!.]* 2>/dev/null; true' >/dev/null 2>&1
rmdir "$WORK" 2>/dev/null
echo "FAILS=$FAILS"
exit "$FAILS"
