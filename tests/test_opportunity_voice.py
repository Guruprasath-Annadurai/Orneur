from __future__ import annotations

import pytest

from orca.opportunity.bridge import OpportunityError, availability, discover, execute_external, rank_saved, reset_for_tests, save
from orca.voice.contracts import VoiceError, capability, delete_transcript, read_transcript, retain, transcribe
from orca.voice.contracts import reset_for_tests as reset_voice


def setup_function():
    reset_for_tests()
    reset_voice()


def test_opportunity_unavailable_without_live_feed():
    status = availability()
    assert status["status"] == "NOT_AVAILABLE"
    assert status["live_source"] is False
    empty = discover("user-a", "jobs")
    assert empty["listings"] == []
    assert empty["live_source"] is False
    fixtures = discover(
        "user-a",
        "jobs",
        fixtures=[
            {"title": "b-role", "owner_user_id": "user-a"},
            {"title": "a-role", "owner_user_id": "user-a"},
            {"title": "secret", "owner_user_id": "user-b"},
        ],
    )
    assert fixtures["synthetic"] is True
    titles = [row["title"] for row in fixtures["listings"]]
    assert "secret" not in titles
    saved = save("user-a", fixtures["listings"][0] | {"synthetic": True})
    ranked = rank_saved("user-a")
    assert ranked[0]["id"] == saved["id"]
    with pytest.raises(OpportunityError) as exc:
        rank_saved("user-a", other_user_id="user-b")
    assert exc.value.code == "access_denied"
    with pytest.raises(OpportunityError):
        execute_external("user-a", listing_id=saved["id"])
    with pytest.raises(OpportunityError):
        save("user-a", {"id": "x", "live_source": True, "synthetic": True})


def test_voice_unavailable_and_consent():
    body = capability()
    assert body["speech_recognition"] == "NOT_AVAILABLE"
    assert body["provider"] is None
    with pytest.raises(VoiceError) as exc:
        transcribe("user-a", b"wav", consent=True)
    assert exc.value.code == "speech_unavailable"
    with pytest.raises(VoiceError) as exc:
        transcribe("user-a", b"wav", consent=False)
    assert exc.value.code == "consent_required"
    retain("user-a", "t1", "hello", consent=True)
    assert read_transcript("user-a", "t1")["text"] == "hello"
    with pytest.raises(VoiceError):
        read_transcript("user-b", "t1")
    deleted = delete_transcript("user-a", "t1")
    assert deleted["deleted"] is True
    with pytest.raises(VoiceError):
        read_transcript("user-a", "t1")
