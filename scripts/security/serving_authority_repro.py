#!/usr/bin/env python3
"""Task B before/after: can an environment flag or a tier-name alias get an unqualified model onto a public edge?

Uses only orca.gateway.wiring + ModelNotRoutableError, so it runs unchanged against the original (PR #25) and the fixed tree:

    python scripts/security/serving_authority_repro.py
    git stash push -- orca && python scripts/security/serving_authority_repro.py; git stash pop     # original wiring

No model, Ollama or network is involved: routing decisions only.
"""
from __future__ import annotations

import os

from orca.gateway import wiring
from orca.gateway.errors import ModelNotRoutableError
from orca.serve.registry import TierResolution


def routable(res, **env) -> bool:
    for k in ("ORNEUR_PUBLIC_EDGE", "ORNEUR_ALLOW_EXPERIMENTAL_SERVING"):
        os.environ.pop(k, None)
    os.environ.update(env)
    wiring.reset_for_tests()
    brain = wiring.brain_for_tier_resolution(res)
    try:
        brain._gateway.resolve_deployment(brain.model_id, brain.model_version, brain.allow_experimental)
        return True
    except ModelNotRoutableError:
        return False
    finally:
        wiring.reset_for_tests()


NOVUS = TierResolution(tier="core", backend="ollama", model="orca-core-combined-v2", data_left_infrastructure=False)
ALIAS = TierResolution(tier="nano", backend="ollama", model="orca-core-combined-v2", data_left_infrastructure=False)   # nano tier pointed at the Novus artifact
LEGACY = TierResolution(tier="nano", backend="ollama", model="orca-nano-v7", data_left_infrastructure=False)

CASES = [
    ("public edge, unqualified Novus, no flag", NOVUS, {"ORNEUR_PUBLIC_EDGE": "1"}, False),
    ("public edge, unqualified Novus, FLAG ONLY", NOVUS, {"ORNEUR_PUBLIC_EDGE": "1", "ORNEUR_ALLOW_EXPERIMENTAL_SERVING": "1"}, False),
    ("public edge, Novus artifact aliased onto the nano tier", ALIAS, {"ORNEUR_PUBLIC_EDGE": "1"}, False),
    ("public edge, pinned legacy Genesis (documented decision kept)", LEGACY, {"ORNEUR_PUBLIC_EDGE": "1"}, True),
    ("private deployment, Novus", NOVUS, {}, True),
]

if __name__ == "__main__":
    bad = 0
    for name, res, env, want in CASES:
        got = routable(res, **env)
        verdict = "ok" if got == want else "EXPLOITABLE" if got and not want else "REGRESSION"
        bad += verdict != "ok"
        print(f"{verdict:<12} served={str(got):<5} {name}")
    raise SystemExit(1 if bad else 0)
