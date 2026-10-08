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
        if not isinstance(blob, (bytes, bytearray)) or not bytes(blob).startswith(b"OBS1"):
            raise FailClosed("JOURNAL")
        self.blob = bytes(blob)
        self.commits += 1


class SyntheticFence:
    """Monotonic generation floor.

    ``authenticate`` / ``pin_observed`` reject a journal whose generation is
    below the floor, or the same generation with a different digest.
    A virgin fence (floor 0 and an empty digest) has no authenticated
    journal yet. Adopting one on boot is a software pin, not TPM NV.
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
        digest = bytes(digest)
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
            raise FailClosed("FENCE")
        if self.virgin:
            return
        if generation != self.floor or digest != self.digest:
            raise FailClosed("FENCE")

    def pin_observed(self, generation: int, digest: bytes) -> None:
        """Record a journal this fence has parsed.

        A virgin fence adopts that generation. A fence that already has a
        floor accepts only the pinned generation and digest.
        """
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
            raise FailClosed("FENCE")
        if self.virgin:
            self.floor = generation
            self.digest = bytes(digest)
            return
        self.authenticate(generation, digest)

    def advance(self, generation: int, digest: bytes) -> None:
        """Move the floor forward by one committed generation."""
        digest = bytes(digest)
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise FailClosed("FENCE")
        if self.virgin:
            self.floor = generation
            self.digest = digest
            return
        if generation != self.floor + 1:
            raise FailClosed("FENCE")
        self.floor = generation
        self.digest = digest
