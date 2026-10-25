"""Match a verified skill record to synthetic opportunity fixtures.

Listings are not invented scholarships or employers beyond the fixture the
caller supplies. This module does not submit an application.
"""
from __future__ import annotations

from datetime import datetime, timezone


class OpportunityError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _clock(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise OpportunityError("naive_clock")
    return now.astimezone(timezone.utc)


def _parse(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OpportunityError("invalid_date")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise OpportunityError("invalid_date") from None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise OpportunityError("naive_date")
    return parsed.astimezone(timezone.utc)


def explain(listing: dict, *, skills: set[str], geo: str, now: datetime) -> dict:
    clock = _clock(now)
    reasons = []
    if listing.get("status") == "contradictory":
        reasons.append("contradictory_listing")
    close = None
    open_at = None
    try:
        if listing.get("closes_at"):
            close = _parse(listing.get("closes_at"))
        if listing.get("opens_at"):
            open_at = _parse(listing.get("opens_at"))
    except OpportunityError as exc:
        reasons.append(exc.code)
    else:
        if close is not None and open_at is not None and close <= open_at:
            reasons.append("invalid_window")
        if close is not None and close <= clock:
            reasons.append("expired")
        if open_at is not None and open_at > clock:
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
    _clock(now)
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
        "external_integration": False,
    }


def checklist(row: dict) -> dict:
    if row["application_submitted"]:
        raise OpportunityError("submission_refused")
    items = ["confirm_identity"]
    items.extend(f"show_skill:{skill}" for skill in row["missing_skills"])
    if "expired" in row["reasons"]:
        items.append("do_not_apply_expired")
    return {"opportunity_id": row["opportunity_id"], "items": items, "application_submitted": False}
