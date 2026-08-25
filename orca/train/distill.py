"""
Distillation pipeline — generate synthetic training data from a stronger
teacher model, in the exact ShareGPT format the existing fine-tuning
pipeline (orca/data/collector.py) already expects.

Two teacher backends:
  - Local Ollama (default) — teacher_model like "llama3.1:70b", needs the
    model pulled and running on your own GPU (the H100 discussed earlier).
    100% local, zero external calls, zero per-token cost beyond electricity.
  - Nvidia-hosted Nemotron (teacher_model="nvidia/nemotron-3-ultra-550b-a55b")
    — a 550B model, far beyond what a single H100 can run locally (needs
    ~275GB+ VRAM even 4-bit quantized). This is a CLOUD call: prompts for
    THIS distillation step leave your machine and go to Nvidia's API. That's
    a real tradeoff, but a bounded one — it's a one-time/batch data
    generation step, not routing live user chat through the cloud on every
    message. Requires NVIDIA_API_KEY (real key, real per-token cost on
    Nvidia's pricing — this module does not estimate that cost for you,
    check Nvidia's pricing page before running at scale).

HONEST SCOPE:
  This module builds the DATA GENERATION pipeline. It does not, by itself,
  make the model smarter — that still requires:
    1. A real teacher model actually capable of better reasoning than what
       you're distilling into (either your own local 70B+ model on the H100,
       or the Nvidia-hosted Nemotron option above).
    2. Running this generation loop for enough prompts (hundreds to
       thousands) to meaningfully shift training data composition — that's
       real wall-clock time (GPU-bound locally, or API-latency-and-cost-bound
       via Nvidia), not a quick script run.
    3. Actually re-running `orca train ultra` (or core/nano) on the
       resulting dataset — fine-tuning itself, separate from this step.
  This module is step 1 of that chain, built and tested against a small
  local model as a stand-in. Steps 2-3 need your hardware, your API budget,
  and your time.

Usage:
    from orca.train.distill import distill_from_seeds

    # Local teacher — 100% local, needs the model on your own GPU
    distill_from_seeds(teacher_model="llama3.1:70b", n_examples=500, variant="ultra")

    # Nvidia-hosted teacher — cloud call, needs NVIDIA_API_KEY env var set
    distill_from_seeds(teacher_model="nvidia/nemotron-3-ultra-550b-a55b", n_examples=500, variant="ultra")

    -> appends to ~/.orca/training/raw/{variant}_distilled_<date>.jsonl
       in the same ShareGPT format orca/data/collector.py already produces,
       so `orca data seed` / `orca train prepare` pick it up automatically.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from orca.config import ORCA_HOME
from orca.data.collector import RAW_DATA_DIR, Conversation, ORCA_SYSTEM_PROMPT
from orca.data.seeds import ALL_DOMAINS, sample_domains, build_prompt

DISTILL_LOG_DIR = ORCA_HOME / "training" / "distill_logs"
DISTILL_LOG_DIR.mkdir(parents=True, exist_ok=True)

NVIDIA_API_BASE = "https://integrate.api.nvidia.com/v1"

# A reasoning-trace instruction appended to the teacher prompt — asks the
# teacher to show its work, not just the final answer. Distilling reasoning
# traces (not just answers) is what actually improves the student's own
# reasoning quality, not just its factual recall.
REASONING_TRACE_SUFFIX = (
    "\n\nThink through this step by step before giving your final answer. "
    "Show your reasoning, then clearly state the conclusion."
)


def _ollama_teacher_generate(prompt: str, teacher_model: str, ollama_host: str, max_tokens: int) -> str:
    payload = json.dumps({
        "model": teacher_model,
        "prompt": prompt + REASONING_TRACE_SUFFIX,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.3},  # low temp — favor consistency for a teacher
    }).encode()
    req = urllib.request.Request(
        f"{ollama_host.rstrip('/')}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:  # generous timeout — teacher models are typically larger/slower
        data = json.loads(resp.read())
    return data.get("response", "")


OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

_CLOUD_MAX_RETRIES = 6
_CLOUD_BASE_BACKOFF = 8.0  # seconds — doubles each retry, so worst case ~8+16+32+64+128+256 = 504s of backoff


def _openai_compatible_generate(
    prompt: str, teacher_model: str, max_tokens: int, base_url: str, api_key: str, on_log=None
) -> str:
    """
    Shared retry/backoff logic for any OpenAI-compatible cloud teacher
    endpoint (Nvidia direct, OpenRouter, etc.) — same provider-agnostic HTTP
    contract, so one implementation instead of duplicating the retry logic
    per provider.

    Retries on 429 (rate limit) and 5xx with exponential backoff, preferring
    the server's own Retry-After header when present over a blind guess —
    the prior unthrottled version hit a rate-limit wall and logged ~290
    consecutive failures instead of slowing down, burning the whole run for
    nothing. A 429 is retried, not counted as a hard failure, unless retries
    exhaust.
    """
    from openai import OpenAI, APIStatusError

    log = on_log or (lambda msg: None)
    client = OpenAI(base_url=base_url, api_key=api_key)

    last_err: Exception | None = None
    for attempt in range(_CLOUD_MAX_RETRIES):
        try:
            completion = client.chat.completions.create(
                model=teacher_model,
                messages=[{"role": "user", "content": prompt + REASONING_TRACE_SUFFIX}],
                temperature=0.3,
                max_tokens=max_tokens,
            )
            return completion.choices[0].message.content or ""
        except APIStatusError as e:
            last_err = e
            if e.status_code not in (429, 500, 502, 503, 504):
                raise  # not a transient error — don't waste retries on e.g. 400/401

            # Prefer the server's own Retry-After signal over a blind guess —
            # it tells us exactly when the limit resets instead of us either
            # waiting longer than necessary (slower than it has to be) or
            # retrying too soon (another guaranteed 429).
            retry_after = None
            try:
                header_val = e.response.headers.get("retry-after")
                if header_val is not None:
                    retry_after = float(header_val)
            except Exception:
                retry_after = None

            backoff = retry_after if retry_after is not None else _CLOUD_BASE_BACKOFF * (2 ** attempt)
            source = "Retry-After header" if retry_after is not None else "exponential backoff"
            log(f"[distill] rate/server error ({e.status_code}), waiting {backoff:.0f}s per {source} "
                f"(attempt {attempt + 1}/{_CLOUD_MAX_RETRIES})")
            time.sleep(backoff)

    raise last_err  # retries exhausted — surface as a real failure


def _nvidia_teacher_generate(prompt: str, teacher_model: str, max_tokens: int, on_log=None) -> str:
    """Calls Nvidia's own hosted endpoint directly. Requires a real NVIDIA_API_KEY."""
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY not set. Distilling from a Nvidia-hosted teacher "
            "(e.g. nvidia/nemotron-3-ultra-550b-a55b) requires a real API key — "
            "cannot proceed without one. Never hardcode the key in source; set "
            "it as an environment variable."
        )
    return _openai_compatible_generate(prompt, teacher_model, max_tokens, NVIDIA_API_BASE, api_key, on_log)


def _openrouter_teacher_generate(prompt: str, teacher_model: str, max_tokens: int, on_log=None) -> str:
    """
    Calls the same teacher model via OpenRouter instead of Nvidia direct —
    a separate provider/account means a separate rate-limit bucket, which is
    the actual reason to use this path: routing around a rate wall on one
    provider, not a quality difference (same underlying model either way).
    Requires a real OPENROUTER_API_KEY.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set. Distilling via OpenRouter requires a "
            "real API key — cannot proceed without one. Never hardcode the key "
            "in source; set it as an environment variable."
        )
    return _openai_compatible_generate(prompt, teacher_model, max_tokens, OPENROUTER_API_BASE, api_key, on_log)


def _teacher_generate(
    prompt: str, teacher_model: str, ollama_host: str, max_tokens: int = 700,
    on_log=None, teacher_backend: str = "auto",
) -> str:
    """
    Dispatches to the right backend for a teacher call.

    teacher_backend:
      "auto"       — 'nvidia/*' model ids go to Nvidia direct, everything
                     else to local Ollama (original behavior, unchanged).
      "openrouter" — force routing through OpenRouter instead, even for a
                     'nvidia/*' model id — both providers use the same
                     'provider/model' naming, so backend choice can't be
                     inferred from the model string alone and must be explicit.
    """
    if teacher_backend == "openrouter":
        return _openrouter_teacher_generate(prompt, teacher_model, max_tokens, on_log=on_log)
    if teacher_model.startswith("nvidia/"):
        return _nvidia_teacher_generate(prompt, teacher_model, max_tokens, on_log=on_log)
    return _ollama_teacher_generate(prompt, teacher_model, ollama_host, max_tokens)


def distill_from_seeds(
    teacher_model: str,
    n_examples: int,
    variant: str = "ultra",
    ollama_host: str = "http://localhost:11434",
    domains: list | None = None,
    on_log=None,
    teacher_backend: str = "auto",
) -> dict:
    """
    Generates n_examples (prompt, teacher_response) pairs using orca's own
    seed domain prompts (orca/data/seeds.py — the same source `orca data
    seed` already draws from), but with the TEACHER model's response instead
    of the current generation pipeline's. Appends to the raw training data
    in ShareGPT format.

    teacher_backend: "auto" (default) picks Nvidia-direct for 'nvidia/*'
    model ids, local Ollama otherwise. Pass "openrouter" to force routing
    the same model through OpenRouter instead — useful for splitting load
    across two separate rate-limit buckets on two different providers.

    Returns a summary dict — counts, output file, failures.
    """
    log = on_log or (lambda msg: None)
    domain_names = [d.name for d in domains] if domains else None

    output_path = RAW_DATA_DIR / f"{variant}_distilled_{time.strftime('%Y%m%d')}.jsonl"
    log_path = DISTILL_LOG_DIR / f"distill_{teacher_model.replace('/', '-')}_{int(time.time())}.jsonl"

    written = 0
    failed = 0

    log(f"[distill] teacher: {teacher_model}  target: {n_examples} examples  -> {output_path}")

    # sample_domains(n, names) returns [(Domain, count), ...] weighted across
    # domains — flatten into one (domain, index) job per requested example.
    allocation = sample_domains(n_examples, domain_names)
    jobs = [domain for domain, count in allocation for _ in range(count)]

    with open(output_path, "a") as out_f, open(log_path, "w") as log_f:
        for i, domain in enumerate(jobs):
            # build_prompt returns (system, user) — the user half is the
            # actual instruction; the domain's system half describes the
            # domain framing, distinct from ORCA_SYSTEM_PROMPT used below.
            _domain_system, prompt_text = build_prompt(domain)

            try:
                response = _teacher_generate(
                    prompt_text, teacher_model, ollama_host, on_log=log, teacher_backend=teacher_backend
                )
            except Exception as e:
                failed += 1
                log(f"[distill] [{i+1}/{len(jobs)}] FAILED: {e}")
                continue

            if teacher_backend == "openrouter" or teacher_model.startswith("nvidia/"):
                # Proactive throttle, not just reactive backoff — the prior run
                # fired requests back-to-back and tripped the rate limit almost
                # immediately, then never recovered. Spacing requests out keeps
                # us under the limit instead of constantly hitting and retrying it.
                time.sleep(1.5)

            if not response.strip() or len(response.strip()) < 20:
                failed += 1
                log(f"[distill] [{i+1}/{len(jobs)}] empty/too-short response, skipped")
                continue

            convo = Conversation(source=f"distill:{teacher_model}", variant=variant)
            convo.add_system(ORCA_SYSTEM_PROMPT)
            convo.add_human(prompt_text)
            convo.add_gpt(response)

            if convo.is_valid():
                out_f.write(json.dumps(convo.to_dict()) + "\n")
                written += 1
                log(f"[distill] [{i+1}/{len(jobs)}] written — domain={domain.name}")
            else:
                failed += 1
                log(f"[distill] [{i+1}/{len(jobs)}] failed validity check, skipped")

            log_f.write(json.dumps({
                "i": i, "domain": domain.name, "prompt": prompt_text[:200],
                "response_preview": response[:300],
            }) + "\n")

    result = {
        "teacher_model": teacher_model,
        "variant": variant,
        "requested": n_examples,
        "written": written,
        "failed": failed,
        "output_file": str(output_path),
        "log_file": str(log_path),
    }
    log(f"[distill] done — {written} written, {failed} failed")
    return result
