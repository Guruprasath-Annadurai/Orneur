"""Authenticated mission execution on the product auth database.

This is not the Phase 15 Postgres mission store. That store needs a
Neon DSN this process is not allowed to provision, and its state list
cannot record an unknown outcome. The Phase 15 machine is unchanged.
"""

from orca.sovereign_mission.service import MissionError, SovereignMission

__all__ = ["MissionError", "SovereignMission"]
