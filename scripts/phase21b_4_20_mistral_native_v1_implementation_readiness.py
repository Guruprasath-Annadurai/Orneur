"""
Phase 21B.4.20 -- CPU-ONLY implementation-readiness evidence for the CANDIDATE runtime configuration `mistral_nemo_native_v1`.

No Modal, no GPU, no provider call, no model weights, no generation. It proves, from the real code paths, that:
  * the candidate is a separate, fingerprinted, model-restricted configuration and the canonical Mistral configuration is still `--tokenizer-mode hf`;
  * the runner's ONE assembly path (`serving_config(..., candidate=...)`) yields exactly the candidate's server flags and the request builder sends no
    chat_template / chat_template_kwargs / reasoning field; generation parameters and the locked protocol are unchanged;
  * the candidate's tokenizer mode maps, through the REAL vLLM v0.29.0 `resolve_tokenizer_args` and registries, to MistralTokenizer + MistralRenderer;
  * the audited native-readiness artifact is hash-verified against an independently pinned constant BEFORE the candidate can be called ready, and the source/snapshot
    provenance verification of that analysis is re-run fail-closed;
  * a CPU-constructed (SYNTHETIC, clearly labelled -- not runtime evidence) container proof is accepted by the REAL `container_proof_problems` and every drifted variant
    (hf fallback, wrong id/fingerprint, kwargs, reasoning parser, chat-template flag, protocol/prompt/model/revision drift) is rejected.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from orca.eval import control_runtime_configuration as rc  # noqa: E402
from orca.eval import locked_smoke_protocol as lp  # noqa: E402

EVIDENCE = REPO_ROOT / "docs/orneur/phase-21/evidence"
OUT = EVIDENCE / "GENESIS_MISTRAL_NEMO_NATIVE_V1_IMPLEMENTATION_READINESS_2026-09-26.json"
READINESS = EVIDENCE / "GENESIS_MISTRAL_NEMO_NATIVE_TOKENIZER_MODE_READINESS_2026-09-26.json"
# Independent pin of the audited native-readiness artifact (sha256 of the committed file). Any change to that artifact must be re-audited and re-pinned here.
PINNED_NATIVE_READINESS_SHA256 = "4befb62b26b34b998faf39c03525146d0ce80725c165f038182b85077829b400"
HARNESS = REPO_ROOT / "scripts/phase21b_4_20_modal_h100_control.py"
RUNNER = REPO_ROOT / "scripts/phase21b_4_20_lightning_runner.py"
CID = rc.MISTRAL_NATIVE_V1_ID
MODEL = "mistralai/Mistral-Nemo-Instruct-2407"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fn_source(path: Path, name: str) -> str:
    text = path.read_text()
    node = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name][-1]
    return ast.get_source_segment(text, node)


def server_argv_from_real_runner_source(cfg: dict, snap: str) -> list[str]:
    """Evaluate the REAL argv list expression assigned to `cmd` inside runner.serve_and_smoke (extracted by ast, not re-written)."""
    text = RUNNER.read_text()
    fn = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "serve_and_smoke"][-1]
    assign = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "cmd" for t in n.targets))
    return eval(compile(ast.Expression(assign.value), "runner_serve_and_smoke_cmd", "eval"), {"sys": sys, "cfg": cfg, "snap": snap})


def main() -> int:
    runner = load(RUNNER, "p4420_runner_impl")
    readiness_mod = load(REPO_ROOT / "scripts/phase21b_4_20_mistral_native_tokenizer_readiness.py", "p4420_native_readiness_impl")
    # ── 10/11: audited native-readiness artifact hash-verified FIRST; provenance verification re-run fail-closed ──────────────────────────────────────
    raw = READINESS.read_bytes()
    if sha(raw) != PINNED_NATIVE_READINESS_SHA256:
        print("REFUSING: the native-readiness artifact differs from its independently pinned sha256")
        return 2
    rd = json.loads(raw)
    if rd["readiness_verdict"] != "NATIVE_MISTRAL_MODE_CPU_READY" or rd["source_integrity_verified"] is not True or rd["snapshot_integrity_verified"] is not True or rd["config_changed"] is not False:
        print("REFUSING: the native-readiness artifact is not a verified CPU-READY result")
        return 2
    src_ok, snap_ok = readiness_mod.verify_inputs()                                   # SystemExit on any missing/mismatched input: fail closed
    if src_ok != rd["verified_source_sha256"] or snap_ok != rd["verified_snapshot_sha256"]:
        print("REFUSING: re-verified inputs differ from those recorded in the readiness artifact")
        return 2
    # ── 1-3: candidate identity / fingerprint ─────────────────────────────────────────────────────────────────────────────────────────────────────
    cand = rc.candidate_configuration(CID, MODEL)
    problems = rc.candidate_problems(cand, model_id=MODEL)
    cand_sha = rc.candidate_configuration_sha256(CID)
    # ── 3/4/5: server argv through the runner's ONE assembly path and its real argv builder ─────────────────────────────────────────────────────────
    cfg = runner.serving_config("mistral_nemo", 420, CID)
    argv = ["<python interpreter>"] + server_argv_from_real_runner_source(cfg, "<local pinned-revision snapshot dir>")[1:]      # host interpreter path is not evidence
    canonical_cfg = runner.serving_config("mistral_nemo", 420)
    canonical_argv = ["<python interpreter>"] + server_argv_from_real_runner_source(canonical_cfg, "<local pinned-revision snapshot dir>")[1:]
    flags = dict(zip(argv[-6::2], argv[-5::2]))          # the candidate's flag tail of the real argv
    # ── 6-8: request builder + generation + protocol ──────────────────────────────────────────────────────────────────────────────────────────────
    gen = {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": cfg["smoke_max_tokens"]}
    payloads = {s["smoke_id"]: runner.build_chat_payload(cfg, s, gen) for s in cfg["smokes"]}
    forbidden_request_keys = ("chat_template", "chat_template_kwargs", "reasoning_effort", "reasoning", "reasoning_parser", "thinking", "enable_thinking", "documents", "tools")
    request_checks = {sid: {"keys": sorted(p), "has_forbidden_request_field": any(k in p for k in forbidden_request_keys),
                            "generation_fields": {k: p[k] for k in ("temperature", "top_p", "seed", "max_tokens")},
                            "content_sha256": sha(p["messages"][0]["content"].encode()), "content_is_canonical": p["messages"] == lp.messages(sid)} for sid, p in payloads.items()}
    # ── 7: mode -> tokenizer/renderer through the REAL vLLM resolve_tokenizer_args and registries ───────────────────────────────────────────────────
    tok_text, rend_text = readiness_mod.src("vllm/tokenizers/registry.py"), readiness_mod.src("vllm/renderers/registry.py")
    tokenizers = readiness_mod.dict_literal(ast.parse(tok_text), "_VLLM_TOKENIZERS")
    renderers = readiness_mod.dict_literal(ast.parse(rend_text), "_VLLM_RENDERERS")
    ns = {"envs": type("E", (), {"VLLM_USE_MODELSCOPE": False})(), "assert_never": lambda x: None, "Path": Path,
          "is_mistral_model_repo": lambda **k: (_ for _ in ()).throw(AssertionError("auto branch not used")), "any_pattern_in_repo_files": lambda **k: (_ for _ in ()).throw(AssertionError("auto branch not used"))}
    exec(compile(readiness_mod.func_source(tok_text, "resolve_tokenizer_args"), "vllm_tokenizers_registry_v0.29.0", "exec"), ns)
    cand_mode = flags["--tokenizer-mode"]
    resolved_mode = ns["resolve_tokenizer_args"]("<pinned snapshot>", tokenizer_mode=cand_mode, runner_type="generate")[0]
    canonical_mode = ns["resolve_tokenizer_args"]("<pinned snapshot>", tokenizer_mode="hf", runner_type="generate")[0]
    mapping = {"candidate_tokenizer_mode": resolved_mode, "tokenizer": list(tokenizers[resolved_mode]), "renderer": list(renderers[resolved_mode]),
               "canonical_tokenizer_mode": canonical_mode, "canonical_tokenizer": list(tokenizers[canonical_mode]), "canonical_renderer": list(renderers[canonical_mode])}
    # ── 9: container-proof contract, exercised with the REAL container_proof_problems (SYNTHETIC proofs; not runtime evidence) ──────────────────────
    hns = {"runtime_config": rc, "locked_protocol": lp, "json": json}
    exec(compile(fn_source(HARNESS, "_same_json"), "harness_same_json", "exec"), hns)
    exec(compile(fn_source(HARNESS, "container_proof_problems"), "harness_container_proof_problems", "exec"), hns)
    check = hns["container_proof_problems"]
    good = {"runtime_configuration_id": CID, "runtime_configuration_id_applied": CID, "runtime_configuration_sha256": cand_sha, "runtime_policy_sha256": rc.PINNED_RUNTIME_POLICY_SHA256,
            "chat_template_kwargs_sent": {sid: None for sid in lp.smoke_ids()}, "smoke_protocol_sha256": lp.protocol_sha256(),
            "prompt_sha256_sent": {sid: lp.prompt_sha256(sid) for sid in lp.smoke_ids()}, "model_id": MODEL, "served_model_id": MODEL, "revision": cand["revision"],
            "precision": "bfloat16", "quantization": None, "reasoning_parser": None, "tokenizer_mode": "mistral", "config_format": "hf", "load_format": "safetensors", "chat_template_flag": None}

    def problems_for(**over):
        proof = copy.deepcopy(good)
        proof.update(over)
        return check({"runtime_configuration_proof": proof}, MODEL, cand["revision"], candidate_id=CID)

    drift = {"tokenizer_mode_hf": problems_for(tokenizer_mode="hf"), "config_format_drift": problems_for(config_format="mistral"), "load_format_drift": problems_for(load_format="auto"),
             "id_applied_canonical_none": problems_for(runtime_configuration_id_applied=None), "wrong_fingerprint": problems_for(runtime_configuration_sha256="0" * 64),
             "kwargs_sent": problems_for(chat_template_kwargs_sent={sid: {"enable_thinking": False} for sid in lp.smoke_ids()}), "reasoning_parser": problems_for(reasoning_parser="qwen3"),
             "chat_template_flag": problems_for(chat_template_flag="x.jinja"), "protocol_sha": problems_for(smoke_protocol_sha256="0" * 64),
             "prompt_hashes": problems_for(prompt_sha256_sent={"A": "0" * 64, "B": "0" * 64, "C": "0" * 64}), "model": problems_for(served_model_id="other/model"),
             "revision": problems_for(revision="0" * 40), "precision": problems_for(precision="float16"), "quantization": problems_for(quantization="fp8")}
    proof_contract = {"synthetic_proof_accepted_problems": problems_for(), "every_drift_rejected": all(bool(v) for v in drift.values()), "drift_problems": drift,
                      "no_silent_fallback_to_hf": bool(drift["tokenizer_mode_hf"]),
                      "note": "SYNTHETIC CPU-constructed proofs exercising the real validator function; they are NOT runtime evidence and prove nothing about GPU serving"}
    ok = bool(not problems and cand_sha == rc.PINNED_CANDIDATE_SHA256[CID] and argv[-6:] == cand["server_args"] and "--reasoning-parser" not in argv and "--chat-template" not in argv
              and canonical_argv[-6:] == ["--tokenizer-mode", "hf", "--config-format", "hf", "--load-format", "safetensors"] and list(mapping["tokenizer"]) == ["mistral", "MistralTokenizer"]
              and list(mapping["renderer"]) == ["mistral", "MistralRenderer"] and not any(v["has_forbidden_request_field"] for v in request_checks.values())
              and all(v["content_is_canonical"] for v in request_checks.values()) and proof_contract["every_drift_rejected"] and not proof_contract["synthetic_proof_accepted_problems"]
              and lp.protocol_sha256() == rc.LOCKED_SMOKE_PROTOCOL_SHA256 and cfg["smoke_max_tokens"] == 64)
    rendered = rd["B3_native_chat_rendering_locked_smokes"]["smokes"]
    art = {"evidence_type": "GENESIS_MISTRAL_NEMO_NATIVE_V1_IMPLEMENTATION_READINESS", "phase": "21B.4.20", "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "candidate_configuration_id": CID, "candidate_status": "CANDIDATE (not canonical; not promoted; nothing selects it by default)",
           "candidate_configuration": cand, "candidate_configuration_sha256": cand_sha, "pinned_candidate_sha256": rc.PINNED_CANDIDATE_SHA256[CID],
           "candidate_canonical_json_sha256": sha(rc.candidate_canonical_bytes(CID)), "candidate_invariant_problems": problems,
           "exact_candidate_server_argv_sanitized": argv, "candidate_flags_tail": argv[-6:], "argv_contains": {"--tokenizer-mode mistral": "--tokenizer-mode" in argv and argv[argv.index("--tokenizer-mode") + 1] == "mistral",
                                                                                                             "--config-format hf": argv[argv.index("--config-format") + 1] == "hf",
                                                                                                             "--load-format safetensors": argv[argv.index("--load-format") + 1] == "safetensors"},
           "argv_contains_no": {"--reasoning-parser": "--reasoning-parser" not in argv, "--chat-template": "--chat-template" not in argv},
           "canonical_mistral_server_argv_tail_UNCHANGED": canonical_argv[-6:], "canonical_mistral_runtime_configuration_UNCHANGED": rc.configuration_for_model(MODEL),
           "request_configuration": {"per_smoke": request_checks, "generation": gen, "no_chat_template_no_kwargs_no_reasoning": not any(v["has_forbidden_request_field"] for v in request_checks.values())},
           "locked_smoke_protocol_sha256": lp.protocol_sha256(), "locked_protocol_unchanged": lp.protocol_sha256() == rc.LOCKED_SMOKE_PROTOCOL_SHA256,
           "model_id": MODEL, "revision": cand["revision"], "precision": "bfloat16", "quantization": None,
           "native_tokenizer_renderer_mapping_from_real_vllm_source": mapping,
           "native_readiness_artifact": {"path": READINESS.name, "sha256": sha(raw), "pinned_sha256": PINNED_NATIVE_READINESS_SHA256, "verified": True, "verdict": rd["readiness_verdict"],
                                         "source_integrity_reverified_fail_closed": True, "snapshot_integrity_reverified_fail_closed": True},
           "cpu_abc_preprocessing_consumed_from_the_hash_verified_readiness_artifact": {sid: {"ok": v["ok"], "chat_template_resolution_error": v["chat_template_resolution_error"], "token_ids_sha256": v["token_ids_sha256"]}
                                                                                       for sid, v in rendered.items()},
           "container_proof_contract": proof_contract,
           "readiness_scope": "CPU-side configuration formalization only; NOT a GPU authorization, NOT a runtime qualification, NOT a promotion. Engine init/weight loading under tokenizer-mode mistral, generation and EOS behaviour are not covered.",
           "candidate_implementation_ready_cpu_side": ok, "canonical_mistral_config_still_hf": canonical_argv[-6:][1] == "hf",
           "no_gpu_used": True, "no_modal_used": True, "no_provider_call": True, "no_model_weights_loaded": True, "no_generation": True, "generated_output_executed": False,
           "status_unchanged": {"attempt_outcome": "UNATTRIBUTED_REQUEST_REJECTION", "technical_serving_status": "NOT_PROVEN", "runtime_qualification_status": "NOT_COMPLETED", "capability_status": "UNPROVEN"}}
    OUT.write_text(json.dumps(art, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"artifact": OUT.name, "ready": ok, "sha": cand_sha, "mapping": mapping, "drift_all_rejected": proof_contract["every_drift_rejected"]}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
