"""Match a verified skill record to synthetic opportunity fixtures.

Listings are not invented scholarships or employers beyond the fixture the
caller supplies. This module does not submit an application.
"""
from __future__ import annotations

from datetime import datetime


class OpportunityError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def explain(listing: dict, *, skills: set[str], geo: str, now: datetime) -> dict:
    reasons = []
    if listing.get("status") == "contradictory":
        reasons.append("contradictory_listing")
    close = listing.get("closes_at")
    if close and _parse(close) <= now:
        reasons.append("expired")
    open_at = listing.get("opens_at")
    if open_at and _parse(open_at) > now:
        reasons.append("not_yet_open")
    if listing.get("geo") and listing["geo"] != geo:
        reasons.append("geo_mismatch")
    required = set(listing.get("required_skills") or [])
    missing = sorted(required - skills)
    if missing:
        reasons.append("missing_skills")
    if listing.get("verification") != "verified":
        reasons.append("unverified_source")
    eligible = not reasons
    return {
        "opportunity_id": listing["opportunity_id"],
        "eligible": eligible,
        "reasons": reasons,
        "missing_skills": missing,
        "source": listing.get("source"),
        "provenance": listing.get("provenance"),
        "application_submitted": False,
    }


def match(*, skills: set[str], geo: str, listings: list[dict], now: datetime) -> dict:
    seen: dict[str, list[dict]] = {}
    for listing in listings:
        seen.setdefault(listing["opportunity_id"], []).append(listing)
    rows = []
    for opportunity_id, group in seen.items():
        if len(group) > 1 and any(left != right for left in group for right in group):
            sample = dict(group[0])
            sample["status"] = "contradictory"
            rows.append(explain(sample, skills=skills, geo=geo, now=now))
            continue
        rows.append(explain(group[0], skills=skills, geo=geo, now=now))
    return {
        "schema": "orneur-opportunity-match/1",
        "results": rows,
        "application_submitted": False,
        "live_provider_connected": False,
    }


def checklist(row: dict) -> dict:
    if row["application_submitted"]:
        raise OpportunityError("submission_refused")
    items = ["confirm_identity"]
    items.extend(f"show_skill:{skill}" for skill in row["missing_skills"])
    if "expired" in row["reasons"]:
        items.append("do_not_apply_expired")
    return {"opportunity_id": row["opportunity_id"], "items": items, "application_submitted": False}
