"""
Phase 15.7 -- source provenance (spec section 4).

A single, shared enum used by ProductContract fields, compiled
Requirements, and Assumptions/Facts alike, so "the owner said this"
is never structurally indistinguishable from "ORNEUR inferred this."
"""
from __future__ import annotations

from enum import Enum


class SourceProvenance(str, Enum):
    OWNER_EXPLICIT = "OWNER_EXPLICIT"
    SOURCE_SPEC = "SOURCE_SPEC"
    INFERRED_ASSUMPTION = "INFERRED_ASSUMPTION"
    SYSTEM_CONSTRAINT = "SYSTEM_CONSTRAINT"
    SECURITY_INVARIANT = "SECURITY_INVARIANT"
    DERIVED_FROM_REQUIREMENT = "DERIVED_FROM_REQUIREMENT"
    EXTERNAL_EVIDENCE = "EXTERNAL_EVIDENCE"
