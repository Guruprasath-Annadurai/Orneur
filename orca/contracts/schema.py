"""
A small, dependency-free JSON Schema SUBSET for JSON_SCHEMA contracts. Fail-closed: any keyword outside the supported set makes the SCHEMA invalid
(INVALID_CONTRACT) instead of being silently ignored. Supported: type, properties, required, additionalProperties, items, enum, const, minLength,
maxLength, minItems, maxItems, minimum, maximum (+ pure annotations title/description/$schema/default/examples).
"""
from __future__ import annotations

from .jsonutil import strict_equal

ANNOTATIONS = frozenset({"title", "description", "$schema", "default", "examples", "$comment"})
KEYWORDS = frozenset({"type", "properties", "required", "additionalProperties", "items", "enum", "const", "minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum"})
TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
MAX_SCHEMA_DEPTH = 12


def check_schema(schema, depth: int = 0) -> str | None:
    """None if the schema is inside the supported subset, otherwise a reason."""
    if depth > MAX_SCHEMA_DEPTH:
        return "schema nesting too deep"
    if isinstance(schema, bool):
        return None
    if not isinstance(schema, dict):
        return "a schema must be an object"
    for k, v in schema.items():
        if k in ANNOTATIONS:
            continue
        if k not in KEYWORDS:
            return f"unsupported schema keyword {k!r}"
        if k == "type":
            ts = v if isinstance(v, list) else [v]
            if not ts or not all(isinstance(t, str) and t in TYPES for t in ts):
                return "invalid 'type'"
        elif k == "properties":
            if not isinstance(v, dict):
                return "'properties' must be an object"
            for sub in v.values():
                r = check_schema(sub, depth + 1)
                if r:
                    return r
        elif k == "required":
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                return "'required' must be a list of strings"
        elif k == "additionalProperties":
            if not isinstance(v, bool):
                r = check_schema(v, depth + 1)
                if r:
                    return r
        elif k == "items":
            r = check_schema(v, depth + 1)
            if r:
                return r
        elif k == "enum":
            if not isinstance(v, list) or not v:
                return "'enum' must be a non-empty list"
        elif k in ("minLength", "maxLength", "minItems", "maxItems"):
            if type(v) is not int or v < 0:
                return f"'{k}' must be a non-negative integer"
        elif k in ("minimum", "maximum"):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return f"'{k}' must be a number"
    return None


def _type_ok(inst, t: str) -> bool:
    if t == "object":
        return isinstance(inst, dict)
    if t == "array":
        return isinstance(inst, list)
    if t == "string":
        return isinstance(inst, str)
    if t == "boolean":
        return isinstance(inst, bool)
    if t == "null":
        return inst is None
    if t == "integer":
        return (isinstance(inst, int) and not isinstance(inst, bool)) or (isinstance(inst, float) and inst.is_integer())
    if t == "number":
        return isinstance(inst, (int, float)) and not isinstance(inst, bool)
    return False


def validate(instance, schema, path: str = "$") -> list[str]:
    """All violations (empty list == valid). The schema must already have passed check_schema."""
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: no value is allowed"]
    errs: list[str] = []
    if "type" in schema:
        ts = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(instance, t) for t in ts):
            return [f"{path}: expected type {ts}"]
    if "const" in schema and not strict_equal(instance, schema["const"]):
        errs.append(f"{path}: does not equal the required constant")
    if "enum" in schema and not any(strict_equal(instance, e) for e in schema["enum"]):
        errs.append(f"{path}: not one of the allowed values")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errs.append(f"{path}: shorter than minLength")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errs.append(f"{path}: longer than maxLength")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append(f"{path}: below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append(f"{path}: above maximum")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errs.append(f"{path}: fewer than minItems")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errs.append(f"{path}: more than maxItems")
        if "items" in schema:
            for i, item in enumerate(instance):
                errs += validate(item, schema["items"], f"{path}[{i}]")
    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errs.append(f"{path}: missing required property {req!r}")
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                errs += validate(v, props[k], f"{path}.{k}")
            else:
                ap = schema.get("additionalProperties", True)
                if ap is False:
                    errs.append(f"{path}: additional property {k!r} is not allowed")
                elif ap is not True:
                    errs += validate(v, ap, f"{path}.{k}")
    return errs
