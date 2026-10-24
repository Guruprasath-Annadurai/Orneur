"""Append-only failure notes for synthetic runs.

A producer cannot close its own record. Resolution stays pending
independent review and does not change weights, grants, or the ledger.
"""
from __future__ import annotations

import hashlib
import json


class FailureGenomeError(Exception):
    """The genome refused the write."""


class FailureGenome:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def record(self, *, failure_id: str, observed: str, produced_by: str) -> dict:
        if not failure_id or not observed or not produced_by:
            raise FailureGenomeError("failure_id, observed, and produced_by are required")
        if any(row["failure_id"] == failure_id for row in self.records):
            raise FailureGenomeError("duplicate failure id")
        body = {
            "failure_id": failure_id,
            "observed": observed,
            "produced_by": produced_by,
            "resolution": "OPEN",
        }
        body["digest"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        stored = dict(body)
        stored["resolved_by"] = None
        stored["regression_test_id"] = None
        self.records.append(stored)
        return dict(stored)

    def resolve(self, failure_id: str, *, decided_by: str, regression_test_id: str) -> dict:
        row = next((item for item in self.records if item["failure_id"] == failure_id), None)
        if row is None:
            raise FailureGenomeError("unknown failure id")
        if not decided_by or decided_by == row["produced_by"]:
            raise FailureGenomeError("producer cannot resolve its own failure")
        if not regression_test_id:
            raise FailureGenomeError("resolution requires a regression test id")
        row["resolution"] = "RESOLVED_PENDING_INDEPENDENT_REVIEW"
        row["resolved_by"] = decided_by
        row["regression_test_id"] = regression_test_id
        return dict(row)
