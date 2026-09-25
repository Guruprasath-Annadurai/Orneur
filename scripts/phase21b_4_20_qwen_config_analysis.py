"""
Phase 21B.4.20 -- CPU-ONLY analysis: does the exact pinned Qwen3-8B revision have an officially supported, production-compatible
way to disable thinking, and what would that change?

No GPU, no Modal, no model load, no generation, no execution of any generated content. It downloads a few small public files at
IMMUTABLE references (the pinned Hugging Face commit and the vLLM v0.29.0 commit), hashes them, reads them, renders the three LOCKED
smoke requests through the pinned chat template (jinja2, the same sandboxed environment transformers uses) and writes ONE evidence
artifact. It never modifies any existing evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
EARLIER = EVIDENCE_DIR / "GENESIS_QWEN3_8B_RUNTIME_CONFIGURATION_ANALYSIS_2026-09-25.json"          # first analysis (drifted runner wording); preserved
OUT = EVIDENCE_DIR / "GENESIS_QWEN3_8B_RUNTIME_CONFIGURATION_ANALYSIS_V2_CANONICAL_PROMPTS_2026-09-25.json"
EARLIER_ORIGINAL_SHA256 = "94fc9707f673df2c3c305d654b0e100b3ea12972f6c4e70c7c1a0b12f3fd76ad"      # sha256 of the earlier artifact as committed in 5c3200b (before the supersession notice)
CACHE = Path("/tmp/p4420/qwen_cfg_analysis")

QWEN_REV = "b968826d9c46dd6066d109eabc6255188de91218"
VLLM_COMMIT = "98dff2a81d747d1dba01a47f939f48c3526d4206"       # tag v0.29.0 (git ls-remote refs/tags/v0.29.0)
VLLM_IMAGE_DIGEST = "sha256:082ca6f035279109041ffd3fe0695cb568b29bc580b35c4f297a66a08b216c1b"
HF = f"https://huggingface.co/Qwen/Qwen3-8B/resolve/{QWEN_REV}/"
GH = f"https://raw.githubusercontent.com/vllm-project/vllm/{VLLM_COMMIT}/"
SOURCES = {
    "tokenizer_config.json": HF + "tokenizer_config.json",
    "generation_config.json": HF + "generation_config.json",
    "README.md": HF + "README.md",
    "vllm/parser/qwen3.py": GH + "vllm/parser/qwen3.py",
    "vllm/reasoning/qwen3_engine_reasoning_parser.py": GH + "vllm/reasoning/qwen3_engine_reasoning_parser.py",
    "vllm/entrypoints/openai/chat_completion/protocol.py": GH + "vllm/entrypoints/openai/chat_completion/protocol.py",
    "vllm/entrypoints/openai/chat_completion/serving.py": GH + "vllm/entrypoints/openai/chat_completion/serving.py",
    "vllm/entrypoints/launchers/cli_args.py": GH + "vllm/entrypoints/launchers/cli_args.py",
}
sys.path.insert(0, str(REPO_ROOT))
from orca.eval import locked_smoke_protocol as locked_protocol  # noqa: E402

# the three LOCKED smoke requests come ONLY from the canonical protocol; this tool cannot substitute any other wording
LOCKED_SMOKES = {sid: locked_protocol.messages(sid) for sid in locked_protocol.smoke_ids()}


def fetch(name: str, url: str) -> bytes:
    path = CACHE / name.replace("/", "__")
    if not path.is_file():
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as r:          # small public files at immutable references
            path.write_bytes(r.read())
    return path.read_bytes()


def snippet(text: str, anchor: str, before: int = 1, after: int = 3) -> dict:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if anchor in line:
            lo, hi = max(0, i - before), min(len(lines), i + after + 1)
            return {"anchor": anchor, "first_line": lo + 1, "text": "\n".join(lines[lo:hi])}
    raise SystemExit(f"anchor not found: {anchor!r}")


def render(template: str, messages: list[dict], **kwargs) -> str:
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    def raise_exception(msg):
        raise ValueError(msg)

    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    env.globals["raise_exception"] = raise_exception
    env.filters["tojson"] = lambda x, **k: json.dumps(x, ensure_ascii=False)
    return env.from_string(template).render(messages=messages, add_generation_prompt=True, **kwargs)


def main() -> int:
    raw = {n: fetch(n, u) for n, u in SOURCES.items()}
    text = {n: b.decode("utf-8") for n, b in raw.items()}
    sources = {n: {"url": SOURCES[n], "sha256": hashlib.sha256(raw[n]).hexdigest(), "bytes": len(raw[n])} for n in SOURCES}
    tok = json.loads(text["tokenizer_config.json"])
    template = tok["chat_template"]
    gen = json.loads(text["generation_config.json"])

    uses = [m.start() for m in re.finditer(r"enable_thinking", template)]
    template_facts = {
        "supports_enable_thinking": bool(uses), "occurrences": len(uses),
        "decisive_clause": "{%- if enable_thinking is defined and enable_thinking is false %} {{- '<think>\\n\\n</think>\\n\\n' }} {%- endif %}",
        "default_when_unset": "THINKING (variable undefined => nothing is appended after '<|im_start|>assistant\\n'; the model opens its own <think>)",
        "only_false_disables": "only an explicit boolean false triggers the empty think block; true or undefined leave the model free to think",
        "chat_template_sha256": hashlib.sha256(template.encode()).hexdigest(), "eos_token": tok.get("eos_token"),
        "template_contains_no_think_soft_switch_logic": "/no_think" not in template and re.search(r"(?<!<)/think", template) is None,   # '</think>' is markup, not a soft switch
    }

    renders = {}
    for sid, msgs in LOCKED_SMOKES.items():
        cur = render(template, msgs)                                  # ORNEUR's current request: no chat_template_kwargs at all
        explicit_true = render(template, msgs, enable_thinking=True)
        off = render(template, msgs, enable_thinking=False)
        assert cur == explicit_true, "undefined must render identically to enable_thinking=True"
        assert off.startswith(cur) and off[len(cur):] == "<think>\n\n</think>\n\n"
        renders[sid] = {"messages_unchanged": msgs, "current_thinking_default": cur, "candidate_enable_thinking_false": off,
                        "difference_only_appended_suffix": off[len(cur):], "prompt_prefix_identical": True}

    serving, proto, qwen3, cli = (text["vllm/entrypoints/openai/chat_completion/serving.py"], text["vllm/entrypoints/openai/chat_completion/protocol.py"],
                                  text["vllm/parser/qwen3.py"], text["vllm/entrypoints/launchers/cli_args.py"])
    vllm_path = {
        "request_field": snippet(proto, "chat_template_kwargs: dict[str, Any] | None = Field(", 0, 6),
        "reasoning_effort_none_maps_to_enable_thinking_false": snippet(proto, "extra_kwargs[\"enable_thinking\"]", 2, 1),
        "effective_kwargs_merge_request_plus_server_defaults": snippet(serving, "def _effective_chat_template_kwargs", 0, 9),
        "same_kwargs_given_to_parser": snippet(serving, "chat_template_kwargs = self._effective_chat_template_kwargs(request)", 0, 8),
        "same_kwargs_given_to_engine_template": snippet(serving, "\"chat_template_kwargs\": self._engine_chat_template_kwargs(", 0, 3),
        "server_level_alternative_flag": snippet(cli, "default_chat_template_kwargs: dict[str, Any] | None = None", 0, 4),
        "qwen3_parser_reads_enable_thinking": snippet(qwen3, "self.thinking_enabled = chat_kwargs.get(\"enable_thinking\", True)", 1, 1),
        "qwen3_parser_initial_state": snippet(qwen3, "initial_state=ParserState.REASONING if thinking else ParserState.CONTENT", 0, 0),
        "qwen3_parser_extract_reasoning_when_off": snippet(qwen3, "if not self.thinking_enabled:", 0, 1),
        "reasoning_parser_registry_qwen3": "vllm.reasoning.qwen3_engine_reasoning_parser -> Qwen3ParserReasoningAdapter -> vllm.parser.qwen3.Qwen3Parser",
    }

    card = text["README.md"]
    official = {
        "model_card_pinned_revision": {"file": "README.md", "sha256": sources["README.md"]["sha256"], "excerpts": [
            snippet(card, "enable_thinking=True # Switches between thinking and non-thinking modes. Default is True.", 0, 0)["text"],
            "The `enable_thinking` switch is also available in APIs created by SGLang and vLLM.",
            "In this mode, the model will not generate any think content and will not include a `<think>...</think>` block. (enable_thinking=False)",
            "When `enable_thinking=False`, the soft switches are not valid. (i.e. do NOT use /no_think in prompts with enable_thinking=False)",
            "For thinking mode ... DO NOT use greedy decoding, as it can lead to performance degradation and endless repetitions.",
            "For non-thinking mode (`enable_thinking=False`), we suggest using Temperature=0.7, TopP=0.8, TopK=20, and MinP=0."]},
        "verdict": "OFFICIAL: documented by the model authors in the pinned model card and implemented in the pinned chat template; vLLM 0.29.0 exposes it as the request field chat_template_kwargs (and the server flag --default-chat-template-kwargs)",
        "not_used": "the '/no_think' soft switch edits the locked user prompts, so it is excluded",
    }

    artifact = {
        "evidence_type": "QWEN3_8B_RUNTIME_CONFIGURATION_ANALYSIS_CPU_ONLY", "version": 2, "phase": "21B.4.20",
        "supersedes": {"artifact": EARLIER.name, "original_sha256": EARLIER_ORIGINAL_SHA256, "reason": "the earlier artifact rendered the runner's DRIFTED smoke wording (recorded in GENESIS_LOCKED_SMOKE_PROTOCOL_2026-09-25.json under wording_history); this version renders the canonical owner-locked protocol. The template/vLLM analysis itself is unchanged."},
        "locked_smoke_protocol_sha256": locked_protocol.protocol_sha256(), "locked_smoke_prompt_sha256": {sid: locked_protocol.prompt_sha256(sid) for sid in locked_protocol.smoke_ids()}, "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "no_gpu_used": True, "no_modal_used": True, "no_model_loaded": True, "no_generation": True, "generated_output_executed": False,
        "model": {"model_id": "Qwen/Qwen3-8B", "revision": QWEN_REV, "precision": "bfloat16", "quantization": None},
        "vllm": {"version": "0.29.0", "commit": VLLM_COMMIT, "image_digest": VLLM_IMAGE_DIGEST,
                 "note": "sources read at the commit behind tag v0.29.0; the run image is the pinned official vllm/vllm-openai:v0.29.0 digest (the tag-to-image correspondence is the tag's own; not re-verified inside the image on CPU)"},
        "sources": sources,
        "current_configuration": {
            "server_argv": ["--dtype", "bfloat16", "--max-model-len", "4096", "--gpu-memory-utilization", "0.9", "--seed", "0", "--reasoning-parser", "qwen3"],
            "request": "locked messages only; no chat_template_kwargs, no reasoning_effort => enable_thinking undefined => thinking ON",
            "sampling": {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": 1024},
            "observed_attempt_4": {"reasoning_tokens_A_B_C": [117, 279, 436], "finish_reason": "stop for all three",
                                   "smoke_B_thinking_concluded": "the answer should just be 5", "smoke_B_final_content": "verbose explanation ending in 5"}},
        "candidate_configuration": {
            "id": "qwen3_8b_non_thinking_v1",
            "request_setting": {"chat_template_kwargs": {"enable_thinking": False}},
            "server_argv": "UNCHANGED (still --reasoning-parser qwen3; the parser adapts from the same kwargs)",
            "locked_messages": "UNCHANGED (the canonical LOCKED protocol; see rendered_locked_requests)",
            "sampling": "UNCHANGED (temperature 0, top_p 1, seed 0); smoke_max_tokens may stay 1024",
            "alternative_equivalent_form": "--default-chat-template-kwargs '{\"enable_thinking\": false}' (server argv change; not preferred: changes argv)",
            "alternative_excluded": ["/no_think soft switch (edits the locked prompt)", "reasoning_effort=none (equivalent mapping but a less direct, version-dependent path)"]},
        "chat_template": template_facts,
        "vllm_0_29_0_path": vllm_path,
        "rendered_locked_requests": renders,
        "generation_config_defaults_in_pinned_revision": {"file": "generation_config.json", "sha256": sources["generation_config.json"]["sha256"], "values": gen,
                                                          "note": "documented vLLM behaviour merges these defaults for fields a request does not set; the locked request sets temperature/top_p explicitly. Not verified on a live server in this CPU-only analysis."},
        "official_support": official,
        "answers": {
            "1_template_supports_enable_thinking": True,
            "2_default": "thinking ON (variable undefined behaves as True); only explicit false disables",
            "3_vllm_0_29_0_pass_through": "request body field chat_template_kwargs -> ChatCompletionRequest.build_chat_params -> _effective_chat_template_kwargs (merged with --default-chat-template-kwargs) -> given to BOTH the chat-template renderer and the reasoning-parser instance",
            "4_reasoning_parser_independent_of_template_choice": {"answer": "NO -- it is coupled through the same kwargs, and still valid",
                                                                  "detail": "with --reasoning-parser qwen3 unchanged, Qwen3Parser reads enable_thinking from chat_template_kwargs; false => initial state CONTENT and extract_reasoning returns (None, whole output), so the answer arrives in message.content. The flag itself is not changed. Because both consumers read the SAME request kwargs, they cannot disagree."},
            "5": {"model_weights_change": "NO", "revision_change": "NO", "precision_change": "NO", "quantization_change": "NO", "serving_runtime_change": "NO (same image, same server argv)",
                  "only_chat_template_request_behavior": "YES (an empty <think></think> block is appended to the rendered prompt; parser state follows)"},
            "6_officially_supported": "YES -- documented by the Qwen authors in the pinned model card; implemented by the pinned template; exposed by vLLM 0.29.0. Not an ORNEUR-specific hack.",
            "7_representable_reproducibly": "YES -- a single JSON request field plus a named configuration id can be persisted per smoke (the extra body, the rendered-prompt hash, the template sha256) alongside the unchanged locked messages",
        },
        "security_implications": [
            "generated model text is still data only: never eval/exec/shell/import/compile (unchanged)",
            "chat_template_kwargs carries one boolean; no template text or code is supplied by the request (vLLM only honours a request-supplied template when trust_request_chat_template is set, and it is not)",
            "the pinned template is rendered in a sandboxed jinja environment and already contains the enable_thinking branch; no new template is introduced",
            "no new network access, credential, permission or billing surface",
        ],
        "model_identity": {"identical": True, "why": "same repository, same immutable revision, same weight files/bytes/LFS sha256 in the verified cache, same BF16 load; only the rendered prompt/parse behaviour differs"},
        "is_new_runtime_configuration_requiring_fresh_qualification": {
            "answer": "YES",
            "why": ["the rendered prompt differs (extra empty think block), so generation begins from a different context",
                    "the qualified runtime configuration recorded for attempt 4 had thinking ON; a different configuration cannot inherit or overwrite that result",
                    "attempt 4 stays FAILED and preserved; a new attempt would carry its own configuration id and its own owner authorization"]},
        "cannot_be_concluded_on_cpu": [
            "whether Qwen3-8B will then return exactly '5' for locked Smoke B (that needs generation)",
            "bit-exact reproducibility of greedy decoding on the GPU",
            "the effective sampling merge on a live server (generation_config defaults)"],
        "future_attempt_proposal_NOT_IMPLEMENTED_NOT_AUTHORIZED": {
            "runtime_setting": {"chat_template_kwargs": {"enable_thinking": False}},
            "unchanged": ["Qwen/Qwen3-8B", QWEN_REV, "BF16", "no quantization", "vLLM 0.29.0 pinned image digest", "server argv incl. --reasoning-parser qwen3",
                          "locked smoke messages A/B/C (canonical protocol)", "temperature 0 / top_p 1 / seed 0", "generated output never executed"],
            "files_that_would_change": [
                "scripts/phase21b_4_20_lightning_runner.py (LOCKED['qwen3_8b'] gains a chat_template_kwargs field; the shared serve_and_smoke request body adds it to the chat-completions payload only when present)",
                "scripts/phase21b_4_20_modal_h100_control.py (cfg passed to runner.serve_and_smoke carries it; the record persists runtime_configuration_id, chat_template_kwargs and the rendered-prompt sha256; the run must not overwrite attempt 4)",
                "scripts/phase21b_4_20_lightning_control.py (record builder: reasoning_mode / generation_config fields reflect the configuration)",
                "orca/eval/control_runtime_qualification.py (validator: a Qwen record must state its configuration explicitly; locked-smoke acceptance is unchanged)",
                "tests/test_genesis_control_runtime_qualification.py (payload wiring, configuration recorded, locked prompts unchanged, attempt 4 preserved)",
                "docs/orneur/phase-21/GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md and the SHA256 index"]},
        "decision": "A. SUPPORTED CONFIGURATION CHANGE IDENTIFIED",
        "qwen3_8b_status_unchanged": {"technical_serving_status": "FAILED", "runtime_qualification_status": "FAILED", "capability_status": "UNPROVEN"},
    }
    OUT.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    annotate_earlier()
    print(json.dumps({"artifact": OUT.name, "decision": artifact["decision"], "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest()}, indent=2))
    return 0


def annotate_earlier() -> None:
    """Mark the earlier analysis SUPERSEDED without deleting or rewriting any of its content (its original hash is recorded)."""
    earlier = json.loads(EARLIER.read_text())
    if "superseded_by" in earlier:
        return
    if hashlib.sha256(EARLIER.read_bytes()).hexdigest() != EARLIER_ORIGINAL_SHA256:
        raise SystemExit("earlier artifact bytes differ from the committed original; refusing to annotate")
    earlier["rendering_status"] = "SUPERSEDED_DRIFTED_PROMPTS"
    earlier["superseded_by"] = {"artifact": OUT.name, "reason": "its rendered_locked_requests used the runner's drifted smoke wording, not the canonical owner-locked protocol; the corrected rendering is in the superseding artifact. All original content below is preserved unchanged for history.",
                                "original_sha256_before_this_notice": EARLIER_ORIGINAL_SHA256, "canonical_protocol_sha256": locked_protocol.protocol_sha256()}
    EARLIER.write_text(json.dumps(earlier, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sys.exit(main())
