"""
OCL schema versioning. A wire artifact's `schema_version` is checked
against this module's supported set before anything else runs -- an
unsupported version fails closed (OCL-SCHEMA-002), never silently
coerced or best-effort parsed.

V1 reader policy (Phase 17 closure section 7 -- documented and tested NOW,
even though only one version exists, so a future 1.x addition does not
require re-deriving this policy from scratch):

- SAME exact version                -> ACCEPT
- unsupported MAJOR (e.g. "2.0.0")  -> REJECT (`UnsupportedSchemaVersion`)
- a future MINOR not explicitly
  registered in `SUPPORTED_SCHEMA_VERSIONS` -> REJECT (never silently
  treated as compatible just because the major matches)
- unknown fields on the wire        -> REJECT (`parse_ocl_draft_json`'s
  strict per-level field-set check, not this module's concern)
- deprecated fields (none exist yet)-> must remain explicitly recognized
  until removed by a future MAJOR version
- removed fields (none exist yet)   -> require an explicit MAJOR version
  transition; this build has nothing to remove

No speculative V2 schema is implemented -- this policy exists so the FIRST
real 1.x/2.0 revision has an already-agreed contract to extend, not a
green field.
"""
from __future__ import annotations

CURRENT_SCHEMA_VERSION = "1.0.0"

# Every version this build's compiler will read. Adding a new compatible
# minor version means adding it here explicitly -- it is never inferred
# from a matching major-version prefix.
SUPPORTED_SCHEMA_VERSIONS = frozenset({CURRENT_SCHEMA_VERSION})


def is_supported_schema_version(version: str) -> bool:
    return version in SUPPORTED_SCHEMA_VERSIONS


def schema_policy_for(version: str) -> str:
    """Returns one of "ACCEPT" / "REJECT_UNSUPPORTED_VERSION" -- a
    documentation/testing hook for the V1 reader policy above. This is
    deliberately NOT a multi-branch major/minor comparison engine (that
    would be speculative V2 machinery); it simply names, for the one
    version that exists, what happens and why."""
    if version == CURRENT_SCHEMA_VERSION:
        return "ACCEPT"
    return "REJECT_UNSUPPORTED_VERSION"
