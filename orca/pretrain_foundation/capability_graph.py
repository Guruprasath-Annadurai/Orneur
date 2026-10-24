"""Versioned routing facts for declared roles.

A caller advertisement is not a qualification. Blocking a task here only
affects routers that receive this object. It does not edit the role registry.
"""
from __future__ import annotations


class CapabilityGraph:
    version = "capability-graph-v1"

    def __init__(self) -> None:
        self._blocked: dict[str, str] = {}

    def block(self, task: str, reason: str) -> None:
        if not task or not reason:
            raise ValueError("task and reason are required")
        self._blocked[task] = reason

    def allows(self, task: str) -> bool:
        return task not in self._blocked

    def advertisement_trusted(self, _payload: dict) -> bool:
        return False
