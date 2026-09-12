"""
Compilation trust context (Phase 17 final closure). The root architectural
fix for a real, reproduced bypass: `provenance.producer_kind` is DATA
INSIDE the untrusted artifact -- a wire payload could self-declare
`producer_kind="DETERMINISTIC_SYSTEM"` and, under the prior closure's
logic, immediately unlock privileged evidence semantics in the SAME
self-authored payload. Trust must come from the INVOCATION/RUNTIME
boundary, never be parsed out of the artifact itself.

`CompilationTrustContext` is supplied by the CALLER of `compile_artifact()`,
never by anything inside the JSON/dataclass being compiled. The public
untrusted wire entry point (`canonical.compile_ocl_json`) ALWAYS compiles
with `UNTRUSTED_MODEL_OR_WIRE`, hardcoded -- no field in the wire payload
can elevate it. Only a caller who has independently, out-of-band,
established that a payload genuinely came from a deterministic system/tool
adapter/human may pass a stronger context explicitly to `compile_artifact()`
directly.
"""
from __future__ import annotations

from enum import Enum


class CompilationTrustContext(str, Enum):
    UNTRUSTED_MODEL_OR_WIRE = "UNTRUSTED_MODEL_OR_WIRE"
    TRUSTED_DETERMINISTIC_SYSTEM = "TRUSTED_DETERMINISTIC_SYSTEM"
    TRUSTED_TOOL_ADAPTER = "TRUSTED_TOOL_ADAPTER"
    TRUSTED_HUMAN_INPUT = "TRUSTED_HUMAN_INPUT"


UNTRUSTED = CompilationTrustContext.UNTRUSTED_MODEL_OR_WIRE

# Trust contexts that make PRIVILEGED_REFERENCE_SOURCE_CLASSES atoms
# admissible. Being in this set is necessary but NOT sufficient for a
# specific atom to compile -- it must also still be an OBSERVATION_REFERENCE
# atom citing a real EvidenceAnchor (see compiler.py). Note this is about
# whether the CALLER independently trusts the compilation, never about what
# the payload's own `provenance.producer_kind` claims.
TRUSTED_CONTEXTS = frozenset({
    CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM,
    CompilationTrustContext.TRUSTED_TOOL_ADAPTER,
    CompilationTrustContext.TRUSTED_HUMAN_INPUT,
})
