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

# ══ CANDIDATE runtime configurations (NOT canonical, NOT part of the pinned policy above) ═══════════════════════════════════════════════════
# A candidate is a separately versioned, separately fingerprinted configuration that a FUTURE owner-authorized attempt may select explicitly. It never
# changes RUNTIME_CONFIGURATIONS, REQUIRED_FROM_ATTEMPT, PINNED_RUNTIME_POLICY_SHA256 or the runner's canonical LOCKED flags, and nothing selects it by default.
MISTRAL_NATIVE_V1_ID = "mistral_nemo_native_v1"
LOCKED_SMOKE_PROTOCOL_SHA256 = "d462103b607e9741786ef86afc0b1769d5857d6e7feef36de516dac87a2b25c1"      # mirrors locked_smoke_protocol.PINNED_PROTOCOL_SHA256 (a test asserts equality)

CANDIDATE_CONFIGURATIONS: dict[str, dict] = {
    MISTRAL_NATIVE_V1_ID: {
        "id": MISTRAL_NATIVE_V1_ID,
        "status": "CANDIDATE",
        "model_id": "mistralai/Mistral-Nemo-Instruct-2407",
        "revision": "04d8a90549d23fc6bd7f642064003592df51e9b3",
        "precision": "bfloat16",
        "quantization": None,
        "server_args": ["--tokenizer-mode", "mistral", "--config-format", "hf", "--load-format", "safetensors"],
        "forbidden_server_flags": ["--reasoning-parser", "--chat-template"],
        "reasoning_parser": None,
        "chat_template": None,
        "chat_template_kwargs": None,
        "generation": {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": 64},
        "smoke_protocol_sha256": LOCKED_SMOKE_PROTOCOL_SHA256,
    },
}
PINNED_CANDIDATE_SHA256 = {MISTRAL_NATIVE_V1_ID: "88a9cfec24af45da3dd4b969e24a3e44e82a6b3a850cb152a76cddbfb135459a"}


def candidate_canonical_bytes(config_id: str, configs=None) -> bytes:
    cfg = (CANDIDATE_CONFIGURATIONS if configs is None else configs)[config_id]
    return json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def candidate_configuration_sha256(config_id: str, configs=None) -> str:
    return hashlib.sha256(candidate_canonical_bytes(config_id, configs)).hexdigest()


def candidate_problems(cfg, *, model_id: str | None = None) -> list[str]:
    """Every way a candidate configuration (or a record's claim of one) can differ from the approved candidate. Empty list == exactly the approved candidate.
    Fail closed: tokenizer mode must be `mistral` (never `hf`), config/load format cannot drift, no reasoning parser, no chat-template override, no hidden kwargs."""
    if not isinstance(cfg, dict):
        return ["candidate configuration is not a mapping"]
    ref = CANDIDATE_CONFIGURATIONS.get(cfg.get("id"))
    if ref is None:
        return [f"unknown candidate configuration id {cfg.get('id')!r}"]
    bad: list[str] = []
    if model_id is not None and (cfg.get("model_id") != ref["model_id"] or model_id != ref["model_id"]):
        bad.append(f"candidate {ref['id']} may only be used with {ref['model_id']} (asked for {model_id!r})")
    args = cfg.get("server_args")
    if not isinstance(args, list) or len(args) % 2 or not all(isinstance(a, str) for a in args):
        return bad + ["server_args is not a flat list of flag/value strings"]
    flags = dict(zip(args[0::2], args[1::2]))
    if flags.get("--tokenizer-mode") != "mistral":
        bad.append(f"--tokenizer-mode must be 'mistral' (found {flags.get('--tokenizer-mode')!r}); an hf substitution is rejected")
    if flags.get("--config-format") != "hf" or flags.get("--load-format") != "safetensors":
        bad.append("--config-format/--load-format drifted from hf/safetensors")
    for f in ref["forbidden_server_flags"]:
        if f in args:
            bad.append(f"{f} may not appear")
    if args != ref["server_args"]:
        bad.append("server_args differ from the approved candidate")
    if cfg.get("reasoning_parser") is not None:
        bad.append("reasoning_parser must be null")
    if cfg.get("chat_template") is not None:
        bad.append("a chat-template override is not allowed")
    if cfg.get("chat_template_kwargs") is not None:
        bad.append("chat_template_kwargs must be null (no hidden kwargs)")
    for key in ("revision", "precision", "quantization", "generation", "smoke_protocol_sha256", "status"):
        if cfg.get(key) != ref[key]:
            bad.append(f"{key} differs from the approved candidate")
    if set(cfg) != set(ref):
        bad.append(f"unexpected/missing fields {sorted(set(cfg) ^ set(ref))}")
    return bad


def candidate_configuration(config_id: str, model_id: str) -> dict:
    """The approved candidate for exactly this model, or ValueError (any other model / unknown id is refused)."""
    ref = CANDIDATE_CONFIGURATIONS.get(config_id)
    if ref is None:
        raise ValueError(f"unknown candidate configuration id {config_id!r}")
    if model_id != ref["model_id"]:
        raise ValueError(f"candidate {config_id} is restricted to {ref['model_id']}, not {model_id!r}")
    return copy.deepcopy(ref)


def candidate_server_args(config_id: str, model_id: str) -> list[str]:
    return list(candidate_configuration(config_id, model_id)["server_args"])


def verify_candidate_integrity(configs=None) -> None:
    for cid, want in PINNED_CANDIDATE_SHA256.items():
        cfgs = CANDIDATE_CONFIGURATIONS if configs is None else configs
        if cid not in cfgs or candidate_configuration_sha256(cid, cfgs) != want:
            raise RuntimeError(f"candidate runtime configuration drift: {cid} fingerprint differs from its pinned sha256")
        problems = candidate_problems(cfgs[cid], model_id=cfgs[cid]["model_id"])
        if problems:
            raise RuntimeError(f"candidate runtime configuration {cid} violates its own invariants: {problems}")


verify_candidate_integrity()

