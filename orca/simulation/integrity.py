"""
SimulationResult tamper-evidence (Phase 11 spec §53). Reuses the exact
HMAC pattern established in `orca.godmode.integrity` (itself modeled on
`orca.auth.tokens`) -- one signing primitive across the codebase, not a
third reinvention.
"""
from __future__ import annotations

import hashlib
import hmac

from orca.config import orneur_env
from orca.simulation.contracts import SimulationResult

_SECRET = orneur_env("SIMULATION_RESULT_SECRET", "dev-secret-change-me")

_SIGNED_FIELDS = ("result_id", "request_id", "mode_used", "verdict", "created_at")


def _canonical_payload(result: SimulationResult) -> str:
    parts = []
    for name in _SIGNED_FIELDS:
        value = getattr(result, name)
        domain_value = value.value if hasattr(value, "value") else value
        parts.append(f"{name}={domain_value}")
    # Effects/warnings/block_reasons are summarized by count + a stable
    # ordering of effect_ids -- binds the SET of effects the reviewer
    # saw without re-serializing full effect payloads into the hash.
    parts.append("effect_ids=" + ",".join(sorted(e.effect_id for e in result.predicted_effects)))
    parts.append("block_reasons=" + "|".join(result.block_reasons))
    return "\x1f".join(parts)


def sign_result(result: SimulationResult) -> str:
    payload = _canonical_payload(result)
    return hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def apply_result_signature(result: SimulationResult) -> SimulationResult:
    result.result_hash = sign_result(result)
    return result


def verify_result_integrity(result: SimulationResult) -> bool:
    """
    True only if `result.result_hash` matches a fresh signature over the
    result's CURRENT core fields (verdict, effects, block reasons) --
    a caller/tool/model that modifies `effects`, `risk`(via verdict),
    `verdict`, or `result_id` after the Chamber issued this result is
    detected here (spec §53: "do not let caller modify effects/risk/
    verdict/simulation ID after review").
    """
    if not result.result_hash:
        return False
    return hmac.compare_digest(result.result_hash, sign_result(result))


# ── Plan-level (Phase 11.1) -- same HMAC pattern, different field set ────

_PLAN_SIGNED_FIELDS = ("plan_simulation_id", "plan_id", "aggregate_verdict", "aggregate_blast_radius", "aggregate_reversibility")


def _plan_canonical_payload(result) -> str:
    parts = []
    for name in _PLAN_SIGNED_FIELDS:
        value = getattr(result, name)
        domain_value = value.value if hasattr(value, "value") else value
        parts.append(f"{name}={domain_value}")
    parts.append("action_order=" + ",".join(result.action_order))
    parts.append("effect_ids=" + ",".join(sorted(e.effect_id for e in result.aggregate_effects)))
    parts.append("block_reasons=" + "|".join(result.block_reasons))
    return "\x1f".join(parts)


def sign_plan_result(result) -> str:
    return hmac.new(_SECRET.encode(), _plan_canonical_payload(result).encode(), hashlib.sha256).hexdigest()


def apply_plan_result_signature(result):
    result.result_hash = sign_plan_result(result)
    return result


def verify_plan_result_integrity(result) -> bool:
    if not result.result_hash:
        return False
    return hmac.compare_digest(result.result_hash, sign_plan_result(result))
