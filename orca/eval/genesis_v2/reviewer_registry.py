"""Reviewer registry: WHO may sign a manual-review disposition (orca.eval.genesis_v2.review), and which review domains they may rule on.
Registering a reviewer performs no review — no private item is reviewed in this phase because no private corpus exists.

Separation of duties: by default an identity registered as an authority (OWNER/DELEGATED_OWNER) may not also act as a reviewer for the same
identity id unless the record sets `allow_dual_role: true` — an explicit, auditable exception rather than a silent one."""
from __future__ import annotations

from orca.eval.genesis_v2 import identity_registry as ID

SCHEMA_VERSION = "genesis-v2-reviewer-registry/1"
REGISTRY_PATH = "docs/orneur/authorization/REVIEWER_REGISTRY.json"
ROLES = ("PRIVATE_BENCHMARK_REVIEWER", "OWNER")
DOMAINS = ("CONTAMINATION_REVIEW", "SPLIT_ISOLATION_REVIEW", "STRUCTURAL_UNASSESSABLE_REVIEW", "SEMANTIC_AMBIGUITY_REVIEW", "FULL_MANUAL_REVIEW")
REQUIRED_FIELDS = ID.BASE_FIELDS + ("allowed_review_domains", "allow_dual_role")


def empty_registry() -> dict:
    return ID.empty_registry(SCHEMA_VERSION)


def load(path):
    return ID.load(path, SCHEMA_VERSION, validate)


def validate_record(r) -> list:
    p = ID.validate_base(r)
    if not isinstance(r, dict):
        return p
    if set(r) != set(REQUIRED_FIELDS):
        return p + [f"reviewer record schema mismatch: expected {sorted(REQUIRED_FIELDS)}, got {sorted(r)}"]
    if r["role"] not in ROLES:
        p.append(f"role must be one of {ROLES}")
    if not isinstance(r["allowed_review_domains"], list) or not r["allowed_review_domains"] or not set(r["allowed_review_domains"]) <= set(DOMAINS):
        p.append("allowed_review_domains must be a non-empty subset of " + str(DOMAINS))
    if not isinstance(r["allow_dual_role"], bool):
        p.append("allow_dual_role must be a boolean")
    return p


def validate(doc) -> list:
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION or not isinstance(doc.get("records"), list):
        return ["registry schema mismatch"]
    p, seen = [], set()
    for r in doc["records"]:
        p += validate_record(r)
        rid = r.get("id") if isinstance(r, dict) else None
        if rid in seen:
            p.append(f"duplicate id {rid}")
        seen.add(rid)
    return p


def active_reviewer_keys(doc: dict) -> list:
    return ID.active_keys(doc)


def check_separation_of_duties(authority_doc: dict, reviewer_doc: dict) -> list:
    auth_ids = {r["id"] for r in authority_doc.get("records", []) if ID.is_active(r)}
    return [r["id"] for r in reviewer_doc.get("records", []) if r.get("id") in auth_ids and not r.get("allow_dual_role", False)]
