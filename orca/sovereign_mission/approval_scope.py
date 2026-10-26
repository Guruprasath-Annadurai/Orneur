"""Versioned canonical approval scope. Dispatch recomputes this digest."""

from __future__ import annotations

from urllib.parse import urlsplit

from orca.sovereign_mission.store import digest

SCOPE_VERSION = 1


def verification_policy(tool: str, arguments: dict) -> dict:
    if tool == "local_marker":
        return {
            "kind": "independent_file_receipt",
            "page_text_trusted": False,
            "verified_completion_allowed": True,
            "requires_pre_post": False,
            "independent_receipt_required_for_verified": True,
        }
    actions = list(arguments.get("actions") or [])
    mutating = bool(set(actions) & {"click", "fill"})
    return {
        "kind": "untrusted_dom_observation",
        "page_text_trusted": False,
        "verified_completion_allowed": False,
        "requires_pre_post": mutating,
        "independent_receipt_required_for_verified": True,
    }


def url_parts(url: str) -> dict:
    parts = urlsplit(url)
    return {
        "scheme": parts.scheme,
        "host": (parts.hostname or "").casefold(),
        "port": parts.port,
        "path": parts.path or "/",
        "query": parts.query,
        "url": url,
    }


def build_scope(
    *,
    mission_id: str,
    owner_user_id: str,
    step_id: str,
    tool: str,
    risk: str,
    arguments: dict,
    approval_id: str,
    nonce: str,
    expires_at: str,
    ttl_seconds: int,
) -> dict:
    payload = {
        "version": SCOPE_VERSION,
        "mission_id": mission_id,
        "owner_user_id": owner_user_id,
        "step_id": step_id,
        "tool": tool,
        "risk": risk,
        "arguments": arguments,
        "approval_id": approval_id,
        "nonce": nonce,
        "expires_at": expires_at,
        "ttl_seconds": ttl_seconds,
        "single_use": True,
        "verification_policy": verification_policy(tool, arguments),
    }
    if tool == "browser":
        payload["url"] = url_parts(arguments["url"])
        payload["actions"] = list(arguments["actions"])
        payload["selector"] = arguments.get("selector")
        payload["input_text"] = arguments.get("text")
        payload["form_values"] = arguments.get("form_values")
        payload["expect"] = arguments.get("expect")
        payload["delta_y"] = arguments.get("delta_y")
    else:
        payload["destination_name"] = arguments.get("name", "marker.txt")
        payload["input_text"] = arguments.get("text")
    return payload


def scope_digest(scope: dict) -> str:
    return digest(scope)
