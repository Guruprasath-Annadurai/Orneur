"""
Immutable typed model of the ORNEUR Contract Compliance Engine.

Four separate concerns are never conflated: contract DETECTION (what the request demands), EXECUTION (how a result is produced),
VALIDATION (an independent check of the exact text about to be emitted) and EMISSION (only a validated SATISFIED result carries
final text). A failed validator can never be turned into SATISFIED: `ContractResult` refuses to hold final output otherwise.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum


class ContractType(str, Enum):
    EXACT_TEXT = "EXACT_TEXT"
    DETERMINISTIC_MATH = "DETERMINISTIC_MATH"
    JSON_LITERAL = "JSON_LITERAL"
    JSON_SCHEMA = "JSON_SCHEMA"
    FREE_TEXT = "FREE_TEXT"
    # Reserved for later extension (deliberately NOT implemented yet): TOOL_RESULT, CODE, SQL, XML, ENUM, REGEX, FUNCTION_ARGUMENTS


class ContractStatus(str, Enum):
    SATISFIED = "SATISFIED"                    # a strict contract's validator passed on the exact text that is emitted (or FREE_TEXT: no strict promise)
    UNSATISFIABLE = "UNSATISFIABLE"            # the contract is well formed but no valid output exists / could be produced (validator failed, division by zero, ...)
    INVALID_CONTRACT = "INVALID_CONTRACT"      # the request declares a strict contract that is itself malformed or unsupported (empty literal, oversize, bad schema)
    EXECUTION_FAILED = "EXECUTION_FAILED"      # execution could not run (model backend raised / none available for a generated contract)


STRICT_TYPES = frozenset({ContractType.EXACT_TEXT, ContractType.DETERMINISTIC_MATH, ContractType.JSON_LITERAL, ContractType.JSON_SCHEMA})


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ContractSpec:
    """What the request demands. Frozen; JSON payloads are held as canonical TEXT so the spec stays hashable and immutable."""
    contract_type: ContractType
    detection_basis: str                       # why the router chose this type (auditable, human readable)
    source_sha256: str = ""                    # sha256 of the request text the contract was derived from
    literal: str | None = None                 # EXACT_TEXT: the exact literal to emit
    expression: str | None = None              # DETERMINISTIC_MATH: the normalized expression
    expected_json: str | None = None           # JSON_LITERAL: canonical JSON text of the required value
    schema_json: str | None = None             # JSON_SCHEMA: canonical JSON text of the schema
    invalid_reason: str | None = None          # set => the contract itself is malformed/unsupported (INVALID_CONTRACT)
    declared_by: str = "REQUEST_TEXT"          # REQUEST_TEXT | REQUEST_METADATA | MODEL_DECLARATION (never trusted, see engine.execute_declared)

    @property
    def strict(self) -> bool:
        return self.contract_type in STRICT_TYPES

    @property
    def requires_model(self) -> bool:
        return self.contract_type in (ContractType.JSON_SCHEMA, ContractType.FREE_TEXT) and self.invalid_reason is None


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    validator: str
    reason: str = ""


@dataclass(frozen=True)
class ContractEvidence:
    """One record per contract execution. Nothing is hidden: any ORNEUR-side transformation is listed explicitly. Generated output is data only and is never executed."""
    contract_type: str
    contract_detection_basis: str
    requested_contract: dict
    execution_strategy: str                    # DETERMINISTIC_EMISSION | MODEL_GENERATION | MODEL_GENERATION_WITH_RECOVERY | NONE
    model_used: str | None
    tool_used: str | None
    raw_model_output: str | None
    deterministic_result: str | None
    validator: str
    validator_result: str                      # PASS | FAIL | NOT_RUN | NOT_APPLICABLE
    validator_reason: str
    repair_attempted: bool
    repair_kind: str | None
    transformations_by_orneur: tuple[str, ...]
    model_calls: int
    final_output: str | None
    final_output_sha256: str | None
    contract_status: str
    strict: bool
    raw_model_compliance_claimed: bool = False  # ALWAYS False: a system contract never claims the raw model complied
    declared_compliance_trusted: bool = False   # ALWAYS False: model-declared compliance is never trusted
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["transformations_by_orneur"] = list(self.transformations_by_orneur)
        return d


@dataclass(frozen=True)
class ContractResult:
    status: ContractStatus
    spec: ContractSpec
    evidence: ContractEvidence
    final_output: str | None = None
    reason: str = ""

    def __post_init__(self):
        if self.status is not ContractStatus.SATISFIED and self.final_output is not None:
            raise ValueError("a non-SATISFIED contract result can never carry final output (fail-closed emission gate)")
        if self.status is ContractStatus.SATISFIED and self.final_output is None:
            raise ValueError("a SATISFIED contract result must carry its final output")

    @property
    def satisfied(self) -> bool:
        return self.status is ContractStatus.SATISFIED

    def emit(self) -> str:
        """The ONLY way to obtain user-visible text: raises the typed failure instead of releasing anything malformed."""
        if self.final_output is None:
            raise ContractViolationError(self)
        return self.final_output


class ContractViolationError(Exception):
    """Typed contract failure handed to the ORNEUR runtime instead of malformed text. Carries the full result/evidence (internal) and a client-safe payload."""

    def __init__(self, result: ContractResult):
        self.result = result
        super().__init__(f"{result.status.value}: {result.reason or result.evidence.validator_reason}")

    def to_client_payload(self) -> dict:
        return {"error_code": f"CONTRACT_{self.result.status.value}", "contract_type": self.result.spec.contract_type.value,
                "message": "The response could not be produced in the requested strict format, so no output was released."}
