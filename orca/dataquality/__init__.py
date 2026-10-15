"""Deterministic dataset-quality and provenance tooling (Workstream E).

Pure CPU / stdlib: no network, no model inference, no training, no provider calls. Every report is canonical JSON with stable key ordering and
carries NO timestamp unless the caller passes an explicit ``now``. Reports aggregate per-check statuses (PASS / FAIL / NOT_EVALUATED) and
deliberately never collapse them into a single quality score.

Reuses (does not duplicate): orca.registry.dataset_manifest (manifest dataclass + sha256_of_file), orca.eval.genesis_v2.similarity (MinHash/LSH,
shingling, skeleton tokens), orca.eval.genesis_contamination (word n-gram fingerprints), orca.eval.genesis_v2.semantic (local semantic engine
contract), orca.eval.genesis_v2.privacy_scan (protected-corpus marker scan), orca.docs.pii_redact and orca.serve.dlp (PII / secret patterns).
"""
from __future__ import annotations

SCHEMA_VERSION = "orneur-dataquality/1"
PASS, FAIL, NOT_EVALUATED = "PASS", "FAIL", "NOT_EVALUATED"
STATUSES = (PASS, FAIL, NOT_EVALUATED)
