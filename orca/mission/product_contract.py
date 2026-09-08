"""
Phase 15.7 -- typed Product Contract (spec sections 1-2, 12).

A ProductContract is the durable-in-spirit (see module docstring's
DURABILITY note below) typed representation an idea compiles into
BEFORE any requirement/mission work begins. Every field may be
legitimately absent -- `None`/empty is not an error, it is "this fact
is not known yet," which is exactly the point (spec section 1: "Do
NOT require every field to contain invented content. A missing fact
must remain missing/unknown.").

DURABILITY (spec section 18): this module, like
`orca.mission.code_mode`'s PrototypeDebt and
`orca.mission.requirements`'s own registry before it, is an
IN-PROCESS module-level registry -- NOT Neon-backed. This is a
disclosed limitation, not a durability claim: a ProductContract does
NOT currently survive a process restart. It was kept in-process
because no Phase 15.7 acceptance criterion requires cross-process
persistence (Phase 15.2's `requirements`/`assumptions` tables already
give the DURABLE requirement/assumption backbone a Product Contract's
compiled output ultimately writes into via
`orca.mission.requirements.register()`), and introducing a new
`product_contracts` table was evaluated and rejected per spec section
17's explicit instruction not to add a table "just because it sounds
cleaner" without a genuine acceptance-criteria need.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContractError(Exception):
    pass


class TargetPlatform(str, Enum):
    WEB = "WEB"
    IOS = "IOS"
    ANDROID = "ANDROID"
    DESKTOP = "DESKTOP"
    API_ONLY = "API_ONLY"
    CLI = "CLI"


class LaunchTarget(str, Enum):
    """Mirrors orca.mission.code_mode.LaunchReadiness exactly -- a
    Product Contract's launch_target is never allowed to silently
    imply PUBLISHED (spec section 2's explicit invariant); PUBLISHED
    is reachable only through real external confirmation, tracked
    elsewhere (Phase 15.10 Production Proof), never self-asserted
    here."""
    ENGINEERING_READY = "ENGINEERING_READY"
    SUBMISSION_READY = "SUBMISSION_READY"
    RELEASE_CANDIDATE = "RELEASE_CANDIDATE"


@dataclass(frozen=True)
class Actor:
    actor_id: str
    name: str

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ContractError("Actor.actor_id must not be empty.")
        if not self.name.strip():
            raise ContractError("Actor.name must not be empty.")


@dataclass(frozen=True)
class UserJourney:
    journey_id: str
    actor_id: str
    description: str

    def __post_init__(self) -> None:
        if not self.journey_id.strip():
            raise ContractError("UserJourney.journey_id must not be empty.")
        if not self.description.strip():
            raise ContractError("UserJourney.description must not be empty.")


@dataclass(frozen=True)
class ProductContract:
    contract_id: str
    version: int
    product_name: str
    product_purpose: str
    source_input: str
    created_at: str
    mission_id: str | None = None
    actors: tuple[Actor, ...] = field(default_factory=tuple)
    user_journeys: tuple[UserJourney, ...] = field(default_factory=tuple)
    functional_requirements_source: str | None = None
    non_functional_requirements_source: str | None = None
    data_classes: tuple[str, ...] = field(default_factory=tuple)
    authentication_needs: str | None = None
    permission_model: str | None = None
    integrations: tuple[str, ...] = field(default_factory=tuple)
    risk_areas: tuple[str, ...] = field(default_factory=tuple)
    assumption_ids: tuple[str, ...] = field(default_factory=tuple)
    unknown_ids: tuple[str, ...] = field(default_factory=tuple)
    target_platforms: tuple[TargetPlatform, ...] = field(default_factory=tuple)
    acceptance_targets: tuple[str, ...] = field(default_factory=tuple)
    launch_target: LaunchTarget | None = None
    out_of_scope: tuple[str, ...] = field(default_factory=tuple)
    superseded_by: str | None = None
    supersedes: str | None = None
    change_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.product_purpose.strip():
            raise ContractError(f"{self.contract_id}: product_purpose must not be empty.")
        if not self.source_input.strip():
            raise ContractError(f"{self.contract_id}: source_input must not be empty.")
        actor_ids = [a.actor_id for a in self.actors]
        if len(actor_ids) != len(set(actor_ids)):
            raise ContractError(f"{self.contract_id}: duplicate actor_id detected.")
        known_actor_ids = set(actor_ids)
        for journey in self.user_journeys:
            if journey.actor_id not in known_actor_ids:
                raise ContractError(
                    f"{self.contract_id}: journey {journey.journey_id!r} references "
                    f"undefined actor_id {journey.actor_id!r}."
                )
        out_of_scope_set = set(self.out_of_scope)
        acceptance_set = set(self.acceptance_targets)
        overlap = out_of_scope_set & acceptance_set
        if overlap:
            raise ContractError(
                f"{self.contract_id}: {overlap!r} listed in both out_of_scope and "
                f"acceptance_targets -- out-of-scope must remain distinguishable from an accepted target."
            )


_REGISTRY: dict[str, ProductContract] = {}


def reset_registry_for_tests() -> None:
    _REGISTRY.clear()


def register_contract(contract: ProductContract) -> ProductContract:
    if contract.contract_id in _REGISTRY:
        raise ContractError(f"{contract.contract_id} is already registered -- contract IDs are immutable once created.")
    _REGISTRY[contract.contract_id] = contract
    return contract


def get_contract(contract_id: str) -> ProductContract:
    try:
        return _REGISTRY[contract_id]
    except KeyError:
        raise ContractError(f"No such contract: {contract_id}") from None


def all_contracts() -> tuple[ProductContract, ...]:
    return tuple(_REGISTRY.values())


def revise_contract(
    old_contract_id: str,
    *,
    new_contract_id: str,
    change_reason: str,
    **overrides,
) -> ProductContract:
    """Creates a NEW contract revision superseding the old one. Never
    mutates the old contract's fields in place -- old evidence stays
    attached to the OLD contract_id/version, never silently
    transferred to the new semantics (spec section 12's core
    invariant). The old contract is updated only to record
    `superseded_by`."""
    if not change_reason.strip():
        raise ContractError("revise_contract() requires a non-empty change_reason.")
    old = get_contract(old_contract_id)
    if old.superseded_by is not None:
        raise ContractError(f"{old_contract_id} is already superseded by {old.superseded_by!r}.")

    base_kwargs = dict(
        contract_id=new_contract_id,
        version=old.version + 1,
        product_name=old.product_name,
        product_purpose=old.product_purpose,
        source_input=old.source_input,
        created_at=_now_iso(),
        mission_id=old.mission_id,
        actors=old.actors,
        user_journeys=old.user_journeys,
        functional_requirements_source=old.functional_requirements_source,
        non_functional_requirements_source=old.non_functional_requirements_source,
        data_classes=old.data_classes,
        authentication_needs=old.authentication_needs,
        permission_model=old.permission_model,
        integrations=old.integrations,
        risk_areas=old.risk_areas,
        assumption_ids=old.assumption_ids,
        unknown_ids=old.unknown_ids,
        target_platforms=old.target_platforms,
        acceptance_targets=old.acceptance_targets,
        launch_target=old.launch_target,
        out_of_scope=old.out_of_scope,
        supersedes=old_contract_id,
        change_reason=change_reason,
    )
    base_kwargs.update(overrides)
    new_contract = ProductContract(**base_kwargs)
    register_contract(new_contract)

    _REGISTRY[old_contract_id] = replace(old, superseded_by=new_contract_id)
    return new_contract
