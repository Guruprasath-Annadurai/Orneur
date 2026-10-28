"""Multi-process helper: attempt a fenced transcript commit and report JSON."""
from __future__ import annotations

import json
import sys
import traceback


def main() -> int:
    raw = sys.stdin.read()
    req = json.loads(raw)
    try:
        from orca.serve import session_store
        from orca.serve.inference import InferenceError, _persist

        session_store.REDIS_URL = req["redis_url"]
        session_store._redis_client = None
        text = _persist(
            user_id=req["user_id"],
            session_id=req["session_id"],
            message=req["message"],
            text=req["text"],
            identity={"served_model": "fixture"},
            model="fixture",
            fence_token=req["fence"],
        )
        sys.stdout.write(json.dumps({"ok": True, "text": text}))
    except Exception as exc:
        code = getattr(exc, "code", None) or "error"
        # InferenceError carries .code; keep that shape for the parent assert.
        payload = {"ok": False, "code": code}
        if code == "error":
            payload["error"] = str(exc)
            payload["trace"] = traceback.format_exc()
        sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
