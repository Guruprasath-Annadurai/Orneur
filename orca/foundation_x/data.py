"""Synthetic data-admission checks.

`license=approved` is metadata, not a usage right. No external corpus is fetched.
"""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass

from orca.eval.genesis_contamination import jaccard, normalize_text, word_ngrams


@dataclass(frozen=True)
class RightsRecord:
    instrument: str
    uri: str
    obligations: tuple[str, ...]
    synthetic_fixture: bool = True


@dataclass(frozen=True)
class AdmittedRecord:
    record_id: str
    text: str
    digest: str
    rights: RightsRecord
    split: str


def admit_text(record_id: str, raw: bytes, rights: RightsRecord | None, *, split: str) -> tuple[AdmittedRecord | None, str | None]:
    """Decode UTF-8, normalize to NFC, and refuse a missing rights record."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "invalid UTF-8"
    if rights is None or not rights.instrument or not rights.uri:
        return None, "usage rights are missing; a license string is not sufficient"
    if rights.instrument.strip().lower() == "approved":
        return None, "license=approved is not a usage-rights instrument"
    normalized = unicodedata.normalize("NFC", text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return AdmittedRecord(record_id, normalized, digest, rights, split), None


def exact_duplicate(left: AdmittedRecord, right: AdmittedRecord) -> bool:
    return left.digest == right.digest and left.record_id != right.record_id


def near_duplicate(left: str, right: str, *, threshold: float = 0.85) -> bool:
    return jaccard(
        frozenset(word_ngrams(normalize_text(left), 5)),
        frozenset(word_ngrams(normalize_text(right), 5)),
    ) >= threshold


def contamination(train: list[AdmittedRecord], evaluation: list[AdmittedRecord]) -> list[tuple[str, str]]:
    """Exact digest overlap between train and evaluation ids."""
    train_digests = {record.digest: record.record_id for record in train}
    hits = []
    for record in evaluation:
        train_id = train_digests.get(record.digest)
        if train_id is not None:
            hits.append((train_id, record.record_id))
    return hits
