"""ORNEUR independent-evaluation infrastructure (Workstream F): synthetic-data-only, no model calls, no network, no secrets.

Everything in this package is a *mechanism* (schemas, gates, statistics, hash chains). Nothing here is evidence of any model capability, holds any
private-corpus material, or authorizes anything. It extends -- never replaces -- the gates in `orca.eval.genesis_v2`.
"""
from __future__ import annotations

PACKAGE_VERSION = "orneur-evalinfra/1"
