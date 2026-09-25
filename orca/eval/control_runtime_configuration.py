"""
The ONE canonical definition of per-control RUNTIME CONFIGURATIONS for Phase 21B.4.20 (request-level behaviour that is part of the
qualified runtime but is neither a model property nor a smoke prompt).

Currently exactly one entry: Qwen3-8B `qwen3_8b_non_thinking_v1` (`chat_template_kwargs: {"enable_thinking": false}`), the officially
supported Qwen switch that the pinned chat template implements and vLLM 0.29.0 forwards to both the template renderer and the
`--reasoning-parser qwen3` parser. It changes only the rendered prompt (an empty think block) and parser state; the checkpoint,
revision, precision, quantization, container, server argv, sampling and the canonical locked smoke prompts are unchanged.

Standard-library only: it is shipped beside the runner into the GPU container, and the runner, the harness, the record builder, the
validator and the tests all read THIS file. Controls with no entry (Mistral-Nemo, Phi-4) receive NO extra request setting.

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
