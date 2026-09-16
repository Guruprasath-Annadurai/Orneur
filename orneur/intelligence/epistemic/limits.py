"""Conservative, finite validation limits for Phase 18 inputs (DoS
protection), mirroring orneur.intelligence.ocl.limits."""
from __future__ import annotations

MAX_ATOMS_ASSESSED = 2000
MAX_EVIDENCE_RESOLUTIONS = 8000
MAX_FEASIBILITY_RECORDS = 2000
MAX_METADATA_KEYS = 64
MAX_METADATA_DEPTH = 4
MAX_STRING_FIELD_LENGTH = 20_000
MAX_OVERLAY_SERIALIZED_BYTES = 8 * 1024 * 1024  # 8 MiB
