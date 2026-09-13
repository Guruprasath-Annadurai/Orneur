"""
Orneur self-updater — checks PyPI for a newer version and upgrades in-place.

IMPORTANT (ORNEUR corporate identity closure): this used to point at PyPI
package "orca-ai". That name is registered on PyPI by an unrelated third
party ("Orca Systems", https://github.com/orca-systems/orca) -- NOT this
project. This project's own package has never been published under that
name (its PyPI release history contains only 0.1.0/0.1.1 by that other
author; this repo's version has never matched). Checking that package's
version for "updates" was a live supply-chain-confusion risk: if that
unrelated package ever published a version number higher than this
project's local version, `self_update()` would silently `pip install
--upgrade orca-ai`, installing a stranger's unrelated software. `_PACKAGE`
now points at "orneur" (unregistered on PyPI as of this writing -- see
docs/orneur/brand/ORNEUR_PACKAGING_MIGRATION.md) instead: until this
project actually publishes under that name, `get_latest_version()` simply
returns None (404), and `is_update_available()` reports no update
available/reachable, which is honest and safe.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

_PYPI_URL = "https://pypi.org/pypi/orneur/json"
_PACKAGE   = "orneur"


def _current_version() -> str:
    try:
        from importlib.metadata import version
        return version(_PACKAGE)
    except Exception:
        from orca.__version__ import __version__
        return __version__


def get_latest_version() -> Optional[str]:
    """Return the latest version string from PyPI, or None on network failure."""
    try:
        import urllib.request, json
        with urllib.request.urlopen(_PYPI_URL, timeout=8) as r:
            data = json.loads(r.read())
        return data["info"]["version"]
    except Exception:
        return None


def _parse_version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except Exception:
        return (0,)


def is_update_available() -> tuple[bool, str, str]:
    """
    Returns (available, current, latest).
    available=False if network is down or already up to date.
    """
    current = _current_version()
    latest  = get_latest_version()
    if not latest:
        return False, current, ""
    if _parse_version(latest) > _parse_version(current):
        return True, current, latest
    return False, current, latest


def self_update(yes: bool = False) -> bool:
    """
    Upgrade orca-ai via pip. Returns True on success.
    Raises RuntimeError if pip fails.
    """
    available, current, latest = is_update_available()
    if not available:
        return False

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", _PACKAGE, "--quiet"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "pip upgrade failed")
    return True
