"""Controlled research feedback.

A proposal can be recorded and tested. It cannot accept itself, and it
cannot modify the acceptance register or a protected path.
"""
from __future__ import annotations

from dataclasses import dataclass, field


PROTECTED_PREFIXES = (
    "docs/orneur/acceptance/",
    "scripts/acceptance/",
    "orca/genesis/training/",
)


class SelfApprovalError(PermissionError):
    pass


@dataclass
class Proposal:
    proposal_id: str
    failure_id: str
    change: str
    author: str
    status: str = "PROPOSED"
    tests: list[str] = field(default_factory=list)


def propose(failure_id: str, change: str, *, author: str, tests: list[str]) -> Proposal:
    if any(change.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        raise SelfApprovalError(f"refusing to propose a write under a protected path: {change}")
    return Proposal(
        proposal_id=f"proposal-{failure_id}",
        failure_id=failure_id,
        change=change,
        author=author,
        tests=list(tests),
    )


def record_result(proposal: Proposal, *, passed: bool) -> Proposal:
    proposal.status = "TEST_RECORDED" if passed else "TEST_FAILED"
    return proposal


def accept(proposal: Proposal, *, approver: str) -> Proposal:
    if not approver or approver == proposal.author or approver == "self":
        raise SelfApprovalError("a proposal cannot accept itself")
    if proposal.status != "TEST_RECORDED":
        raise SelfApprovalError("acceptance requires a recorded passing test")
    proposal.status = "HUMAN_ACCEPTED"
    return proposal
