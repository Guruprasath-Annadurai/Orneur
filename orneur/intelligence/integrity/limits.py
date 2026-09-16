"""Conservative, finite validation limits for Phase 19 inputs (DoS
protection), mirroring orneur.intelligence.epistemic.limits."""
from __future__ import annotations

MAX_ASSERTIONS_PER_PROPOSAL = 500
MAX_SCOPE_ATOMS = 500
MAX_POLICY_STATE_ENTRIES = 16
MAX_METADATA_KEYS = 64
MAX_METADATA_DEPTH = 4
MAX_STRING_FIELD_LENGTH = 20_000
MAX_RECEIPT_SERIALIZED_BYTES = 8 * 1024 * 1024  # 8 MiB
