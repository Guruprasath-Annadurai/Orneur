"""
The ONE canonical definition of per-control RUNTIME CONFIGURATIONS for Phase 21B.4.20 (request-level behaviour that is part of the
qualified runtime but is neither a model property nor a smoke prompt).

Currently exactly one entry: Qwen3-8B `qwen3_8b_non_thinking_v1` (`chat_template_kwargs: {"enable_thinking": false}`), the officially
supported Qwen switch that the pinned chat template implements and vLLM 0.29.0 forwards to both the template renderer and the
`--reasoning-parser qwen3` parser. It changes only the rendered prompt (an empty think block) and parser state; the checkpoint,
revision, precision, quantization, container, server argv, sampling and the canonical locked smoke prompts are unchanged.

Standard-library only: it is shipped beside the runner into the GPU container, and the runner, the harness, the record builder, the
validator and the tests all read THIS file. Controls with no entry (Mistral-Nemo, Phi-4) receive NO extra request setting.

Fail-closed policy pin: `PINNED_RUNTIME_POLICY_SHA256` is the SHA256 of the canonical JSON of the complete protected POLICY document (configuration id,
model id, revision, precision, quantization, reasoning parser, exact chat_template_kwargs AND required_from_attempt -- see
`runtime_policy_document`). Importing this module runs `verify_runtime_configuration_integrity()`, so if the canonical data itself drifts the
container, the local harness and the validator all stop; agreeing on a drifted value is impossible. The pin is over the policy DATA, not the
Python source file. (`PINNED_QWEN_CONFIGURATION_SHA256` additionally pins the configuration-only hash the earlier proofs carried.)

Attempt history is never renumbered: attempts 1-4 predate this configuration (attempt 4 ran with thinking ON and stays as recorded).
The configuration is REQUIRED on records whose final attempt number is >= `REQUIRED_FROM_ATTEMPT[model_id]`.
"""
from __future__ import annotations

import copy
import hashlib
import json

QWEN_CONFIGURATION_ID = "qwen3_8b_non_thinking_v1"

RUNTIME_CONFIGURATIONS: dict[str, dict] = {
    "Qwen/Qwen3-8B": {
        "id": QWEN_CONFIGURATION_ID,
        "model_id": "Qwen/Qwen3-8B",
        "revision": "b968826d9c46dd6066d109eabc6255188de91218",
        "precision": "bfloat16",
        "quantization": None,
        "reasoning_parser": "qwen3",
        "chat_template_kwargs": {"enable_thinking": False},
    },
}

# First attempt number that must carry (and prove) the configuration. Earlier attempts are historical and untouched.
REQUIRED_FROM_ATTEMPT: dict[str, int] = {"Qwen/Qwen3-8B": 5}


def configuration_for_model(model_id: str) -> dict | None:
    cfg = RUNTIME_CONFIGURATIONS.get(model_id)
    return copy.deepcopy(cfg) if cfg is not None else None


def configuration_sha256(model_id: str) -> str | None:
    cfg = RUNTIME_CONFIGURATIONS.get(model_id)
    if cfg is None:
        return None
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def chat_template_kwargs_for_model(model_id: str) -> dict | None:
    """The kwargs sent with EVERY locked smoke request for this model, or None (no extra setting) for controls without a configuration."""
    cfg = RUNTIME_CONFIGURATIONS.get(model_id)
    return copy.deepcopy(cfg["chat_template_kwargs"]) if cfg is not None else None


def effective_reasoning_mode(default_mode, runtime_configuration) -> str:
    """The reasoning mode a record must DESCRIBE, derived from the EFFECTIVE runtime configuration -- never from the model's default template
    capability. Loading `--reasoning-parser qwen3` does not mean thinking is on: with `enable_thinking=false` the parser starts in CONTENT
    state and the rendered prompt carries an empty think block, so the run is NON_THINKING."""
    cfg = runtime_configuration or {}
    kwargs = cfg.get("chat_template_kwargs")
    if isinstance(kwargs, dict) and kwargs.get("enable_thinking") is False:
        return (f"NON_THINKING (enable_thinking=false via chat_template_kwargs; approved runtime configuration {cfg.get('id')}); "
                "--reasoning-parser qwen3 is loaded but thinking is not enabled")
    return default_mode


# ── fail-closed pinned policy fingerprint ────────────────────────────────────────────────────────────────────────
POLICY_ID = "GENESIS_CONTROL_RUNTIME_CONFIGURATION_POLICY"
PINNED_QWEN_CONFIGURATION_SHA256 = "c88e0e140797d25ea9c86bc642d23706d9b6e76c241c49d2b6b354a40b83bab1"
PINNED_RUNTIME_POLICY_SHA256 = "50c0b455e710aa53d0ec4d5515c9f9835b51ebac14391242813ceef961b6c62e"


def runtime_policy_document(configs=None, required_from=None) -> dict:
    """The complete protected policy: for every approved control, every field that defines its runtime configuration plus the attempt from
    which it is required. Sorted by model id so the canonical JSON is deterministic."""
    configs = RUNTIME_CONFIGURATIONS if configs is None else configs
    required_from = REQUIRED_FROM_ATTEMPT if required_from is None else required_from
    return {"policy_id": POLICY_ID,
            "policies": [{"runtime_configuration_id": c.get("id"), "model_id": c.get("model_id"), "revision": c.get("revision"), "precision": c.get("precision"),
                          "quantization": c.get("quantization"), "reasoning_parser": c.get("reasoning_parser"),
                          "chat_template_kwargs": copy.deepcopy(c.get("chat_template_kwargs")), "required_from_attempt": required_from.get(m)}
                         for m, c in sorted(configs.items())]}


def runtime_policy_canonical_bytes(configs=None, required_from=None) -> bytes:
    return json.dumps(runtime_policy_document(configs, required_from), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def runtime_policy_sha256(configs=None, required_from=None) -> str:
    return hashlib.sha256(runtime_policy_canonical_bytes(configs, required_from)).hexdigest()


def verify_runtime_configuration_integrity(configs=None, required_from=None) -> None:
    """Fail closed if ANY protected field of the approved policy differs from the pinned one."""
    got = runtime_policy_sha256(configs, required_from)
    if got != PINNED_RUNTIME_POLICY_SHA256:
        raise RuntimeError(f"runtime configuration policy drift: fingerprint {got} != pinned {PINNED_RUNTIME_POLICY_SHA256}")
    cfgs = RUNTIME_CONFIGURATIONS if configs is None else configs
    qwen = cfgs.get("Qwen/Qwen3-8B")
    if qwen is None or hashlib.sha256(json.dumps(qwen, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest() != PINNED_QWEN_CONFIGURATION_SHA256:
        raise RuntimeError("runtime configuration policy drift: the approved Qwen3-8B configuration differs from its pinned fingerprint")


verify_runtime_configuration_integrity()
