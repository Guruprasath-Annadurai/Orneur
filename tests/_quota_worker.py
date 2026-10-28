"""Cross-process quota admission worker."""
from __future__ import annotations

import json
import sys

from orca.auth.store import reserve_quota


def main() -> None:
    cmd = json.loads(sys.stdin.read() or "{}")
    try:
        out = reserve_quota(cmd["user_id"], cmd.get("tier", "free"), "message", request_id=cmd.get("request_id"))
    except Exception as exc:
        out = {"ok": False, "error": type(exc).__name__, "code": getattr(exc, "code", "")}
    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
