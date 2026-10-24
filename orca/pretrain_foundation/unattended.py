"""Deterministic incident intake without a patch-generating model.

Poll creates or reuses an incident from a detector result. Patch generation
stays NOT DEMONSTRATED until an authorized model backend is enrolled.
A detector result is data; it is not permission to edit the repository.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from orca.pretrain_foundation.incident_engine import IncidentEngine

PATCH_GENERATION = "NOT DEMONSTRATED"


class UnattendedRepair:
    def __init__(self, root: Path, detector, *, now=None, worker_id: str = "repair-worker") -> None:
        self.engine = IncidentEngine(root, now=now)
        self.detector = detector
        self.worker_id = worker_id

    def poll(self) -> dict | None:
        fault = self.detector()
        if not isinstance(fault, dict):
            return None
        fingerprint = str(fault.get("fingerprint") or "")
        signal = str(fault.get("signal") or "")
        commit = str(fault.get("source_commit") or "")
        if not fingerprint or not signal or not commit:
            return None
        incident_id = "INC-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
        row = self.engine.detect(
            incident_id=incident_id,
            source_commit=commit,
            signal=signal,
            fingerprint=fingerprint,
            owner_id=self.worker_id,
            deadline_unix=self.engine.now() + 3600,
            budget_units=8,
            retry_limit=3,
        )
        row["patch_generation"] = PATCH_GENERATION
        row["human_command"] = False
        return row

    def investigate(self, incident_id: str, source_text: str) -> dict:
        digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        self.engine.note(incident_id, actor_id=self.worker_id, text=f"source digest {digest}")
        return {
            "source_digest": digest,
            "patch_generation": PATCH_GENERATION,
            "patch_text": None,
            "production_authorization": "DENIED",
        }

    def report(self, incident_id: str) -> dict:
        report = self.engine.build_report(incident_id)
        report["patch_generation"] = PATCH_GENERATION
        report["production_authorization"] = "DENIED"
        report["autonomous_patch"] = False
        return report
