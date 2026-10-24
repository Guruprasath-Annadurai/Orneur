"""Backend contracts for spoken-mission intake.

Wake-word detection, mobile OS integration, and automotive certification
are unsupported. Text passed here is stored, not understood by a model.
"""
from __future__ import annotations

SUPPORTED = frozenset({"intake_text", "short_ack", "status_summary", "deferred_approval"})
UNSUPPORTED = frozenset({"wake_word", "mobile_os", "automotive", "driving_mode"})


class VoiceError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def intake(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise VoiceError("empty_intake")
    return {
        "schema": "orneur-voice-intake/1",
        "kind": "intake_text",
        "text": text.strip(),
        "understood_by_model": False,
        "wake_word": False,
    }


def status_summary(state: str) -> dict:
    return {"schema": "orneur-voice-summary/1", "kind": "status_summary", "state": state, "audio_rendered": False}


def capability(name: str) -> dict:
    if name in UNSUPPORTED:
        return {"name": name, "status": "unsupported", "tested_on_device": False}
    if name in SUPPORTED:
        return {"name": name, "status": "contract_only", "tested_on_device": False}
    raise VoiceError("unknown_capability")
