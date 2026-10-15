"""Synthetic journal sink and fence.

``SYNTHETIC_NOT_REAL_HARDWARE_PROOF``. ``MemorySink`` is process memory.
``SyntheticFence`` is a software generation floor for deterministic tests.
Neither one is a TPM NV index, and neither one is hardware enforcement.
A newly constructed fence has not authenticated a journal.
"""

from __future__ import annotations

from orca.rse.imp1.verdict import FailClosed

SYNTHETIC_NOT_REAL_HARDWARE_PROOF = "SYNTHETIC_NOT_REAL_HARDWARE_PROOF"


class JournalSink:
    """Durable commit of one session journal blob.

    ``commit`` must return only after the blob is the value a later boot
    would read. Raising leaves the previous blob as the last candidate.
    """

    def commit(self, blob: bytes) -> None:
        raise FailClosed("JOURNAL_COMMIT")


class MemorySink(JournalSink):
    """In-memory stand-in used by tests. Not a disk and not a TPM."""

    label = SYNTHETIC_NOT_REAL_HARDWARE_PROOF

    def __init__(self) -> None:
        self.blob: bytes | None = None
        self.commits = 0

    def commit(self, blob: bytes) -> None:
        if not isinstance(blob, (bytes, bytearray)) or not bytes(blob).startswith((b"OBS1", b"OMJ1")):
            raise FailClosed("JOURNAL")
        self.blob = bytes(blob)
        self.commits += 1


class SyntheticFence:
    """Monotonic generation floor for tests.

    A virgin fence has authenticated nothing. It cannot adopt a historical
    journal. ``advance`` moves it only when a commit of a new generation
    succeeds, starting at generation 1. This object is not a TPM NV index.
    """

    label = SYNTHETIC_NOT_REAL_HARDWARE_PROOF

    def __init__(self, floor: int = 0, digest: bytes = b"") -> None:
        if not isinstance(floor, int) or isinstance(floor, bool) or floor < 0:
            raise FailClosed("FENCE")
        if not isinstance(digest, (bytes, bytearray)):
            raise FailClosed("FENCE")
        self.floor = floor
        self.digest = bytes(digest)

    @property
    def virgin(self) -> bool:
        return self.floor == 0 and self.digest == b""

    def authenticate(self, generation: int, digest: bytes) -> None:
        """Accept only the one generation this fence has already committed."""
        digest = bytes(digest)
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise FailClosed("FENCE")
        if len(digest) != 32 or self.virgin or generation != self.floor or digest != self.digest:
            raise FailClosed("FENCE")

    def pin_observed(self, generation: int, digest: bytes) -> None:
        """Historical adoption is not a boot path.

        A previous build let a virgin fence take whatever generation it was
        shown. That bypass is closed. Callers restore through ``boot`` after
        ``advance`` has committed a generation.
        """
        del generation, digest
        raise FailClosed("FENCE")

    def advance(self, generation: int, digest: bytes) -> None:
        """Move the floor forward by one committed generation.

        The first successful commit is generation 1. A later commit is only
        ``floor + 1``. An arbitrary historical generation is refused.
        """
        digest = bytes(digest)
        if not isinstance(generation, int) or isinstance(generation, bool) or len(digest) != 32:
            raise FailClosed("FENCE")
        if self.virgin:
            if generation != 1:
                raise FailClosed("FENCE")
            self.floor = 1
            self.digest = digest
            return
        if generation != self.floor + 1:
            raise FailClosed("FENCE")
        self.floor = generation
        self.digest = digest
