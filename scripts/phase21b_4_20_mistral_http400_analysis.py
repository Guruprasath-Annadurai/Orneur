"""
Phase 21B.4.20 -- CPU-ONLY analysis: why did the exact pinned Mistral-Nemo server return HTTP 400 for all three canonical chat requests?

No GPU, no Modal, no model weights, no generation, no execution of any response text. It reads the immutable raw server log of attempt 1, the pinned
Mistral files (tokenizer/config/generation config/chat template) and the vLLM v0.29.0 sources at an immutable commit, runs the EXACT ORNEUR payloads
for A/B/C through the pinned HF tokenizer + chat template + tokenization on CPU (with the transformers/tokenizers versions recorded in the run's own
log), traces every payload field against the vLLM source, and writes ONE artifact. It never modifies any existing evidence and it does not invent a fix.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.simplefilter("ignore")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from orca.eval import locked_smoke_protocol as lp  # noqa: E402

EVIDENCE = REPO_ROOT / "docs/orneur/phase-21/evidence"
OUT = EVIDENCE / "GENESIS_MISTRAL_NEMO_HTTP400_CPU_ROOT_CAUSE_ANALYSIS_2026-09-25.json"
CACHE = Path("/tmp/p4420/mistral_src")
RAW_LOG = EVIDENCE / "GENESIS_CONTROL_MISTRAL_NEMO_MODAL_H100_ATTEMPT1_RAW_LOG_2026-09-24.txt"
RAW_LOG_SHA256 = "c4986233bce379dd1ff374ac856cee41235425e47886d455379f29852aed8aa3"
REV = "04d8a90549d23fc6bd7f642064003592df51e9b3"
VLLM_COMMIT = "98dff2a81d747d1dba01a47f939f48c3526d4206"       # tag v0.29.0
HF = f"https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/resolve/{REV}/"
GH = f"https://raw.githubusercontent.com/vllm-project/vllm/{VLLM_COMMIT}/"
HF_FILES = ("tokenizer.json", "special_tokens_map.json", "tokenizer_config.json", "config.json", "generation_config.json")
VLLM_FILES = {"renderers/hf.py": "vllm/renderers/hf.py", "renderers/params.py": "vllm/renderers/params.py", "renderers/registry.py": "vllm/renderers/registry.py",
              "chat_completion/protocol.py": "vllm/entrypoints/openai/chat_completion/protocol.py", "chat_completion/serving.py": "vllm/entrypoints/openai/chat_completion/serving.py",
              "serve/engine/serving.py": "vllm/entrypoints/serve/engine/serving.py",
              "exception_handling/validation.py": "vllm/entrypoints/serve/exception_handling/handlers/validation.py", "tokenizers/hf.py": "vllm/tokenizers/hf.py",
              "tokenizers/registry.py": "vllm/tokenizers/registry.py"}


def fetch(url: str, name: str) -> bytes:
    path = CACHE / name.replace("/", "__")
    if not path.is_file():
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as r:
            path.write_bytes(r.read())
    return path.read_bytes()


def snippet(text: str, anchor: str, before: int = 1, after: int = 4) -> dict:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if anchor in line:
            lo, hi = max(0, i - before), min(len(lines), i + after + 1)
            return {"anchor": anchor, "first_line": lo + 1, "text": "\n".join(lines[lo:hi])}
    raise SystemExit(f"anchor not found: {anchor!r}")


def main() -> int:
    hf_raw = {f: fetch(HF + f, f) for f in HF_FILES}
    vllm_raw = {k: fetch(GH + v, "vllm__" + v.replace("/", "__")) for k, v in VLLM_FILES.items()}
    assert hashlib.sha256(RAW_LOG.read_bytes()).hexdigest() == RAW_LOG_SHA256
    log = RAW_LOG.read_text()
    sources = {"pinned_hf": {f: {"url": HF + f, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for f, b in hf_raw.items()},
               "vllm_v0_29_0": {k: {"url": GH + VLLM_FILES[k], "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for k, b in vllm_raw.items()}}

    import tokenizers
    import transformers
    from jinja2 import Environment, meta
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(CACHE))
    tcfg = json.loads(hf_raw["tokenizer_config.json"])
    versions_in_run = re.search(r"versions: (\{.*\})", log).group(1)
    template_vars = sorted(meta.find_undeclared_variables(Environment().parse(tok.chat_template)))

    spec = importlib.util.spec_from_file_location("p21b420_runner_for_analysis", REPO_ROOT / "scripts/phase21b_4_20_lightning_runner.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    cfg = runner.serving_config("mistral_nemo")
    gen = {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": cfg["smoke_max_tokens"]}
    max_model_len = 4096
    trace = {}
    for smoke in cfg["smokes"]:
        sid = smoke["smoke_id"]
        payload = runner.build_chat_payload(cfg, smoke, gen)
        if smoke["stream"]:
            payload = dict(payload, stream=True, stream_options={"include_usage": True})
        conv = [{"role": "user", "content": payload["messages"][0]["content"]}]
        kw = dict(add_generation_prompt=True, continue_final_message=False, documents=None)          # what vLLM's HfRenderer forwards (reasoning_effort is filtered out)
        entry = {"exact_payload": payload, "payload_prompt_sha256": hashlib.sha256(payload["messages"][0]["content"].encode()).hexdigest(),
                 "prompt_is_canonical": payload["messages"] == lp.messages(sid),
                 "fields_sent": sorted(payload), "stages": {}}
        try:
            ids = tok.apply_chat_template(conversation=conv, tools=None, chat_template=tok.chat_template, tokenize=True, return_dict=False, **kw)
            text = tok.apply_chat_template(conversation=conv, tools=None, chat_template=tok.chat_template, tokenize=False, **kw)
            entry["stages"]["chat_template_render_and_tokenize_cpu"] = {"result": "PASS", "rendered_text": text, "token_ids": ids, "n_tokens": len(ids),
                                                                        "bos_count": ids.count(tok.bos_token_id), "eos_token": tok.eos_token}
            entry["stages"]["prompt_plus_max_tokens_within_max_model_len"] = {"result": "PASS" if len(ids) + payload["max_tokens"] <= max_model_len else "FAIL",
                                                                              "prompt_tokens": len(ids), "max_tokens": payload["max_tokens"], "max_model_len": max_model_len}
        except Exception as e:  # noqa: BLE001
            entry["stages"]["chat_template_render_and_tokenize_cpu"] = {"result": "FAIL", "error": f"{type(e).__name__}: {str(e)[:300]}"}
        trace[sid] = entry

    http = vllm_raw["renderers/hf.py"].decode()
    proto = (vllm_raw["chat_completion/protocol.py"]).decode()
    params = (vllm_raw["renderers/params.py"]).decode()
    serving = (vllm_raw["chat_completion/serving.py"]).decode()
    valid = (vllm_raw["exception_handling/validation.py"]).decode()
    log_lines = log.split("\n")
    post_lines = [i + 1 for i, ln in enumerate(log_lines) if '"POST /v1/chat/completions HTTP/1.1"' in ln]
    between = log_lines[post_lines[0] - 8: post_lines[-1]] if post_lines else []
    log_facts = {
        "raw_log_sha256": RAW_LOG_SHA256, "post_chat_completions_lines": post_lines,
        "line_numbering_note": "Python text-mode (universal-newline) line numbers; the file contains carriage returns (progress output) so `grep -n` numbers the same lines lower (POST lines 117-119)",
        "statuses": re.findall(r'"POST /v1/chat/completions HTTP/1.1" (\d{3})', log),
        "content_format_line": next((ln for ln in log_lines if "Detected the chat template content format" in ln), None),
        "versions_in_run": versions_in_run,
        "traceback_in_log": any("Traceback" in ln for ln in log_lines),
        "transformers_chat_template_exception_logged": any("An error occurred in `transformers` while applying chat template" in ln for ln in log_lines),
        "error_with_model_logged": any("Error with model" in ln for ln in log_lines),
        "error_level_lines_before_the_400s": [ln for ln in log_lines[: post_lines[0] - 1] if " ERROR " in ln] if post_lines else [],
        "window_before_and_including_the_400s": between,
        "request_latencies_seconds": re.findall(r"smoke ([ABC]) status=None latency=([0-9.]+)s", log)}

    source_evidence = {
        "template_failure_is_logged_and_wrapped_as_ValueError_400": {"file": "renderers/hf.py", **snippet(http, "An error occurred in `transformers` while applying chat template", 3, 2)},
        "kwargs_forwarded_to_apply_chat_template": {"file": "renderers/params.py", **snippet(params, "def get_apply_chat_template_kwargs", 0, 4)},
        "hf_renderer_tokenize_default_and_return_dict_false": {"file": "renderers/hf.py", **snippet(http, "Force `return_dict=False`", 3, 3)},
        "stream_options_requires_stream": {"file": "chat_completion/protocol.py", **snippet(proto, "Stream options can only be defined when `stream=True`", 3, 2)},
        "seed_field": {"file": "chat_completion/protocol.py", **snippet(proto, "seed: int | None = Field(None, ge=_INT64_MIN, le=_INT64_MAX)", 0, 0)},
        "check_model_failure_is_logged": {"file": "chat_completion/serving.py", **snippet(serving, "Error with model", 2, 2)},
        "create_error_response_default_is_400": {"file": "serve/engine/serving.py", **snippet(vllm_raw["serve/engine/serving.py"].decode(), "status_code: HTTPStatus = HTTPStatus.BAD_REQUEST", 3, 3)},
        "pydantic_request_validation_errors_are_logged_only_with_log_error_stack": {"file": "exception_handling/validation.py", **snippet(valid, "if req.app.state.args.log_error_stack", 1, 6)},
        "token_length_check": {"file": "renderers/params.py", **snippet(params, "if len(tokens) > max_input_tokens", 1, 4)},
        "max_output_vs_max_total_check": {"file": "renderers/params.py", **snippet(params, "max_output_tokens > max_total_tokens", 3, 4)},
    }

    field_trace = {
        "model": "mistralai/Mistral-Nemo-Instruct-2407 == --served-model-name (the run log shows no 'Error with model' line, and an unknown model would be 404 not 400)",
        "messages": "single user message, string content; content-format 'string' detected (log); renders + tokenizes on CPU (see stages)",
        "temperature": "0 -> float field, no constraint that rejects 0",
        "top_p": "1 -> float field, no constraint that rejects 1",
        "seed": "0 -> within the int64 field bounds",
        "max_tokens": "64 -> plain int field; max_output_tokens (64) is far below max_model_len (4096) and prompt+64 <= 4096 for A/B/C",
        "stream (A only)": "true", "stream_options.include_usage (A only)": "accepted because stream is true (B and C send no stream_options)",
        "summary": "no field is sent that the request schema, the sampling validation or the token-length checks reject",
        "qwen_comparison": "identical request fields succeeded for Qwen3-8B (HTTP 200) except: model, max_tokens (1024 vs 64), and the presence of chat_template_kwargs (Qwen only)"}

    comparison = {
        "qwen_attempt_5_vs_mistral_attempt_1": {
            "same": ["runner request builder", "temperature 0", "top_p 1", "seed 0", "stream mode per smoke", "vLLM 0.29.0 image", "HF renderer", "OpenAI chat-completions endpoint"],
            "different": ["model / tokenizer / chat template", "max_tokens 1024 vs 64", "chat_template_kwargs present vs absent", "server flags (--reasoning-parser qwen3 vs --tokenizer-mode hf --config-format hf --load-format safetensors)"]},
        "hf_tokenizer_mode_compatibility": {
            "cpu_result": "chat template renders and tokenizes with the pinned HF tokenizer for all three payloads (transformers %s, tokenizers %s)" % (transformers.__version__, tokenizers.__version__),
            "caveat_observed": "transformers logs that the pinned tokenizer.json has an 'incorrect regex pattern' (\"This will lead to incorrect tokenization\"); this concerns tokenization fidelity under hf mode, not request validation, and is not shown to cause the 400",
            "not_established": "whether hf tokenizer mode is fully compatible with ChatCompletion for this revision on the real server"},
        "alternative_official_mistral_flags": {
            "fact": "vLLM v0.29.0 registers a separate 'mistral' tokenizer mode and renderer (mistral-common based) and the pinned repo also ships consolidated.safetensors, params.json and tekken.json; the owner locked the hf path",
            "not_established": "that the hf flags are unsupported or that the mistral flags are required; no change is proposed"}}

    decision = {
        "answer": "B. ROOT CAUSE NOT ESTABLISHED CPU-ONLY",
        "why": ["the exact HTTP 400 was not reproduced: vLLM's request model, renderer, engine input path and server were not executed (vLLM is not installable on this CPU host and the model must not be loaded)",
                "every stage that could be run on CPU with the exact payloads passes: chat-template render, tokenization, length checks (transformers 5.16.1 / tokenizers 0.23.2 = the run's own versions)",
                "no field/value in the ORNEUR payload was found, in the vLLM v0.29.0 sources, to be rejected on this Mistral path",
                "the immutable raw server log contains no traceback and no 'An error occurred in `transformers` while applying chat template' line, which the template path would log; that makes a template-application error unlikely but does not prove it, and it does not exclude the paths vLLM does not log (pydantic request-validation rejections are logged only with --log-error-stack, and ValueError -> create_error_response paths are not logged)",
                "the API error bodies were never captured, which is the only direct evidence of the cause"],
        "not_invented": "no fix is proposed; nothing was changed to make a test pass",
        "classification_of_the_issue": "UNATTRIBUTED (harness/request configuration vs vLLM runtime vs tokenizer/template vs model runtime cannot be distinguished)",
        "narrowing": {"excluded_or_unlikely": ["model name mismatch", "prompt too long", "streaming option misuse", "seed/temperature/top_p/max_tokens range violations", "chat-template render exception (logged, absent)"],
                      "remaining": ["a rejection inside vLLM's request/renderer path that is not logged", "an interaction between hf tokenizer mode and the Mistral repo files on the real server"]},
        "what_would_establish_it": "one authorized run of the SAME configuration with the runner's HTTP error-body capture (already implemented) would record the API error body; that would require its own owner authorization and a new attempt",
        "correction_changes_model_identity": "n/a (no correction proposed)", "correction_changes_canonical_prompts": "n/a", "correction_changes_sampling": "n/a"}

    artifact = {
        "evidence_type": "MISTRAL_NEMO_HTTP400_CPU_ONLY_ROOT_CAUSE_ANALYSIS", "phase": "21B.4.20", "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "no_gpu_used": True, "no_modal_used": True, "no_model_weights_loaded": True, "no_generation": True, "generated_output_executed": False, "mistral_rerun": False,
        "subject": {"model_id": "mistralai/Mistral-Nemo-Instruct-2407", "revision": REV, "attempt": 1, "server_flags": cfg["extra_args"], "canonical_protocol_sha256": lp.protocol_sha256()},
        "cpu_library_versions_used": {"transformers": transformers.__version__, "tokenizers": tokenizers.__version__, "in_run_log": versions_in_run},
        "sources": sources,
        "pinned_files_facts": {"tokenizer_class": tcfg.get("tokenizer_class"), "bos_token": tcfg.get("bos_token"), "eos_token": tcfg.get("eos_token"), "add_bos_token": tcfg.get("add_bos_token"),
                               "chat_template_present": bool(tok.chat_template), "chat_template_chars": len(tok.chat_template), "chat_template_undeclared_variables": template_vars,
                               "config_json_architectures": json.loads(hf_raw["config.json"]).get("architectures"),
                               "generation_config": json.loads(hf_raw["generation_config.json"]), "vocab_size": len(tok)},
        "request_by_request_trace": trace, "field_by_field_trace": field_trace, "raw_server_log_facts": log_facts, "vllm_source_evidence": source_evidence,
        "comparison": comparison, "decision": decision,
        "status_unchanged": {"mistral_nemo": "NOT_PROVEN / NOT_COMPLETED", "qwen3_8b": "FAILED", "phi4": "NOT_TESTED", "capability": "UNPROVEN"}}
    OUT.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"artifact": OUT.name, "decision": decision["answer"], "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
                      "stages": {k: {s: v["result"] for s, v in e["stages"].items() if isinstance(v, dict) and "result" in v} for k, e in trace.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
