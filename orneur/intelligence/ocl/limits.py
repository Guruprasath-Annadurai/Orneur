"""
OCL V1 conservative validation limits (spec section 33: "set conservative
validation limits based on evidence", section 17: DoS protection against
oversized/pathological graphs). These are deliberately generous but finite
-- chosen so ordinary cognitive artifacts (see performance benchmarks in
PHASE17_EVIDENCE.md) pass comfortably while a pathological/adversarial
payload is rejected before it can consume unbounded validation time.
"""
from __future__ import annotations

MAX_ATOMS_PER_ARTIFACT = 2000
MAX_RELATIONS_PER_ARTIFACT = 4000
MAX_METADATA_KEYS = 64
MAX_METADATA_DEPTH = 4
MAX_STRING_FIELD_LENGTH = 20_000  # a single atom's content/summary text
MAX_ARTIFACT_SERIALIZED_BYTES = 8 * 1024 * 1024  # 8 MiB wire payload cap
