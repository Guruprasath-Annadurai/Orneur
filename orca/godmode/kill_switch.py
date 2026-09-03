"""
System-level Godmode kill switch (Phase 10 spec §15). File-backed under
`ORCA_HOME` (the same real, existing home-directory convention every
other persisted registry in this codebase uses -- `orca.gateway.wiring`'s
deployment records, `orca.connectors`' would-be lease store) so it
survives a process restart (spec §58): a restarted process must not
"forget" that the kill switch was active.

The kill switch itself never depends on model behavior -- it is a plain
file flag checked by Python code only; no model output path can set,
clear, or inspect it (no tool exposes this module to `AgentToolRegistry`
at all -- see AGENT_INTEGRATION.md).
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.config import ORCA_HOME
from orca.godmode.contracts import now_iso

_KILL_SWITCH_FILE = ORCA_HOME / "godmode" / "kill_switch.flag"


@dataclass
class KillSwitchStatus:
    active: bool
    activated_at: str | None
    reason: str | None


def activate(*, reason: str = "") -> KillSwitchStatus:
    _KILL_SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KILL_SWITCH_FILE.write_text(f"{now_iso()}\n{reason}\n")
    return status()


def deactivate() -> KillSwitchStatus:
    if _KILL_SWITCH_FILE.exists():
        _KILL_SWITCH_FILE.unlink()
    return status()


def is_active() -> bool:
    return _KILL_SWITCH_FILE.exists()


def status() -> KillSwitchStatus:
    if not _KILL_SWITCH_FILE.exists():
        return KillSwitchStatus(active=False, activated_at=None, reason=None)
    try:
        lines = _KILL_SWITCH_FILE.read_text().splitlines()
        activated_at = lines[0] if lines else None
        reason = lines[1] if len(lines) > 1 else None
    except Exception:
        activated_at, reason = None, None
    return KillSwitchStatus(active=True, activated_at=activated_at, reason=reason)
