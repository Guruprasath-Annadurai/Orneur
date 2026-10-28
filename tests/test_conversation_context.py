from __future__ import annotations

import json
import uuid

from orca.serve.conversation_context import assemble_messages, MAX_CHARS
from orca.serve import conversations, message_versions


def _commit_pair(sid: str, user_id: str, user_text: str, asst_text: str, *, umid: str, amid: str) -> None:
    fence = uuid.uuid4().hex
    auth = conversations.acquire_authority(sid, user_id, fence, ttl_s=30.0)
    assert auth is not None
    result = conversations.commit_turn(
        sid,
        user_text,
        asst_text,
        user_id=user_id,
        turn_id=amid,
        fence_token=fence,
        epoch=auth.epoch,
        meta={"message_id": amid, "user_message_id": umid},
    )
    assert result.ok, result
    conversations.release_authority(sid, fence, auth.epoch)
    message_versions.seed(sid, user_id, umid, "user", user_text)
    message_versions.seed(sid, user_id, amid, "assistant", asst_text)


def test_assemble_includes_prior_turns_and_not_duplicate_current(isolated_home):
    sid = "ctxsess01"
    _commit_pair(
        sid,
        "u1",
        "My colour is blue.",
        "Noted blue.",
        umid="aaaaaaaa",
        amid="bbbbbbbb",
    )
    msgs = assemble_messages(session_id=sid, current_user_text="What colour?", user_id="u1")
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"] == "My colour is blue."
    assert msgs[-1]["content"] == "What colour?"
    pending = "pendsess1"
    fence = uuid.uuid4().hex
    auth = conversations.acquire_authority(pending, "u1", fence, ttl_s=30.0)
    assert auth is not None
    # User-only pending turn is not a committed pair; current text alone is sent.
    conversations.release_authority(pending, fence, auth.epoch)
    again = assemble_messages(session_id=pending, current_user_text="only this", user_id="u1")
    assert again == [{"role": "user", "content": "only this"}]


def test_assemble_uses_edited_active_version_and_drops_stale_tail(isolated_home):
    sid = "editsess1"
    _commit_pair(
        sid,
        "u1",
        "favourite fruit is pineapple",
        "pineapple is tasty",
        umid="cccccccc",
        amid="dddddddd",
    )
    view = message_versions.edit(sid, "u1", "cccccccc", "favourite fruit is mango")
    assert view["created"] is True
    msgs = assemble_messages(session_id=sid, current_user_text="Which fruit?", user_id="u1")
    sent = " ".join(m["content"] for m in msgs)
    assert "favourite fruit is mango" in sent
    assert "pineapple" not in sent
    assert msgs[-1]["content"] == "Which fruit?"


def test_assemble_excludes_finished_temporary_and_bounds_chars(isolated_home):
    from orca.serve import temporary_chat

    sid = "tempsess1"
    temporary_chat.activate(sid, "u1", 3600)
    _commit_pair(sid, "u1", "secret", "ok", umid="eeeeeeee", amid="eeeeasst")
    temporary_chat.finish(sid, "u1", "closed")
    msgs = assemble_messages(session_id=sid, current_user_text="hello", user_id="u1")
    assert msgs == [{"role": "user", "content": "hello"}]
    huge = "x" * (MAX_CHARS + 50)
    bounded = assemble_messages(session_id=None, current_user_text=huge)
    assert len(bounded[0]["content"]) <= MAX_CHARS


def test_assemble_refuses_another_users_session(isolated_home):
    from orca.auth.store import record_user_session

    sid = "ownedsess1"
    _commit_pair(sid, "alice", "secret from alice", "ok", umid="iiiiiiii", amid="jjjjjjjj")
    record_user_session("alice", sid)
    leaked = assemble_messages(session_id=sid, current_user_text="What did I say?", user_id="bob")
    assert leaked == [{"role": "user", "content": "What did I say?"}]
    owned = assemble_messages(session_id=sid, current_user_text="What did I say?", user_id="alice")
    assert owned[0]["content"] == "secret from alice"


def test_hidden_covers_expired_temporary_records(isolated_home):
    from orca.serve import temporary_chat

    sid = "expiredtmp"
    temporary_chat.activate(sid, "u1", 3600)
    _commit_pair(sid, "u1", "temp secret", "ok", umid="kkkkkkkk", amid="kkkkasst")
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
    _commit_pair(sid, "u1", "token ALPHA-9", "stored", umid="ffffffff", amid="gggggggg")
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
