"""Honest speech capability contracts. No speech backend is invoked."""

from __future__ import annotations

from datetime import datetime, timezone

SCHEMA_VERSION = "orneur.voice/1"
NOT_AVAILABLE = "NOT_AVAILABLE"


class VoiceError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_TRANSCRIPTS: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def capability() -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "speech_recognition": NOT_AVAILABLE,
        "speech_synthesis": NOT_AVAILABLE,
        "provider": None,
        "reason": "no_executable_speech_backend",
    }


def transcribe(user_id: str, audio: bytes, *, consent: bool) -> dict:
    if not user_id:
        raise VoiceError("unauthenticated")
    if not consent:
        raise VoiceError("consent_required")
    if not audio:
        raise VoiceError("audio_refused")
    raise VoiceError("speech_unavailable")


def retain(user_id: str, transcript_id: str, text: str, *, consent: bool) -> dict:
    if not user_id:
        raise VoiceError("unauthenticated")
    if not consent:
        raise VoiceError("consent_required")
    row = {
        "id": transcript_id,
        "user_id": user_id,
        "text": text,
        "retained_at": _now(),
        "synthetic": True,
        "provider": None,
    }
    _TRANSCRIPTS[f"{user_id}:{transcript_id}"] = row
    return row


def delete_transcript(user_id: str, transcript_id: str) -> dict:
    if not user_id:
        raise VoiceError("unauthenticated")
    key = f"{user_id}:{transcript_id}"
    existed = key in _TRANSCRIPTS
    _TRANSCRIPTS.pop(key, None)
    return {"deleted": existed, "id": transcript_id, "user_id": user_id}


def read_transcript(user_id: str, transcript_id: str) -> dict:
    if not user_id:
        raise VoiceError("unauthenticated")
    row = _TRANSCRIPTS.get(f"{user_id}:{transcript_id}")
    if row is None:
        raise VoiceError("not_found")
    return dict(row)


def reset_for_tests() -> None:
    _TRANSCRIPTS.clear()
