"""
OCL schema versioning. A wire artifact's `schema_version` is checked
against this module's supported set before anything else runs -- an
unsupported version fails closed (OCL-SCHEMA-002), never silently
coerced or best-effort parsed.
"""
from __future__ import annotations

CURRENT_SCHEMA_VERSION = "1.0.0"

# Versions this build's compiler can read. V1.0.0 is the only version that
# exists yet; this set exists so a future minor version can be added here
# without touching every call site.
SUPPORTED_SCHEMA_VERSIONS = frozenset({CURRENT_SCHEMA_VERSION})


def is_supported_schema_version(version: str) -> bool:
    return version in SUPPORTED_SCHEMA_VERSIONS
