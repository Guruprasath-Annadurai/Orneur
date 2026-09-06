"""
Orca Backend Layer — routes each tier to self-hosted Ollama OR a frontier
API (OpenAI/Anthropic), behind Orca's existing governance stack.

This is the concrete implementation of the "bring-your-own-frontier-model"
product thesis (see docs/STARTUP_PLAN.md §2): a customer who needs full data
sovereignty runs entirely on self-hosted Genesis/Novus/Aeternum (OllamaBackend,
$0 marginal cost, data never leaves their infrastructure). A customer who
wants frontier capability with Orca's compliance wrapper around it can point
a tier at OpenAI or Anthropic instead — same audit log, same moderation,
same RBAC, same billing integration, different model underneath.

WHY THIS ISN'T A GENERIC MULTI-PROVIDER SDK WRAPPER:
  - Every backend reports real token usage and cost — self-hosted is
    always $0 marginal (already-owned/rented compute), frontier APIs cost
    real money per token. This feeds directly into orca/serve/metrics.py
    and, eventually, usage-based billing on top of orca/license/stripe_hook.py.
  - A backend's identity travels with every response (BackendResponse.backend,
    .model, .data_left_infrastructure) specifically so orca/serve/api.py can
    write an honest audit log entry — "this request never left your
    infrastructure" vs "this request was sent to Anthropic" is the actual
    product for a compliance-driven buyer, not an implementation detail to
    hide.
  - Data-sovereignty enforcement (DATA_SOVEREIGNTY_LOCK) lives at the
    resolution layer (orca/serve/registry.py), not here — a locked
    deployment should never even construct a non-Ollama backend instance,
    let alone call it. That's a fail-closed design, not a warning.
  - Persona/capability-claim gating differs by backend on purpose (see
    orca/personas.py and orca/governance/model_cards.py): a self-hosted
    fine-tune's capability CLAIM is Orca's own to verify (eval/redteam data
    Orca generated). A frontier-API passthrough is a claim about a model
    Orca never trained — applying Orca's narrow redteam thresholds to
    GPT-4/Claude would be both unfair to the provider and meaningless as
    a safety signal. The honest move there is disclosure, not a score.

HONEST SCOPE:
  - OpenAIBackend uses the official `openai` SDK (already a project
    dependency via the `nvidia` extra's openai>=1.0.0 requirement).
  - AnthropicBackend uses the official `anthropic` SDK via a deferred
    import (same pattern as chromadb/diffusers elsewhere in this
    codebase) — it's a NEW optional dependency (see pyproject.toml's
    `frontier` extra), not yet installed in this environment, so its
    live path is untested here. The unit tests below mock the SDK calls;
    treat the real HTTP path as unverified until it's actually run
    against a real API key.
  - Pricing tables are approximate, hand-maintained snapshots — provider
    pricing changes. Do not treat cost_usd as billing-grade without
    verifying against the provider's current published rates.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Protocol

import httpx

from orca.config import CONFIG

# ─────────────────────────────────────────────────────────────────────────────
#  Approximate per-million-token pricing — hand-maintained, verify before
#  treating as billing-grade. USD.
# ─────────────────────────────────────────────────────────────────────────────

_OPENAI_PRICING_PER_MILLION = {
    "gpt-4o":       {"input": 2.50, "output": 10.00},
    "gpt-4o-mini":  {"input": 0.15, "output": 0.60},
    "gpt-4-turbo":  {"input": 10.00, "output": 30.00},
}

_ANTHROPIC_PRICING_PER_MILLION = {
    "claude-opus-4-8":   {"input": 5.00, "output": 25.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5":  {"input": 1.00, "output": 5.00},
}


def _estimate_cost(pricing_table: dict, model: str, input_tokens: int, output_tokens: int) -> float:
    rates = pricing_table.get(model)
    if not rates:
        return 0.0  # unknown model — don't fabricate a cost, surface as 0 and let ops notice the gap
    return round(
        input_tokens / 1_000_000 * rates["input"] + output_tokens / 1_000_000 * rates["output"], 6
    )


@dataclass
class BackendResponse:
    text: str
    backend: str            # "ollama" | "openai" | "anthropic"
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    data_left_infrastructure: bool  # False for Ollama (self-hosted), True for any external API


class Backend(Protocol):
    name: str

    def generate(
        self, prompt: str, system: str = "", max_tokens: int = 1024, temperature: float = 0.7,
    ) -> BackendResponse: ...

    def is_available(self) -> bool: ...


class OllamaBackend:
    """Self-hosted inference — $0 marginal cost, data never leaves this
    machine/deployment. Wraps the same Ollama HTTP API orca/brain/providers.py
    already uses, kept as a separate thin implementation here so this module
    has no dependency on OrcaBrain's model-resolution logic (that stays in
    providers.py; this module is purely about backend EXECUTION once a
    model name has already been resolved)."""

    name = "ollama"

    def __init__(self, model: str, host: Optional[str] = None):
        self.model = model
        self.host = (host or CONFIG.ollama.host).rstrip("/")

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
            return True
        except Exception:
            return False

    def generate(
        self, prompt: str, system: str = "", max_tokens: int = 1024, temperature: float = 0.7,
    ) -> BackendResponse:
        t0 = time.time()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        r = httpx.post(f"{self.host}/api/generate", json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        # Ollama reports token counts for local models; not all versions
        # populate these fields, so default to 0 rather than raising.
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)
        return BackendResponse(
            text=data.get("response", ""),
            backend=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=0.0,
            latency_ms=(time.time() - t0) * 1000,
            data_left_infrastructure=False,
        )


class OpenAIBackend:
    """Frontier-API passthrough via OpenAI. Real cost per token — see
    _OPENAI_PRICING_PER_MILLION. data_left_infrastructure=True always."""

    name = "openai"

    def __init__(self, model: str, api_key: str):
        if not api_key:
            raise ValueError("OpenAIBackend requires an API key (set ORCA_OPENAI_API_KEY).")
        self.model = model
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def is_available(self) -> bool:
        return bool(self._api_key)

    def generate(
        self, prompt: str, system: str = "", max_tokens: int = 1024, temperature: float = 0.7,
    ) -> BackendResponse:
        t0 = time.time()
        client = self._get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = client.chat.completions.create(
            model=self.model, messages=messages, max_tokens=max_tokens, temperature=temperature,
        )
        text = resp.choices[0].message.content or ""
        input_tokens = resp.usage.prompt_tokens if resp.usage else 0
        output_tokens = resp.usage.completion_tokens if resp.usage else 0

        return BackendResponse(
            text=text,
            backend=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_estimate_cost(_OPENAI_PRICING_PER_MILLION, self.model, input_tokens, output_tokens),
            latency_ms=(time.time() - t0) * 1000,
            data_left_infrastructure=True,
        )


class AnthropicBackend:
    """Frontier-API passthrough via Anthropic. Deferred SDK import (same
    pattern as chromadb/diffusers elsewhere) — `anthropic` is an optional
    dependency (pyproject.toml `frontier` extra), not required unless a
    deployment actually configures this backend."""

    name = "anthropic"

    def __init__(self, model: str, api_key: str):
        if not api_key:
            raise ValueError("AnthropicBackend requires an API key (set ORCA_ANTHROPIC_API_KEY).")
        self.model = model
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise ImportError(
                    "AnthropicBackend requires the 'anthropic' package. "
                    "Install with: pip install -e '.[frontier]'"
                ) from e
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def is_available(self) -> bool:
        return bool(self._api_key)

    def generate(
        self, prompt: str, system: str = "", max_tokens: int = 1024, temperature: float = 0.7,
    ) -> BackendResponse:
        t0 = time.time()
        client = self._get_client()

        resp = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or None,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        input_tokens = resp.usage.input_tokens if resp.usage else 0
        output_tokens = resp.usage.output_tokens if resp.usage else 0

        return BackendResponse(
            text=text,
            backend=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_estimate_cost(_ANTHROPIC_PRICING_PER_MILLION, self.model, input_tokens, output_tokens),
            latency_ms=(time.time() - t0) * 1000,
            data_left_infrastructure=True,
        )


def build_backend(backend_name: str, model: str, **kwargs) -> Backend:
    """Factory — orca/serve/registry.py is the only intended caller, since
    it's also where the data-sovereignty lock is enforced (a locked
    deployment must never reach this factory with a non-ollama backend
    name in the first place)."""
    if backend_name == "ollama":
        return OllamaBackend(model=model, host=kwargs.get("host"))
    if backend_name == "openai":
        return OpenAIBackend(model=model, api_key=kwargs.get("api_key", ""))
    if backend_name == "anthropic":
        return AnthropicBackend(model=model, api_key=kwargs.get("api_key", ""))
    raise ValueError(f"Unknown backend '{backend_name}'. Available: ollama, openai, anthropic")
