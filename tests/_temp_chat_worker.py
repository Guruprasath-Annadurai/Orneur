"""Child process for tests/test_temporary_chat_multiprocess.py. Runs against ORNEUR_HOME given in the environment; prints one JSON line per step."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid


def say(**kw):
    print(json.dumps(kw), flush=True)


def _commit(sid, uid, n):
    from orca.serve import conversations, message_versions, temporary_chat

    fence = uuid.uuid4().hex
    auth = conversations.acquire_authority(sid, uid, fence, ttl_s=30.0)
    if auth is None:
        return "no-authority"
    try:
        with temporary_chat.commit_guard(sid) as ok:
            if not ok:
                return "refused"
            umid, amid = uuid.uuid4().hex, uuid.uuid4().hex
            res = conversations.commit_turn(sid, f"secret question {n}", f"secret answer {n}", user_id=uid, turn_id=uuid.uuid4().hex,
                                            fence_token=fence, epoch=auth.epoch, meta={"message_id": amid, "user_message_id": umid})
            if not res.ok:
                return "commit-" + str(res.reason)
            message_versions.seed(sid, uid, umid, "user", f"secret question {n}")
            return "committed"
    finally:
        conversations.release_authority(sid, fence, auth.epoch)


def main() -> None:
    mode, sid, uid = sys.argv[1:4]
    from orca.auth.db import init_db
    from orca.auth.store import claim_session
    from orca.serve import temporary_chat

    init_db()
    if mode == "open":
        claim_session(sid, uid)
        say(opened=temporary_chat.activate(sid, uid, 600)["state"])
        say(commit=_commit(sid, uid, 1))
    elif mode == "crash_in_close":
        def die(*a, **k):
            os._exit(9)

        temporary_chat._delete_contents = die
        temporary_chat.finish(sid, uid, "closed")
        say(unexpected="finish returned")
    elif mode == "committer":
        for n in range(2, 400):
            outcome = _commit(sid, uid, n)
            say(n=n, outcome=outcome)
            if outcome != "committed":
                break
            time.sleep(0.005)
    elif mode == "close":
        time.sleep(float(os.environ.get("CLOSE_DELAY", "0")))
        say(closed=temporary_chat.finish(sid, uid, "closed"))
    elif mode == "enforce":
        say(enforce=temporary_chat.enforce(sid))
    else:
        raise SystemExit("unknown mode " + mode)


if __name__ == "__main__":
    main()
