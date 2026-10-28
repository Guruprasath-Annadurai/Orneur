from __future__ import annotations

import json

from orca.serve.conversation_context import assemble_messages, MAX_CHARS
from orca.serve import conversations, message_versions


def test_assemble_includes_prior_turns_and_not_duplicate_current(isolated_home):
    sid = "ctxsess01"
    conversations.append(sid, "user", "My colour is blue.", meta={"message_id": "aaaaaaaa"})
    conversations.append(sid, "assistant", "Noted blue.", meta={"message_id": "bbbbbbbb"})
    msgs = assemble_messages(session_id=sid, current_user_text="What colour?")
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"] == "My colour is blue."
    assert msgs[-1]["content"] == "What colour?"
    pending = "pendsess1"
    conversations.append(pending, "user", "only this", meta={"message_id": "hhhhhhhh"})
    again = assemble_messages(session_id=pending, current_user_text="only this")
    assert again == [{"role": "user", "content": "only this"}]


def test_assemble_uses_edited_active_version_and_drops_stale_tail(isolated_home):
    sid = "editsess1"
    conversations.append(sid, "user", "favourite fruit is pineapple", meta={"message_id": "cccccccc"})
    conversations.append(sid, "assistant", "pineapple is tasty", meta={"message_id": "dddddddd"})
    message_versions.seed(sid, "u1", "cccccccc", "user", "favourite fruit is pineapple")
    view = message_versions.edit(sid, "u1", "cccccccc", "favourite fruit is mango")
    assert view["created"] is True
    msgs = assemble_messages(session_id=sid, current_user_text="Which fruit?")
    sent = " ".join(m["content"] for m in msgs)
    assert "favourite fruit is mango" in sent
    assert "pineapple" not in sent
    assert msgs[-1]["content"] == "Which fruit?"


def test_assemble_excludes_finished_temporary_and_bounds_chars(isolated_home):
    from orca.serve import temporary_chat

    sid = "tempsess1"
    temporary_chat.activate(sid, "u1", 3600)
    conversations.append(sid, "user", "secret", meta={"message_id": "eeeeeeee"})
    temporary_chat.finish(sid, "u1", "closed")
    msgs = assemble_messages(session_id=sid, current_user_text="hello")
    assert msgs == [{"role": "user", "content": "hello"}]
    huge = "x" * (MAX_CHARS + 50)
    bounded = assemble_messages(session_id=None, current_user_text=huge)
    assert len(bounded[0]["content"]) <= MAX_CHARS


def test_assemble_refuses_another_users_session(isolated_home):
    from orca.auth.store import record_user_session

    sid = "ownedsess1"
    conversations.append(sid, "user", "secret from alice", meta={"message_id": "iiiiiiii"})
    conversations.append(sid, "assistant", "ok", meta={"message_id": "jjjjjjjj"})
    record_user_session("alice", sid)
    leaked = assemble_messages(session_id=sid, current_user_text="What did I say?", user_id="bob")
    assert leaked == [{"role": "user", "content": "What did I say?"}]
    owned = assemble_messages(session_id=sid, current_user_text="What did I say?", user_id="alice")
    assert owned[0]["content"] == "secret from alice"


def test_hidden_covers_expired_temporary_records(isolated_home):
    from orca.serve import temporary_chat

    sid = "expiredtmp"
    temporary_chat.activate(sid, "u1", 3600)
    conversations.append(sid, "user", "temp secret", meta={"message_id": "kkkkkkkk"})
    assert temporary_chat.is_hidden(sid) is True
    path = temporary_chat._path(sid)
    record = json.loads(path.read_text())
    record["state"] = "expired"
    record["expires_at"] = 0
    path.write_text(json.dumps(record))
    assert temporary_chat.is_active(sid) is False
    assert temporary_chat.is_hidden(sid) is True
    msgs = assemble_messages(session_id=sid, current_user_text="hello", user_id="u1")
    assert msgs == [{"role": "user", "content": "hello"}]


def test_persist_to_redis_forwards_fence_token(isolated_home, monkeypatch):
    from orca.serve import api, session_store

    captured = {}

    def _save(session_id, model_variant, history, expected_revision=None, fence_token=None):
        captured["fence_token"] = fence_token
        return True

    monkeypatch.setattr(session_store, "enabled", lambda: True)
    monkeypatch.setattr(session_store, "save_session_state", _save)
    sess = api._Session.__new__(api._Session)
    sess.id = "fence-sess"
    sess.model_variant = "core"
    sess._known_revision = 3
    sess._agent = type("A", (), {"get_history": lambda self: [{"role": "user", "content": "x"}]})()
    assert sess.persist_to_redis(fence_token="lease-1") is True
    assert captured["fence_token"] == "lease-1"


def test_kernel_inference_request_contains_history(isolated_home, monkeypatch):
    import asyncio

    from orca.cognitive.contracts import CognitiveRequest
    from orca.cognitive.kernel import CognitiveKernel
    from orca.gateway.contracts import InferenceResponse

    sid = "kernsess1"
    conversations.append(sid, "user", "token ALPHA-9", meta={"message_id": "ffffffff"})
    conversations.append(sid, "assistant", "stored", meta={"message_id": "gggggggg"})
    captured = {}

    class FakeGW:
        def register_deployment(self, deployment):
            return None

        def register_runtime(self, *args, **kwargs):
            return None

        async def generate(self, request, allow_experimental=False):
            captured["messages"] = list(request.messages)
            return InferenceResponse(
                request_id=request.request_id, model_id="orneur-novus", resolved_version="fixture-llama",
                runtime="ollama", deployment_id="dep", output="ok", finish_reason="stop",
                prompt_tokens=1, completion_tokens=1, latency_ms=1, queue_latency_ms=0, model_latency_ms=1,
            )

    monkeypatch.setattr(CognitiveKernel, "_gateway", lambda self: FakeGW())
    monkeypatch.setattr(
        "orca.serve.registry.resolve_tier_backend",
        lambda tier: type("R", (), {"tier": tier, "backend": "ollama", "model": "fixture-llama", "data_left_infrastructure": False})(),
    )
    from orca.cognitive.wiring import reset_for_tests

    reset_for_tests()
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="Say hi.", session_id=sid, tenant="u1")
    result = asyncio.run(kernel.execute(req))
    assert result.output == "ok"
    roles = [m["role"] for m in captured["messages"]]
    assert roles[0] == "user" and "token ALPHA-9" in captured["messages"][0]["content"]
    assert captured["messages"][-1]["content"] == "Say hi."
