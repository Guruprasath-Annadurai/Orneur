"""
Lifecycle ranking for Model Society hard filters. A single explicit,
auditable ordering -- reused everywhere Society needs to compare a
checkpoint's lifecycle against a role's minimum requirement, rather than
scattering ad-hoc string comparisons (Phase 7 spec §47).

REJECTED and RETIRED are never routable regardless of any role's declared
minimum -- see `is_lifecycle_disqualified`.
"""
from __future__ import annotations

from orca.registry.model_spec import LifecycleState

# A society-specific pseudo-state, distinct from any orca.registry.model_spec
# LifecycleState value on purpose. Genesis's legacy 7B checkpoint
# (orca-nano-v7) is RETIRED in the formal ModelRegistry promotion state
# machine -- that RETIRED reflects "not the canonical future 3B
# architecture" (see orca/registry/model_spec.py's legacy_note), NOT
# "unsafe/withdrawn from serving." It is, in fact, the exact artifact that
# has served the "nano" tier in production for a long time via a separate,
# untouched authority (orca/serve/registry.py's tier resolution, which does
# not consult ModelRegistry lifecycle at all -- see
# docs/orneur/phase-7/CURRENT_MODEL_ROUTING.md). Treating it as
# ModelRegistry-RETIRED (never routable) would regress real, working
# behavior for no safety benefit; treating it as ModelRegistry-PRODUCTION
# would be a false claim this project has not earned. LEGACY_PRODUCTION_SERVING
# names the real, disclosed, in-between fact.
LEGACY_PRODUCTION_SERVING = "LEGACY_PRODUCTION_SERVING"

_RANK: dict[str, int] = {
    LifecycleState.REJECTED.value: -1,
    LifecycleState.RETIRED.value: -1,
    LifecycleState.EXPERIMENTAL.value: 0,
    LifecycleState.CANDIDATE.value: 1,
    LifecycleState.EVALUATING.value: 1,
    LifecycleState.APPROVED.value: 2,
    LifecycleState.TRAINED.value: 2,
    LifecycleState.PRODUCTION.value: 3,
    LEGACY_PRODUCTION_SERVING: 2,
}


def lifecycle_rank(lifecycle_state: str) -> int:
    return _RANK.get(lifecycle_state, -1)


def is_lifecycle_disqualified(lifecycle_state: str) -> bool:
    """REJECTED/RETIRED (the formal ModelRegistry states) are always
    disqualified -- no role requirement can override this (spec §13:
    lifecycle is a hard filter, never a ranking dimension).
    LEGACY_PRODUCTION_SERVING is deliberately NOT included here -- see its
    definition above."""
    return lifecycle_state in (LifecycleState.REJECTED.value, LifecycleState.RETIRED.value)


def is_experimental(lifecycle_state: str) -> bool:
    return lifecycle_state == LifecycleState.EXPERIMENTAL.value
