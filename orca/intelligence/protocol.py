"""ORNEUR Core Intelligence Protocol (stable, model-independent contracts).

Frozen dataclasses plus ``problems()`` validators. Nothing here names a model
family, a parameter count, or a neural architecture: models are replaceable
organs behind these interfaces. This module implements contracts only; it
does not implement any subsystem.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

PROTOCOL_VERSION = "orneur.core-protocol/1.1.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPEN_NAME = re.compile(r"^(FUTURE:)?[A-Za-z][A-Za-z0-9_.\-]{0,63}$")


class ProtocolViolation(ValueError):
    """Raised by ``assert_valid``; carries every problem found."""

    def __init__(self, kind: str, problems: Sequence[str]):
        super().__init__(f"{kind}: " + "; ".join(problems))
        self.kind, self.problems = kind, tuple(problems)


class _Contract:
    def problems(self) -> list[str]:  # pragma: no cover - overridden
        return []

    def assert_valid(self, *args: Any, **kwargs: Any) -> "_Contract":
        found = self.problems(*args, **kwargs)
        if found:
            raise ProtocolViolation(type(self).__name__, found)
        return self

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), default=lambda o: o.value if isinstance(o, Enum) else str(o)))

    def digest(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _need(obj: Any, names: Sequence[str], out: list[str]) -> None:
    for n in names:
        v = getattr(obj, n)
        if _blank(v) or (isinstance(v, (tuple, list, dict)) and not v):
            out.append(f"{n} is required")


def _unit(name: str, v: Any, out: list[str]) -> None:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0.0 <= float(v) <= 1.0:
        out.append(f"{name} must be within [0, 1]")


# ---------------------------------------------------------------- enums
class ComputeMode(str, Enum):
    FAST = "FAST"
    REASON = "REASON"
    FRONTIER = "FRONTIER"


class CounterEvidenceStatus(str, Enum):
    SEARCHED_FOUND = "SEARCHED_FOUND"
    SEARCHED_NONE_FOUND = "SEARCHED_NONE_FOUND"
    NOT_SEARCHED = "NOT_SEARCHED"


class DiscoveryOutcome(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_TEST = "UNDER_TEST"
    CONFIRMED = "CONFIRMED"
    FALSIFIED = "FALSIFIED"
    ACTED_ON = "ACTED_ON"
    EXPIRED = "EXPIRED"


class HypothesisVerdict(str, Enum):
    UNTESTED = "UNTESTED"
    SUPPORTED = "SUPPORTED"
    FALSIFIED = "FALSIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"


class QualificationState(str, Enum):
    CANDIDATE = "CANDIDATE"
    SHADOW = "SHADOW"
    QUALIFIED = "QUALIFIED"
    RETIRED = "RETIRED"


class OutcomeSource(str, Enum):
    OBSERVED_WORLD_STATE = "OBSERVED_WORLD_STATE"
    MEASURED_METRIC = "MEASURED_METRIC"
    TOOL_RESULT = "TOOL_RESULT"
    USER_PREFERENCE = "USER_PREFERENCE"  # never a valid Outcome source


class PromotionVerdict(str, Enum):
    PROMOTE = "PROMOTE"
    REJECT = "REJECT"
    HOLD = "HOLD"


class MigrationAsset(str, Enum):
    DATASETS = "datasets"
    EVAL_SUITES = "eval_suites"
    EXPERTS = "experts"
    MEMORY_SCHEMAS = "memory_schemas"
    WORLD_MODELS = "world_models"
    DISCOVERY_HISTORY = "discovery_history"
    OUTCOME_HISTORY = "outcome_history"
    FAILURE_GENOME = "failure_genome"
    COGNITIVE_PRIMITIVES = "cognitive_primitives"
    ROUTER_BEHAVIOR = "router_behavior"
    AUTHORITY_EVIDENCE_CONTRACTS = "authority_evidence_contracts"


class MigrationMechanism(str, Enum):
    DISTILLATION = "distillation"
    CONTINUED_TRAINING = "continued_training"
    REPRESENTATION_CONVERSION = "representation_conversion"
    ADAPTER_CONVERSION = "adapter_conversion"
    REINDEXING = "reindexing"
    REPLAY = "replay"
    SHADOW_COMPARISON = "shadow_comparison"
    DUAL_RUNNING = "dual_running"
    EVAL_PRESERVING_CUTOVER = "eval_preserving_cutover"
    NO_CHANGE_REQUIRED = "no_change_required"


# ---------------------------------------------------------------- content digests
def content_digest(data: "str | bytes") -> str:
    """Lowercase SHA-256 of the exact canonical bytes: UTF-8 of the text exactly as released, no normalisation."""
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    return hashlib.sha256(raw).hexdigest()


def _is_digest(v: Any) -> bool:
    return isinstance(v, str) and bool(_SHA256.match(v))


# ---------------------------------------------------------------- trusted runtime provenance
PROVENANCE_KINDS = frozenset({"ROUTER", "DETERMINISTIC_AUTHORITY", "CLAIM_EXTRACTOR", "EPISTEMIC_SCREENER", "VERIFIER"})

# Fields a payload that arrives from a model, a user or any untrusted deserialisation may never supply:
# they are stripped (or the payload rejected) before it is turned into a protocol object.
PRIVILEGED_FIELDS = frozenset({
    "seal", "provenance", "classification_provenance", "deterministic_provenance", "claim_extraction_provenance",
    "screening_provenance", "output_kind", "presented_as", "model_calls", "contract_status", "contract_evidence_ref",
    "contract_output_digest", "claims_trusted", "verifications"})


def strip_privileged(payload: Any) -> tuple[Any, list[str]]:
    """Remove privileged provenance/authority fields from an untrusted mapping (recursively).

    Returns (clean_copy, sorted list of stripped dotted paths). Callers that prefer rejection must reject
    when the list is non-empty. Nothing removed here is ever re-derivable from the payload itself.
    """
    stripped: list[str] = []

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, Mapping):
            out = {}
            for k, v in node.items():
                here = f"{path}.{k}" if path else str(k)
                if k in PRIVILEGED_FIELDS:
                    stripped.append(here)
                    continue
                out[k] = walk(v, here)
            return out
        if isinstance(node, (list, tuple)):
            return [walk(v, f"{path}[{i}]") for i, v in enumerate(node)]
        return node

    return walk(payload, ""), sorted(stripped)


@dataclass(frozen=True)
class RuntimeProvenance(_Contract):
    """Evidence that a TRUSTED ORNEUR runtime component produced/observed something.

    ``seal`` is an HMAC over every other field under a key that only a ``ProvenanceLedger`` holds. A string
    such as "ORNEUR_ROUTER" typed into a payload therefore carries no authority: without a ledger-issued seal
    the provenance does not verify. This is deliberately light (an in-process trust anchor, not PKI); a later
    generation may replace the seal with signatures without changing this contract's fields.
    """

    provenance_id: str
    component_id: str
    component_kind: str
    execution_ref: str
    authority_evidence_ref: str
    input_digest: str
    output_digest: str
    seal: str

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["provenance_id", "component_id", "execution_ref", "authority_evidence_ref"], out)
        if self.component_kind not in PROVENANCE_KINDS:
            out.append(f"component_kind must be one of {sorted(PROVENANCE_KINDS)}")
        for n in ("input_digest", "output_digest", "seal"):
            if not _is_digest(getattr(self, n)):
                out.append(f"{n} must be a lowercase sha256 hex digest")
        return out

    def _body(self) -> bytes:
        d = {k: getattr(self, k) for k in ("provenance_id", "component_id", "component_kind", "execution_ref",
                                           "authority_evidence_ref", "input_digest", "output_digest")}
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


class ProvenanceLedger:
    """The trust anchor. Only code holding a ledger instance can mint or verify RuntimeProvenance."""

    def __init__(self, secret: Optional[bytes] = None):
        self._key = secret if secret is not None else secrets.token_bytes(32)
        self._issued: set[str] = set()

    def issue(self, *, component_id: str, component_kind: str, execution_ref: str, authority_evidence_ref: str,
              input_digest: str, output_digest: str) -> RuntimeProvenance:
        pid = hashlib.sha256(f"{component_id}|{component_kind}|{execution_ref}|{input_digest}|{output_digest}".encode()).hexdigest()
        unsealed = RuntimeProvenance(pid, component_id, component_kind, execution_ref, authority_evidence_ref,
                                     input_digest, output_digest, "0" * 64)
        seal = hmac.new(self._key, unsealed._body(), hashlib.sha256).hexdigest()
        self._issued.add(pid)
        return replace(unsealed, seal=seal)

    def verify(self, prov: Any) -> bool:
        if not isinstance(prov, RuntimeProvenance) or prov.problems() or prov.provenance_id not in self._issued:
            return False
        want = hmac.new(self._key, prov._body(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(want, prov.seal)


def classification_digest(kind: "OutputKind") -> str:
    """The digest a router provenance must carry to vouch for an output_kind assignment."""
    return content_digest(f"output_kind={kind.value}")


def _prov_problems(label: str, prov: Optional[RuntimeProvenance], ledger: "ProvenanceLedger", *, kind: str,
                   output_digest: Optional[str] = None, authority_ref: Optional[str] = None,
                   component_id: Optional[str] = None, input_digest: Optional[str] = None) -> list[str]:
    if prov is None:
        return [f"{label} requires trusted runtime provenance"]
    if not ledger.verify(prov):
        return [f"{label} provenance is not verifiable by the trusted ledger (self-asserted or forged)"]
    out: list[str] = []
    if prov.component_kind != kind:
        out.append(f"{label} provenance must come from a {kind} component")
    if output_digest is not None and prov.output_digest != output_digest:
        out.append(f"{label} provenance output_digest does not match the bound digest")
    if authority_ref is not None and prov.authority_evidence_ref != authority_ref:
        out.append(f"{label} provenance authority_evidence_ref does not match the contract evidence")
    if component_id is not None and prov.component_id != component_id:
        out.append(f"{label} provenance component_id does not match")
    if input_digest is not None and prov.input_digest != input_digest:
        out.append(f"{label} provenance input_digest does not match what was verified")
    return out


# ---------------------------------------------------------------- evidence
@dataclass(frozen=True)
class EvidenceReference(_Contract):
    ref_id: str
    kind: str
    source_uri: str
    content_digest: str
    retrieved_at: str
    tenant_id: str

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["ref_id", "kind", "source_uri", "retrieved_at", "tenant_id"], out)
        if not _SHA256.match(self.content_digest or ""):
            out.append("content_digest must be a lowercase sha256 hex digest")
        return out


# ---------------------------------------------------------------- objectives / world
@dataclass(frozen=True)
class Objective(_Contract):
    objective_id: str
    tenant_id: str
    statement: str
    success_metrics: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    parent_objective_id: Optional[str] = None
    status: str = "ACTIVE"
    revision: int = 0
    created_at: str = ""

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["objective_id", "tenant_id", "statement", "success_metrics", "created_at"], out)
        if self.status not in {"ACTIVE", "PAUSED", "ACHIEVED", "ABANDONED"}:
            out.append("status must be ACTIVE|PAUSED|ACHIEVED|ABANDONED")
        if self.revision < 0:
            out.append("revision must be >= 0")
        return out


@dataclass(frozen=True)
class WorldState(_Contract):
    """One immutable WorldModelVersion (V_n). State content is referenced by digest."""

    world_id: str
    tenant_id: str
    version: int
    parent_version: Optional[int]
    content_digest: str
    created_at: str
    protocol_version: str = PROTOCOL_VERSION

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["world_id", "tenant_id", "created_at"], out)
        if not _SHA256.match(self.content_digest or ""):
            out.append("content_digest must be sha256 hex")
        if self.version < 0:
            out.append("version must be >= 0")
        if (self.version == 0) != (self.parent_version is None):
            out.append("parent_version is None exactly when version == 0")
        elif self.parent_version is not None and self.parent_version != self.version - 1:
            out.append("parent_version must equal version - 1")
        return out


WORLD_CHANGE_KINDS = frozenset({"ADD", "UPDATE", "REMOVE", "RETRACT"})


@dataclass(frozen=True)
class WorldDelta(_Contract):
    """Explicit V_n + evidence -> V_n+1 transition. Every change cites evidence."""

    delta_id: str
    world_id: str
    tenant_id: str
    base_version: int
    result_version: int
    changes: tuple[Mapping[str, Any], ...]
    created_at: str

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["delta_id", "world_id", "tenant_id", "changes", "created_at"], out)
        if self.result_version != self.base_version + 1:
            out.append("result_version must equal base_version + 1")
        for i, c in enumerate(self.changes):
            if c.get("kind") not in WORLD_CHANGE_KINDS:
                out.append(f"changes[{i}].kind must be one of {sorted(WORLD_CHANGE_KINDS)}")
            if _blank(c.get("target_ref")):
                out.append(f"changes[{i}].target_ref is required")
            if not c.get("evidence_refs"):
                out.append(f"changes[{i}].evidence_refs is required")
        return out


def propagate_delta(edges: Mapping[str, Sequence[str]], node_kinds: Mapping[str, str],
                    changed: Sequence[str]) -> dict[str, list[str]]:
    """World Delta -> dependency graph -> assumptions -> conclusions -> objectives.

    ``edges[x]`` lists nodes that DEPEND ON x. ``node_kinds`` maps node -> one of
    ``assumption|conclusion|objective|other``. Returns impacted nodes grouped by kind
    (sorted, deterministic) so selective re-verification can be scheduled.
    """
    seen: set[str] = set()
    stack = list(changed)
    while stack:
        n = stack.pop()
        for dep in edges.get(n, ()):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    grouped: dict[str, list[str]] = {"assumption": [], "conclusion": [], "objective": [], "other": []}
    for n in sorted(seen):
        k = node_kinds.get(n, "other")
        grouped[k if k in grouped else "other"].append(n)
    return grouped


# ---------------------------------------------------------------- discovery / hypothesis
DISCOVERY_TYPES = frozenset({"OPPORTUNITY", "RISK", "CONTRADICTION", "WEAK_SIGNAL", "UNEXPECTED_CONNECTION",
                             "NOVEL_HYPOTHESIS", "MISSING_INFORMATION", "INVALIDATED_CONCLUSION",
                             "CROSS_DOMAIN_TRANSFER"})


@dataclass(frozen=True)
class Discovery(_Contract):
    discovery_id: str
    objective_id: str
    discovery_type: str
    statement: str
    why_non_obvious: str
    evidence_refs: tuple[str, ...]
    counter_evidence_refs: tuple[str, ...]
    counter_evidence_status: CounterEvidenceStatus
    assumptions: tuple[str, ...]
    confidence: float
    estimated_importance: float
    falsification_condition: str
    suggested_experiment: str
    potential_action: str
    affected_prior_decisions: tuple[str, ...]
    outcome_status: DiscoveryOutcome
    created_at: str
    updated_at: str
    tenant_id: str = ""
    revision: int = 0
    parent_digest: Optional[str] = None

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["discovery_id", "objective_id", "statement", "why_non_obvious", "evidence_refs",
                     "falsification_condition", "created_at", "updated_at", "tenant_id"], out)
        if self.discovery_type not in DISCOVERY_TYPES:
            out.append(f"discovery_type must be one of {sorted(DISCOVERY_TYPES)}")
        _unit("confidence", self.confidence, out)
        _unit("estimated_importance", self.estimated_importance, out)
        st = self.counter_evidence_status
        if st is CounterEvidenceStatus.SEARCHED_FOUND and not self.counter_evidence_refs:
            out.append("counter_evidence_refs required when counter_evidence_status is SEARCHED_FOUND")
        if st is CounterEvidenceStatus.SEARCHED_NONE_FOUND and self.counter_evidence_refs:
            out.append("counter_evidence_refs must be empty when SEARCHED_NONE_FOUND")
        if st is CounterEvidenceStatus.NOT_SEARCHED:
            if isinstance(self.confidence, (int, float)) and self.confidence > 0.5:
                out.append("confidence is capped at 0.5 while counter-evidence has not been searched")
            if self.outcome_status in {DiscoveryOutcome.CONFIRMED, DiscoveryOutcome.ACTED_ON}:
                out.append("a discovery cannot be CONFIRMED/ACTED_ON before counter-evidence is searched")
        if self.revision < 0 or (self.revision == 0) != (self.parent_digest is None):
            out.append("parent_digest is None exactly when revision == 0")
        if self.revision > 0 and not (isinstance(self.parent_digest, str) and _SHA256.match(self.parent_digest)):
            out.append("parent_digest must be a lowercase sha256 hex digest when revision > 0")
        return out

    def revise(self, updated_at: str, **changes: Any) -> "Discovery":
        """Immutable update: returns a new revision that chains to this one's digest."""
        return replace(self, updated_at=updated_at, revision=self.revision + 1,
                       parent_digest=self.digest(), **changes)


@dataclass(frozen=True)
class Hypothesis(_Contract):
    hypothesis_id: str
    tenant_id: str
    statement: str
    supporting_evidence_refs: tuple[str, ...]
    counter_evidence_refs: tuple[str, ...]
    assumptions: tuple[str, ...]
    prediction: str
    falsification_test: str
    experiment_ref: Optional[str] = None
    simulation_ref: Optional[str] = None
    result_refs: tuple[str, ...] = ()
    verdict: HypothesisVerdict = HypothesisVerdict.UNTESTED

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["hypothesis_id", "tenant_id", "statement", "prediction", "falsification_test"], out)
        if self.verdict in {HypothesisVerdict.SUPPORTED, HypothesisVerdict.FALSIFIED}:
            if not self.result_refs:
                out.append("SUPPORTED/FALSIFIED verdicts require result_refs from an executed test")
            if not (self.experiment_ref or self.simulation_ref):
                out.append("SUPPORTED/FALSIFIED verdicts require an experiment_ref or simulation_ref")
        return out


# Factual/inferential verification methods. Contract compliance is deliberately NOT one of them:
# it proves format/contract correctness, never truth (see CognitiveResult).
VERIFICATION_METHODS = frozenset({"DETERMINISTIC", "TOOL", "ADVERSARIAL_EXPERT", "SIMULATION", "HUMAN"})


@dataclass(frozen=True)
class ClaimBinding(_Contract):
    """A claim-bearing span of one specific output, identified by content, not by a mutable reference.

    Extensibility hook for claim-level (progressive) verification: non-claim prose needs no verification,
    while the factual claims are enumerated, digest-bound and individually verifiable. Only the claim's
    canonical representation or span digest is stored: never hidden reasoning.
    """

    claim_id: str
    output_ref: str
    output_digest: str
    claim_digest: str
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    canonical_claim: Optional[str] = None

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["claim_id", "output_ref"], out)
        for n in ("output_digest", "claim_digest"):
            if not _is_digest(getattr(self, n)):
                out.append(f"{n} must be a lowercase sha256 hex digest")
        has_span = self.span_start is not None or self.span_end is not None
        if has_span and not (isinstance(self.span_start, int) and isinstance(self.span_end, int)
                             and 0 <= self.span_start < self.span_end):
            out.append("span must be integers with 0 <= span_start < span_end")
        if not has_span and _blank(self.canonical_claim):
            out.append("a claim needs a span or a canonical_claim representation")
        if self.canonical_claim is not None and not _blank(self.canonical_claim) and _is_digest(self.claim_digest) \
                and content_digest(self.canonical_claim) != self.claim_digest:
            out.append("claim_digest must equal the sha256 of canonical_claim")
        return out

    def matches_output(self, released_text: str) -> bool:
        """True iff ``released_text`` is exactly the bound output and (for span claims) the span is the bound claim."""
        if content_digest(released_text) != self.output_digest:
            return False
        if self.span_start is not None and self.span_end is not None:
            if self.span_end > len(released_text):
                return False
            return content_digest(released_text[self.span_start:self.span_end]) == self.claim_digest
        return True


@dataclass(frozen=True)
class VerificationResult(_Contract):
    """Verification of either a whole output or one claim, bound to immutable content by digest.

    ``subject_ref`` names the output; ``subject_digest`` is the sha256 of the exact canonical bytes the
    verifier was given (the immutable identity). A reference alone is never enough: a mutable reference could
    be re-pointed after verification (time-of-check/time-of-use). With ``claim_id`` set the verdict covers only
    that claim (``claim_digest``), still inside the output identified by ``subject_digest``.
    """

    verification_id: str
    subject_ref: str
    method: str
    verdict: str
    evidence_refs: tuple[str, ...]
    verifier_id: str
    producer_id: str
    subject_digest: str = ""
    claim_id: Optional[str] = None
    claim_digest: Optional[str] = None
    provenance: Optional[RuntimeProvenance] = None

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["verification_id", "subject_ref", "verifier_id", "producer_id"], out)
        if self.method not in VERIFICATION_METHODS:
            out.append(f"method must be one of {sorted(VERIFICATION_METHODS)}")
        if self.verdict not in {"PASSED", "FAILED", "INCONCLUSIVE"}:
            out.append("verdict must be PASSED|FAILED|INCONCLUSIVE")
        if self.verifier_id == self.producer_id:
            out.append("verifier must be independent of the producer")
        if self.verdict == "PASSED" and not self.evidence_refs:
            out.append("a PASSED verification requires evidence_refs")
        if not _is_digest(self.subject_digest):
            out.append("subject_digest must be a lowercase sha256 hex digest of the exact verified output")
        if (self.claim_id is None) != (self.claim_digest is None):
            out.append("claim_id and claim_digest must be set together")
        if self.claim_digest is not None and not _is_digest(self.claim_digest):
            out.append("claim_digest must be a lowercase sha256 hex digest")
        return out

    def trusted_problems(self, ledger: ProvenanceLedger) -> list[str]:
        """Shape problems plus proof that a trusted VERIFIER component actually consumed this exact content."""
        seen = self.claim_digest if self.claim_digest is not None else self.subject_digest
        return self.problems() + _prov_problems("verification", self.provenance, ledger, kind="VERIFIER",
                                                component_id=self.verifier_id, input_digest=seen)


# ---------------------------------------------------------------- compute / request / result
@dataclass(frozen=True)
class ComputeBudget(_Contract):
    """Compute expressed as budgets, never as a model size."""

    latency_target_ms: Optional[int] = None
    cost_ceiling_units: Optional[float] = None
    reasoning_steps: Optional[int] = None
    max_experts: Optional[int] = None
    verification_depth: int = 1

    def problems(self) -> list[str]:
        out: list[str] = []
        for n in ("latency_target_ms", "cost_ceiling_units", "reasoning_steps", "max_experts"):
            v = getattr(self, n)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
                out.append(f"{n} must be positive when set")
        if self.verification_depth < 0:
            out.append("verification_depth must be >= 0")
        return out


@dataclass(frozen=True)
class CognitiveRequest(_Contract):
    request_id: str
    tenant_id: str
    mode: str
    input_ref: str
    objective_id: Optional[str] = None
    budget: ComputeBudget = field(default_factory=ComputeBudget)
    contract_ref: Optional[str] = None
    protocol_version: str = PROTOCOL_VERSION

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["request_id", "tenant_id", "input_ref"], out)
        if self.mode not in {m.value for m in ComputeMode} and not (
                isinstance(self.mode, str) and self.mode.startswith("FUTURE:") and _OPEN_NAME.match(self.mode)):
            out.append("mode must be FAST|REASON|FRONTIER or a FUTURE:<name> extension")
        if self.protocol_version != PROTOCOL_VERSION:
            out.append(f"protocol_version must be {PROTOCOL_VERSION}")
        return out + self.budget.problems()


@dataclass(frozen=True)
class InformationGainQuery(_Contract):
    """The single highest-value question when evidence is insufficient."""

    question: str
    target_uncertainty: str
    expected_uncertainty_reduction: float
    alternatives_considered: tuple[str, ...]

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["question", "target_uncertainty"], out)
        _unit("expected_uncertainty_reduction", self.expected_uncertainty_reduction, out)
        if self.question.count("?") > 1:
            out.append("ask exactly one question")
        return out


class OutputKind(str, Enum):
    """Assigned by the ORNEUR router from trusted runtime state, never by a model or a payload."""

    DETERMINISTIC_EXACT_TEXT = "DETERMINISTIC_EXACT_TEXT"
    DETERMINISTIC_MATH = "DETERMINISTIC_MATH"
    DETERMINISTIC_JSON_LITERAL = "DETERMINISTIC_JSON_LITERAL"
    GENERATED_EPISTEMIC = "GENERATED_EPISTEMIC"                          # makes factual/inferential claims
    GENERATED_STRUCTURED_EPISTEMIC = "GENERATED_STRUCTURED_EPISTEMIC"    # schema-shaped output that makes factual claims
    GENERATED_TRANSFORMATIVE = "GENERATED_TRANSFORMATIVE"                # rewrite/translate/format/summarise supplied material
    GENERATED_CREATIVE = "GENERATED_CREATIVE"                            # fiction, brainstorming presented as ideas


# Outputs whose correctness is completely established by an authoritative deterministic mechanism (no model).
DETERMINISTIC_KINDS = {
    OutputKind.DETERMINISTIC_EXACT_TEXT: "EXACT_TEXT",
    OutputKind.DETERMINISTIC_MATH: "DETERMINISTIC_MATH",
    OutputKind.DETERMINISTIC_JSON_LITERAL: "JSON_LITERAL",
}
EPISTEMIC_KINDS = frozenset({OutputKind.GENERATED_EPISTEMIC, OutputKind.GENERATED_STRUCTURED_EPISTEMIC})
NON_EPISTEMIC_GENERATED_KINDS = frozenset({OutputKind.GENERATED_TRANSFORMATIVE, OutputKind.GENERATED_CREATIVE})

# How a result may be represented to the user for each kind (rule D: creative content is never presented as fact).
PRESENTATION = {
    OutputKind.DETERMINISTIC_EXACT_TEXT: "DETERMINISTIC_OUTPUT",
    OutputKind.DETERMINISTIC_MATH: "DETERMINISTIC_OUTPUT",
    OutputKind.DETERMINISTIC_JSON_LITERAL: "DETERMINISTIC_OUTPUT",
    OutputKind.GENERATED_EPISTEMIC: "VERIFIED_CLAIMS",
    OutputKind.GENERATED_STRUCTURED_EPISTEMIC: "VERIFIED_CLAIMS",
    OutputKind.GENERATED_TRANSFORMATIVE: "TRANSFORMATION_OF_SUPPLIED_MATERIAL",
    OutputKind.GENERATED_CREATIVE: "FICTION_OR_IDEATION",
}


@dataclass(frozen=True)
class CognitiveResult(_Contract):
    """Contract Compliance, factual Verification and provenance are three DISTINCT concepts.

    * ``contract_*`` fields say the output satisfied its format contract; they never say it is true.
    * ``verifications`` (whole-output, or claim-level through ``claim_bindings``) say the *claims* are supported.
      They qualify only when bound to this exact output by ``output_ref`` AND ``output_digest`` and only when a
      trusted VERIFIER provenance proves the verifier consumed those bytes.
    * ``*_provenance`` fields prove a trusted ORNEUR runtime component made the privileged statement
      (router classification, deterministic authority, claim extraction, epistemic screening). Strings such as
      "ORNEUR_ROUTER" are not authority; a ``ProvenanceLedger`` must verify the seal.

    Which outputs need factual verification: epistemic ones (they assert things about the world). Deterministic
    outputs are established by their authoritative mechanism; transformative and creative outputs need none for
    the content they merely reshape or invent, but any *new factual claim* they carry is enumerated in
    ``claim_bindings`` and verified individually. COMPLETED results are validated only against a trusted ledger.
    """

    request_id: str
    status: str  # COMPLETED | FAILED_CLOSED | NEEDS_INFORMATION
    output_ref: Optional[str]
    evidence_refs: tuple[str, ...]
    verifications: tuple[VerificationResult, ...]
    confidence: Optional[float]
    output_kind: Optional[OutputKind] = None
    output_digest: Optional[str] = None
    presented_as: Optional[str] = None
    contract_type: Optional[str] = None
    contract_status: Optional[str] = None
    contract_evidence_ref: Optional[str] = None
    contract_output_digest: Optional[str] = None
    model_calls: int = 0
    claim_bindings: tuple[ClaimBinding, ...] = ()
    source_digests: tuple[str, ...] = ()
    classification_provenance: Optional[RuntimeProvenance] = None
    deterministic_provenance: Optional[RuntimeProvenance] = None
    claim_extraction_provenance: Optional[RuntimeProvenance] = None
    screening_provenance: Optional[RuntimeProvenance] = None
    information_request: Optional[InformationGainQuery] = None

    def problems(self, trust: Optional[ProvenanceLedger] = None) -> list[str]:
        out: list[str] = []
        _need(self, ["request_id"], out)
        if self.status not in {"COMPLETED", "FAILED_CLOSED", "NEEDS_INFORMATION"}:
            out.append("status must be COMPLETED|FAILED_CLOSED|NEEDS_INFORMATION")
        if self.status != "COMPLETED" and self.output_ref is not None:
            out.append("only COMPLETED results may carry an output_ref")
        if self.status == "NEEDS_INFORMATION":
            if self.information_request is None:
                out.append("NEEDS_INFORMATION requires an information_request")
            else:
                out += self.information_request.problems()
        if self.confidence is not None:
            _unit("confidence", self.confidence, out)
        if self.status == "COMPLETED":
            out += self._completion_problems(trust)
        return out

    def release_matches(self, released: "str | bytes") -> bool:
        """TOCTOU guard: the bytes about to be emitted must hash to the digest that was verified."""
        return self.output_digest is not None and content_digest(released) == self.output_digest

    # -- completion -----------------------------------------------------------------------------------
    def _completion_problems(self, trust: Optional[ProvenanceLedger]) -> list[str]:
        out: list[str] = []
        if _blank(self.output_ref):
            out.append("COMPLETED requires output_ref")
        if self.confidence is None:
            out.append("COMPLETED requires a calibrated confidence")
        if not _is_digest(self.output_digest):
            out.append("COMPLETED requires output_digest (sha256 of the exact canonical bytes released)")
        if trust is None:
            return out + ["COMPLETED results are only valid against a trusted ProvenanceLedger (fail closed)"]
        if self.output_kind is None:
            return out + ["COMPLETED requires an output_kind assigned by the ORNEUR router"]
        kind = self.output_kind
        out += _prov_problems("output_kind classification", self.classification_provenance, trust, kind="ROUTER",
                              output_digest=classification_digest(kind))
        if self.presented_as != PRESENTATION[kind]:
            out.append(f"{kind.value} must be presented as {PRESENTATION[kind]} (creative/transformative output is never "
                       "presented as verified fact; epistemic output only as verified claims)")
        if kind in DETERMINISTIC_KINDS:
            return out + self._deterministic_problems(kind, trust)
        if any(v.verdict == "FAILED" for v in self.verifications):
            out.append("a FAILED verification blocks completion")
        if self.deterministic_provenance is not None:
            out.append("deterministic provenance may only accompany deterministic outputs")
        if kind is OutputKind.GENERATED_STRUCTURED_EPISTEMIC:
            if self.contract_type != "JSON_SCHEMA":
                out.append("GENERATED_STRUCTURED_EPISTEMIC requires contract_type JSON_SCHEMA")
            if not (self.contract_status == "SATISFIED" and not _blank(self.contract_evidence_ref)):
                out.append("GENERATED_STRUCTURED_EPISTEMIC requires a SATISFIED contract with contract_evidence_ref")
            if self.contract_output_digest is not None and self.contract_output_digest != self.output_digest:
                out.append("contract_output_digest must equal output_digest")
        elif self.contract_type not in (None, "FREE_TEXT"):
            out.append(f"{kind.value} may only carry contract_type FREE_TEXT")
        if kind in EPISTEMIC_KINDS:
            return out + self._epistemic_coverage_problems(trust)
        return out + self._non_epistemic_problems(trust)

    def _deterministic_problems(self, kind: OutputKind, trust: ProvenanceLedger) -> list[str]:
        out: list[str] = []
        want = DETERMINISTIC_KINDS[kind]
        if self.contract_type != want:
            out.append(f"{kind.value} requires contract_type {want}")
        if not (self.contract_status == "SATISFIED" and not _blank(self.contract_evidence_ref)):
            out.append("a deterministic output requires a SATISFIED contract with contract_evidence_ref")
        if self.contract_output_digest != self.output_digest:
            out.append("a deterministic output requires contract_output_digest equal to output_digest")
        if self.model_calls != 0:
            out.append("a deterministic output must have been produced with zero model calls")
        out += _prov_problems("deterministic authority", self.deterministic_provenance, trust, kind="DETERMINISTIC_AUTHORITY",
                              output_digest=self.output_digest, authority_ref=self.contract_evidence_ref)
        return out

    def _qualifies(self, v: VerificationResult, trust: ProvenanceLedger, claim: Optional[ClaimBinding]) -> bool:
        if v.verdict != "PASSED" or v.trusted_problems(trust):
            return False
        if v.subject_ref != self.output_ref or v.subject_digest != self.output_digest:
            return False
        if claim is None:
            return v.claim_id is None
        return v.claim_id == claim.claim_id and v.claim_digest == claim.claim_digest

    def _claims_problems(self, trust: ProvenanceLedger) -> list[str]:
        out: list[str] = []
        for c in self.claim_bindings:
            out += [f"claim {c.claim_id}: {p}" for p in c.problems()]
            if c.output_ref != self.output_ref or c.output_digest != self.output_digest:
                out.append(f"claim {c.claim_id} is not bound to this exact output (ref and digest must match)")
            elif not any(self._qualifies(v, trust, c) for v in self.verifications):
                out.append(f"claim {c.claim_id} has no passing, trusted, digest-bound claim verification")
        return out

    def _epistemic_coverage_problems(self, trust: ProvenanceLedger) -> list[str]:
        whole = any(self._qualifies(v, trust, None) for v in self.verifications)
        if whole:
            return self._claims_problems(trust) if self.claim_bindings else []
        if self.claim_bindings:
            out = _prov_problems("claim extraction", self.claim_extraction_provenance, trust, kind="CLAIM_EXTRACTOR",
                                 output_digest=self.output_digest)
            return out + self._claims_problems(trust)
        return ["an epistemic result requires a passing, trusted, digest-bound Verification of this exact output "
                "(or trusted claim-level coverage of every factual claim); contract compliance does not substitute for "
                "factual verification"]

    def _non_epistemic_problems(self, trust: ProvenanceLedger) -> list[str]:
        out = _prov_problems("epistemic screening", self.screening_provenance, trust, kind="EPISTEMIC_SCREENER",
                             output_digest=self.output_digest)
        if self.output_kind is OutputKind.GENERATED_TRANSFORMATIVE:
            if not self.source_digests or not all(_is_digest(d) for d in self.source_digests):
                out.append("a transformation requires the sha256 digests of the supplied source material")
        # Rule C: any NEW factual claim carried by a transformation or a creative work is epistemic for that claim.
        return out + self._claims_problems(trust)


# ---------------------------------------------------------------- experts
@dataclass(frozen=True)
class ExpertCapability(_Contract):
    expert_id: str
    kind: str  # open vocabulary; future experts are legal
    realization: str  # open vocabulary (adapter, checkpoint, symbolic, simulator, FUTURE:...)
    capability_tags: tuple[str, ...]
    state: QualificationState
    qualification_eval_refs: tuple[str, ...] = ()
    interface_version: str = PROTOCOL_VERSION

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["expert_id", "capability_tags"], out)
        for n in ("kind", "realization"):
            if not _OPEN_NAME.match(getattr(self, n) or ""):
                out.append(f"{n} must be a plain name (optionally FUTURE:-prefixed)")
        if self.state is QualificationState.QUALIFIED and not self.qualification_eval_refs:
            out.append("QUALIFIED experts require qualification_eval_refs")
        return out


@dataclass(frozen=True)
class ExpertRequest(_Contract):
    request_id: str
    expert_id: str
    tenant_id: str
    task_ref: str
    budget: ComputeBudget = field(default_factory=ComputeBudget)

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["request_id", "expert_id", "tenant_id", "task_ref"], out)
        return out + self.budget.problems()


@dataclass(frozen=True)
class ExpertResult(_Contract):
    request_id: str
    expert_id: str
    status: str  # OK | FAILED | REFUSED
    output_ref: Optional[str]
    evidence_refs: tuple[str, ...] = ()
    self_reported_confidence: Optional[float] = None
    claims_trusted: bool = False  # expert claims are never trusted; ORNEUR verifies

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["request_id", "expert_id"], out)
        if self.status not in {"OK", "FAILED", "REFUSED"}:
            out.append("status must be OK|FAILED|REFUSED")
        if self.status == "OK" and _blank(self.output_ref):
            out.append("OK requires output_ref")
        if self.claims_trusted:
            out.append("expert self-reports are never trusted (claims_trusted must be False)")
        return out


# ---------------------------------------------------------------- outcome learning
@dataclass(frozen=True)
class PreferenceFeedback(_Contract):
    """What the user LIKED. Deliberately a different type from Outcome."""

    feedback_id: str
    tenant_id: str
    response_ref: str
    signal: str
    created_at: str

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["feedback_id", "tenant_id", "response_ref", "signal", "created_at"], out)
        return out


@dataclass(frozen=True)
class Outcome(_Contract):
    """Did the recommendation/action actually work? Never derived from preference alone."""

    outcome_id: str
    tenant_id: str
    objective_id: str
    decision_ref: str
    action_ref: str
    expected_outcome: str
    time_horizon: str
    success_metric: str
    source: OutcomeSource
    status: str = "PENDING"  # PENDING | OBSERVED
    observed_outcome: Optional[str] = None
    observation_evidence_refs: tuple[str, ...] = ()
    difference: Optional[str] = None
    root_cause: Optional[str] = None
    lesson: Optional[str] = None
    reusable_strategy_candidate_ref: Optional[str] = None

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["outcome_id", "tenant_id", "objective_id", "decision_ref", "action_ref",
                     "expected_outcome", "time_horizon", "success_metric"], out)
        if self.source is OutcomeSource.USER_PREFERENCE:
            out.append("user preference is not an outcome source; use PreferenceFeedback")
        if self.status not in {"PENDING", "OBSERVED"}:
            out.append("status must be PENDING|OBSERVED")
        if self.status == "OBSERVED":
            if _blank(self.observed_outcome):
                out.append("OBSERVED requires observed_outcome")
            if not self.observation_evidence_refs:
                out.append("OBSERVED requires observation_evidence_refs")
        elif self.observed_outcome is not None:
            out.append("PENDING outcomes cannot carry observed_outcome")
        return out


@dataclass(frozen=True)
class FailureGenomeEntry(_Contract):
    entry_id: str
    tenant_id: str
    failure_class: str
    trigger_conditions: tuple[str, ...]
    capability_gap: str
    evidence_refs: tuple[str, ...]
    scope: str = "TENANT_PRIVATE"  # or ANONYMIZED_SHAREABLE
    anonymization_evidence_ref: Optional[str] = None
    occurrences: int = 1

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["entry_id", "tenant_id", "failure_class", "trigger_conditions", "capability_gap",
                     "evidence_refs"], out)
        if self.scope not in {"TENANT_PRIVATE", "ANONYMIZED_SHAREABLE"}:
            out.append("scope must be TENANT_PRIVATE|ANONYMIZED_SHAREABLE")
        if self.scope == "ANONYMIZED_SHAREABLE" and _blank(self.anonymization_evidence_ref):
            out.append("cross-tenant sharing requires anonymization_evidence_ref")
        return out


@dataclass(frozen=True)
class CognitivePrimitive(_Contract):
    """A structured, versioned strategy. Raw reasoning traces are never stored."""

    primitive_id: str
    version: int
    problem_class: str
    strategy_steps: tuple[str, ...]
    worked_conditions: tuple[str, ...]
    failed_conditions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    state: QualificationState = QualificationState.CANDIDATE
    qualification_eval_refs: tuple[str, ...] = ()
    raw_reasoning_trace_stored: bool = False

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["primitive_id", "problem_class", "strategy_steps", "worked_conditions", "evidence_refs"], out)
        if self.version < 1:
            out.append("version must be >= 1")
        if self.raw_reasoning_trace_stored:
            out.append("free-form reasoning traces must not be stored as a permanent asset")
        if self.state is QualificationState.QUALIFIED and not self.qualification_eval_refs:
            out.append("QUALIFIED primitives require qualification_eval_refs")
        return out


# ---------------------------------------------------------------- migration / promotion
@dataclass(frozen=True)
class ArchitectureDescriptor(_Contract):
    architecture_id: str
    generation: int
    family_label: str  # informational only; no logic may branch on it

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["architecture_id", "family_label"], out)
        if self.generation < 0:
            out.append("generation must be >= 0")
        return out


@dataclass(frozen=True)
class AssetMigration(_Contract):
    asset: MigrationAsset
    mechanisms: tuple[MigrationMechanism, ...]
    preservation_eval_refs: tuple[str, ...] = ()

    def problems(self) -> list[str]:
        out: list[str] = []
        if not self.mechanisms:
            out.append(f"{self.asset.value}: at least one mechanism is required")
        return out


@dataclass(frozen=True)
class ArchitectureMigrationManifest(_Contract):
    manifest_id: str
    source: ArchitectureDescriptor
    target: ArchitectureDescriptor
    assets: tuple[AssetMigration, ...]
    shadow_comparison_ref: Optional[str]
    rollback_plan_ref: Optional[str]
    obsolescence_review_ref: Optional[str]  # Self-Obsolescence Rule: what is now unnecessary?
    cutover_approved: bool = False
    protocol_version: str = PROTOCOL_VERSION

    def problems(self) -> list[str]:
        out: list[str] = _collect(self.source, self.target)
        _need(self, ["manifest_id"], out)
        if self.source.architecture_id == self.target.architecture_id:
            out.append("source and target architecture must differ")
        have = {a.asset for a in self.assets}
        for a in MigrationAsset:
            if a not in have:
                out.append(f"asset class {a.value} is not covered")
        for a in self.assets:
            out += a.problems()
        if self.cutover_approved:
            for n in ("shadow_comparison_ref", "rollback_plan_ref", "obsolescence_review_ref"):
                if _blank(getattr(self, n)):
                    out.append(f"cutover_approved requires {n}")
            for a in self.assets:
                if a.asset in {MigrationAsset.EVAL_SUITES, MigrationAsset.AUTHORITY_EVIDENCE_CONTRACTS} \
                        and not a.preservation_eval_refs:
                    out.append(f"cutover requires preservation_eval_refs for {a.asset.value}")
        return out


def _collect(*items: _Contract) -> list[str]:
    out: list[str] = []
    for i in items:
        out += i.problems()
    return out


@dataclass(frozen=True)
class PromotionDecision(_Contract):
    decision_id: str
    candidate_id: str
    candidate_produced_by: str
    decided_by: str
    decider_kind: str  # HUMAN_OWNER | QUALIFIED_GATE_SERVICE
    verdict: PromotionVerdict
    decider_qualification_ref: Optional[str] = None  # required for QUALIFIED_GATE_SERVICE
    frozen_eval_ref: Optional[str] = None
    adversarial_eval_ref: Optional[str] = None
    regression_eval_ref: Optional[str] = None
    shadow_deployment_ref: Optional[str] = None
    measured_improvement: Optional[float] = None
    regressions_found: Optional[int] = None

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["decision_id", "candidate_id", "candidate_produced_by", "decided_by"], out)
        if self.decider_kind not in {"HUMAN_OWNER", "QUALIFIED_GATE_SERVICE"}:
            out.append("decider_kind must be HUMAN_OWNER|QUALIFIED_GATE_SERVICE")
        if self.decided_by in {self.candidate_produced_by, self.candidate_id}:
            out.append("a self-generated component cannot promote itself")
        if self.decider_kind == "QUALIFIED_GATE_SERVICE":
            if _blank(self.decider_qualification_ref):
                out.append("QUALIFIED_GATE_SERVICE requires decider_qualification_ref (evidence the service is qualified)")
            elif self.decider_qualification_ref == self.candidate_id:
                out.append("a candidate cannot vouch for its own promoter")
        if self.verdict is PromotionVerdict.PROMOTE:
            for n in ("frozen_eval_ref", "adversarial_eval_ref", "regression_eval_ref", "shadow_deployment_ref"):
                if _blank(getattr(self, n)):
                    out.append(f"PROMOTE requires {n}")
            if self.measured_improvement is None or self.measured_improvement <= 0:
                out.append("PROMOTE requires a measured positive improvement")
            if self.regressions_found is None or self.regressions_found != 0:
                out.append("PROMOTE requires zero regressions")
        return out
