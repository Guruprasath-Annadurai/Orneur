"""Four-arm research-comparison definitions and the FAIL-CLOSED validator that gates every comparison.

SYNTHETIC / NOT EVIDENCE OF MODEL CAPABILITY. This module hashes and compares configuration only; it loads no model and contacts nothing.

Arm ids reuse the existing evalinfra arm vocabulary (orca.evalinfra.stats_paired.ARMS):
  B0  arm 1  base model alone (vendor template, no scaffolding)
  B1  arm 2  base model + a REGISTERED, budget-matched standardized prompt
  B2  arm 3  base model + the ORNEUR system
  T2  arm 4  FUTURE tuned model + the IDENTICAL ORNEUR system      (primary comparison: T2 vs B2)

A comparison is accepted only if ALL of the following hold; otherwise `require_valid` raises ArmRefusal listing every problem (nothing is partially accepted):
  * exactly the four arms are present, each with the exact key set (a missing / extra / duplicated arm refuses);
  * B2 and T2 carry byte-identical ORNEUR system blocks (prompts, retrieval config, tool set, decoding, budgets, code SHA) => equal `system_config_hash`,
    and their whole run configuration (scaffold, decoding, budgets, system) is identical once the model identity is removed: they differ ONLY in model identity;
  * T2's model is tuned, derived from exactly B2's base model, and is a different model identity from B2's; B0/B1/B2 use the same base model;
  * B1's prompt is registered (sha256 pinned in the registry), fits the input budget, and its prompt-engineering effort equals the ORNEUR system's;
  * decoding parameters and inference budgets are equal across all four arms (budget-matched).
"""
from __future__ import annotations

from orca.evalinfra.canon import HEX40, is_hex64, is_int, obj_hash
from orca.evalinfra.config_lock import SCHEMA_VERSION as CONFIG_SCHEMA
from orca.evalinfra.config_lock import validate_config
from orca.evalinfra.errors import EvalInfraError

ARMS_SCHEMA = "orneur-evalinfra-arms/1"
BANNER = "SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY"
ARM_IDS = ("B0", "B1", "B2", "T2")                      # arm 1..4
ARM_NUMBER = {"B0": 1, "B1": 2, "B2": 3, "T2": 4}
SCAFFOLD = {"B0": "vendor_template_only", "B1": "standard_prompt", "B2": "orneur_system", "T2": "orneur_system"}
EFFECTS = (("system_effect", "B2", "B1", "arm 3 - arm 2"),
           ("training_inside_product_effect", "T2", "B2", "arm 4 - arm 3 (PRIMARY)"),
           ("standardized_prompt_effect", "B1", "B0", "arm 2 - arm 1"))
TOP_KEYS = frozenset({"schema_version", "synthetic", "banner", "comparison_id", "code_sha", "tokenizer", "chat_template_sha256", "primary_comparison",
                      "prompt_registry", "arms"})
ARM_KEYS = frozenset({"arm", "model", "base_model", "scaffold", "prompt_id", "decoding", "budgets", "system"})
SYSTEM_KEYS = frozenset({"code_sha", "prompts", "retrieval", "tool_set", "decoding", "budgets", "engineering_iterations"})
RETRIEVAL_KEYS = frozenset({"enabled", "corpus_sha256", "top_k", "rerank"})
BUDGET_KEYS = frozenset({"max_input_tokens", "max_output_tokens", "max_tool_calls", "max_retrieval_calls", "max_wall_clock_s"})
PROMPT_KEYS = frozenset({"sha256", "token_count", "engineering_iterations"})
MODEL_KEYS = frozenset({"id", "revision", "kind"})


class ArmRefusal(EvalInfraError, ValueError):
    """A comparison (or an aggregate) was refused. Fail closed: nothing downstream may run."""


def _tag(problems: list, cond, msg: str) -> None:
    if not cond:
        problems.append(msg)


def _system_problems(s, where: str) -> list:
    p: list = []
    if not isinstance(s, dict) or set(s) != SYSTEM_KEYS:
        return [f"{where}: system keys must be exactly {sorted(SYSTEM_KEYS)}"]
    _tag(p, isinstance(s["code_sha"], str) and bool(HEX40.match(s["code_sha"])), f"{where}: code_sha must be a 40-hex commit")
    pr = s["prompts"]
    _tag(p, isinstance(pr, dict) and bool(pr) and all(isinstance(k, str) and k and is_hex64(v) for k, v in pr.items()), f"{where}: prompts must map names to sha256 hex")
    r = s["retrieval"]
    _tag(p, isinstance(r, dict) and set(r) == RETRIEVAL_KEYS and isinstance(r["enabled"], bool) and is_hex64(r["corpus_sha256"]) and is_int(r["top_k"]) and r["top_k"] >= 0
         and isinstance(r["rerank"], bool), f"{where}: retrieval keys/types")
    t = s["tool_set"]
    _tag(p, isinstance(t, list) and all(isinstance(x, str) and x for x in t) and t == sorted(set(t)), f"{where}: tool_set must be a sorted list of unique tool ids")
    p += _budget_problems(s["budgets"], f"{where}.budgets")
    p += _decoding_problems(s["decoding"], f"{where}.decoding")
    _tag(p, is_int(s["engineering_iterations"]) and s["engineering_iterations"] >= 0, f"{where}: engineering_iterations must be a non-negative integer")
    return p


def _budget_problems(b, where: str) -> list:
    if not isinstance(b, dict) or set(b) != BUDGET_KEYS or not all(is_int(v) and v >= 0 for v in b.values()):
        return [f"{where}: budgets must be exactly {sorted(BUDGET_KEYS)} as non-negative integers"]
    return []


def _decoding_problems(d, where: str) -> list:
    try:                                                    # reuse the locked-config decoding rules verbatim
        validate_config(_probe_config(d))
    except EvalInfraError as e:
        return [f"{where}: {e.code} {e.detail}"]
    return []


def _probe_config(decoding) -> dict:
    h, rev = "0" * 64, "a" * 40
    return {"schema_version": CONFIG_SCHEMA, "arm": "B0", "synthetic": True, "model": {"id": "probe", "revision": rev}, "tokenizer": {"id": "probe", "revision": rev},
            "chat_template_sha256": h, "decoding": decoding, "system_prompt_sha256": h, "tool_rag_kernel_config_sha256": h, "code_sha": rev}


def system_config_hash(arm_entry: dict) -> str:
    """Hash of the ORNEUR system block carried by an arm (prompts, retrieval config, tool set, decoding, budgets, code SHA, engineering effort)."""
    s = arm_entry.get("system") if isinstance(arm_entry, dict) else None
    if not isinstance(s, dict):
        raise ArmRefusal("NO_SYSTEM_BLOCK", "this arm carries no ORNEUR system block")
    return obj_hash(s)


def run_config_without_model(arm_entry: dict) -> str:
    """Hash of EVERYTHING about how an arm runs except which model runs it (arm id and model identity removed)."""
    return obj_hash({k: v for k, v in arm_entry.items() if k not in ("arm", "model", "base_model")})


def problems(defn) -> list:
    """Every reason the comparison must be refused (empty list == acceptable). Never raises."""
    try:
        return _problems(defn)
    except Exception as e:                                  # fail closed on anything unexpected
        return [f"validator error ({type(e).__name__}); refused"]


def _problems(defn) -> list:
    if not isinstance(defn, dict) or set(defn) != TOP_KEYS:
        return [f"top-level keys must be exactly {sorted(TOP_KEYS)}"]
    p: list = []
    _tag(p, defn["schema_version"] == ARMS_SCHEMA, "schema_version")
    _tag(p, defn["synthetic"] is True, "synthetic must be true (this infrastructure runs only against model doubles and synthetic items)")
    _tag(p, defn["banner"] == BANNER, "banner must be the SYNTHETIC / NOT EVIDENCE banner")
    _tag(p, isinstance(defn["comparison_id"], str) and bool(defn["comparison_id"]), "comparison_id")
    _tag(p, isinstance(defn["code_sha"], str) and bool(HEX40.match(defn["code_sha"])), "code_sha must be a 40-hex commit")
    _tag(p, is_hex64(defn["chat_template_sha256"]), "chat_template_sha256")
    _tag(p, defn["primary_comparison"] == {"treatment": "T2", "control": "B2"}, "primary_comparison must be exactly T2 (arm 4) vs B2 (arm 3)")
    tk = defn["tokenizer"]
    _tag(p, isinstance(tk, dict) and set(tk) == {"id", "revision"} and isinstance(tk["id"], str) and tk["id"], "tokenizer must be {id, revision}")
    arms = defn["arms"]
    if not isinstance(arms, list) or not all(isinstance(a, dict) and isinstance(a.get("arm"), str) for a in arms):
        return p + ["arms must be a list of arm objects"]
    ids = [a["arm"] for a in arms]
    missing = [a for a in ARM_IDS if a not in ids]
    extra = [a for a in ids if a not in ARM_IDS]
    dup = sorted({a for a in ids if ids.count(a) > 1})
    _tag(p, not missing, f"MISSING_ARM: {missing} (all four arms are required; a comparison with a missing arm is refused)")
    _tag(p, not extra, f"unknown arm(s) {extra}")
    _tag(p, not dup, f"duplicate arm(s) {dup}")
    if missing or extra or dup:
        return p
    by = {a["arm"]: a for a in arms}
    for a in ARM_IDS:
        e = by[a]
        if set(e) != ARM_KEYS:
            p.append(f"{a}: arm keys must be exactly {sorted(ARM_KEYS)}")
            return p
        m = e["model"]
        _tag(p, isinstance(m, dict) and set(m) == MODEL_KEYS and m["kind"] in ("base", "tuned") and isinstance(m["id"], str) and bool(m["id"])
             and isinstance(m["revision"], str) and bool(HEX40.match(m["revision"]) or is_hex64(m["revision"])), f"{a}: model must be {{id, revision(immutable hex), kind}}")
        _tag(p, e["scaffold"] == SCAFFOLD[a], f"{a}: scaffold must be {SCAFFOLD[a]!r}")
        p += _decoding_problems(e["decoding"], f"{a}.decoding")
        p += _budget_problems(e["budgets"], f"{a}.budgets")
    if p:
        return p
    b0, b1, b2, t2 = (by[a] for a in ARM_IDS)
    # models: the three base arms share one base; T2 is the tuned derivative of exactly that base and is a different identity
    for a in (b0, b1, b2):
        _tag(p, a["model"]["kind"] == "base" and a["base_model"] is None, f"{a['arm']}: must be the base model (kind base, base_model null)")
    _tag(p, b0["model"] == b1["model"] == b2["model"], "B0, B1 and B2 must use the identical base model (id + revision)")
    _tag(p, t2["model"]["kind"] == "tuned", "T2 must be the tuned model (kind tuned)")
    _tag(p, t2["base_model"] == {"id": b2["model"]["id"], "revision": b2["model"]["revision"]}, "T2.base_model must be exactly B2's base model")
    _tag(p, {k: t2["model"][k] for k in ("id", "revision")} != {k: b2["model"][k] for k in ("id", "revision")}, "T2's model identity must differ from B2's")
    # arms 3 and 4: byte-identical system, differing ONLY in model identity
    for a in (b2, t2):
        p += _system_problems(a["system"], f"{a['arm']}.system")
    for a in (b0, b1):
        _tag(p, a["system"] is None, f"{a['arm']}: must not carry an ORNEUR system block")
    if not p:
        _tag(p, system_config_hash(b2) == system_config_hash(t2), "SYSTEM_CONFIG_MISMATCH: B2 and T2 system blocks (prompts / retrieval / tool set / decoding / budgets / code SHA) are not byte-identical")
        _tag(p, run_config_without_model(b2) == run_config_without_model(t2), "B2 and T2 differ in something other than model identity")
        _tag(p, b2["system"]["code_sha"] == defn["code_sha"], "system.code_sha must equal the comparison code_sha")
        _tag(p, b2["system"]["decoding"] == b2["decoding"] and b2["system"]["budgets"] == b2["budgets"], "the system block's decoding/budgets must equal the arm's")
        # budget matching across ALL arms
        for a in (b0, b1, t2):
            _tag(p, a["decoding"] == b2["decoding"], f"{a['arm']}: decoding parameters must equal B2's (budget-matched)")
            _tag(p, a["budgets"] == b2["budgets"], f"{a['arm']}: inference budgets must equal B2's (budget-matched)")
        # arm 2: registered prompt, budget matched
        reg, pid = defn["prompt_registry"], b1["prompt_id"]
        for a in (b0, b2, t2):
            _tag(p, a["prompt_id"] is None, f"{a['arm']}: prompt_id must be null (only arm 2 uses the standardized prompt)")
        if not (isinstance(reg, dict) and isinstance(pid, str) and pid in reg):
            p.append("PROMPT_NOT_REGISTERED: B1's prompt_id is not in the prompt registry")
        else:
            r = reg[pid]
            if not isinstance(r, dict) or set(r) != PROMPT_KEYS or not is_hex64(r["sha256"]) or not is_int(r["token_count"]) or not is_int(r["engineering_iterations"]):
                p.append("PROMPT_REGISTRY_ENTRY: must be exactly {sha256, token_count, engineering_iterations}")
            else:
                _tag(p, r["token_count"] <= b1["budgets"]["max_input_tokens"], "PROMPT_OVER_BUDGET: registered prompt exceeds the input-token budget")
                _tag(p, r["engineering_iterations"] == b2["system"]["engineering_iterations"],
                     "PROMPT_EFFORT_NOT_MATCHED: arm-2 prompt-engineering iterations must equal the ORNEUR system's (equal best-effort budget)")
                _tag(p, r["sha256"] not in b2["system"]["prompts"].values(), "the standardized prompt must be a different artifact from the ORNEUR system prompts")
    return p


def require_valid(defn) -> dict:
    ps = problems(defn)
    if ps:
        raise ArmRefusal("COMPARISON_REFUSED", "; ".join(ps))
    by = {a["arm"]: a for a in defn["arms"]}
    return {"ok": True, "banner": BANNER, "system_config_hash": system_config_hash(by["B2"]), "arm_run_config_hashes": {a: obj_hash(by[a]) for a in ARM_IDS},
            "definition_sha256": obj_hash(defn), "primary_comparison": defn["primary_comparison"]}


def to_lock_config(defn: dict, arm: str) -> dict:
    """The config_lock manifest for one arm, derived mechanically from the (valid) definition so a lock can never silently diverge from it."""
    require_valid(defn)
    e = next(a for a in defn["arms"] if a["arm"] == arm)
    if e["system"] is not None:
        prompt_h = obj_hash(e["system"]["prompts"])
        stack_h = obj_hash({"retrieval": e["system"]["retrieval"], "tool_set": e["system"]["tool_set"], "budgets": e["system"]["budgets"],
                            "engineering_iterations": e["system"]["engineering_iterations"]})
    elif arm == "B1":
        prompt_h = defn["prompt_registry"][e["prompt_id"]]["sha256"]
        stack_h = obj_hash({"scaffold": e["scaffold"], "budgets": e["budgets"]})
    else:
        prompt_h = obj_hash({"scaffold": e["scaffold"]})
        stack_h = obj_hash({"scaffold": e["scaffold"], "budgets": e["budgets"]})
    return validate_config({"schema_version": CONFIG_SCHEMA, "arm": arm, "synthetic": True, "model": {"id": e["model"]["id"], "revision": e["model"]["revision"]},
                            "tokenizer": defn["tokenizer"], "chat_template_sha256": defn["chat_template_sha256"], "decoding": e["decoding"],
                            "system_prompt_sha256": prompt_h, "tool_rag_kernel_config_sha256": stack_h, "code_sha": defn["code_sha"]})


# ------------------------------------------------------------------------------------------------------------------------------ synthetic example
def make_example_definitions(**over) -> dict:
    """A VALID synthetic definition (placeholder ids/hashes derived from labels; no real model is named or selected)."""
    import copy
    import hashlib
    h = lambda s: hashlib.sha256(s.encode()).hexdigest()    # noqa: E731
    h1 = lambda s: hashlib.sha1(s.encode()).hexdigest()     # noqa: E731
    dec = {"do_sample": False, "temperature": 0, "top_p": 1.0, "top_k": 0, "max_new_tokens": 64}
    bud = {"max_input_tokens": 2048, "max_output_tokens": 64, "max_tool_calls": 4, "max_retrieval_calls": 2, "max_wall_clock_s": 30}
    code = h1("synthetic-orneur-code")
    system = {"code_sha": code, "prompts": {"system": h("synthetic-orneur-system-prompt"), "planner": h("synthetic-orneur-planner-prompt")},
              "retrieval": {"enabled": True, "corpus_sha256": h("synthetic-corpus"), "top_k": 4, "rerank": False}, "tool_set": ["calculator", "search_stub"],
              "decoding": dec, "budgets": bud, "engineering_iterations": 5}
    base = {"id": "synthetic/base-double", "revision": h1("rev-base-double"), "kind": "base"}
    tuned = {"id": "synthetic/tuned-double", "revision": h1("rev-tuned-double"), "kind": "tuned"}

    def arm(a, model, base_model, pid, sysb):
        return {"arm": a, "model": dict(model), "base_model": base_model, "scaffold": SCAFFOLD[a], "prompt_id": pid, "decoding": dict(dec), "budgets": dict(bud),
                "system": sysb}
    d = {"schema_version": ARMS_SCHEMA, "synthetic": True, "banner": BANNER, "comparison_id": "synthetic-four-arm-demo", "code_sha": code,
         "tokenizer": {"id": "synthetic/tokenizer", "revision": h1("tok")}, "chat_template_sha256": h("template"),
         "primary_comparison": {"treatment": "T2", "control": "B2"},
         "prompt_registry": {"std-prompt-v1": {"sha256": h("synthetic-standard-prompt"), "token_count": 220, "engineering_iterations": 5}},
         "arms": [arm("B0", base, None, None, None), arm("B1", base, None, "std-prompt-v1", None), arm("B2", base, None, None, copy.deepcopy(system)),
                  arm("T2", tuned, {"id": base["id"], "revision": base["revision"]}, None, copy.deepcopy(system))]}
    d.update(over)
    return d
