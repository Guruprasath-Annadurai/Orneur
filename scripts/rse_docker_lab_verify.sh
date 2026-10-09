#!/usr/bin/env bash
# ORNEUR RSE Synthetic Integration Docker Lab -- end-to-end verification.
#
# Builds the image FROM the exact checked-out commit (not a possibly-stale
# local image), proves the built image's /app/orca content is byte-for-byte
# identical to this commit's orca/ tree, runs both the normal and the
# deliberate-failure harness scenarios via `docker compose up
# --exit-code-from`, verifies the effective Docker network mode and
# resource limits from OUTSIDE the container (never via a docker.sock mount
# inside it), and leaves no container or volume behind either way.
#
# Usable both locally and as the CI step for this (exit code is the single
# source of truth either way).
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

COMPOSE_FILE="docker-rse-integration-lab.yml"
SERVICE="rse-test-runner"
CONTAINER="orneur-rse-test"
IMAGE_TAG="orneur-rse:latest"

FAIL=0
note() { echo; echo "=== $1 ==="; }
ok()   { echo "OK   $1"; }
bad()  { echo "FAIL $1" >&2; FAIL=1; }

sha256_tool() {
  if command -v sha256sum >/dev/null 2>&1; then echo "sha256sum"; else echo "shasum -a 256"; fi
}

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

note "Source identity"
SOURCE_SHA="$(git rev-parse HEAD)"
echo "Source commit: $SOURCE_SHA"

note "Build image from this exact checkout"
docker build -t "$IMAGE_TAG" . >/tmp/rse-lab-build.log 2>&1 || { cat /tmp/rse-lab-build.log; bad "image build"; exit 1; }
IMAGE_ID="$(docker image inspect "$IMAGE_TAG" --format '{{.Id}}')"
echo "Image: $IMAGE_TAG"
echo "Image ID (content digest): $IMAGE_ID"

note "Source-to-image reproducibility: orca/ tree hash (host) vs /app/orca (image)"
SHATOOL="$(sha256_tool)"
HOST_HASH="$(find orca -type f -print0 | sort -z | xargs -0 $SHATOOL | $SHATOOL | awk '{print $1}')"
IMAGE_HASH="$(docker run --rm --entrypoint sh "$IMAGE_TAG" -c \
  "find /app/orca -type f -print0 | sort -z | xargs -0 sha256sum | sed 's#/app/##'" | $SHATOOL | awk '{print $1}')"
echo "host orca/ tree hash:        $HOST_HASH"
echo "image /app/orca/ tree hash:  $IMAGE_HASH"
if [[ "$HOST_HASH" == "$IMAGE_HASH" ]]; then
  ok "image content is byte-for-byte identical to commit $SOURCE_SHA's orca/ tree"
else
  bad "image content does NOT match the source commit's orca/ tree"
fi

run_scenario() {
  local label="$1" expect_exit="$2"
  shift 2
  note "Scenario: $label (expect docker compose exit $expect_exit)"
  cleanup
  set +e
  env "$@" docker compose -f "$COMPOSE_FILE" up --exit-code-from "$SERVICE" >/tmp/rse-lab-run.log 2>&1
  local actual_exit=$?
  set -e
  cat /tmp/rse-lab-run.log
  local container_exit
  container_exit="$(docker inspect "$CONTAINER" --format '{{.State.ExitCode}}')"
  echo "docker compose up exit code: $actual_exit | container State.ExitCode: $container_exit"
  if [[ "$actual_exit" == "$expect_exit" && "$container_exit" == "$expect_exit" ]]; then
    ok "$label: exit codes match (compose=$actual_exit, container=$container_exit)"
  else
    bad "$label: expected exit $expect_exit, got compose=$actual_exit container=$container_exit"
  fi

  note "Effective Docker network mode and resource limits (host-side docker inspect, no docker.sock in the container)"
  local net mem memswap nanocpus pids ro capdrop capadd secopt
  net="$(docker inspect "$CONTAINER" --format '{{.HostConfig.NetworkMode}}')"
  mem="$(docker inspect "$CONTAINER" --format '{{.HostConfig.Memory}}')"
  memswap="$(docker inspect "$CONTAINER" --format '{{.HostConfig.MemorySwap}}')"
  nanocpus="$(docker inspect "$CONTAINER" --format '{{.HostConfig.NanoCpus}}')"
  pids="$(docker inspect "$CONTAINER" --format '{{.HostConfig.PidsLimit}}')"
  ro="$(docker inspect "$CONTAINER" --format '{{.HostConfig.ReadonlyRootfs}}')"
  capdrop="$(docker inspect "$CONTAINER" --format '{{.HostConfig.CapDrop}}')"
  capadd="$(docker inspect "$CONTAINER" --format '{{.HostConfig.CapAdd}}')"
  secopt="$(docker inspect "$CONTAINER" --format '{{.HostConfig.SecurityOpt}}')"
  echo "NetworkMode=$net Memory=$mem MemorySwap=$memswap NanoCpus=$nanocpus PidsLimit=$pids ReadonlyRootfs=$ro CapDrop=$capdrop CapAdd=$capadd SecurityOpt=$secopt"
  [[ "$net" == "none" ]] && ok "effective network mode is 'none'" || bad "effective network mode is '$net', expected 'none'"
  [[ "$mem" == "268435456" ]] && ok "memory limit is 256MiB" || bad "memory limit is $mem, expected 268435456"
  [[ "$nanocpus" == "1000000000" ]] && ok "cpu limit is 1.0" || bad "cpu limit is $nanocpus, expected 1000000000"
  [[ "$pids" == "64" ]] && ok "pids limit is 64" || bad "pids limit is $pids, expected 64"
  [[ "$ro" == "true" ]] && ok "root filesystem is read-only" || bad "root filesystem read-only is $ro, expected true"
  [[ "$capdrop" == "[ALL]" ]] && ok "all capabilities dropped" || bad "CapDrop is $capdrop, expected [ALL]"
  [[ "$capadd" == "[]" || "$capadd" == "<no value>" ]] && ok "no capabilities added" || bad "CapAdd is $capadd, expected none"

  cleanup
}

run_scenario "normal (positive + negative + isolation checks)" 0
run_scenario "deliberate control failure" 1 RSE_HARNESS_SELFTEST_CONTROL=1

note "Post-test cleanup check"
LEFTOVER="$(docker ps -a --filter "name=$CONTAINER" --format '{{.Names}}')"
if [[ -z "$LEFTOVER" ]]; then
  ok "no leftover containers named $CONTAINER"
else
  bad "leftover container still present: $LEFTOVER"
fi

note "Summary"
echo "Source SHA: $SOURCE_SHA"
echo "Image ID:   $IMAGE_ID"
if [[ "$FAIL" == "0" ]]; then
  echo "RESULT: PASS"
else
  echo "RESULT: FAIL" >&2
fi
exit "$FAIL"
