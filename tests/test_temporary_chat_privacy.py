"""Temporary-chat lifecycle: no LTM, no reappearance, no leftover versions/locks."""

from __future__ import annotations

import time
import uuid

import pytest

from orca.auth.db import init_db
from orca.auth.store import claim_session
from orca.serve import conversations, message_versions, temporary_chat


def test_is_hidden_covers_expired_and_closed(isolated_home):
    init_db()
    sid = "tmp" + uuid.uuid4().hex[:12]
    uid = "tmp-owner"
    claim_session(sid, uid)
    temporary_chat.activate(sid, uid, ttl_seconds=60)
    assert temporary_chat.is_hidden(sid) is True
    assert temporary_chat.is_active(sid) is True
    conversations.append(sid, "user", "secret-temp")
    conversations.append(sid, "assistant", "reply")
    mid = "msg" + uuid.uuid4().hex[:12]
    message_versions.seed(sid, uid, mid, "user", "secret-temp")
    finished = temporary_chat.finish(sid, uid, "closed")
    assert finished["state"] == "closed"
    assert temporary_chat.is_hidden(sid) is True
    assert temporary_chat.is_active(sid) is False
    assert conversations.last_activity(sid) is None
    # Version files removed by finish cascade; lock must not linger.
    assert not temporary_chat._lock_path(sid).exists()


def test_expired_temp_chat_cannot_reappear_in_hidden_filter(isolated_home):
    init_db()
    sid = "exp" + uuid.uuid4().hex[:12]
    uid = "exp-owner"
    claim_session(sid, uid)
    temporary_chat.activate(sid, uid, ttl_seconds=60)
    # Force expiry via finish(expired) path.
    conversations.append(sid, "user", "gone")
    view = temporary_chat.finish(sid, uid, "expired")
    assert view["state"] == "expired"
    assert temporary_chat.is_hidden(sid) is True
    assert conversations.last_activity(sid) is None


def test_omit_long_term_for_any_temp_record(isolated_home):
    from orca.serve.api import _omit_long_term

    init_db()
    sid = "ltm" + uuid.uuid4().hex[:12]
    uid = "ltm-owner"
    claim_session(sid, uid)
    assert _omit_long_term(sid) is False
    temporary_chat.activate(sid, uid, ttl_seconds=120)
    assert _omit_long_term(sid) is True
    temporary_chat.finish(sid, uid, "closed")
    assert _omit_long_term(sid) is True


def test_stream_may_publish_refuses_after_temp_finish(isolated_home, monkeypatch):
    from orca.serve.api import _stream_may_publish

    init_db()
    sid = "pub" + uuid.uuid4().hex[:12]
    uid = "pub-owner"
    claim_session(sid, uid)
    temporary_chat.activate(sid, uid, ttl_seconds=60)
    monkeypatch.setattr("orca.serve.session_store.enabled", lambda: False)
    assert _stream_may_publish(sid, "fence") is True
    temporary_chat.finish(sid, uid, "closed")
    assert _stream_may_publish(sid, "fence") is False
