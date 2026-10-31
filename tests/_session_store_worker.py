"""OS-process worker for Redis lease/CAS checks."""
from __future__ import annotations

import json
import sys
import time

from orca.serve import session_store as ss


def main() -> None:
    cmd = json.loads(sys.stdin.read() or "{}")
    op = cmd["op"]
    sid = cmd["sid"]
    try:
        if op == "hold":
            ok = ss.acquire_session_lease(sid, cmd["fence"], ttl_ms=cmd.get("ttl_ms", 4000))
            time.sleep(cmd.get("sleep_s", 1.0))
            out = {"ok": ok, "released": ss.release_session_lease(sid, cmd["fence"]) if ok else False}
        elif op == "acquire":
            out = {"ok": ss.acquire_session_lease(sid, cmd["fence"], ttl_ms=cmd.get("ttl_ms", 2000))}
        elif op == "save":
            out = {
                "ok": ss.save_session_state(
                    sid, "nano", cmd.get("history") or [],
                    expected_revision=cmd.get("rev"),
                    fence_token=cmd.get("fence"),
                )
            }
        else:
            out = {"error": op}
    except Exception as exc:
        out = {"error": repr(exc)}
    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
