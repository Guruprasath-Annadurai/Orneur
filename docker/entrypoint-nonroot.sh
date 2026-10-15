#!/bin/sh
# Start as root only long enough to make the persistent data directory usable by the unprivileged
# application user, then drop privileges for good. If already unprivileged, just exec.
set -eu
APP_USER="${ORNEUR_APP_USER:-orneur}"
DATA_DIR="${ORNEUR_HOME:-/data}"

if [ "$(id -u)" = "0" ]; then
    app_uid="$(id -u "$APP_USER")"
    mkdir -p "$DATA_DIR"
    # Re-own recursively when ANYTHING under the data directory is not ours (a volume written by an older root-running image, or one whose
    # earlier re-own was interrupted -- the top level can already be ours while a subtree is not). `find ... -print -quit` stops at the first
    # foreign entry, so a healthy volume costs one directory walk of cheap stat calls, not a recursive chown. chown -R does not follow symlinks.
    if [ -n "$(find "$DATA_DIR" -xdev ! -uid "$app_uid" -print -quit)" ]; then
        chown -R "$app_uid:$(id -g "$APP_USER")" "$DATA_DIR"
    fi
    chmod 0700 "$DATA_DIR"
    exec runuser -u "$APP_USER" -- "$@"
fi
exec "$@"
