"""Status of the 35 advanced capabilities.

IMPLEMENTED_SYNTHETIC means a deterministic handler or typed contract ran
in tests. It does not mean independently qualified or production authorized.
Capability C27 here is proof of non-execution. It is not acceptance-register
row C27.
"""
from __future__ import annotations

ALLOWED_STATUSES = frozenset({
    "RESEARCH_ONLY",
    "DESIGNED",
    "IMPLEMENTED_SYNTHETIC",
    "TESTED",
    "INDEPENDENTLY_QUALIFIED",
    "PRODUCTION_AUTHORIZED",
    "BLOCKED",
})

# (capability_id, status, implementation)
CAPABILITIES: tuple[tuple[str, str, str], ...] = (
    ("A01", "IMPLEMENTED_SYNTHETIC", "evidence_contract.Claim"),
    ("A02", "IMPLEMENTED_SYNTHETIC", "governed_handlers.falsify_claim"),
    ("A03", "DESIGNED", "role orchestration.team-selector; no adaptive model budget"),
    ("A04", "DESIGNED", "role reasoning.causal-tagger; no causal handler"),
    ("A05", "DESIGNED", "role reasoning.counterfactual-simulator; no simulator handler"),
    ("A06", "IMPLEMENTED_SYNTHETIC", "evidence_contract.transition"),
    ("A07", "IMPLEMENTED_SYNTHETIC", "governed_handlers.arbitrate_claims"),
    ("A08", "DESIGNED", "role reasoning.hypothesis-keeper"),
    ("A09", "IMPLEMENTED_SYNTHETIC", "governed_handlers.falsify_claim unsupported outcome"),
    ("B10", "IMPLEMENTED_SYNTHETIC", "governed_handlers.select_team"),
    ("B11", "DESIGNED", "team_benchmark records method diversity only for these handlers"),
    ("B12", "IMPLEMENTED_SYNTHETIC", "capability_graph.CapabilityGraph; advertisements are not trusted"),
    ("B13", "IMPLEMENTED_SYNTHETIC", "governed_handlers.screen_untrusted"),
    ("B14", "DESIGNED", "role orchestration.dependency-scheduler; Orchestrator already rejects cycles"),
    ("B15", "DESIGNED", "role verification.human-review-escalator"),
    ("B16", "IMPLEMENTED_SYNTHETIC", "failure_genome.FailureGenome; producer cannot close its own record"),
    ("B17", "DESIGNED", "role orchestration.reroute-proposer"),
    ("B18", "DESIGNED", "qualification_state stops at IMPLEMENTED_SYNTHETIC"),
    ("C19", "IMPLEMENTED_SYNTHETIC", "governed_handlers.decide_authority"),
    ("C20", "DESIGNED", "queued grant is read at invoke; in-flight handler body is not preempted"),
    ("C21", "DESIGNED", "DenialReceipt is a record, not a signature"),
    ("C22", "DESIGNED", "role memory.tenant-isolator covers the read check only"),
    ("C23", "IMPLEMENTED_SYNTHETIC", "governed_handlers.screen_untrusted"),
    ("C24", "DESIGNED", "tests cover injection, cross-tenant, self-promotion, and expired grants"),
    ("C25", "IMPLEMENTED_SYNTHETIC", "agents.Orchestrator.restore_snapshot refuses a forged success"),
    ("C26", "DESIGNED", "risk class does not grant permissions"),
    ("C27", "IMPLEMENTED_SYNTHETIC", "governed_handlers.record_denial; not acceptance-register C27"),
    ("D28", "IMPLEMENTED_SYNTHETIC", "governed_handlers.deny_self_promotion"),
    ("D29", "IMPLEMENTED_SYNTHETIC", "synthetic_suite.shadow_tournament; winner is not promoted"),
    ("D30", "IMPLEMENTED_SYNTHETIC", "governed_handlers.account_cost"),
    ("D31", "IMPLEMENTED_SYNTHETIC", "governed_handlers.bound_deadline"),
    ("D32", "DESIGNED", "autonomy levels are not a released control"),
    ("D33", "DESIGNED", "Orchestrator traces exist; no user-facing mission API"),
    ("D34", "DESIGNED", "no native-model fallback is substituted"),
    ("D35", "DESIGNED", "no qualified capability is promoted by this module"),
)


def validate_capabilities() -> None:
    if len(CAPABILITIES) != 35:
        raise ValueError(f"expected 35 capabilities, found {len(CAPABILITIES)}")
    ids = [item[0] for item in CAPABILITIES]
    if len(set(ids)) != 35:
        raise ValueError("capability ids are not unique")
    for _cap_id, status, _impl in CAPABILITIES:
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"status {status} is not allowed")
        if status in {"INDEPENDENTLY_QUALIFIED", "PRODUCTION_AUTHORIZED"}:
            raise ValueError("this module must not mark a capability qualified or authorized")
