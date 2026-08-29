"""
Shared identifier sanitization for the model/dataset/checkpoint/evaluation
registries. Every registry ID (checkpoint_id, dataset_id, run_id,
evaluation_id) is used to construct a file path under ORCA_HOME/registry/ --
an unsanitized ID (e.g. "../../etc/passwd" or an absolute path) would be a
path-traversal vector into arbitrary file read/write, the same class of bug
already fixed once this phase in orca/mcp/fs_server.py.
"""
from __future__ import annotations

import re

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


class InvalidRegistryId(ValueError):
    pass


def validate_id(value: str, kind: str = "id") -> str:
    # The character-class regex alone would accept ".." (both chars are in
    # the allowed set) -- a real traversal payload once used to build
    # "<dir>/../something.json". Reject "." and ".." explicitly.
    if (
        not isinstance(value, str)
        or not _SAFE_ID.match(value)
        or value in (".", "..")
        or ".." in value
    ):
        raise InvalidRegistryId(
            f"Invalid {kind} '{value}': must be 1-200 chars of letters, digits, '.', '_', '-' only, "
            f"must not be '.' or '..' or contain '..' (no path separators or traversal sequences)."
        )
    return value
