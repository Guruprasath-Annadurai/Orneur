"""Conservative, finite validation limits for Phase 20 inputs (DoS
protection), mirroring orneur.intelligence.integrity.limits."""
from __future__ import annotations

MAX_REQUIREMENTS_PER_TASK = 32
MAX_MATERIAL_ATOMS_PER_TASK = 500
MAX_REGISTRY_ENTRIES = 32
MAX_METADATA_KEYS = 64
MAX_METADATA_DEPTH = 4
MAX_STRING_FIELD_LENGTH = 20_000
MAX_DECISION_SERIALIZED_BYTES = 8 * 1024 * 1024  # 8 MiB
