"""Errors of the vector-store layer. Standard library only (the server imports this path without chromadb installed)."""
from __future__ import annotations


class VectorError(Exception):
    """Base class. Messages never contain user content."""


class VectorUnavailable(VectorError):
    """The vector store did not answer in time, is restarting, or failed. The operation did NOT complete as far as the caller can know."""


class VectorTimeout(VectorUnavailable):
    """The operation's wall-clock deadline passed. The caller was released at the deadline; the operation may still be running or may have completed."""


class VectorBusy(VectorError):
    """Admission refused: too many operations are running or waiting (backpressure). Nothing was started."""


class VectorOwnershipError(VectorError):
    """The collection is bound to a different conversation (or its binding cannot be verified): it is not read and not written."""


class VectorNotFound(VectorError):
    """No such collection."""
