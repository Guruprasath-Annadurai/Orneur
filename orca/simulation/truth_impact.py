"""
Truth-affected verdict (Phase 11.1 spec §22). A critical assumption that
fails real Truth Fabric verification must not leave a high-risk
simulation at PASS -- deterministic downgrade policy, no model voting.
"""
from __future__ import annotations

from orca.simulation.contracts import Assumption, SimulationVerdict

_FAILED_VERIFICATION_STATES = {"CONTESTED", "UNVERIFIED"}


def apply_truth_impact_to_verdict(
    verdict: SimulationVerdict, assumptions: list[Assumption], *, is_high_risk: bool,
) -> tuple[SimulationVerdict, list[str]]:
    """
    Only ever DOWNGRADES a verdict, never upgrades one -- a
    Truth-verified assumption does not turn a BLOCK into a PASS (spec
    §45: only this module's own comparison against real
    `Assumption.verification_state` values can move the verdict, never
    a model/user claim of "verified"). For a non-high-risk simulation,
    Truth outcomes are recorded but never gate the verdict (spec §22
    scopes the requirement to high-risk simulations specifically).
    """
    warnings: list[str] = []
    if not is_high_risk:
        return verdict, warnings

    failed = [a for a in assumptions if a.verification_state in _FAILED_VERIFICATION_STATES]
    if not failed:
        return verdict, warnings

    warnings.append(f"{len(failed)} assumption(s) failed Truth Fabric verification ({sorted({a.verification_state for a in failed})}) for a high-risk simulation")

    if verdict == SimulationVerdict.BLOCK:
        return verdict, warnings  # already the worst outcome
    if any(a.verification_state == "CONTESTED" for a in failed):
        return SimulationVerdict.REVISE, warnings  # conflicting evidence -- the plan may need to change, not just wait
    return SimulationVerdict.INCONCLUSIVE, warnings  # UNVERIFIED only -- insufficient evidence, not necessarily wrong
