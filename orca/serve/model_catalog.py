"""Server-authoritative serving catalog.

The client names a model. The server maps that name to a permitted tier.
``model_variant`` is never the access decision; a spoofed ``nano`` label
cannot lower the catalog tier of the requested model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orca.auth.store import model_access_allowed
from orca.config import ORCA_HOME, orneur_env
from orca.serve.usage import NATIVE_FAMILIES

_NATIVE_PREFIXES = ("genesis", "novus", "aeternum", "orneur-genesis", "orneur-novus", "orneur-aeternum")


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    tier: str
    aliases: tuple[str, ...] = ()
    development: bool = False


# Qualified development fixtures only. Production models must be provisioned
# explicitly (ORCA_HOME/serve_catalog.json or ORNEUR_MODEL_CATALOG).
_BUILTIN: dict[str, CatalogEntry] = {
    "fixture-llama": CatalogEntry("fixture-llama", "nano", ("fixture-llama:latest",), development=True),
    "pro-llama": CatalogEntry("pro-llama", "ultra", ("pro-llama:latest",), development=True),
}

_runtime: dict[str, CatalogEntry] = {}


def _native(name: str) -> bool:
    n = (name or "").strip().lower()
    if n in NATIVE_FAMILIES:
        return True
    return any(n == p or n.startswith(p + ":") or n.startswith(p + "-") for p in _NATIVE_PREFIXES)


def _index(entry: CatalogEntry) -> None:
    _runtime[entry.name.lower()] = entry
    for alias in entry.aliases:
        _runtime[alias.lower()] = entry


def reset_catalog_for_tests() -> None:
    _runtime.clear()
    for entry in _BUILTIN.values():
        _index(entry)


def provision_model(name: str, tier: str, *, aliases: tuple[str, ...] = (), development: bool = False) -> CatalogEntry:
    if _native(name):
        raise ValueError("native_identity_refused")
    tier = (tier or "").removeprefix("orca-")
    if tier not in {"nano", "core", "ultra"}:
        raise ValueError("unknown_tier")
    entry = CatalogEntry(name=name, tier=tier, aliases=aliases, development=development)
    _index(entry)
    return entry


def _load_file_catalog() -> None:
    path = orneur_env("MODEL_CATALOG") or str(ORCA_HOME / "serve_catalog.json")
    p = Path(path)
    if not p.is_file():
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return
    rows = raw if isinstance(raw, list) else (raw.get("models") or [])
    for row in rows:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        try:
            provision_model(
                str(row["name"]),
                str(row.get("tier") or "nano"),
                aliases=tuple(row.get("aliases") or ()),
                development=bool(row.get("development")),
            )
        except ValueError:
            continue


reset_catalog_for_tests()
_load_file_catalog()


def lookup(model: str) -> CatalogEntry | None:
    if not isinstance(model, str) or not model.strip():
        return None
    return _runtime.get(model.strip().lower())


class CatalogError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def authorize_model(*, user: object, model: str, claimed_variant: str | None) -> CatalogEntry:
    if _native(model) or (claimed_variant and _native(claimed_variant)):
        raise CatalogError("native_identity_refused")
    entry = lookup(model)
    if entry is None:
        raise CatalogError("unknown_model")
    claimed = (claimed_variant or "").strip().removeprefix("orca-")
    if claimed and claimed not in {"", "nano", "core", "ultra"}:
        raise CatalogError("unknown_model")
    if claimed and claimed != entry.tier:
        raise CatalogError("variant_mismatch")
    ok, _reason = model_access_allowed(user, entry.tier)
    if not ok:
        raise CatalogError("model_access_denied")
    return entry
