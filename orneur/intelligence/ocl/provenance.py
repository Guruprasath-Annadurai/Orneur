"""
Cognitive provenance (spec section 9). Model identity references use the
REAL Phase 16 vocabulary (`orca.registry.model_spec`) -- OCL does not
invent a second model-lifecycle vocabulary. Structural validation (is this
family/lifecycle value real, can an EXTERNAL_PROVIDER claim a native
family) lives in `compiler.py`, not here -- these are plain data shapes.
"""
from __future__ import annotations

from dataclasses import dataclass

from orneur.intelligence.ocl.enums import ProducerKind


@dataclass(frozen=True)
class ModelIdentityRef:
    """A reference to a model's identity -- never the model's raw weights,
    never a claim of authority. `family`/`lifecycle_state` are validated at
    compile time against `orca.registry.model_spec.MODEL_SPECS`/
    `LifecycleState`, not re-declared here."""
    family: str | None = None            # "genesis" | "novus" | "aeternum", or None
    generation: int | None = None
    checkpoint_id: str | None = None
    artifact_digest: str | None = None
    lifecycle_state: str | None = None   # a orca.registry.model_spec.LifecycleState value
    provider_id: str | None = None       # set only for EXTERNAL_PROVIDER, e.g. "openai:gpt-4o"


@dataclass(frozen=True)
class Provenance:
    producer_kind: ProducerKind
    producer_id: str
    model_identity: ModelIdentityRef | None = None
    invocation_ref: str | None = None
    schema_version: str | None = None
