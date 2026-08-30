"""
Process-wide CognitiveKernel singleton -- same pattern as
orca/gateway/wiring.py's shared ModelGateway. Built lazily so tests can
construct their own isolated CognitiveKernel instances without touching
this module-level singleton at all.
"""
from __future__ import annotations

import threading

from orca.cognitive.kernel import CognitiveKernel

_lock = threading.Lock()
_kernel: CognitiveKernel | None = None


def get_shared_kernel() -> CognitiveKernel:
    global _kernel
    with _lock:
        if _kernel is None:
            _kernel = CognitiveKernel()
        return _kernel


def reset_for_tests() -> None:
    global _kernel
    with _lock:
        _kernel = None
