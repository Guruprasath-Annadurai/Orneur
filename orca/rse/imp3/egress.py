"""Result egress. Staged ciphertext has zero acceptance authority.

Witnessed RESULT evidence is the only way an artifact may be labelled
accepted. That label is still not training, qualification, or deployment
authority: those locks stay denied.
"""

from __future__ import annotations

import struct

from orca.rse.imp1.verdict import FailClosed

ZERO_ACCEPTANCE_AUTHORITY = "ZERO_ACCEPTANCE_AUTHORITY"
DOWNSTREAM = frozenset({
    "APPROVED", "ACCEPTED", "QUALIFICATION_INPUT", "TRAINING_INPUT", "EXPORTABLE", "DEPLOYABLE",
})


class Egress:
    def __init__(self) -> None:
        self._witnessed: set[bytes] = set()
        self._admit = object()

    def stage(self, digest: bytes) -> str:
        if not isinstance(digest, (bytes, bytearray)) or len(digest) != 32:
            raise FailClosed("DIGEST")
        return ZERO_ACCEPTANCE_AUTHORITY

    def note_witnessed(self, digest: bytes, *, admit: object = None) -> None:
        """Admit a digest only with the token ``accept_result`` holds.

        A one-argument call is not acceptance authority.
        """
        if admit is not self._admit:
            raise FailClosed("RESULT_EGRESS")
        if not isinstance(digest, (bytes, bytearray)) or len(digest) != 32:
            raise FailClosed("DIGEST")
        self._witnessed.add(bytes(digest))

    def witnessed(self, digest: bytes) -> bool:
        return bytes(digest) in self._witnessed

    def classify(self, digest: bytes, status: str) -> str:
        if status not in DOWNSTREAM:
            raise FailClosed("STATUS")
        if bytes(digest) not in self._witnessed:
            raise FailClosed(ZERO_ACCEPTANCE_AUTHORITY)
        return status

    def export(self) -> bytes:
        items = b"".join(sorted(self._witnessed))
        return b"OEG1" + bytes([1]) + struct.pack(">I", len(self._witnessed)) + items

    @classmethod
    def parse(cls, raw: bytes) -> "Egress":
        data = bytes(raw)
        if len(data) < 9 or data[:4] != b"OEG1" or data[4] != 1:
            raise FailClosed("EGRESS")
        count = struct.unpack_from(">I", data, 5)[0]
        if count > 4096 or len(data) != 9 + count * 32:
            raise FailClosed("EGRESS")
        egress = cls()
        offset = 9
        for _ in range(count):
            item = data[offset:offset + 32]
            offset += 32
            if item in egress._witnessed:
                raise FailClosed("EGRESS")
            egress._witnessed.add(item)
        return egress
