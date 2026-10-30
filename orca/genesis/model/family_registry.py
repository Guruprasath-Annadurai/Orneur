"""Honest identity records for GENESIS, NOVUS, and AETERNUM.

A record in this registry is a software contract. It is not a trained
model, not a checkpoint, and not a frontier-capability claim. Statuses
that would say otherwise are rejected.
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.genesis.model.config import GenesisModelConfig

FAMILIES = ("GENESIS", "NOVUS", "AETERNUM")

# These words are refused. Nothing in this module can promote a family
# into them, including a caller who passes digests.
FORBIDDEN_STATUSES = frozenset({
    "AVAILABLE",
    "TRAINED",
    "PROMOTABLE",
    "FRONTIER_QUALIFIED",
    "FRONTIER-QUALIFIED",
})

HONEST_STATUSES = frozenset({
    "UNSPECIFIED",
    "INTERFACE_ONLY",
    "CONFIGURATION_ONLY",
    "EXPERIMENTAL_UNTRAINED",
    "NOT_AVAILABLE",
    "EVIDENCE_RECORDED_NOT_ACCEPTED",
})

REQUIRED_CONTRACT_FIELDS = {
    "GENESIS": (
        "architecture_id",
        "tokenizer_binding",
        "parameter_count_check",
        "checkpoint_format",
        "training_identity",
        "general_language_eval",
        "multilingual_eval",
        "resource_estimate",
    ),
    "NOVUS": (
        "model_identity",
        "structured_output_eval",
        "tool_schema_eval",
        "repository_edit_eval",
        "task_completion_eval",
        "execution_trace",
    ),
    "AETERNUM": (
        "model_identity",
        "reasoning_eval",
        "long_horizon_scoring",
        "plan_verification",
        "research_source_eval",
        "calibration_metric",
    ),
}


class ModelFamilyContractError(Exception):
    """The record claims a status or identity the evidence does not support."""


@dataclass(frozen=True)
class ModelFamilyRecord:
    family: str
    status: str
    architecture_id: str | None = None
    tokenizer_digest: str | None = None
    parameter_count: int | None = None
    checkpoint_digest: str | None = None
    training_run_id: str | None = None
    eval_report_digest: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        validate_record(self)


def validate_record(record: ModelFamilyRecord) -> None:
    if record.family not in FAMILIES:
        raise ModelFamilyContractError(f"unknown model family {record.family!r}")
    if record.status in FORBIDDEN_STATUSES:
        raise ModelFamilyContractError(
            f"status {record.status!r} is refused. A registry entry is not a trained "
            "model and cannot be marked AVAILABLE, TRAINED, PROMOTABLE, or FRONTIER_QUALIFIED."
        )
    if record.status not in HONEST_STATUSES:
        raise ModelFamilyContractError(f"status {record.status!r} is not a known honest status")
    untrained = {
        "UNSPECIFIED",
        "INTERFACE_ONLY",
        "CONFIGURATION_ONLY",
        "EXPERIMENTAL_UNTRAINED",
        "NOT_AVAILABLE",
    }
    if record.status in untrained and (record.checkpoint_digest or record.training_run_id):
        raise ModelFamilyContractError(
            f"status {record.status} cannot carry a checkpoint digest or a training run id"
        )
    if record.status == "EVIDENCE_RECORDED_NOT_ACCEPTED":
        missing = [
            name
            for name in ("checkpoint_digest", "training_run_id", "eval_report_digest")
            if not getattr(record, name)
        ]
        if missing:
            raise ModelFamilyContractError(
                "EVIDENCE_RECORDED_NOT_ACCEPTED still requires checkpoint_digest, "
                f"training_run_id, and eval_report_digest; missing {missing}. "
                "That status is not acceptance and not training authorization."
            )


def assert_parameter_count(config: GenesisModelConfig, claimed: int) -> None:
    """Reject a claimed parameter count that disagrees with the config."""
    actual = config.total_parameters()
    if claimed != actual:
        raise ModelFamilyContractError(
            f"claimed parameter count {claimed} != config total {actual} for {config.architecture_version}"
        )


def contract_fields(family: str) -> tuple[str, ...]:
    try:
        return REQUIRED_CONTRACT_FIELDS[family]
    except KeyError as exc:
        raise ModelFamilyContractError(f"unknown model family {family!r}") from exc


def default_registry() -> dict[str, ModelFamilyRecord]:
    """The registry as this repository can honestly state it.

    GENESIS has an implemented architecture interface (`genesis-arch-v1`)
    and no training authorization. NOVUS and AETERNUM have no native
    checkpoint registered here.
    """
    return {
        "GENESIS": ModelFamilyRecord(
            family="GENESIS",
            status="INTERFACE_ONLY",
            architecture_id="genesis-arch-v1",
            notes=(
                "Decoder-only transformer interface and training-step code exist. "
                "No checkpoint is registered as trained. Not frontier-qualified."
            ),
        ),
        "NOVUS": ModelFamilyRecord(
            family="NOVUS",
            status="NOT_AVAILABLE",
            notes="No native NOVUS checkpoint or authorized training identity is registered.",
        ),
        "AETERNUM": ModelFamilyRecord(
            family="AETERNUM",
            status="NOT_AVAILABLE",
            notes="No native AETERNUM checkpoint is registered. Interface fields are a contract, not a model.",
        ),
    }
