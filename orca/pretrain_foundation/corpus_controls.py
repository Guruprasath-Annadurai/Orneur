"""Phase 4 corpus control boundaries (synthetic / non-training fixtures only).

Refuses unauthorized corpus creation and protected holdout exposure.
Does not ingest user conversations. Refuses remote URL / object-store origins.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any


class CorpusControlError(Exception):
    """Corpus admission or custody boundary violation."""


ALLOWED_FIXTURE_CLASSES = frozenset({
    "synthetic_unit_fixture",
    "legally_authorized_non_training_fixture",
})

_REMOTE_SCHEMES = (
    "http://",
    "https://",
    "ftp://",
    "s3://",
    "gs://",
    "azure://",
)


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


def refuse_remote_origin(source: str | os.PathLike[str]) -> None:
    """Refuse URL / object-store origins. Corpus readers are local-path only.

    ``pathlib.Path`` collapses ``https://`` to ``https:/`` on POSIX, so both
    the raw string and the Path-mangled form are rejected.
    """
    text = os.fspath(source).strip()
    lowered = text.lower()
    for scheme in _REMOTE_SCHEMES:
        if lowered.startswith(scheme):
            raise CorpusControlError(
                f"remote corpus origin refused ({scheme.rstrip(':/')}); local path required"
            )
        # Path("https://host/x") -> "https:/host/x" on POSIX.
        mangled = scheme.replace("://", ":/")
        if lowered.startswith(mangled):
            raise CorpusControlError(
                f"remote corpus origin refused ({scheme.rstrip(':/')}); local path required"
            )
    if "://" in text or (":/" in text and not text.startswith("/") and not text.startswith("./")):
        # Catch other URI-like schemes after Path mangling (e.g. custom:// -> custom:/).
        scheme_name = text.split(":", 1)[0]
        if scheme_name and scheme_name.isalnum():
            raise CorpusControlError(
                f"non-local URI scheme refused for corpus origin: {scheme_name}"
            )


def training_bound_reader_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs every training-bound corpus reader must use.

    License metadata is still not a training grant; G8 remains required for
    real corpus creation. This only hardens the software admission path.
    """
    kwargs: dict[str, Any] = {"require_license": True}
    kwargs.update(overrides)
    if not kwargs.get("require_license", True):
        raise CorpusControlError("training-bound readers cannot disable require_license")
    return kwargs
