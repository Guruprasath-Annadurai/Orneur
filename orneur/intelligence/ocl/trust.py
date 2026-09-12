"""
Compilation trust context (Phase 17 final closure). The root architectural
fix for a real, reproduced bypass: `provenance.producer_kind` is DATA
INSIDE the untrusted artifact -- a wire payload could self-declare
`producer_kind="DETERMINISTIC_SYSTEM"` and, under an earlier closure's
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

`compile_artifact()` MUST reject anything that is not a genuine
`CompilationTrustContext` instance (`InvalidTrustContext`) -- a plain
string that happens to equal an enum member's value is NOT accepted, even
though `str`-mixin `Enum` members compare/hash equal to their string
value. This closes a real bypass where `trust_context="TRUSTED_
DETERMINISTIC_SYSTEM"` (a bare string, not the enum) was silently treated
as trusted.
"""
from __future__ import annotations

from enum import Enum

from orneur.intelligence.ocl.enums import EvidenceKind, SourceClass


class CompilationTrustContext(str, Enum):
    UNTRUSTED_MODEL_OR_WIRE = "UNTRUSTED_MODEL_OR_WIRE"
    TRUSTED_DETERMINISTIC_SYSTEM = "TRUSTED_DETERMINISTIC_SYSTEM"
    TRUSTED_TOOL_ADAPTER = "TRUSTED_TOOL_ADAPTER"
    TRUSTED_HUMAN_INPUT = "TRUSTED_HUMAN_INPUT"


UNTRUSTED = CompilationTrustContext.UNTRUSTED_MODEL_OR_WIRE

# Not every trusted caller is equally capable (Phase 17 final closure
# section 6). A TRUSTED_TOOL_ADAPTER is not a Court or Policy system, and
# TRUSTED_HUMAN_INPUT proves only that the runtime authenticated a human
# source -- it must NOT itself unlock deterministic-policy/Court/
# Production-Proof semantics. This matrix says which SourceClass values
# each trust context may unlock. UNTRUSTED_MODEL_OR_WIRE unlocks none of
# the privileged ones -- MODEL_ASSERTION, HUMAN_INPUT,
# EXTERNAL_EVIDENCE_REFERENCE (an UNVERIFIED reference, deliberately NOT
# privileged -- see enums.py), UNKNOWN, and DERIVED_COGNITIVE_PROPOSAL
# remain always expressible regardless of trust context, since none of
# them require compiler-side privilege at all.
SOURCE_CLASS_CAPABILITY_MATRIX: dict[CompilationTrustContext, frozenset] = {
    CompilationTrustContext.UNTRUSTED_MODEL_OR_WIRE: frozenset(),
    CompilationTrustContext.TRUSTED_TOOL_ADAPTER: frozenset({
        SourceClass.MEASURED_EVIDENCE_REFERENCE,
    }),
    CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM: frozenset({
        SourceClass.MEASURED_EVIDENCE_REFERENCE,
        SourceClass.DETERMINISTIC_POLICY_REFERENCE,
    }),
    CompilationTrustContext.TRUSTED_HUMAN_INPUT: frozenset(),
}

# Which EvidenceKind values each trust context may cite on a privileged
# atom (section 7) -- a second, independent gate alongside the SourceClass
# matrix above, so e.g. a TRUSTED_TOOL_ADAPTER cannot certify a
# COURT_DECISION merely because it is "trusted" in some generic sense.
EVIDENCE_KIND_CAPABILITY_MATRIX: dict[CompilationTrustContext, frozenset] = {
    CompilationTrustContext.UNTRUSTED_MODEL_OR_WIRE: frozenset(),
    CompilationTrustContext.TRUSTED_TOOL_ADAPTER: frozenset({
        EvidenceKind.MEASURED_SYSTEM_DATA, EvidenceKind.TOOL_OUTPUT,
        EvidenceKind.SOURCE_DOCUMENT, EvidenceKind.EXTERNAL_RETRIEVAL_RESULT,
    }),
    CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM: frozenset({
        EvidenceKind.MEASURED_SYSTEM_DATA, EvidenceKind.VERIFICATION_RECORD,
        EvidenceKind.PRODUCTION_PROOF, EvidenceKind.COURT_DECISION,
        EvidenceKind.DETERMINISTIC_POLICY_FACT,
    }),
    CompilationTrustContext.TRUSTED_HUMAN_INPUT: frozenset(),
}


def is_valid_trust_context(value) -> bool:
    """`value` must be an actual `CompilationTrustContext` ENUM MEMBER, not
    a plain string that happens to equal one's value. `isinstance(value,
    CompilationTrustContext)` alone is the correct, sufficient check here:
    a bare Python `str` is never `isinstance` of an `Enum` subclass, even a
    `str`-mixin one -- only real membership on `CompilationTrustContext`
    satisfies it. (The real bug this closes was elsewhere: code that
    checked membership via `trust_context in {...enum members...}`, which
    -- because `str`-mixin `Enum` equality/hash matches the plain string --
    silently accepted a bare string. Using `isinstance` directly avoids
    that trap entirely.)"""
    return isinstance(value, CompilationTrustContext)
