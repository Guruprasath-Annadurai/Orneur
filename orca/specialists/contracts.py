"""Specialist invocation contracts. Capability is necessary, not sufficient."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SpecialistError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SpecialistSpec:
    role: str
    version: str
    capabilities: frozenset[str]
    side_effect: str
    description: str


@dataclass
class SpecialistResult:
    role: str
    status: str
    output: dict[str, Any]
    evidence: dict[str, Any]
    tenant_id: str
    synthetic: bool = False
    error: str | None = None


@dataclass
class TaskNode:
    task_id: str
    role: str
    payload: dict[str, Any]
    depends_on: tuple[str, ...] = ()
    capabilities: frozenset[str] = field(default_factory=frozenset)
    irreversible: bool = False
