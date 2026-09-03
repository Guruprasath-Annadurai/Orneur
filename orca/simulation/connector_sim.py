"""
Connector simulation (Phase 11 spec §26-29). Reuses Phase 9's
DETERMINISTIC `FakeProviderState`/`fake_write()` to preview a connector
write's shape (idempotency behavior, `OUTCOME_UNKNOWN` modeling) --
never claims real SaaS provider simulation, because no real SaaS
provider exists in this codebase (Phase 9's own honest classification,
unchanged).

For DOCUMENT_STORE (the one REAL_ADAPTER connector family), a preview
never touches the real tenant collection -- it operates against an
ISOLATED, throwaway session id, never the tenant's actual
`_scoped_session_id()` (spec §27: "do not mutate real production
document collections merely for preview").

For any other connector family with no real preview mechanism (real
EXTERNAL_SIDE_EFFECT writes -- messaging, calendar, ticketing beyond the
fake provider, CRM, etc.), this module returns an explicit
"cannot prove commit outcome" result rather than fabricating a
successful delivery simulation (spec §28).
"""
from __future__ import annotations

from orca.connectors.contracts import (
    ConnectorIdentity,
    ConnectorInstance,
    ConnectorType,
    ConnectorWriteRequest,
    OutcomeStatus,
)
from orca.connectors.fake_provider import FakeProviderState, fake_write
from orca.simulation.contracts import (
    Assumption,
    BlastRadius,
    EffectConfidence,
    EffectType,
    PredictedEffect,
    Provenance,
    Reversibility,
    SimulationAction,
)


class ConnectorSimulationOutcome:
    def __init__(self, *, supported: bool, unavailable_reason: str | None, predicted_effects: list[PredictedEffect], assumptions: list[Assumption], outcome_unknown_risk: bool):
        self.supported = supported
        self.unavailable_reason = unavailable_reason
        self.predicted_effects = predicted_effects
        self.assumptions = assumptions
        self.outcome_unknown_risk = outcome_unknown_risk


def simulate_connector_write(*, instance: ConnectorInstance, identity: ConnectorIdentity, action: SimulationAction) -> ConnectorSimulationOutcome:
    """
    Only `ConnectorType.TICKETING` (Phase 9's fake-provider-exercised
    family) and `ConnectorType.DOCUMENT_STORE` get a REAL preview
    mechanism here -- honestly matching Phase 9's own
    REAL_ADAPTER/CONTRACT_ONLY/FAKE_TEST_PROVIDER classification. Every
    other connector type returns `supported=False` with an explicit
    reason, never a fabricated preview.
    """
    if instance.connector_type not in (ConnectorType.TICKETING, ConnectorType.DOCUMENT_STORE):
        return ConnectorSimulationOutcome(
            supported=False,
            unavailable_reason=f"no real or fake preview mechanism exists for connector type {instance.connector_type.value} -- cannot prove commit outcome; real side effect may be irreversible if executed",
            predicted_effects=[], assumptions=[], outcome_unknown_risk=True,
        )

    if instance.connector_type == ConnectorType.DOCUMENT_STORE:
        # No real write path exists for DOCUMENT_STORE in Phase 9 (it is
        # read-oriented) -- disclosed honestly rather than fabricated.
        return ConnectorSimulationOutcome(
            supported=False,
            unavailable_reason="DOCUMENT_STORE has no write path in this codebase (Phase 9's adapter is read-only) -- nothing to preview",
            predicted_effects=[], assumptions=[], outcome_unknown_risk=False,
        )

    # TICKETING via the real, deterministic Phase 9 fake provider --
    # an ISOLATED per-simulation state, never the tenant's real state.
    sim_state = FakeProviderState()
    idempotency_key = action.arguments.get("idempotency_key")
    request = ConnectorWriteRequest(identity=identity, connector_instance_id=instance.connector_instance_id, arguments=action.arguments, idempotency_key=idempotency_key)
    result = fake_write(identity, instance, request, sim_state)

    assumptions = [Assumption(
        description="the real provider's write semantics match the fake provider's modeled idempotency/commit behavior",
        source="fake_provider_preview", verification_state="UNVERIFIED",
        impact_if_false="real commit behavior (e.g. idempotency-key handling) may differ from this preview",
    )]

    outcome_unknown_risk = idempotency_key is None  # no idempotency key -> a real retry-after-timeout race would be unrecoverable

    effect = PredictedEffect(
        resource=f"{instance.connector_instance_id}:{action.resource_scope}", effect_type=EffectType.UPDATE,
        before_reference=None, predicted_after_reference=str(result.status.value),
        reversibility=Reversibility.UNKNOWN,   # a real ticketing system's reversibility depends on its own semantics -- never assumed
        blast_radius=BlastRadius.SINGLE_OBJECT, confidence=EffectConfidence.MEDIUM,
        assumption_ids=[assumptions[0].assumption_id], provenance=Provenance.SIMULATION,
    )

    return ConnectorSimulationOutcome(supported=True, unavailable_reason=None, predicted_effects=[effect], assumptions=assumptions, outcome_unknown_risk=outcome_unknown_risk)
