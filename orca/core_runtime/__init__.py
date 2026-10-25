"""Local product runtime for structured missions.

This package does not replace ``orca.mission.mission_store`` (Postgres) or
the in-process product-contract registry. It does not load model weights,
authorize training, or submit applications.
"""

SCHEMA = "orneur-core-runtime/1"
