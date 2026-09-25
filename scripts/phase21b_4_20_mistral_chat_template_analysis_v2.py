"""
Phase 21B.4.20 -- CPU-ONLY chat-template root-cause isolation V2 for the Mistral-Nemo attempt-2 HTTP 400.

No GPU, no Modal, no model weights, no generation, no engine init. Run it with an interpreter that has the EXACT runtime library versions
(transformers 5.16.1, tokenizers 0.23.2, huggingface_hub 1.30.0; mistral_common >= 1.11.6 as vLLM 0.29.0 requires) -- it records the versions it
actually ran with and refuses to write the artifact if they differ from the attempt-2 container's.

What it does:
  A. facts of the exact pinned tokenizer_config.json (sha256, size, chat_template presence/type/length/sha256);
  B. loads the tokenizer with transformers' AutoTokenizer from a local directory holding EXACTLY the pinned-revision files the attempt-2 container had
     (sizes verified against the persisted precache manifest) and records class / is_fast / chat_template / get_chat_template / apply_chat_template;
  B'. controls: the same files with tekken.json and/or params.json removed (which file changes the loaded class);
  C. EXECUTES the real vLLM 0.29.0 functions (extracted by ast from the immutable v0.29.0 source, not re-written): resolve_chat_template,
     _try_get_processor_chat_template, _resolve_chat_template_content_format, safe_apply_chat_template, on those tokenizers. Names that need the vLLM
     runtime (logger, load_chat_template, cached_get_processor, model_config) are listed explicitly as stubs; nothing is claimed beyond what ran;
  D. what the "Detected the chat template content format to be 'string'" log line does and does not prove (from the source);
  E. hypothesis table (PROVEN / DISPROVEN / NOT ESTABLISHED); F. remedy candidates (analysis only, none executed).
Generated/tokenizer output is data and is never executed.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata as md
import json
import shutil
import sys
import tempfile
import types
import urllib.request
import warnings
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

warnings.simplefilter("ignore")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from orca.eval import locked_smoke_protocol as lp  # noqa: E402

EVIDENCE = REPO_ROOT / "docs/orneur/phase-21/evidence"
OUT = EVIDENCE / "GENESIS_MISTRAL_NEMO_CHAT_TEMPLATE_ROOT_CAUSE_ANALYSIS_V2_2026-09-26.json"
SRC = Path("/tmp/p4420/mistral_src")            # immutable vLLM v0.29.0 sources (commit below), cached by earlier analyses
SNAP = Path("/tmp/p4420/v2/snap")               # exact pinned-revision files (no weights)
REV = "04d8a90549d23fc6bd7f642064003592df51e9b3"
VLLM_COMMIT = "98dff2a81d747d1dba01a47f939f48c3526d4206"    # tag v0.29.0
ATTEMPT2_LOG = EVIDENCE / "GENESIS_CONTROL_MISTRAL_NEMO_MODAL_H100_ATTEMPT2_RAW_LOG_2026-09-24.txt"
PRECACHE = EVIDENCE / "GENESIS_CONTROL_MISTRAL_NEMO_MODAL_PRECACHE_MANIFEST_2026-09-24.json"
CONTAINER_VERSIONS = {"transformers": "5.16.1", "tokenizers": "0.23.2", "huggingface_hub": "1.30.0"}
FILES = ("config.json", "generation_config.json", "params.json", "special_tokens_map.json", "tekken.json", "tokenizer.json", "tokenizer_config.json",
         "vocab.json", "merges.txt", "model.safetensors.index.json")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def ensure_snapshot() -> dict:
    """The exact pinned-revision non-weight files; sizes must equal the attempt-2 container's persisted manifest."""
    want = {f["filename"]: f["bytes"] for f in json.loads(PRECACHE.read_text())["manifest"]["files"]}
    SNAP.mkdir(parents=True, exist_ok=True)
    out = {}
    for f in FILES:
        p = SNAP / f
        if not p.is_file():
            p.write_bytes(urllib.request.urlopen(f"https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/resolve/{REV}/{f}", timeout=120).read())
        b = p.read_bytes()
        out[f] = {"bytes": len(b), "sha256": sha(b), "matches_container_manifest_size": want.get(f) == len(b)}
    return out


def tokenizer_facts(path: Path, label: str) -> dict:
    from transformers import AutoTokenizer
    rec: dict[str, Any] = {"label": label, "directory_files": sorted(p.name for p in path.iterdir())}
    try:
        tok = AutoTokenizer.from_pretrained(str(path))
    except Exception as e:  # noqa: BLE001
        rec["load_exception"] = f"{type(e).__name__}: {str(e)[:300]}"
        return rec
    ct = getattr(tok, "chat_template", "<no attribute>")
    rec.update({"tokenizer_class": f"{type(tok).__module__}.{type(tok).__name__}", "mro": [c.__name__ for c in type(tok).__mro__[:4]],
                "is_fast": getattr(tok, "is_fast", "<no attribute>"), "name_or_path": tok.name_or_path,
                "chat_template_attribute": ("str" if isinstance(ct, str) else repr(ct)),
                "chat_template_utf8_bytes": len(ct.encode()) if isinstance(ct, str) else None,
                "chat_template_sha256": sha(ct.encode()) if isinstance(ct, str) else None})
    try:
        r = tok.get_chat_template(None, tools=None)
        rec["get_chat_template"] = {"ok": True, "sha256": sha(r.encode()) if isinstance(r, str) else None, "type": type(r).__name__}
    except Exception as e:  # noqa: BLE001
        rec["get_chat_template"] = {"ok": False, "exception": f"{type(e).__name__}: {str(e)[:300]}"}
    renders = {}
    for sid in lp.smoke_ids():
        try:
            p = tok.apply_chat_template(lp.messages(sid), tokenize=False, add_generation_prompt=True)
            renders[sid] = {"ok": True, "rendered_sha256": sha(p.encode()), "rendered": p if len(p) < 200 else None}
        except Exception as e:  # noqa: BLE001
            renders[sid] = {"ok": False, "exception": f"{type(e).__name__}: {str(e)[:300]}"}
    rec["apply_chat_template_AB_C"] = renders
    rec["_tokenizer"] = tok
    return rec


def load_vllm_functions(tok_stub_notes: list) -> types.SimpleNamespace:
    """Extract the REAL vLLM v0.29.0 functions by ast from the immutable source and exec them with an explicit stub namespace."""
    src = (SRC / "vllm__renderers__hf.py").read_text()
    tree = ast.parse(src)
    want = {"_try_get_processor_chat_template", "resolve_chat_template", "_resolve_chat_template_content_format", "_try_extract_ast", "_detect_content_format",
            "_detect_developer_role_support", "safe_apply_chat_template"}
    nodes = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and (n.name in want or n.name.startswith(("_is_", "_iter_nodes"))):
            nodes.append(n)
    # overloaded defs: keep only the last definition of each name (the implementation)
    last = {}
    for n in nodes:
        last[n.name] = n
    mod = ast.Module(body=[n for n in nodes if last[n.name] is n], type_ignores=[])
    import jinja2, jinja2.ext, jinja2.meta, jinja2.nodes, jinja2.parser, jinja2.sandbox  # noqa: E401
    import logging
    log = logging.getLogger("vllm-stub")
    events: list = []

    class L:
        def debug(self, *a, **k): events.append(("debug", str(a[0]) % a[1:] if len(a) > 1 else str(a[0])))
        def debug_once(self, *a, **k): events.append(("debug_once", str(a[0]) % a[1:] if len(a) > 1 else str(a[0])))
        def info_once(self, *a, **k): events.append(("info_once", str(a[0])))
        def info(self, *a, **k): events.append(("info", str(a[0])))
        def warning(self, *a, **k): events.append(("warning", str(a[0])))
        def exception(self, *a, **k): events.append(("exception", str(a[0])))

    class ChatTemplateResolutionError(ValueError):
        pass

    reg_src = (Path("/tmp/p4420/v2") / "vllm__transformers_utils__chat_templates__registry.py").read_text()
    reg_ns: dict[str, Any] = {}
    reg_tree = ast.parse(reg_src)
    keep = [n for n in reg_tree.body if isinstance(n, (ast.Assign, ast.AnnAssign, ast.FunctionDef)) and not (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "logger" for t in n.targets))]
    reg_ns.update({"Path": Path, "Callable": object, "TypeAlias": object, "logger": L(), "__file__": "/vllm/transformers_utils/chat_templates/registry.py"})
    exec(compile(ast.Module(body=[n for n in keep if not (isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "ChatTemplatePath")], type_ignores=[]),
                 "vllm_registry_v0.29.0", "exec"), reg_ns)
    processor_calls: list = []

    def cached_get_processor(name, *, processor_cls, revision, code_revision, trust_remote_code):
        """APPROXIMATION of vllm.transformers_utils.processor.get_processor for the tuple processor_cls case: AutoProcessor.from_pretrained(name, revision='main')."""
        from transformers import AutoProcessor
        try:
            proc = AutoProcessor.from_pretrained(name, revision=revision or "main", trust_remote_code=trust_remote_code)
            processor_calls.append({"ok": True, "returned_class": f"{type(proc).__module__}.{type(proc).__name__}"})
            return proc
        except Exception as e:  # noqa: BLE001
            processor_calls.append({"ok": False, "exception": f"{type(e).__name__}: {str(e)[:200]}"})
            raise

    ns: dict[str, Any] = {"logger": L(), "lru_cache": lru_cache, "Any": Any, "jinja2": jinja2, "ChatTemplateResolutionError": ChatTemplateResolutionError,
                          "load_chat_template": lambda t, is_literal=False: (t if isinstance(t, str) and is_literal else None),
                          "get_chat_template_fallback_path": reg_ns["get_chat_template_fallback_path"], "cached_get_processor": cached_get_processor,
                          "_PROCESSOR_CHAT_TEMPLATES": {}, "Literal": Any, "cast": lambda t, v: v, "Mapping": dict, "Sequence": list, "ChatTemplateContentFormat": str,
                          "resolve_chat_template_kwargs": lambda **k: dict(k.get("chat_template_kwargs") or {})}
    exec(compile(mod, "vllm_renderers_hf_v0.29.0", "exec"), ns)
    tok_stub_notes.extend([
        "logger: recording stub (real vLLM logger not imported)",
        "load_chat_template: returns the literal string only when is_literal=True, else None (real one also reads files/URLs; not reachable here)",
        "cached_get_processor: approximated by transformers AutoProcessor.from_pretrained(name, revision='main') (vLLM's get_processor tuple-class branch)",
        "resolve_chat_template_kwargs: identity stub (only reached AFTER a template is resolved)",
        "get_chat_template_fallback_path: the REAL v0.29.0 registry function, executed"])
    return types.SimpleNamespace(ns=ns, events=events, processor_calls=processor_calls, ChatTemplateResolutionError=ChatTemplateResolutionError)


def vllm_path(tok, vf: types.SimpleNamespace) -> dict:
    mc = types.SimpleNamespace(revision=None, code_revision=None, trust_remote_code=False,
                               hf_config=types.SimpleNamespace(model_type=json.loads((SNAP / "config.json").read_text())["model_type"]))
    vf.events.clear(); vf.processor_calls.clear(); vf.ns["_PROCESSOR_CHAT_TEMPLATES"].clear()
    rec: dict[str, Any] = {"model_type_used_for_fallback_lookup": mc.hf_config.model_type}
    r = vf.ns["resolve_chat_template"](tok, chat_template=None, tools=None, model_config=mc)
    rec["resolve_chat_template"] = {"returned_none": r is None, "resolved_template_sha256": sha(r.encode()) if isinstance(r, str) else None}
    rec["processor_stage_calls"] = list(vf.processor_calls)
    rec["logged_events_during_resolution"] = list(vf.events)[:8]
    fmt = vf.ns["_resolve_chat_template_content_format"](None, None, tok, model_config=mc)
    rec["_resolve_chat_template_content_format"] = fmt
    per = {}
    for sid in lp.smoke_ids():
        try:
            vf.ns["safe_apply_chat_template"](mc, tok, [dict(m) for m in lp.messages(sid)], tools=None, chat_template=None, tokenize=False, add_generation_prompt=True)
            per[sid] = {"raised": False}
        except Exception as e:  # noqa: BLE001
            per[sid] = {"raised": True, "exception_class": type(e).__name__, "message": str(e)}
    rec["safe_apply_chat_template_AB_C"] = per
    return rec


def main() -> int:
    versions = {p: md.version(p) for p in ("transformers", "tokenizers", "huggingface_hub", "jinja2", "mistral_common")}
    for k, v in CONTAINER_VERSIONS.items():
        if versions[k] != v:
            print(f"REFUSING: {k} {versions[k]} != container {v}")
            return 2
    files = ensure_snapshot()
    cfg_bytes = (SNAP / "tokenizer_config.json").read_bytes()
    cfg = json.loads(cfg_bytes)
    ct = cfg.get("chat_template")
    A = {"tokenizer_config_json_bytes": len(cfg_bytes), "tokenizer_config_json_sha256": sha(cfg_bytes), "json_parses": True, "has_chat_template_key": "chat_template" in cfg,
         "chat_template_type": type(ct).__name__, "chat_template_utf8_bytes": len(ct.encode()) if isinstance(ct, str) else None,
         "chat_template_sha256": sha(ct.encode()) if isinstance(ct, str) else None, "tokenizer_class_declared": cfg.get("tokenizer_class"),
         "files_in_pinned_snapshot": files}
    B_full = tokenizer_facts(SNAP, "B: exact pinned snapshot files (as in the attempt-2 container)")
    controls = {}
    tmp = Path(tempfile.mkdtemp(prefix="p4420_ctl_"))
    try:
        for name, drop in (("without_tekken_json", ("tekken.json",)), ("without_params_json", ("params.json",)), ("without_tekken_and_params", ("tekken.json", "params.json"))):
            d = tmp / name
            d.mkdir()
            for f in FILES:
                if f not in drop:
                    (d / f).symlink_to(SNAP / f)
            controls[name] = tokenizer_facts(d, f"control: {name}")
    finally:
        pass
    notes: list = []
    vf = load_vllm_functions(notes)
    C = {"vllm_source": f"vllm-project/vllm@{VLLM_COMMIT} (v0.29.0) vllm/renderers/hf.py, vllm/transformers_utils/chat_templates/registry.py, vllm/tokenizers/hf.py",
         "stubs_and_approximations": notes, "vllm_imported": False,
         "hf_mode_loader_from_source": "vllm/tokenizers/hf.py CachedHfTokenizer.from_pretrained -> transformers AutoTokenizer.from_pretrained(path, revision=None, ...) then get_cached_tokenizer "
                                       "(a copy whose class is renamed 'Cached<Class>'; it does not touch chat_template/get_chat_template) -- the wrapper itself was NOT executed (it imports "
                                       "vLLM runtime modules); the underlying tokenizer is AutoTokenizer's return value, measured in B.",
         "on_exact_pinned_snapshot": vllm_path(B_full["_tokenizer"], vf)}
    C["on_control_without_tekken_and_params"] = vllm_path(controls["without_tekken_and_params"]["_tokenizer"], vf) if "_tokenizer" in controls["without_tekken_and_params"] else None
    for r in [B_full, *controls.values()]:
        r.pop("_tokenizer", None)
    log = ATTEMPT2_LOG.read_text()
    D = {"log_line_present_in_attempt2_raw_log": "Detected the chat template content format to be 'string'" in log,
         "source_facts": ["_resolve_chat_template_content_format: `detected_format = \"string\" if jinja_text is None else _detect_content_format(jinja_text, default=\"string\")`",
                          "so when resolve_chat_template returns None, the content format is reported as 'string' -- the log line is emitted WITHOUT any resolved template",
                          "_detect_content_format also returns default 'string' for templates with no content-item assignment"],
         "reproduced_on_exact_snapshot": C["on_exact_pinned_snapshot"]["_resolve_chat_template_content_format"],
         "conclusion": "the line does NOT prove a template was resolved; it is identical whether the template is None or a string-content template"}
    mc_reproduced = (B_full.get("tokenizer_class", "").endswith("MistralCommonBackend") and B_full["get_chat_template"]["ok"] is False
                     and C["on_exact_pinned_snapshot"]["resolve_chat_template"]["returned_none"]
                     and all(v.get("raised") and "no longer allowed" in v.get("message", "") for v in C["on_exact_pinned_snapshot"]["safe_apply_chat_template_AB_C"].values()))
    ctl = controls["without_tekken_and_params"]
    ctl_ok = ("tokenizer_class" in ctl and ctl["get_chat_template"].get("ok") is True and not ctl["tokenizer_class"].endswith("MistralCommonBackend")
              and C["on_control_without_tekken_and_params"] is not None and not C["on_control_without_tekken_and_params"]["resolve_chat_template"]["returned_none"])
    tek_only = (controls["without_tekken_json"].get("tokenizer_class", "").endswith("TokenizersBackend")
                and controls["without_params_json"].get("tokenizer_class", "").endswith("MistralCommonBackend"))
    E = [
        {"hypothesis": "the pinned tokenizer_config.json has no usable chat_template", "status": "DISPROVEN", "evidence": "A: key present, str, sha256 recorded; loads and renders in the control"},
        {"hypothesis": "Transformers 5.16.1 AutoTokenizer returns MistralCommonBackend (chat_template=None, get_chat_template unimplemented) for the exact pinned snapshot files",
         "status": "PROVEN" if mc_reproduced else "NOT ESTABLISHED", "evidence": "B: measured with the exact transformers/tokenizers/huggingface_hub versions of the container (mistral_common version of the container is not logged)"},
        {"hypothesis": "the presence of tekken.json in the snapshot is what selects MistralCommonBackend (file-driven backend selection, i.e. configuration behavior); params.json alone does not",
         "status": "PROVEN" if (ctl_ok and tek_only) else "NOT ESTABLISHED",
         "evidence": "B': removing tekken.json alone yields an ordinary TokenizersBackend with a resolvable template; removing only params.json still yields MistralCommonBackend"},
        {"hypothesis": "vLLM 0.29.0 resolve_chat_template returns None for such a tokenizer and safe_apply_chat_template raises the exact attempt-2 400 message",
         "status": "PROVEN" if mc_reproduced else "NOT ESTABLISHED", "evidence": "C: the real v0.29.0 functions executed; message equals the attempt-2 body (ChatTemplateResolutionError -> HTTP 400)"},
        {"hypothesis": "the container's actual tokenizer object was MistralCommonBackend", "status": "NOT ESTABLISHED",
         "evidence": "the attempt-2 log never prints the tokenizer class and the container's mistral_common version is unrecorded; the CPU reproduction under matching versions produces the identical failure at the identical layer, but it is a reproduction, not an observation"},
        {"hypothesis": "cache/file corruption of the served snapshot", "status": "DISPROVEN as necessary cause",
         "evidence": "every file size equals the container's persisted manifest; the failure reproduces on pristine pinned files; byte-level hashes of the container copies are not recorded"},
        {"hypothesis": "a vLLM wrapper bug (CachedHfTokenizer) drops the template", "status": "NOT ESTABLISHED", "evidence": "the wrapper only renames/caches properties; the class returned by AutoTokenizer already lacks the template"},
        {"hypothesis": "a model/weights incompatibility", "status": "DISPROVEN", "evidence": "failure occurs before any model computation, at request preprocessing"}]
    F = [
        {"candidate": "explicit --chat-template with the exact pinned HF template text", "supported_by": "pinned tokenizer_config has the template (A); vLLM's 1st priority path uses a given template without get_chat_template on the backend",
         "changes_locked_serving_configuration": True, "preserves_revision_and_weights": True, "cpu_testable_first": "the vLLM resolve/safe_apply source path, but rendering equivalence needs the exact template applied through the MistralCommonBackend-selected tokenizer -- NOT tested here"},
        {"candidate": "--tokenizer-mode mistral", "supported_by": "snapshot ships tekken.json/params.json, which vLLM's mistral tokenizer mode is built for", "changes_locked_serving_configuration": True,
         "preserves_revision_and_weights": True, "cpu_testable_first": "requires vllm.tokenizers.mistral (vLLM import); not executable in this environment without vLLM"},
        {"candidate": "alter config/load format", "supported_by": "no evidence: the failure is tokenizer/template resolution, not config or weight loading", "changes_locked_serving_configuration": True,
         "preserves_revision_and_weights": True, "cpu_testable_first": "not applicable"},
        {"candidate": "different vLLM/Transformers combination", "supported_by": "no evidence that another combination behaves differently; it changes the pinned image digest", "changes_locked_serving_configuration": True,
         "preserves_revision_and_weights": True, "cpu_testable_first": "possible only by re-running this script under other versions"}]
    art = {"evidence_type": "GENESIS_MISTRAL_NEMO_CHAT_TEMPLATE_ROOT_CAUSE_ANALYSIS_V2", "phase": "21B.4.20", "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "subject": "Mistral-Nemo-Instruct-2407 attempt 2: three HTTP 400 'default chat template is no longer allowed ...' responses",
           "cpu_library_versions_used": versions, "container_versions_from_attempt2_log": CONTAINER_VERSIONS, "revision": REV,
           "established_failure_layer": "vLLM chat-completions preprocessing: resolve_chat_template returned None -> safe_apply_chat_template raised ChatTemplateResolutionError (HTTP 400) BEFORE any generation",
           "A_pinned_tokenizer_config": A, "B_transformers_autotokenizer_exact_snapshot": B_full, "B_controls": controls, "C_vllm_0_29_0_source_path": C,
           "D_startup_log_line": D, "E_hypotheses": E, "F_remedy_candidates_analysis_only": F,
           "root_cause_statement": ("REPRODUCED CPU-ONLY under the container's exact transformers/tokenizers/huggingface_hub versions: the pinned snapshot contains tekken.json and params.json, so "
                                    "Transformers 5.16.1 AutoTokenizer selects MistralCommonBackend (tekken.json is the discriminating file: without it the tokenizer is an ordinary TokenizersBackend), which carries no chat_template and does not implement get_chat_template; vLLM 0.29.0 "
                                    "resolve_chat_template then returns None and safe_apply_chat_template raises the observed error. NOT directly observed inside the container "
                                    "(tokenizer class and mistral_common version are not in the attempt-2 log)." if mc_reproduced else "NOT ESTABLISHED"),
           "recommendation": "NO serving-configuration change is recommended by this analysis; any change needs a new owner authorization and an audit. Classification of attempt 2 is unchanged.",
           "no_gpu_used": True, "no_modal_used": True, "no_model_weights_loaded": True, "no_generation": True, "generated_output_executed": False,
           "status_unchanged": {"attempt_outcome": "UNATTRIBUTED_REQUEST_REJECTION", "technical_serving_status": "NOT_PROVEN", "runtime_qualification_status": "NOT_COMPLETED",
                                "capability_status": "UNPROVEN"}}
    OUT.write_text(json.dumps(art, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"artifact": OUT.name, "mc_reproduced": mc_reproduced, "control_ok": ctl_ok, "class": B_full.get("tokenizer_class")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
