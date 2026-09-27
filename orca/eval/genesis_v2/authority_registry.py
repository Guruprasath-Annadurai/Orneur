"""Authority registry: WHO may sign a model-execution authorization (orca.eval.genesis_v2.authorization), and what classes/stages/permissions
their signature is scoped to. Registering an authority is NOT authorizing a run — orca.eval.genesis_v2.authorization.verify() still requires a
separately signed, request-exact authorization record checked against these keys. Private signing keys never appear here."""
from __future__ import annotations

from orca.eval.genesis_v2 import identity_registry as ID
from orca.eval.genesis_v2 import spec as _spec

SCHEMA_VERSION = "genesis-v2-authority-registry/1"
REGISTRY_PATH = "docs/orneur/authorization/AUTHORITY_REGISTRY.json"
ROLES = ("OWNER", "DELEGATED_OWNER")
AUTHORIZATION_CLASSES = ("QUALIFICATION", "SCREENING", "TRAINABILITY_PILOT", "DATA_SEEDING", "REGRESSION")
REQUIRED_FIELDS = ID.BASE_FIELDS + ("permitted_authorization_classes", "permitted_eval_stages", "gpu_permission", "spend_permission",
                                    "provider_inference_permission")


def empty_registry() -> dict:
    return ID.empty_registry(SCHEMA_VERSION)


def load(path):
    return ID.load(path, SCHEMA_VERSION, validate)


def validate_record(r) -> list:
    p = ID.validate_base(r)
    if not isinstance(r, dict):
        return p
    if set(r) != set(REQUIRED_FIELDS):
        return p + [f"authority record schema mismatch: expected {sorted(REQUIRED_FIELDS)}, got {sorted(r)}"]
    if r["role"] not in ROLES:
        p.append(f"role must be one of {ROLES}")
    if not isinstance(r["permitted_authorization_classes"], list) or not r["permitted_authorization_classes"] or not set(r["permitted_authorization_classes"]) <= set(AUTHORIZATION_CLASSES):
        p.append("permitted_authorization_classes must be a non-empty subset of " + str(AUTHORIZATION_CLASSES))
    if not isinstance(r["permitted_eval_stages"], list) or not r["permitted_eval_stages"] or not set(r["permitted_eval_stages"]) <= set(_spec.STAGE_SPLIT):
        p.append("permitted_eval_stages must be a non-empty subset of " + str(tuple(_spec.STAGE_SPLIT)))
    for k in ("gpu_permission", "spend_permission", "provider_inference_permission"):
        if not isinstance(r.get(k), bool):
            p.append(f"{k} must be a boolean")
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


def active_authority_keys(doc: dict) -> list:
    """Feeds orca.eval.genesis_v2.authorization.verify(..., keys=...) directly (only the base id/role/public_key_hex/identity fields)."""
    return ID.active_keys(doc)


def authority_for_request(doc: dict, *, authorization_class: str, stage: str, gpu: bool, spend: bool, provider_inference: bool) -> list:
    """Active authority records actually scoped to cover a given request shape — a stricter view than 'any active key'."""
    out = []
    for r in doc.get("records", []):
        if not ID.is_active(r):
            continue
        if authorization_class not in r.get("permitted_authorization_classes", []) or stage not in r.get("permitted_eval_stages", []):
            continue
        if gpu and not r.get("gpu_permission"):
            continue
        if spend and not r.get("spend_permission"):
            continue
        if provider_inference and not r.get("provider_inference_permission"):
            continue
        out.append(r)
    return out
