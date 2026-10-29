"""Phase 4 corpus control boundaries (synthetic / non-training fixtures only).

Refuses unauthorized corpus creation and protected holdout exposure.
Does not ingest user conversations.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


class CorpusControlError(Exception):
    """Corpus admission or custody boundary violation."""


ALLOWED_FIXTURE_CLASSES = frozenset({
    "synthetic_unit_fixture",
    "legally_authorized_non_training_fixture",
})


@dataclass(frozen=True)
class CorpusAdmissionRequest:
    fixture_class: str
    source_license_id: str | None
    content_sha256: str
    holdout: bool
    training_authorized: bool
    corpus_generation_granted: bool


def admit_fixture(request: CorpusAdmissionRequest) -> str:
    """Return an admission verdict string; raise on forbidden cases."""
    if request.fixture_class not in ALLOWED_FIXTURE_CLASSES:
        raise CorpusControlError(
            f"fixture class {request.fixture_class!r} is not an authorized non-training class"
        )
    if request.holdout and request.training_authorized:
        raise CorpusControlError("holdout material cannot be admitted under a training identity")
    if request.fixture_class != "synthetic_unit_fixture" and not request.corpus_generation_granted:
        raise CorpusControlError("corpus generation grant required for non-synthetic fixtures")
    if not request.content_sha256 or len(request.content_sha256) != 64:
        raise CorpusControlError("per-record content sha256 required")
    if request.source_license_id is None and request.fixture_class != "synthetic_unit_fixture":
        raise CorpusControlError("source/license identity binding required")
    return "ADMITTED_NON_TRAINING_FIXTURE"


def corpus_digest(records: list[bytes]) -> str:
    """Immutable digest over ordered record content hashes."""
    h = hashlib.sha256()
    for record in records:
        h.update(hashlib.sha256(record).digest())
    return h.hexdigest()


def invalidate_on_digest_change(*, frozen_digest: str, candidate_digest: str) -> None:
    if frozen_digest != candidate_digest:
        raise CorpusControlError(
            "corpus digest changed; frozen dataset is invalidated and must not be used"
        )


def refuse_user_conversation_ingestion(*, source_type: str) -> None:
    if source_type in {"user_conversation", "private_chat", "customer_transcript"}:
        raise CorpusControlError(
            f"unauthorized user-conversation ingestion refused ({source_type})"
        )
