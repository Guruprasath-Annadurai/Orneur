"""Private-storage integration: SYNTHETIC test backends that implement the SAME interface as the real stores in orca.eval.genesis_v2.store
(`PrivateCorpusStore`: describe / write_corpus / read_split) plus a grant-gated reader.

HONEST SCOPE: these backends are for tests and the synthetic demo only. They provide no confidentiality (the directory backend stores plaintext in
a 0700 temp directory) and are explicitly NOT "private-grade": `is_private_grade()` is False for them, so they can never satisfy the
`private_storage_genuinely_configured` freeze prerequisite. The real backends (EncryptedFileStore / EncryptedVaultWriter+Reader) are in
orca.eval.genesis_v2.store; a real PRIVATE_GITHUB_REPO / PRIVATE_OBJECT_STORE remains descriptor-only and needs the founder.

Invariants shared with the real store (and tested against it): an unconfigured backend refuses every operation; a corpus id is write-once; both
private splits are mandatory; the SEAL digest is authenticated on every read; any digest mismatch fails closed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from orca.eval.genesis_v2 import spec as V2
from orca.eval.genesis_v2 import store as ST
from orca.evalinfra.errors import AccessDeniedError

SYNTHETIC_KIND = "SYNTHETIC_TEST_ONLY"
_CORPUS_ID = re.compile(r"^gce2c-[0-9a-f]{16,64}$")


def _validate_write(corpus_id: str, splits: dict) -> None:
    if not (isinstance(corpus_id, str) and _CORPUS_ID.match(corpus_id)):
        raise ST.PrivateStorageViolation("corpus_id must look like gce2c-<hex>")
    if set(splits) != set(V2.PRIVATE_SPLITS) or not all(isinstance(v, (bytes, bytearray)) for v in splits.values()):
        raise ST.PrivateStorageViolation("write_corpus needs bytes for exactly " + str(V2.PRIVATE_SPLITS))


def _digests(splits: dict) -> dict:
    return {s: hashlib.sha256(bytes(v)).hexdigest() for s, v in splits.items()}


class SyntheticMemoryStore:
    """In-memory synthetic backend. `configured=False` models 'no private storage boundary': every call raises PrivateStorageNotConfigured."""

    def __init__(self, *, configured: bool = False):
        self._configured = configured
        self._data: dict = {}

    def _need(self) -> None:
        if not self._configured:
            raise ST.PrivateStorageNotConfigured("synthetic backend is not configured; refusing (fail closed)")

    def describe(self) -> dict:
        return {"kind": SYNTHETIC_KIND, "configured": self._configured, "private_grade": False, "confidential": False, "write_once": True}

    def write_corpus(self, corpus_id: str, splits: dict) -> str:
        self._need()
        _validate_write(corpus_id, splits)
        if corpus_id in self._data:
            raise ST.PrivateStorageViolation("a corpus id can be used once")
        d = _digests(splits)
        cdig = ST.corpus_digest_of(d)
        self._data[corpus_id] = {"digests": d, "corpus_digest": cdig, "splits": {s: bytes(v) for s, v in splits.items()}}
        return cdig

    def read_split(self, corpus_id: str, split: str, *, expected_corpus_digest: str) -> bytes:
        self._need()
        if split not in V2.PRIVATE_SPLITS:
            raise ST.PrivateStorageViolation(f"{split!r} is not a private split")
        rec = self._data.get(corpus_id)
        if rec is None:
            raise ST.PrivateStorageIntegrityError("corpus has no SEAL (partial or missing write)")
        if rec["corpus_digest"] != expected_corpus_digest or ST.corpus_digest_of(rec["digests"]) != expected_corpus_digest:
            raise ST.PrivateStorageIntegrityError("corpus digest mismatch")
        plain = rec["splits"][split]
        if hashlib.sha256(plain).hexdigest() != rec["digests"][split]:
            raise ST.PrivateStorageIntegrityError("split digest mismatch")
        return plain

    def tamper_for_test(self, corpus_id: str, split: str, new_bytes: bytes) -> None:
        """Test hook only: simulates storage corruption so tests can prove reads fail closed."""
        self._data[corpus_id]["splits"][split] = bytes(new_bytes)


class SyntheticDirStore:
    """Tempdir synthetic backend (plaintext!). directory=None models 'unconfigured'. Refuses a directory inside the repository."""

    def __init__(self, directory=None, *, repo_root=None):
        self._dir = None
        if directory is not None:
            d = Path(directory)
            if ST._inside_repo(d, repo_root):
                raise ST.PrivateStorageViolation("a private artifact directory must live OUTSIDE the repository working tree")
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)
            self._dir = d

    def _need(self) -> Path:
        if self._dir is None:
            raise ST.PrivateStorageNotConfigured("synthetic directory backend is not configured; refusing (fail closed)")
        return self._dir

    def describe(self) -> dict:
        return {"kind": SYNTHETIC_KIND, "configured": self._dir is not None, "private_grade": False, "confidential": False, "write_once": True}

    def write_corpus(self, corpus_id: str, splits: dict) -> str:
        base = self._need()
        _validate_write(corpus_id, splits)
        cdir = base / corpus_id
        cdir.mkdir(mode=0o700, exist_ok=False)                   # write-once
        d = _digests(splits)
        for s in V2.PRIVATE_SPLITS:
            (cdir / f"{s}.bin").write_bytes(bytes(splits[s]))
        cdig = ST.corpus_digest_of(d)
        (cdir / "SEAL.json").write_text(json.dumps({"digests": d, "corpus_digest": cdig}, sort_keys=True))   # written LAST
        return cdig

    def read_split(self, corpus_id: str, split: str, *, expected_corpus_digest: str) -> bytes:
        base = self._need()
        if split not in V2.PRIVATE_SPLITS:
            raise ST.PrivateStorageViolation(f"{split!r} is not a private split")
        if not _CORPUS_ID.match(corpus_id):
            raise ST.PrivateStorageViolation("corpus_id must look like gce2c-<hex>")
        try:
            seal = json.loads((base / corpus_id / "SEAL.json").read_text())
            digests = seal["digests"]
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            raise ST.PrivateStorageIntegrityError("corpus has no valid SEAL (partial or missing write)") from None
        if not isinstance(digests, dict) or set(digests) != set(V2.PRIVATE_SPLITS):
            raise ST.PrivateStorageIntegrityError("SEAL is not the expected split-digest map")
        if seal.get("corpus_digest") != ST.corpus_digest_of(digests) or seal.get("corpus_digest") != expected_corpus_digest:
            raise ST.PrivateStorageIntegrityError("corpus digest mismatch")
        try:
            plain = (base / corpus_id / f"{split}.bin").read_bytes()
        except FileNotFoundError:
            raise ST.PrivateStorageIntegrityError("split artifact missing") from None
        if hashlib.sha256(plain).hexdigest() != digests[split]:
            raise ST.PrivateStorageIntegrityError("split digest mismatch")
        return plain


def is_private_grade(store) -> bool:
    """True only for a real, configured, non-synthetic store kind. Synthetic backends are NEVER private-grade (so they cannot satisfy a freeze prerequisite)."""
    try:
        d = store.describe()
    except Exception:
        return False
    return bool(d.get("configured")) and d.get("kind") in ST.KINDS and d.get("kind") != SYNTHETIC_KIND and d.get("private_grade", True) is not False


class GuardedReader:
    """Wraps a store so a private-split read is possible ONLY with a live grant from the protected-evaluation gate (see orca.evalinfra.access).
    The grant must name this exact split and corpus digest; a missing, mismatched or foreign grant is a denial -- the store is never touched."""

    def __init__(self, store, *, grant_checker):
        self._store = store
        self._check = grant_checker

    def read_split(self, grant, corpus_id: str, split: str, *, expected_corpus_digest: str) -> bytes:
        reasons = self._check(grant, split=split, corpus_digest=expected_corpus_digest)
        if reasons:
            raise AccessDeniedError(reasons)
        return self._store.read_split(corpus_id, split, expected_corpus_digest=expected_corpus_digest)
