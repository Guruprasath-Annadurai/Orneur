#!/bin/sh
# Start as root only long enough to make the persistent data directory usable by the unprivileged
# application user, then drop privileges for good. If already unprivileged, just exec.
set -eu
APP_USER="${ORNEUR_APP_USER:-orneur}"
DATA_DIR="${ORNEUR_HOME:-/data}"

if [ "$(id -u)" = "0" ]; then
    app_uid="$(id -u "$APP_USER")"
    mkdir -p "$DATA_DIR"
    # Re-own recursively only when the top level is not already ours (a volume written by an older
    # root-running image); this avoids a full tree walk on every start.
    if [ "$(stat -c %u "$DATA_DIR")" != "$app_uid" ]; then
        chown -R "$app_uid:$(id -g "$APP_USER")" "$DATA_DIR"
    fi
    chmod 0700 "$DATA_DIR"
    exec runuser -u "$APP_USER" -- "$@"
fi
exec "$@"
