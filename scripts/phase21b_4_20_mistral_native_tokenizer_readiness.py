"""
Phase 21B.4.20 -- CPU-ONLY readiness analysis of vLLM's NATIVE Mistral tokenizer/renderer path for Mistral-Nemo-Instruct-2407 (`--tokenizer-mode mistral`).

No GPU, no Modal, no provider call, no model weights, no generation, no engine. Run with an interpreter holding the container's exact transformers 5.16.1 /
tokenizers 0.23.2 / huggingface_hub 1.30.0 and mistral_common >= 1.11.6 (vLLM 0.29.0's requirement; the installed version is recorded -- the container's is not logged).

What is executed vs. only read (nothing is claimed beyond what ran):
  * B1  registries: the real `_VLLM_TOKENIZERS` / `_VLLM_RENDERERS` dict literals are parsed from the immutable v0.29.0 source; the real `resolve_tokenizer_args`
        is executed for the explicit modes 'hf' and 'mistral' (the 'auto' branch is quoted from source, not executed); renderer selection is quoted from
        `renderer_from_config` (renderer_mode is taken from tokenizer_args_from_config, i.e. it equals the tokenizer mode).
  * B2  the REAL `vllm/tokenizers/mistral.py` module source is executed unmodified against the real mistral_common and transformers, with only its vLLM-internal imports
        stubbed (chat_utils, chat-completion protocol, logger, TokenizerLike). `MistralTokenizer.from_pretrained(<exact pinned non-weight snapshot>)` is then called.
  * B3  the REAL `safe_apply_chat_template` of `vllm/renderers/mistral.py` is executed (module executed with BaseRenderer/parse_chat_messages/... stubbed; `MistralRenderer.render_messages`
        itself is NOT called), with the apply-kwargs derived by executing the real `merge_kwargs` on the values `ChatCompletionRequest.build_chat_params` produces for a default request.
  * B4  deterministic comparison with the failed HF chain, chain steps marked reproduced/not reproduced.
  * SECONDARY  the explicit pinned Jinja template through vLLM's real HF `resolve_chat_template` on the MistralCommonBackend the HF path yields.
Generated/decoded text is data and is never executed.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata as md
import importlib.util
import json
import sys
import types
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generic, TypeVar

warnings.simplefilter("ignore")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from orca.eval import locked_smoke_protocol as lp  # noqa: E402

EVIDENCE = REPO_ROOT / "docs/orneur/phase-21/evidence"
OUT = EVIDENCE / "GENESIS_MISTRAL_NEMO_NATIVE_TOKENIZER_MODE_READINESS_2026-09-26.json"
SRC = Path("/tmp/p4420/mistral_src")
SNAP = Path("/tmp/p4420/v2/snap")
REV = "04d8a90549d23fc6bd7f642064003592df51e9b3"
VLLM_COMMIT = "98dff2a81d747d1dba01a47f939f48c3526d4206"
CONTAINER_VERSIONS = {"transformers": "5.16.1", "tokenizers": "0.23.2", "huggingface_hub": "1.30.0"}
SOURCES = {"vllm/tokenizers/registry.py": "v3__vllm__tokenizers__registry.py", "vllm/renderers/registry.py": "v3__vllm__renderers__registry.py",
           "vllm/tokenizers/mistral.py": "v3__vllm__tokenizers__mistral.py", "vllm/renderers/mistral.py": "v3__vllm__renderers__mistral.py",
           "vllm/renderers/hf.py": "vllm__renderers__hf.py", "vllm/renderers/params.py": "vllm__renderers__params.py",
           "vllm/entrypoints/openai/chat_completion/protocol.py": "vllm__vllm__entrypoints__openai__chat_completion__protocol.py"}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

# ── independent pinned input hashes (NOT read from any readiness artifact) ─────────────────────────────────────────────────────────────────
# SHA256 of every vLLM v0.29.0 (commit above) source file this analysis executes or quotes. Any missing file or mismatch => refuse; there is no fallback.
EXPECTED_SOURCE_SHA256 = {
    "vllm/tokenizers/registry.py": "9515c9d30b5b87e1706d1905c51dfac45ff75eb72bb34957181b7907dc29ca73",
    "vllm/renderers/registry.py": "a08f893773e22d4b249726f2cec930ea70eb508f32a4903bacffba37b07fdf5b",
    "vllm/tokenizers/mistral.py": "923bd30cd82b685c2cd51586f933bf1e893d31c348b204af9d54bb578968eb65",
    "vllm/renderers/mistral.py": "586b99a78050d99172b742fa81be535eea91b82967f2837f8c43a8ed6f5434d8",
    "vllm/renderers/hf.py": "2b24612a7163f176f205f9a976ebabafc2ac7840ed5516574b0776272c02ed26",
    "vllm/renderers/params.py": "30104415b818465eb1114852104a9b52b9792a4eed9bc3f32a355d8cf33dd8e0",
    "vllm/entrypoints/openai/chat_completion/protocol.py": "8a1f1138f79557aa5b5add12e81b9745fd5e286fa35f0502a97f2a377d41665b",
    "vllm/transformers_utils/chat_templates/registry.py": "ab10d6c7edfdd78eefb08591db02749689b1f02227dcbcd0320e8768e89360e7",
}
SOURCE_LOCAL_PATHS = {**{k: SRC / v for k, v in SOURCES.items()}, "vllm/transformers_utils/chat_templates/registry.py": Path("/tmp/p4420/v2") / "vllm__transformers_utils__chat_templates__registry.py"}
SNAPSHOT_REQUIRED_FILES = ("config.json", "generation_config.json", "params.json", "special_tokens_map.json", "tekken.json", "tokenizer.json", "tokenizer_config.json", "vocab.json",
                           "merges.txt", "model.safetensors.index.json")
V2_EVIDENCE = EVIDENCE / "GENESIS_MISTRAL_NEMO_CHAT_TEMPLATE_ROOT_CAUSE_ANALYSIS_V2_2026-09-26.json"


def verify_inputs() -> tuple[dict, dict]:
    """Fail closed BEFORE any analysis: pinned vLLM sources by SHA256, and the non-weight snapshot files by SHA256 against the committed V2 root-cause evidence."""
    src_ok: dict[str, str] = {}
    for name, want in EXPECTED_SOURCE_SHA256.items():
        path = SOURCE_LOCAL_PATHS[name]
        if not path.is_file():
            raise SystemExit(f"REFUSING: vLLM source file missing: {name} ({path})")
        got = sha(path.read_bytes())
        if got != want:
            raise SystemExit(f"REFUSING: vLLM source {name} sha256 {got} != pinned {want}")
        src_ok[name] = got
    v2 = json.loads(V2_EVIDENCE.read_text())
    if v2.get("revision") != REV:
        raise SystemExit("REFUSING: root-cause V2 evidence is not for the pinned revision")
    expected = {k: v["sha256"] for k, v in v2["A_pinned_tokenizer_config"]["files_in_pinned_snapshot"].items()}
    snap_ok: dict[str, str] = {}
    for f in SNAPSHOT_REQUIRED_FILES:
        path = SNAP / f
        if f not in expected or len(expected[f]) != 64:
            raise SystemExit(f"REFUSING: V2 evidence has no sha256 for {f}")
        if not path.is_file():
            raise SystemExit(f"REFUSING: pinned snapshot file missing: {f}")
        got = sha(path.read_bytes())
        if got != expected[f]:
            raise SystemExit(f"REFUSING: snapshot file {f} sha256 {got} != V2 evidence {expected[f]}")
        snap_ok[f] = got
    return src_ok, snap_ok



def src(name: str) -> str:
    return (SRC / SOURCES[name]).read_text()


def dict_literal(tree: ast.Module, name: str) -> dict:
    for n in tree.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            tgt = n.targets[0] if isinstance(n, ast.Assign) else n.target
            if getattr(tgt, "id", "") == name:
                return ast.literal_eval(n.value)
    raise KeyError(name)


def func_source(text: str, name: str) -> str:
    tree = ast.parse(text)
    node = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name][-1]
    return ast.get_source_segment(text, node)


def install_vllm_stubs() -> None:
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    class _Logger:
        def __getattr__(self, _):
            return lambda *a, **k: None

    T = TypeVar("T")

    class BaseRenderer(Generic[T]):
        def __init__(self, config, tokenizer):
            self.model_config = getattr(config, "model_config", None)
            self._tokenizer = tokenizer
            self._executor = None

        def get_tokenizer(self):
            return self._tokenizer

    for n in ("vllm", "vllm.entrypoints", "vllm.entrypoints.openai", "vllm.entrypoints.openai.chat_completion", "vllm.tokenizers", "vllm.renderers", "vllm.utils"):
        mod(n, __path__=[])
    mod("vllm.entrypoints.chat_utils", ChatCompletionMessageParam=dict, ConversationMessage=dict, parse_chat_messages=None, parse_chat_messages_async=None)
    mod("vllm.entrypoints.openai.chat_completion.protocol", ChatCompletionRequest=object)
    mod("vllm.logger", init_logger=lambda *_: _Logger())
    mod("vllm.tokenizers.protocol", TokenizerLike=object)
    mod("vllm.config", VllmConfig=object)
    mod("vllm.utils.async_utils", make_async=lambda f, executor=None: f)
    mod("vllm.renderers.base", BaseRenderer=BaseRenderer)
    mod("vllm.renderers.inputs", DictPrompt=dict)
    mod("vllm.renderers.inputs.preprocess", parse_dec_only_prompt=lambda x: x)
    mod("vllm.renderers.params", ChatParams=object)


def exec_real_module(dotted: str, source_text: str, file_label: str):
    m = types.ModuleType(dotted)
    m.__package__ = dotted.rsplit(".", 1)[0]
    m.__file__ = file_label
    sys.modules[dotted] = m
    exec(compile(source_text, file_label, "exec"), m.__dict__)
    return m


def main() -> int:
    versions = {p: md.version(p) for p in ("transformers", "tokenizers", "huggingface_hub", "mistral_common", "jinja2")}
    for k, v in CONTAINER_VERSIONS.items():
        if versions[k] != v:
            print(f"REFUSING: {k} {versions[k]} != container {v}")
            return 2
    src_verified, snap_verified = verify_inputs()
    # ── B1 ─────────────────────────────────────────────────────────────────────────────────────────────────────
    tok_reg_text, rend_reg_text = src("vllm/tokenizers/registry.py"), src("vllm/renderers/registry.py")
    tokenizers = dict_literal(ast.parse(tok_reg_text), "_VLLM_TOKENIZERS")
    renderers = dict_literal(ast.parse(rend_reg_text), "_VLLM_RENDERERS")
    ns: dict[str, Any] = {"envs": types.SimpleNamespace(VLLM_USE_MODELSCOPE=False), "assert_never": lambda x: None, "Path": Path,
                          "is_mistral_model_repo": lambda **k: (_ for _ in ()).throw(AssertionError("auto branch must not run for explicit modes")),
                          "any_pattern_in_repo_files": lambda **k: (_ for _ in ()).throw(AssertionError("auto branch must not run for explicit modes"))}
    exec(compile(func_source(tok_reg_text, "resolve_tokenizer_args"), "vllm_tokenizers_registry_v0.29.0", "exec"), ns)
    resolved = {m: ns["resolve_tokenizer_args"](str(SNAP), tokenizer_mode=m, runner_type="generate")[0] for m in ("hf", "mistral")}
    rfc = func_source(rend_reg_text, "renderer_from_config")
    auto_src = tok_reg_text[tok_reg_text.index("    # Try to use official Mistral tokenizer if possible"):tok_reg_text.index("    # Fallback to HF tokenizer")]
    B1 = {"vllm_commit": VLLM_COMMIT, "source_files": {k: {"sha256": sha((SRC / v).read_bytes()), "bytes": (SRC / v).stat().st_size} for k, v in SOURCES.items()},
          "tokenizer_registry__VLLM_TOKENIZERS": {k: tokenizers[k] for k in ("hf", "mistral")}, "renderer_registry__VLLM_RENDERERS": {k: renderers[k] for k in ("hf", "mistral")},
          "explicit_mode_resolution_executed": {"hf": {"tokenizer_mode_returned": resolved["hf"], "tokenizer": tokenizers["hf"], "renderer": renderers[resolved["hf"]]},
                                                "mistral": {"tokenizer_mode_returned": resolved["mistral"], "tokenizer": tokenizers["mistral"], "renderer": renderers[resolved["mistral"]]}},
          "renderer_selection_source": rfc, "renderer_mode_equals_tokenizer_mode": "renderer_mode, *_ = tokenizer_args_from_config(model_config, **kwargs)" in rfc,
          "auto_mode_source_NOT_EXECUTED": auto_src,
          "conclusion": "the attempt-2 explicit `--tokenizer-mode hf` selected CachedHfTokenizer + HfRenderer (registry values above); `--tokenizer-mode mistral` selects MistralTokenizer + MistralRenderer. "
                        "'auto' would select mistral for a Mistral repo containing tekken.json / tokenizer.model.v* (source quoted, not executed)."}
    # ── B2 ─────────────────────────────────────────────────────────────────────────────────────────────────────
    install_vllm_stubs()
    mt_mod = exec_real_module("vllm.tokenizers.mistral", src("vllm/tokenizers/mistral.py"), "vllm/tokenizers/mistral.py@v0.29.0")
    B2: dict[str, Any] = {"executed_real_source": "vllm/tokenizers/mistral.py (module executed unmodified)",
                          "stubbed_vllm_internals": ["vllm.entrypoints.chat_utils", "vllm.entrypoints.openai.chat_completion.protocol", "vllm.logger", "vllm.tokenizers.protocol.TokenizerLike (plain base)"]}
    tk = None
    try:
        tk = mt_mod.MistralTokenizer.from_pretrained(str(SNAP))
        B2.update({"construction": "SUCCEEDED", "vllm_class": "MistralTokenizer", "transformers_backend": f"{type(tk.transformers_tokenizer).__module__}.{type(tk.transformers_tokenizer).__name__}",
                   "mistral_common_tokenizer_class": f"{type(tk.mistral).__module__}.{type(tk.mistral).__name__}",
                   "underlying_tokenizer_class": f"{type(tk.tokenizer).__module__}.{type(tk.tokenizer).__name__}", "is_tekken": tk.is_tekken, "is_spm": tk.is_spm,
                   "tokenizer_version": tk.version, "mistral_common_version": versions["mistral_common"], "validation_mode": str(tk.mistral._chat_completion_request_validator._mode),
                   "bos_id": tk.bos_token_id, "eos_id": tk.eos_token_id, "pad_id": tk.pad_token_id, "vocab_size": tk.vocab_size,
                   "tokenizer_source_file_in_snapshot": "tekken.json", "tekken_json_sha256": sha((SNAP / "tekken.json").read_bytes())})
    except Exception as e:  # noqa: BLE001
        B2.update({"construction": "FAILED", "exception": f"{type(e).__name__}: {str(e)[:400]}"})
    # ── B3 ─────────────────────────────────────────────────────────────────────────────────────────────────────
    B3: dict[str, Any] = {}
    if tk is not None:
        params_text = src("vllm/renderers/params.py")
        mk_ns: dict[str, Any] = {"Any": Any}
        exec(compile("from __future__ import annotations\n" + func_source(params_text, "merge_kwargs"), "vllm_params_merge_kwargs_v0.29.0", "exec"), mk_ns)
        merge = mk_ns["merge_kwargs"]
        # values ChatCompletionRequest.build_chat_params produces for a default request (add_generation_prompt=True, continue_final_message=False, documents/reasoning_effort None)
        extra = dict(add_generation_prompt=True, continue_final_message=False, documents=None, reasoning_effort=None)
        chat_template_kwargs = merge(None, extra)
        apply_kwargs = merge(chat_template_kwargs, dict(chat_template=None, return_dict=False))
        rend_mod = exec_real_module("vllm.renderers.mistral", src("vllm/renderers/mistral.py"), "vllm/renderers/mistral.py@v0.29.0")
        B3 = {"executed_real_function": "vllm.renderers.mistral.safe_apply_chat_template (real source) -> MistralTokenizer.apply_chat_template (real) -> MistralCommonBackend.apply_chat_template",
              "apply_kwargs_derived_by_real_merge_kwargs": apply_kwargs, "no_chat_template_or_kwargs_supplied_by_the_request": True,
              "MistralRenderer.render_messages_called": False, "smokes": {}}
        ids_by = {}
        for sid in lp.smoke_ids():
            msgs = lp.messages(sid)
            try:
                ids = rend_mod.safe_apply_chat_template(tk, [dict(m) for m in msgs], **apply_kwargs)
                text_keep = tk.decode(ids, skip_special_tokens=False)
                ids_by[sid] = ids
                B3["smokes"][sid] = {"ok": True, "chat_template_resolution_error": False, "token_count": len(ids), "token_ids": ids, "token_ids_sha256": sha(json.dumps(ids).encode()),
                                     "decoded_with_special_tokens": text_keep, "decoded_sha256": sha(text_keep.encode()), "prompt_sha256_of_user_message": lp.prompt_sha256(sid)}
            except Exception as e:  # noqa: BLE001
                B3["smokes"][sid] = {"ok": False, "chat_template_resolution_error": type(e).__name__ == "ChatTemplateResolutionError", "exception": f"{type(e).__name__}: {str(e)[:300]}"}
        # informational: does the ordinary Jinja rendering, tokenized by the ordinary tokenizer.json, give the same ids?
        try:
            from transformers import AutoTokenizer
            import tempfile
            d = Path(tempfile.mkdtemp(prefix="p4420_ctl_"))
            for f in SNAP.iterdir():
                if f.name not in ("tekken.json", "params.json"):
                    (d / f.name).symlink_to(f)
            ctl = AutoTokenizer.from_pretrained(str(d))
            for sid in lp.smoke_ids():
                if B3["smokes"][sid]["ok"]:
                    rendered = ctl.apply_chat_template(lp.messages(sid), tokenize=False, add_generation_prompt=True)
                    ids2 = ctl.encode(rendered, add_special_tokens=False)
                    B3["smokes"][sid]["informational_same_ids_as_ordinary_hf_jinja_render_plus_tokenizer_json"] = (ids2 == ids_by[sid])
        except Exception as e:  # noqa: BLE001
            B3["informational_comparison_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    all_ok = bool(tk is not None and B3.get("smokes") and all(s["ok"] for s in B3["smokes"].values()) and not any(s.get("chat_template_resolution_error") for s in B3["smokes"].values()))
    # ── SECONDARY: explicit pinned template through the real HF resolve_chat_template on the backend the HF path yields ─────────────────────────────
    spec = importlib.util.spec_from_file_location("v2mod", REPO_ROOT / "scripts/phase21b_4_20_mistral_chat_template_analysis_v2.py")
    v2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v2)
    hf_tok = tk.transformers_tokenizer if tk is not None else None
    from transformers import AutoTokenizer
    hf_path_tok = AutoTokenizer.from_pretrained(str(SNAP))
    vf = v2.load_vllm_functions([])
    mc = types.SimpleNamespace(revision=None, code_revision=None, trust_remote_code=False, hf_config=types.SimpleNamespace(model_type="mistral"))
    template = json.loads((SNAP / "tokenizer_config.json").read_text())["chat_template"]
    sec: dict[str, Any] = {"backend_class_from_hf_mode": f"{type(hf_path_tok).__module__}.{type(hf_path_tok).__name__}", "template_sha256": sha(template.encode())}
    try:
        r = vf.ns["resolve_chat_template"](hf_path_tok, chat_template=template, tools=None, model_config=mc)
        sec["resolve_chat_template_with_explicit_template"] = {"ok": True, "returned_sha256": sha(r.encode()) if isinstance(r, str) else None}
    except Exception as e:  # noqa: BLE001
        sec["resolve_chat_template_with_explicit_template"] = {"ok": False, "exception": f"{type(e).__name__}: {str(e)[:250]}",
                                                                "note": "vLLM's 1st-priority branch calls tokenizer.get_chat_template(<explicit template>) which MistralCommonBackend does not implement; the exception is NOT caught in that branch"}
    try:
        p = hf_path_tok.apply_chat_template(lp.messages("B"), chat_template=template, tokenize=False, add_generation_prompt=True)
        sec["backend_apply_chat_template_with_chat_template_argument"] = {"ok": True, "output": p[:120], "note": "MistralCommonBackend ignores/does not use the supplied Jinja template (its own native rendering answered)"}
    except Exception as e:  # noqa: BLE001
        sec["backend_apply_chat_template_with_chat_template_argument"] = {"ok": False, "exception": f"{type(e).__name__}: {str(e)[:250]}"}
    sec["status"] = ("NOT_PROVEN" if sec["resolve_chat_template_with_explicit_template"]["ok"] else "NOT_VIABLE_ON_THIS_BACKEND (executed real vLLM path raises)")
    sec["recommended"] = False
    # ── B4 / verdict ──────────────────────────────────────────────────────────────────────────────────────────────
    failed_hf_chain = ["CachedHfTokenizer / HfRenderer", "AutoTokenizer -> MistralCommonBackend (tekken.json present)", "resolve_chat_template -> None (get_chat_template NotImplementedError swallowed at debug)",
                       "safe_apply_chat_template raises ChatTemplateResolutionError -> HTTP 400"]
    native_chain = ["MistralTokenizer / MistralRenderer", "MistralCommonBackend.from_pretrained(mode=test) -> mistral_common Tekkenizer",
                    "safe_apply_chat_template -> MistralTokenizer.apply_chat_template -> MistralCommonBackend.apply_chat_template (no HF Jinja, no get_chat_template)", "prompt token ids produced"]
    steps_repro = {"MistralTokenizer_constructed": B2.get("construction") == "SUCCEEDED", "tekken_backend": B2.get("is_tekken") is True,
                   "native_apply_chat_template_A_B_C": all_ok, "no_ChatTemplateResolutionError": all_ok}
    verdict = "NATIVE_MISTRAL_MODE_CPU_READY" if (all_ok and B2.get("construction") == "SUCCEEDED" and B2.get("is_tekken") and resolved["mistral"] == "mistral") else "NATIVE_MISTRAL_MODE_NOT_PROVEN"
    art = {"evidence_type": "GENESIS_MISTRAL_NEMO_NATIVE_TOKENIZER_MODE_READINESS", "phase": "21B.4.20", "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "revision": REV, "cpu_library_versions_used": versions, "container_versions_from_attempt2_log": CONTAINER_VERSIONS,
           "source_integrity_verified": True, "verified_source_sha256": src_verified, "snapshot_integrity_verified": True, "verified_snapshot_sha256": snap_verified,
           "input_provenance_note": "vLLM source hashes are pinned constants in this script (not read from any prior readiness artifact); snapshot hashes are checked against the committed root-cause V2 evidence; no download or provider call is made here",
           "mistral_common_note": "vLLM 0.29.0 requires mistral_common[image] >= 1.11.6; the container's exact mistral_common version is NOT recorded in the attempt-2 log",
           "B1_mode_selection_from_vllm_source": B1, "B2_mistral_tokenizer_construction": B2, "B3_native_chat_rendering_locked_smokes": B3,
           "B4_comparison": {"failed_hf_chain": failed_hf_chain, "native_mistral_chain": native_chain, "native_chain_reproduced_cpu_side": steps_repro,
                             "failed_hf_chain_reproduced_by": "GENESIS_MISTRAL_NEMO_CHAT_TEMPLATE_ROOT_CAUSE_ANALYSIS_V2_2026-09-26.json"},
           "secondary_explicit_chat_template_hf_renderer": sec,
           "known_source_facts_for_native_mode": ["vllm/tokenizers/mistral.py validate_request_params: a request carrying chat_template or chat_template_kwargs is rejected in Mistral mode (the locked smokes send neither)",
                                                  "MistralTokenizer.apply_chat_template pops add_generation_prompt and lets mistral_common build the [INST] prompt"],
           "not_covered_by_cpu_evidence": ["engine initialization and weight loading with --tokenizer-mode mistral (and its interaction with --config-format hf / --load-format safetensors)",
                                           "stop-token/EOS behaviour and the generated text on GPU", "the container's exact mistral_common version", "any behaviour of MistralRenderer.render_messages beyond its safe_apply_chat_template step"],
           "readiness_verdict": verdict,
           "verdict_reasons": ([f"MistralTokenizer constructed from the exact pinned snapshot on tekken ({B2.get('mistral_common_tokenizer_class')})", "locked smokes A/B/C rendered to token ids through the real vLLM safe_apply_chat_template with no ChatTemplateResolutionError and no get_chat_template call",
                                "registry evidence: tokenizer_mode mistral -> MistralTokenizer and MistralRenderer"] if verdict == "NATIVE_MISTRAL_MODE_CPU_READY" else ["see B2/B3 failures"]),
           "readiness_scope": "CPU-side prompt preprocessing path only; NOT a GPU authorization and NOT a runtime qualification. The canonical configuration (--tokenizer-mode hf) is UNCHANGED.",
           "config_changed": False, "no_gpu_used": True, "no_modal_used": True, "no_provider_call": True, "no_model_weights_loaded": True, "no_generation": True, "generated_output_executed": False,
           "status_unchanged": {"attempt_outcome": "UNATTRIBUTED_REQUEST_REJECTION", "technical_serving_status": "NOT_PROVEN", "runtime_qualification_status": "NOT_COMPLETED", "capability_status": "UNPROVEN"}}
    OUT.write_text(json.dumps(art, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"artifact": OUT.name, "verdict": verdict, "construction": B2.get("construction"), "smokes": {k: v.get("ok") for k, v in B3.get("smokes", {}).items()},
                      "secondary": sec["status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
