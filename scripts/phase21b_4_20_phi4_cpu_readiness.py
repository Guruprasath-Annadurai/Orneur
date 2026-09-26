"""
Phase 21B.4.20 -- CPU-ONLY runtime-readiness audit of the exact locked Phi-4 control (microsoft/phi-4 @ 2db69c1c3e91a05d2c64a3185acfbaf36f744e25).

No GPU, no Modal, no model weights, no generation. Run with an interpreter holding the container's exact transformers 5.16.1 / tokenizers 0.23.2 / huggingface_hub 1.30.0.
Everything is read from the ACTUAL source of truth (nothing assumed):
  1. canonical Phi-4 serving configuration: the runner's `serving_config("phi4")` and its real server-argv expression (extracted by ast from serve_and_smoke);
  2. exact pinned snapshot: every non-weight file needed for tokenizer construction / chat-template resolution / config loading is verified fail-closed by pinned SHA256 constants, by the
     size recorded in the container's persisted pre-cache manifest, and against the Hugging Face tree of the EXACT revision (git blob sha1 + size). A mutable ref or any mismatch refuses;
  3. CPU tokenizer/chat preprocessing of the locked A/B/C messages through transformers AutoTokenizer AND through the REAL vLLM v0.29.0 functions (`resolve_tokenizer_args` incl. its 'auto'
     branch and repo_utils helpers, `resolve_chat_template`, `safe_apply_chat_template`), extracted by ast from the pinned sources with explicitly listed stubs; deterministic (rendered twice);
  4. the exact request payloads through the REAL request builder; 5. the future server argv; 6. the container-proof contract through the REAL `container_proof_problems`.
Nothing here is runtime or capability qualification. Generated/decoded text is data and is never executed.
"""
from __future__ import annotations

import ast
import copy
import fnmatch
import functools
import hashlib
import importlib.metadata as md
import importlib.util
import json
import re
import sys
import types
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

warnings.simplefilter("ignore")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from orca.eval import control_runtime_configuration as rc  # noqa: E402
from orca.eval import locked_smoke_protocol as lp  # noqa: E402

EVIDENCE = REPO_ROOT / "docs/orneur/phase-21/evidence"
OUT = EVIDENCE / "GENESIS_PHI4_RUNTIME_READINESS_2026-09-26.json"
RUNNER = REPO_ROOT / "scripts/phase21b_4_20_lightning_runner.py"
HARNESS = REPO_ROOT / "scripts/phase21b_4_20_modal_h100_control.py"
PRECACHE = EVIDENCE / "GENESIS_CONTROL_PHI4_MODAL_PRECACHE_MANIFEST_2026-09-24.json"
PHI_RECORD = EVIDENCE / "GENESIS_CONTROL_PHI4_RUNTIME_QUALIFICATION_2026-09-24.json"
MODEL = "microsoft/phi-4"
REV = "2db69c1c3e91a05d2c64a3185acfbaf36f744e25"
EXPECTED_WEIGHT_BYTES = 29319042992
SNAP = Path("/tmp/p4420/phi4/snap")
SRC = Path("/tmp/p4420/mistral_src")
CONTAINER_VERSIONS = {"transformers": "5.16.1", "tokenizers": "0.23.2", "huggingface_hub": "1.30.0"}
HF_TREE = f"https://huggingface.co/api/models/{MODEL}/tree/{REV}"

# Independent pins (NOT read from any artifact): SHA256 of every non-weight file this analysis uses.
PHI_SNAPSHOT_SHA256 = {
    "config.json": "07eedad2c48798b6e3728e4a1b75e0e092019a375ba725a40e40c78d13664045",
    "generation_config.json": "6acf48d95f0a1deb97acf54d946636243e299bf315b068efd719708ceea5741d",
    "tokenizer_config.json": "2b707658c7c2b41580155a45503d7d3b42dc2f530bef678f67a39bf5d10b0510",
    "tokenizer.json": "9f38d05d9d25756bb2f181ab5a0cebcd59e638df10336fc7ed1010f7296d0298",
    "vocab.json": "741943243bd0035a8082ef0ccc09ef62e7ce7ec2f2f053aeedd808dba1c2ffc5",
    "merges.txt": "b6fe424e334903f7fb84d3a106d9730455f4744b9fe3c21ee136d97a00e72502",
    "special_tokens_map.json": "b0e1617caf68ebcd6af7426d6afdbe62a3fb8fbe56ea84782a88fc8cbd464b1d",
    "added_tokens.json": "e2c8dff553db16508eb2bbaf1de51c13256727ddde88b5c65e1e75c224e277f0",
    "model.safetensors.index.json": "51f3004b8d5b478473f26eb8cb5ac7e5aacc39938ad365f0c8933b18dfa9a158",
}
# vLLM v0.29.0 (commit 98dff2a8...) sources: the audited set used by the native-readiness analysis plus the repo_utils helpers used by tokenizer-mode auto-resolution.
EXTRA_SOURCE_SHA256 = {"vllm/transformers_utils/repo_utils.py": "e49f14267604cf7e5a9b95e09c7be2801cf4364e06ea9b3fe7226d6654731793"}
EXTRA_SOURCE_PATHS = {"vllm/transformers_utils/repo_utils.py": Path("/tmp/p4420/phi4/vllm__transformers_utils__repo_utils.py")}


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


def _assign_in_function(path: Path, fn_name: str, target: str):
    text = path.read_text()
    fn = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == fn_name][-1]
    node = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == target for t in n.targets))
    return ast.Expression(node.value)


def verify_inputs(readiness_mod) -> dict:
    """Fail closed BEFORE analysis. Returns the verified hash maps."""
    if not re.fullmatch(r"[0-9a-f]{40}", REV) or REV == "main":
        raise SystemExit("REFUSING: the revision must be the exact 40-hex pin, never a mutable ref")
    runner = load(RUNNER, "p4420_runner_phi")
    lock = runner.LOCKED["phi4"]
    if lock["model_id"] != MODEL or lock["revision"] != REV or lock["expected_weight_bytes"] != EXPECTED_WEIGHT_BYTES:
        raise SystemExit("REFUSING: the runner's locked Phi-4 identity differs from the pinned identity")
    manifest = json.loads(PRECACHE.read_text())["manifest"]
    if manifest["revision"] != REV or manifest["model_id"] != MODEL or manifest["weight_bytes_observed"] != EXPECTED_WEIGHT_BYTES or manifest["staging_verified"] is not True:
        raise SystemExit("REFUSING: the persisted pre-cache manifest does not match the pinned identity")
    manifest_sizes = {f["filename"]: f["bytes"] for f in manifest["files"]}
    try:
        tree = json.loads(urllib.request.urlopen(HF_TREE, timeout=60).read())                    # public read of the EXACT revision's file tree
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"REFUSING: cannot verify against the Hugging Face tree of the exact revision ({type(e).__name__})")
    oids = {e["path"]: (e.get("oid"), e.get("size")) for e in tree if e.get("type") == "file"}
    snap_ok: dict[str, dict] = {}
    for f, want in PHI_SNAPSHOT_SHA256.items():
        path = SNAP / f
        if not path.is_file():
            raise SystemExit(f"REFUSING: pinned snapshot file missing: {f}")
        b = path.read_bytes()
        if sha(b) != want:
            raise SystemExit(f"REFUSING: {f} sha256 {sha(b)} != pinned {want}")
        if manifest_sizes.get(f) != len(b):
            raise SystemExit(f"REFUSING: {f} size differs from the container's persisted manifest")
        blob = hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()
        if f not in oids or oids[f] != (blob, len(b)):
            raise SystemExit(f"REFUSING: {f} does not match the Hugging Face tree of the exact revision (git blob sha1 / size)")
        snap_ok[f] = {"sha256": want, "bytes": len(b), "git_blob_sha1": blob, "matches_container_manifest_size": True, "matches_hf_tree_at_exact_revision": True}
    src_ok: dict[str, str] = {}
    for name, want in {**readiness_mod.EXPECTED_SOURCE_SHA256, **EXTRA_SOURCE_SHA256}.items():
        path = {**readiness_mod.SOURCE_LOCAL_PATHS, **EXTRA_SOURCE_PATHS}[name]
        if not path.is_file():
            raise SystemExit(f"REFUSING: vLLM source file missing: {name}")
        if sha(path.read_bytes()) != want:
            raise SystemExit(f"REFUSING: vLLM source {name} differs from its pinned sha256")
        src_ok[name] = want
    return {"snapshot": snap_ok, "sources": src_ok, "hf_tree_files": sorted(oids), "hf_tree_has_consolidated_or_tekken": any(fnmatch.fnmatch(p, "consolidated*.safetensors") or p == "tekken.json" or fnmatch.fnmatch(p, "tokenizer.model.v*") for p in oids)}


def main() -> int:
    versions = {p: md.version(p) for p in ("transformers", "tokenizers", "huggingface_hub", "jinja2")}
    for k, v in CONTAINER_VERSIONS.items():
        if versions[k] != v:
            print(f"REFUSING: {k} {versions[k]} != container {v}")
            return 2
    readiness_mod = load(REPO_ROOT / "scripts/phase21b_4_20_mistral_native_tokenizer_readiness.py", "p4420_native_readiness_phi")
    verified = verify_inputs(readiness_mod)
    runner = load(RUNNER, "p4420_runner_phi2")
    v2 = load(REPO_ROOT / "scripts/phase21b_4_20_mistral_chat_template_analysis_v2.py", "p4420_v2_phi")
    # ── 1: canonical configuration from the real source of truth ───────────────────────────────────────────────────────────────────────────────
    cfg = runner.serving_config("phi4", 420)
    gen_expr = _assign_in_function(RUNNER, "serve_and_smoke", "gen_cfg")
    gen = eval(compile(gen_expr, "runner_gen_cfg", "eval"), {"cfg": cfg})
    argv = ["<python interpreter>"] + eval(compile(_assign_in_function(RUNNER, "serve_and_smoke", "cmd"), "runner_cmd", "eval"), {"sys": sys, "cfg": cfg, "snap": "<local pinned-revision snapshot dir>"})[1:]
    flags = {a: argv[i + 1] for i, a in enumerate(argv) if a.startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--")}
    canonical = {"model_id": cfg["model_id"], "revision": cfg["revision"], "extra_args": cfg["extra_args"], "runtime_configuration": cfg["runtime_configuration"],
                 "chat_template_kwargs": (cfg["runtime_configuration"] or {}).get("chat_template_kwargs"), "max_model_len": cfg["max_model_len"], "gpu_memory_utilization": cfg["gpu_memory_utilization"],
                 "smoke_max_tokens": cfg["smoke_max_tokens"], "sampling_generation_config": gen, "tokenizer_mode": flags.get("--tokenizer-mode"), "config_format": flags.get("--config-format"),
                 "load_format": flags.get("--load-format"), "reasoning_parser": flags.get("--reasoning-parser"), "phi_specific_server_flags": cfg["extra_args"],
                 "vllm_defaults_relied_on": "no --tokenizer-mode (vLLM default 'auto'), no --config-format/--load-format (defaults), no --generation-config override (vLLM default 'auto' reads the pinned generation_config.json, which has no sampling defaults)",
                 "source_of_truth": "scripts/phase21b_4_20_lightning_runner.py serving_config('phi4') + the argv expression of serve_and_smoke (ast-extracted)"}
    argv_checks = {"model_flag_is_local_pinned_snapshot_placeholder": argv[argv.index("--model") + 1] == "<local pinned-revision snapshot dir>", "served_model_name": flags["--served-model-name"] == MODEL,
                   "dtype_bfloat16": flags["--dtype"] == "bfloat16", "no_quantization_flag": "--quantization" not in argv, "no_reasoning_parser": "--reasoning-parser" not in argv,
                   "no_chat_template_flag": "--chat-template" not in argv, "no_tokenizer_mode_flag": "--tokenizer-mode" not in argv, "no_config_or_load_format_flag": "--config-format" not in argv and "--load-format" not in argv,
                   "no_extra_args_beyond_the_common_argv": cfg["extra_args"] == [] and argv[-2:] == ["--seed", "0"], "max_model_len_4096": flags["--max-model-len"] == "4096",
                   "identity_equals_locked_pin": cfg["model_id"] == MODEL and cfg["revision"] == REV and runner.LOCKED["phi4"]["expected_weight_bytes"] == EXPECTED_WEIGHT_BYTES}
    # ── 3: tokenizer + chat preprocessing (transformers, exact versions) ───────────────────────────────────────────────────────────────────────
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(str(SNAP))
    tcfg = json.loads((SNAP / "tokenizer_config.json").read_text())
    ct = tcfg.get("chat_template")
    tokenizer = {"tokenizer_class": f"{type(tok).__module__}.{type(tok).__name__}", "declared_tokenizer_class": tcfg.get("tokenizer_class"), "is_fast": getattr(tok, "is_fast", None),
                 "name_or_path": tok.name_or_path, "chat_template_source": "tokenizer_config.json chat_template @ the pinned revision", "chat_template_present": isinstance(ct, str),
                 "chat_template_utf8_bytes": len(ct.encode()) if isinstance(ct, str) else None, "chat_template_sha256": sha(ct.encode()) if isinstance(ct, str) else None,
                 "bos": {"token": tok.bos_token, "id": tok.bos_token_id}, "eos": {"token": tok.eos_token, "id": tok.eos_token_id}, "pad": {"token": tok.pad_token, "id": tok.pad_token_id},
                 "generation_config_eos_token_ids": json.loads((SNAP / "generation_config.json").read_text()).get("eos_token_id"), "vocab_size": len(tok)}
    try:
        r = tok.get_chat_template(None, tools=None)
        tokenizer["get_chat_template"] = {"ok": True, "sha256": sha(r.encode())}
    except Exception as e:  # noqa: BLE001
        tokenizer["get_chat_template"] = {"ok": False, "exception": f"{type(e).__name__}: {str(e)[:250]}"}
    pre: dict[str, Any] = {}
    for sid in lp.smoke_ids():
        try:
            rendered = [tok.apply_chat_template(lp.messages(sid), tokenize=False, add_generation_prompt=True) for _ in range(2)]
            ids = [tok(r, add_special_tokens=False)["input_ids"] for r in rendered]
            decoded = tok.decode(ids[0], skip_special_tokens=False)
            pre[sid] = {"ok": True, "deterministic": rendered[0] == rendered[1] and ids[0] == ids[1], "rendered": rendered[0], "rendered_sha256": sha(rendered[0].encode()), "token_count": len(ids[0]),
                        "token_ids": ids[0], "token_ids_sha256": sha(json.dumps(ids[0]).encode()), "decoded_equals_rendered": decoded == rendered[0], "chat_template_exception": None}
        except Exception as e:  # noqa: BLE001
            pre[sid] = {"ok": False, "chat_template_exception": f"{type(e).__name__}: {str(e)[:300]}"}
    # the REAL vLLM path (HF renderer): resolve_chat_template + safe_apply_chat_template on this tokenizer
    vf = v2.load_vllm_functions([])
    mc = types.SimpleNamespace(revision=None, code_revision=None, trust_remote_code=False, hf_config=types.SimpleNamespace(model_type=json.loads((SNAP / "config.json").read_text())["model_type"]))
    vf.events.clear(); vf.processor_calls.clear(); vf.ns["_PROCESSOR_CHAT_TEMPLATES"].clear()
    resolved = vf.ns["resolve_chat_template"](tok, chat_template=None, tools=None, model_config=mc)
    vllm_hf: dict[str, Any] = {"model_type": mc.hf_config.model_type, "resolve_chat_template": {"returned_none": resolved is None, "resolved_template_sha256": sha(resolved.encode()) if isinstance(resolved, str) else None,
                                                                                             "equals_tokenizer_config_template": resolved == ct},
                               "processor_stage_calls": list(vf.processor_calls), "logged_events": list(vf.events)[:6], "content_format_detected": vf.ns["_resolve_chat_template_content_format"](None, None, tok, model_config=mc), "safe_apply": {}}
    for sid in lp.smoke_ids():
        try:
            out = vf.ns["safe_apply_chat_template"](mc, tok, [dict(m) for m in lp.messages(sid)], tools=None, chat_template=None, tokenize=False, add_generation_prompt=True)
            vllm_hf["safe_apply"][sid] = {"raised": False, "equals_transformers_render": out == pre[sid].get("rendered")}
        except Exception as e:  # noqa: BLE001
            vllm_hf["safe_apply"][sid] = {"raised": True, "exception_class": type(e).__name__, "message": str(e)[:300]}
    # mode resolution through the REAL resolve_tokenizer_args (auto branch) and the REAL repo_utils helpers, on the local snapshot dir (as in the container) and on the exact HF tree listing
    tok_reg_text, rend_reg_text = readiness_mod.src("vllm/tokenizers/registry.py"), readiness_mod.src("vllm/renderers/registry.py")
    ru_text = EXTRA_SOURCE_PATHS["vllm/transformers_utils/repo_utils.py"].read_text()
    ru_ns: dict[str, Any] = {"cache": functools.cache, "Path": Path, "os": __import__("os"), "fnmatch": fnmatch, "logger": types.SimpleNamespace(error=lambda *a, **k: None),
                             "with_retry": lambda f, msg: f(), "envs": types.SimpleNamespace(VLLM_USE_MODELSCOPE=False), "huggingface_hub": __import__("huggingface_hub"), "hf_api": None, "Any": Any}
    ru_tree = ast.parse(ru_text)
    keep = [n for n in ru_tree.body if isinstance(n, ast.FunctionDef) and n.name in ("list_repo_files", "list_filtered_repo_files", "any_pattern_in_repo_files", "is_mistral_model_repo")]
    exec(compile(ast.Module(body=[ast.fix_missing_locations(n) for n in keep], type_ignores=[]), "vllm_repo_utils_v0.29.0", "exec"), ru_ns)
    ns = {"envs": types.SimpleNamespace(VLLM_USE_MODELSCOPE=False), "assert_never": lambda x: None, "Path": Path, "is_mistral_model_repo": ru_ns["is_mistral_model_repo"], "any_pattern_in_repo_files": ru_ns["any_pattern_in_repo_files"]}
    exec(compile(readiness_mod.func_source(tok_reg_text, "resolve_tokenizer_args"), "vllm_tokenizers_registry_v0.29.0", "exec"), ns)
    mode_local = ns["resolve_tokenizer_args"](str(SNAP), tokenizer_mode="auto", runner_type="generate")[0]
    tree_files = verified["hf_tree_files"]
    ru_ns["list_repo_files"] = lambda repo_id, **k: tree_files                                                             # the exact revision's full file listing
    ns2 = dict(ns, is_mistral_model_repo=lambda **k: any(fnmatch.fnmatch(f.rsplit("/", 1)[-1], "consolidated*.safetensors") for f in tree_files),
               any_pattern_in_repo_files=lambda **k: any(fnmatch.fnmatch(f.rsplit("/", 1)[-1], p) for f in tree_files for p in k["allow_patterns"]))
    mode_tree = ns2["resolve_tokenizer_args"](MODEL, tokenizer_mode="auto", runner_type="generate")[0]
    tokenizers = readiness_mod.dict_literal(ast.parse(tok_reg_text), "_VLLM_TOKENIZERS")
    renderers = readiness_mod.dict_literal(ast.parse(rend_reg_text), "_VLLM_RENDERERS")
    mode = {"tokenizer_mode_default": "auto", "resolved_on_local_snapshot_dir": mode_local, "resolved_on_exact_hf_tree_listing": mode_tree, "tokenizer": list(tokenizers[mode_local]), "renderer": list(renderers[mode_local]),
            "mistral_native_path_selected": mode_local == "mistral", "hf_tree_has_consolidated_or_tekken_or_tokenizer_model_v": verified["hf_tree_has_consolidated_or_tekken"],
            "note": "vLLM 0.29.0 'auto' picks the Mistral tokenizer only for repos with consolidated*.safetensors AND tekken.json/tokenizer.model.v*; Phi-4 has neither, so the HF renderer + a chat template in tokenizer_config.json is the path"}
    # ── 4: request payloads through the REAL builder ────────────────────────────────────────────────────────────────────────────────────────────
    forbidden = ("chat_template", "chat_template_kwargs", "reasoning_effort", "reasoning", "reasoning_parser", "thinking", "enable_thinking", "documents", "tools", "extra_body")
    payloads = {}
    for s in cfg["smokes"]:
        p = runner.build_chat_payload(cfg, s, gen)
        payloads[s["smoke_id"]] = {"payload": p, "keys": sorted(p), "has_forbidden_field": any(k in p for k in forbidden), "messages_canonical": p["messages"] == lp.messages(s["smoke_id"]),
                                   "user_content_sha256": sha(p["messages"][0]["content"].encode()), "expected_prompt_sha256": lp.prompt_sha256(s["smoke_id"])}
    # ── 6: container-proof contract through the REAL harness function ───────────────────────────────────────────────────────────────────────────
    hns: dict[str, Any] = {"runtime_config": rc, "locked_protocol": lp, "json": json}
    exec(compile(fn_source(HARNESS, "_same_json"), "harness_same_json", "exec"), hns)
    exec(compile(fn_source(HARNESS, "container_proof_problems"), "harness_container_proof_problems", "exec"), hns)
    check = hns["container_proof_problems"]
    good = {"runtime_configuration_id": None, "runtime_configuration_id_applied": None, "runtime_configuration_sha256": rc.configuration_sha256(MODEL), "runtime_policy_sha256": rc.PINNED_RUNTIME_POLICY_SHA256,
            "chat_template_kwargs_sent": {sid: None for sid in lp.smoke_ids()}, "smoke_protocol_sha256": lp.protocol_sha256(), "prompt_sha256_sent": {sid: lp.prompt_sha256(sid) for sid in lp.smoke_ids()},
            "model_id": MODEL, "served_model_id": MODEL, "revision": REV, "precision": "bfloat16", "quantization": None, "reasoning_parser": None, "tokenizer_mode": None, "config_format": None,
            "load_format": None, "chat_template_flag": None}

    def problems(**over):
        proof = copy.deepcopy(good)
        proof.update(over)
        return check({"runtime_configuration_proof": proof}, MODEL, REV, cfg["extra_args"])

    noflag = copy.deepcopy(good)
    del noflag["chat_template_flag"]
    drift = {"qwen_reasoning_parser": problems(reasoning_parser="qwen3"), "qwen_config_id": problems(runtime_configuration_id="qwen3_8b_non_thinking_v1", runtime_configuration_id_applied="qwen3_8b_non_thinking_v1"),
             "qwen_kwargs_sent": problems(chat_template_kwargs_sent={sid: {"enable_thinking": False} for sid in lp.smoke_ids()}),
             "qwen_config_fingerprint": problems(runtime_configuration_sha256=rc.configuration_sha256("Qwen/Qwen3-8B")),
             "mistral_hf_flags": problems(tokenizer_mode="hf", config_format="hf", load_format="safetensors"), "mistral_native_mode": problems(tokenizer_mode="mistral"),
             "mistral_candidate_id": problems(runtime_configuration_id=rc.MISTRAL_NATIVE_V1_ID, runtime_configuration_id_applied=rc.MISTRAL_NATIVE_V1_ID),
             "chat_template_flag": problems(chat_template_flag="t.jinja"), "chat_template_flag_unproven": check({"runtime_configuration_proof": noflag}, MODEL, REV, cfg["extra_args"]),
             "protocol_sha": problems(smoke_protocol_sha256="0" * 64), "prompt_hashes": problems(prompt_sha256_sent={"A": "0" * 64, "B": "0" * 64, "C": "0" * 64}), "model": problems(served_model_id="x"),
             "revision": problems(revision="0" * 40), "precision": problems(precision="float16"), "quantization": problems(quantization="fp8"), "runtime_policy": problems(runtime_policy_sha256="0" * 64),
             "no_proof": check({}, MODEL, REV, cfg["extra_args"])}
    candidate_refused = False
    try:
        check({"runtime_configuration_proof": good}, MODEL, REV, None, candidate_id=rc.MISTRAL_NATIVE_V1_ID)
    except ValueError:
        candidate_refused = True
    proof_contract = {"synthetic_good_phi_proof_problems": problems(), "every_drift_rejected": all(bool(v) for v in drift.values()), "drift_problems": drift,
                      "mistral_candidate_refused_for_phi": candidate_refused,
                      "validator_side": "orca.eval.control_runtime_qualification._check_container_execution_proof: Phi-4 has no approved runtime configuration (runtime_configuration_id must be None), null kwargs for A/B/C, "
                                        "tokenizer_mode/config_format/load_format/reasoning_parser all None, chat_template_flag must be present and null for Phi-4, canonical protocol/prompt hashes, exact model/revision, bfloat16, no quantization; a declared candidate id is refused (restricted to Mistral)",
                      "note": "SYNTHETIC proofs exercising the real functions; NOT runtime evidence"}
    phi_rec = json.loads(PHI_RECORD.read_text())
    ok = bool(all(argv_checks.values()) and tokenizer["chat_template_present"] and tokenizer["get_chat_template"]["ok"] and all(v["ok"] and v["deterministic"] and v["decoded_equals_rendered"] for v in pre.values())
              and not vllm_hf["resolve_chat_template"]["returned_none"] and vllm_hf["resolve_chat_template"]["equals_tokenizer_config_template"] and all(not v["raised"] and v["equals_transformers_render"] for v in vllm_hf["safe_apply"].values())
              and mode_local == "hf" and mode_tree == "hf" and not any(v["has_forbidden_field"] for v in payloads.values()) and all(v["messages_canonical"] for v in payloads.values())
              and proof_contract["every_drift_rejected"] and not proof_contract["synthetic_good_phi_proof_problems"] and candidate_refused and phi_rec["attempts"] == []
              and phi_rec["runtime_qualification_status"] == "NOT_TESTED" and lp.protocol_sha256() == rc.LOCKED_SMOKE_PROTOCOL_SHA256 and gen == {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": 64}
              and rc.configuration_for_model(MODEL) is None)
    art = {"evidence_type": "GENESIS_PHI4_RUNTIME_READINESS", "phase": "21B.4.20", "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "model_id": MODEL, "revision": REV, "expected_weight_bytes": EXPECTED_WEIGHT_BYTES, "cpu_library_versions_used": versions, "container_versions_from_prior_attempt_logs": CONTAINER_VERSIONS,
           "runtime": "vLLM 0.29.0, existing pinned container digest, bfloat16, no quantization (unchanged)",
           "input_verification": {"snapshot_integrity_verified": True, "source_integrity_verified": True, "verified_snapshot": verified["snapshot"], "verified_vllm_sources_sha256": verified["sources"],
                                  "method": "pinned sha256 constants + container pre-cache manifest sizes + Hugging Face tree at the exact revision (git blob sha1 and size); a mutable ref, missing file or mismatch refuses",
                                  "hf_tree_file_list": verified["hf_tree_files"]},
           "canonical_phi4_configuration": canonical, "server_argv_sanitized": argv, "server_argv_checks": argv_checks, "tokenizer": tokenizer, "chat_preprocessing_transformers": pre,
           "vllm_hf_renderer_path_real_functions": vllm_hf, "tokenizer_mode_resolution_real_vllm": mode, "request_payloads_real_builder": payloads, "container_proof_contract": proof_contract,
           "stubs_and_approximations": ["vLLM itself is not imported; the real functions are extracted by ast from the pinned v0.29.0 sources and executed with recorded stubs (logger, load_chat_template, cached_get_processor approximated by AutoProcessor.from_pretrained, "
                                        "resolve_chat_template_kwargs identity, list_repo_files/with_retry/envs for the repo_utils helpers)", "the vLLM CachedHfTokenizer wrapper itself is not executed; the underlying tokenizer is AutoTokenizer's return value"],
           "not_covered": ["engine initialization and weight loading of Phi-4", "generation behaviour and EOS/stop behaviour", "whether the model answers the locked prompts with the exact required outputs (response behaviour)",
                           "the container's mistral_common/other library versions beyond those logged"],
           "phi4_record_state": {"attempts": phi_rec["attempts"], "runtime_qualification_status": phi_rec["runtime_qualification_status"], "technical_serving_status": phi_rec["technical_serving_status"], "capability_status": phi_rec["capability_status"]},
           "readiness_verdict": "PHI4_CPU_READY" if ok else "PHI4_CPU_NOT_READY",
           "statements": ["CPU readiness is NOT runtime qualification", "CPU readiness is NOT capability qualification", "NO GPU was used", "NO generation occurred"],
           "canonical_phi_configuration_changed": False, "no_new_candidate_created": True, "no_gpu_used": True, "no_modal_used": True, "no_provider_call": True, "no_model_weights_loaded": True, "no_generation": True,
           "generated_output_executed": False}
    OUT.write_text(json.dumps(art, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"artifact": OUT.name, "verdict": art["readiness_verdict"], "argv_checks_all": all(argv_checks.values()), "tokenizer_class": tokenizer["tokenizer_class"], "mode": mode_local,
                      "pre_ok": {k: v["ok"] for k, v in pre.items()}, "drift_all_rejected": proof_contract["every_drift_rejected"]}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
