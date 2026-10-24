"""Planning inventory of 100 agent roles.

A row here is a versioned contract. `implemented=True` means a synthetic
handler in `governed_handlers.py` can run it. It does not mean the role
is independently qualified or production authorized.
"""
from __future__ import annotations

from dataclasses import dataclass

FORBIDDEN = (
    "self_promotion",
    "training",
    "spend",
    "weight_mutation",
    "ledger_edit",
    "cross_tenant_read",
    "silent_deployment",
)


@dataclass(frozen=True)
class RoleContract:
    agent_id: str
    group: str
    name: str
    version: str
    purpose: str
    supported_tasks: tuple[str, ...]
    input_schema: str
    output_schema: str
    trust_classification: str
    qualification_state: str
    model_dependency: str
    tool_dependency: str
    required_authority: str
    allowed: tuple[str, ...]
    forbidden: tuple[str, ...]
    tenant_scope: str
    resource_budget: str
    evidence_contract: str
    retry_limit: int
    timeout_ticks: int
    cancellation: str
    failure_behavior: str
    privacy: str
    verification_method: str
    implemented: bool


def _role(group: str, slug: str, purpose: str, task: str, *, implemented: bool = False) -> RoleContract:
    return RoleContract(
        agent_id=f"{group}.{slug}.v1",
        group=group,
        name=slug,
        version="v1",
        purpose=purpose,
        supported_tasks=(task,),
        input_schema="json-object",
        output_schema="json-object",
        trust_classification="UNTRUSTED_DECLARATION",
        qualification_state="DECLARED" if not implemented else "IMPLEMENTED_SYNTHETIC",
        model_dependency="none",
        tool_dependency="deterministic-function" if implemented else "none",
        required_authority="governed" if implemented else "not-granted",
        allowed=("read-synthetic-fixture",) if implemented else ("declare-only",),
        forbidden=FORBIDDEN,
        tenant_scope="caller-tenant",
        resource_budget="in-process-ticks",
        evidence_contract="orca.pretrain_foundation.evidence_contract",
        retry_limit=1,
        timeout_ticks=5,
        cancellation="parent-cancel-propagates; a succeeded task is not rewritten",
        failure_behavior="fail-closed; no fabricated completion",
        privacy="synthetic fixtures only; no training ingestion",
        verification_method="independent-handler" if implemented else "not-qualified",
        implemented=implemented,
    )


_ROWS: tuple[tuple[str, str, str, str, bool], ...] = (
    ("orchestration", "mission-planner", "Split one mission into ordered subtasks.", "mission.plan", False),
    ("orchestration", "dependency-scheduler", "Order subtasks and refuse a cycle.", "mission.schedule", False),
    ("orchestration", "budget-keeper", "Stop scheduling when the budget is spent.", "mission.budget", False),
    ("orchestration", "cancellation-propagator", "Cancel open child tasks when the parent is cancelled.", "mission.cancel", False),
    ("orchestration", "team-selector", "Select the smallest implemented team that covers the requested tasks.", "team.select", True),
    ("orchestration", "deadline-controller", "Report an incomplete result when the tick budget is spent.", "deadline.bound", True),
    ("orchestration", "reroute-proposer", "Propose a new allocation without adding permissions.", "mission.reroute", False),
    ("orchestration", "evidence-binder", "Attach result digests to a mission record.", "mission.bind", False),
    ("orchestration", "abstention-clerk", "Record that the mission stopped for lack of evidence.", "mission.abstain", False),
    ("orchestration", "rollout-recorder", "Record that a proposal was not applied.", "mission.record", False),
    ("research", "source-locator", "Name a candidate source without fetching it.", "research.locate", False),
    ("research", "primary-reader", "Read a supplied primary excerpt.", "research.read", False),
    ("research", "citation-extractor", "Extract a citation string from a supplied excerpt.", "research.cite", False),
    ("research", "date-checker", "Compare a claimed date with a supplied source date.", "research.date", False),
    ("research", "contradiction-scout", "Flag two supplied excerpts that disagree.", "research.contradict", False),
    ("research", "prior-art-surveyor", "List supplied prior-art records.", "research.prior", False),
    ("research", "license-reader", "Read a supplied license label without treating it as clearance.", "research.license", False),
    ("research", "uncertainty-flagger", "Mark a research claim whose source is missing.", "research.uncertainty", False),
    ("research", "synthesis-writer", "Draft a synthesis that stays labeled INFERRED.", "research.synthesize", False),
    ("research", "research-abstainer", "Abstain when the supplied sources are insufficient.", "research.abstain", False),
    ("retrieval", "query-planner", "Plan a retrieval query without running it.", "retrieval.plan", False),
    ("retrieval", "authorized-retriever", "Retrieve only inside an authorized tenant scope.", "retrieval.fetch", False),
    ("retrieval", "provenance-binder", "Bind a retrieved span to a source id.", "retrieval.provenance", False),
    ("retrieval", "span-extractor", "Extract a span from a supplied document.", "retrieval.span", False),
    ("retrieval", "freshness-checker", "Compare a span timestamp with a supplied clock.", "retrieval.freshness", False),
    ("retrieval", "tenant-scope-guard", "Refuse a retrieval outside the caller tenant.", "retrieval.tenant", False),
    ("retrieval", "contamination-screener", "Flag a span that matches a held-out marker.", "retrieval.contamination", False),
    ("retrieval", "exclusion-applier", "Drop a source that is on the exclusion list.", "retrieval.exclude", False),
    ("retrieval", "manifest-hasher", "Hash a supplied retrieval manifest.", "retrieval.hash", False),
    ("retrieval", "retrieval-denier", "Deny retrieval when authorization is absent.", "retrieval.deny", False),
    ("reasoning", "arithmetic-checker", "Check a supplied integer equation.", "reasoning.arithmetic", False),
    ("reasoning", "algebra-solver", "Solve a supplied bounded equation.", "reasoning.algebra", False),
    ("reasoning", "proof-checker", "Check a supplied proof object with a deterministic checker.", "reasoning.proof", False),
    ("reasoning", "causal-tagger", "Label a statement as observation, correlation, or hypothesis.", "reasoning.causal", False),
    ("reasoning", "counterfactual-simulator", "Evaluate a supplied alternative under stated assumptions.", "reasoning.counterfactual", False),
    ("reasoning", "hypothesis-keeper", "Keep a bounded set of competing hypotheses.", "reasoning.hypotheses", False),
    ("reasoning", "assumption-lister", "List assumptions supplied with a conclusion.", "reasoning.assumptions", False),
    ("reasoning", "unit-checker", "Check that a numeric claim carries units.", "reasoning.units", False),
    ("reasoning", "constraint-checker", "Check a claim against a supplied constraint.", "reasoning.constraints", False),
    ("reasoning", "reasoning-abstainer", "Abstain when the calculation inputs are missing.", "reasoning.abstain", False),
    ("coding", "spec-reader", "Read a supplied specification excerpt.", "coding.spec", False),
    ("coding", "patch-drafter", "Draft a patch text without applying it.", "coding.patch", False),
    ("coding", "test-writer", "Draft a test text without running a production suite.", "coding.test", False),
    ("coding", "static-reviewer", "Review a supplied diff text.", "coding.review", False),
    ("coding", "sandbox-runner", "Run a supplied fixture in an already-authorized sandbox.", "coding.sandbox", False),
    ("coding", "regression-comparator", "Compare two supplied test outcomes.", "coding.regression", False),
    ("coding", "dependency-auditor", "Read a supplied dependency list.", "coding.dependencies", False),
    ("coding", "interface-checker", "Check a supplied signature against a contract.", "coding.interface", False),
    ("coding", "rollback-author", "Draft a rollback note without deploying it.", "coding.rollback", False),
    ("coding", "code-abstainer", "Abstain when the specification is missing.", "coding.abstain", False),
    ("verification", "claim-classifier", "Classify a claim as OBSERVED or UNKNOWN without self-verifying it.", "claim.classify", True),
    ("verification", "independent-falsifier", "Refute a claim whose text contradicts its evidence span.", "claim.falsify", True),
    ("verification", "citation-auditor", "Check that a citation names a source id.", "verification.citation", False),
    ("verification", "calculation-recomputer", "Recompute a supplied integer operation.", "verification.recompute", False),
    ("verification", "contradiction-arbiter", "Hold a disagreement open instead of resolving it by vote.", "claim.arbitrate", True),
    ("verification", "result-comparator", "Compare two supplied handler results.", "verification.compare", False),
    ("verification", "unsupported-claim-marker", "Mark a claim that has no evidence span.", "verification.unsupported", False),
    ("verification", "calibration-scorer", "Score abstentions on a supplied fixture.", "verification.calibration", False),
    ("verification", "human-review-escalator", "Mark a judgment as requiring a human reviewer.", "verification.escalate", False),
    ("verification", "verification-abstainer", "Abstain when the verifier lacks evidence.", "verification.abstain", False),
    ("security", "authority-gate", "Decide a tool request without executing the tool.", "authority.decide", True),
    ("security", "revocation-reader", "Read a revocation flag before a queued handler runs.", "security.revocation", False),
    ("security", "denial-recorder", "Record a denial receipt for the guarded path.", "authority.deny", True),
    ("security", "injection-screener", "Refuse untrusted text that tries to change authority.", "content.screen", True),
    ("security", "tenant-boundary", "Refuse a cross-tenant task assignment.", "security.tenant", False),
    ("security", "path-guard", "Refuse a path that leaves the fixture root.", "security.path", False),
    ("security", "grant-expiry-checker", "Refuse an expired grant.", "security.expiry", False),
    ("security", "self-promotion-denier", "Refuse a promotion decided by its producer.", "promotion.deny", True),
    ("security", "secret-redactor", "Redact a supplied secret pattern from a fixture.", "security.redact", False),
    ("security", "policy-fail-closed", "Deny when policy evidence is missing.", "security.fail-closed", False),
    ("memory", "memory-admission", "Admit a memory record only with an explicit permission.", "memory.admit", False),
    ("memory", "memory-reader", "Read a memory record inside the caller tenant.", "memory.read", False),
    ("memory", "memory-writer", "Write a memory record inside the caller tenant.", "memory.write", False),
    ("memory", "retention-enforcer", "Apply a supplied retention limit.", "memory.retention", False),
    ("memory", "deletion-verifier", "Check a supplied deletion receipt against a store listing.", "memory.delete", False),
    ("memory", "contamination-firewall", "Keep retrieved text out of trusted memory.", "memory.firewall", False),
    ("memory", "scope-separator", "Separate user, task, and agent memory scopes.", "memory.scope", False),
    ("memory", "tenant-isolator", "Refuse a memory read across tenants.", "memory.isolate", True),
    ("memory", "export-guard", "Refuse an export without an export permission.", "memory.export", False),
    ("memory", "memory-denier", "Deny memory access when the permission is absent.", "memory.deny", False),
    ("model", "family-registrar", "Read the GENESIS, NOVUS, and AETERNUM contract statuses.", "model.family", False),
    ("model", "tokenizer-contract", "Read a tokenizer contract without training a tokenizer.", "model.tokenizer", False),
    ("model", "eval-runner", "Run a synthetic eval item, not a public benchmark.", "model.eval", False),
    ("model", "contamination-guard", "Keep an eval item out of a training manifest.", "model.contamination", False),
    ("model", "checkpoint-identity", "Compare a supplied checkpoint digest.", "model.checkpoint", False),
    ("model", "training-lock-watcher", "Refuse a payload that asks to enable training, GPU, or spend.", "training.watch", True),
    ("model", "baseline-comparator", "Compare a candidate score with a supplied baseline.", "model.baseline", False),
    ("model", "cost-accountant", "Sum known prices and keep an unknown price as UNKNOWN.", "cost.account", True),
    ("model", "regression-gate", "Fail a promotion when a supplied regression is material.", "model.regression", False),
    ("model", "model-claim-denier", "Refuse a status that claims a family is trained.", "model.claim", False),
    ("product", "workflow-coordinator", "Coordinate a supplied workflow id.", "product.workflow", False),
    ("product", "handoff-writer", "Draft a handoff from supplied evidence ids.", "product.handoff", False),
    ("product", "status-reporter", "Report handler status without promoting it.", "product.status", False),
    ("product", "approval-requester", "Request a human approval without granting one.", "product.approve", False),
    ("product", "incident-recorder", "Record a supplied incident.", "product.incident", False),
    ("product", "customer-scope-guard", "Refuse work outside the supplied customer scope.", "product.scope", False),
    ("product", "release-blocker", "Block a release when qualification is absent.", "product.release", False),
    ("product", "evidence-publisher", "Publish a supplied evidence digest.", "product.publish", False),
    ("product", "rollback-coordinator", "Coordinate a rollback note without deploying it.", "product.rollback", False),
    ("product", "product-abstainer", "Abstain when the workflow evidence is incomplete.", "product.abstain", False),
)


def load_roles() -> tuple[RoleContract, ...]:
    roles = tuple(_role(group, slug, purpose, task, implemented=implemented) for group, slug, purpose, task, implemented in _ROWS)
    validate_roles(roles)
    return roles


def validate_roles(roles: tuple[RoleContract, ...]) -> None:
    if len(roles) != 100:
        raise ValueError(f"expected 100 roles, found {len(roles)}")
    ids = [role.agent_id for role in roles]
    if len(set(ids)) != 100:
        raise ValueError("role ids are not unique")
    groups: dict[str, int] = {}
    for role in roles:
        groups[role.group] = groups.get(role.group, 0) + 1
        if role.version != "v1":
            raise ValueError(f"{role.agent_id} is not versioned v1")
        if role.qualification_state == "QUALIFIED":
            raise ValueError(f"{role.agent_id} cannot be constructed as qualified")
        if "self_promotion" not in role.forbidden:
            raise ValueError(f"{role.agent_id} does not forbid self promotion")
    if len(groups) != 10 or any(count != 10 for count in groups.values()):
        raise ValueError(f"expected 10 groups of 10, found {groups}")


def implemented_roles() -> tuple[RoleContract, ...]:
    return tuple(role for role in load_roles() if role.implemented)


def role_for_task(task: str) -> RoleContract | None:
    for role in implemented_roles():
        if task in role.supported_tasks:
            return role
    return None
