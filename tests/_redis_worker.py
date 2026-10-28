"""Independent-process worker for tests/test_redis_independent_processes.py.

Reads one JSON command per stdin line, writes one JSON reply per line.
Each process has its own interpreter, its own orca.serve.api._sessions and
its own Redis connection -- nothing is shared except Redis itself.
"""
import json
import sys

from orca.serve import api, session_store as ss


def main():
    # Each process hosts its own fake model backend (no live inference needed
    # to exercise session state).
    from _pytest.monkeypatch import MonkeyPatch
    from tests.fake_ollama import FakeOllama, point_orneur_at
    backend = FakeOllama(reply="ok", chunks=("ok",))
    backend.__enter__()
    point_orneur_at(backend, MonkeyPatch())
    for line in sys.stdin:
        cmd = json.loads(line)
        op, sid = cmd["op"], cmd.get("sid")
        try:
            if op == "seed":  # build a session, give it history, publish it
                s = api._get_session(sid)
                s.agent.load_history(cmd["history"])
                out = {"persisted": s.persist_to_redis(), "known": s._known_revision}
            elif op == "edit":  # what the edit route does after commit
                out = {"live_sync": api._replace_visible_copy(sid, cmd["previous"], cmd["new"], "user")}
            elif op == "history":
                s = api._get_session(sid)
                out = {"history": [m.get("content") for m in s.agent.get_history()],
                       "freshness": s.context_freshness, "known": s._known_revision}
            elif op == "persist":
                out = {"persisted": api._sessions[sid].persist_to_redis()}
            elif op == "has_local":
                out = {"has_local": sid in api._sessions}
            else:
                out = {"error": f"unknown op {op}"}
        except Exception as exc:  # report, never die silently
            out = {"error": repr(exc)}
        print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
