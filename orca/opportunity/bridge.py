"""Proof + Opportunity Bridge contracts.

No live listings are minted. When no authorized source adapter is
configured, discovery returns NOT_AVAILABLE. Saved rows are user-owned
and ranked only among records the caller already stored.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "orneur.opportunity/1"
NOT_AVAILABLE = "NOT_AVAILABLE"


class OpportunityError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_SAVED: dict[str, list[dict]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def availability() -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "status": NOT_AVAILABLE,
        "live_source": False,
        "reason": "no_authorized_source_adapter",
    }


def discover(user_id: str, query: str, *, fixtures: list[dict] | None = None) -> dict:
    if not user_id or not isinstance(user_id, str):
        raise OpportunityError("unauthenticated")
    if not isinstance(query, str) or not query.strip():
        raise OpportunityError("query_refused")
    if fixtures is None:
        return {
            "schema": SCHEMA_VERSION,
            "status": NOT_AVAILABLE,
            "query": query.strip(),
            "listings": [],
            "live_source": False,
            "synthetic": False,
        }
    listings = []
    seen: set[str] = set()
    for item in fixtures:
        if item.get("owner_user_id") not in (None, user_id):
            continue
        key = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        listings.append(
            {
                "id": key[:16],
                "title": item.get("title"),
                "source": item.get("source", "fixture"),
                "captured_at": item.get("captured_at") or _now(),
                "license": item.get("license", "unspecified"),
                "synthetic": True,
                "provenance": "caller_fixture",
            }
        )
    return {
        "schema": SCHEMA_VERSION,
        "status": "fixture_only",
        "query": query.strip(),
        "listings": listings,
        "live_source": False,
        "synthetic": True,
    }


def save(user_id: str, listing: dict) -> dict:
    if not user_id:
        raise OpportunityError("unauthenticated")
    if listing.get("live_source"):
        raise OpportunityError("live_source_refused")
    if not listing.get("synthetic"):
        raise OpportunityError("unprovenanced_refused")
    row = {
        "user_id": user_id,
        "listing": listing,
        "saved_at": _now(),
        "id": hashlib.sha256(f"{user_id}:{listing.get('id')}".encode()).hexdigest()[:16],
    }
    bucket = _SAVED.setdefault(user_id, [])
    if any(existing["id"] == row["id"] for existing in bucket):
        return row
    bucket.append(row)
    return row


def rank_saved(user_id: str, other_user_id: str | None = None) -> list[dict]:
    if other_user_id and other_user_id != user_id:
        raise OpportunityError("access_denied")
    rows = list(_SAVED.get(user_id, []))
    return sorted(rows, key=lambda row: str(row["listing"].get("title") or ""), reverse=False)


def reset_for_tests() -> None:
    _SAVED.clear()


def execute_external(user_id: str, *_args: Any, **_kwargs: Any) -> None:
    raise OpportunityError("execution_not_authorized")
