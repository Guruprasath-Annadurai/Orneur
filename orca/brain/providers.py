"""
Orca Brain — 100% local, 100% yours.

No external APIs. No Anthropic. No OpenAI. No data leaving your machine.
All inference runs through Ollama on your hardware.

Model priority:
  1. Your fine-tuned 'orca' model (the goal)
  2. Best available open-weight model as interim brain
  3. Error — install Ollama

Set via environment:
  ORCA_CORE_MODEL=orca           ← your fine-tuned model name in Ollama
  ORCA_NANO_MODEL=orca-nano      ← lightweight variant
  ORCA_OLLAMA_HOST=localhost:11434
"""
from __future__ import annotations

import json
import os
from typing import Iterator

import httpx

from orca.config import CONFIG

PREFERRED_OPEN_MODELS = [
    "llama3.1:8b",
    "llama3.1:70b",
    "llama3:8b",
    "mistral:7b",
    "qwen2.5:7b",
    "gemma2:9b",
    "phi3:medium",
]


class OrcaBrain:
    """
    Orca's local brain — talks to Ollama, uses YOUR model when available.
    Zero network calls to any third party. Runs entirely on your machine.
    """

    def __init__(self, model: str | None = None, host: str | None = None):
        self.host = host or CONFIG.ollama.host
        self._requested_model = model
        self._resolved_model: str | None = None

    @property
    def model(self) -> str:
        if self._resolved_model is None:
            self._resolved_model = self._resolve_model()
        return self._resolved_model

    def _resolve_model(self) -> str:
        available = self._list_available()

        # Explicit model requested
        if self._requested_model:
            # Ollama's /api/tags always returns tagged names (e.g.
            # "orca-nano:latest"), but a configured/resolved model name is
            # typically bare ("orca-nano") — a real production bug found via
            # load testing: every chat request failed with "model not found"
            # even though the exact model WAS listed, just under its tagged
            # name. Accept either form, same normalization
            # orca/serve/registry.py's _model_installed() already applies.
            if (
                self._requested_model in available
                or f"{self._requested_model}:latest" in available
            ):
                return self._requested_model
            raise RuntimeError(
                f"Model '{self._requested_model}' not found in Ollama.\n"
                f"Available: {', '.join(available)}\n"
                f"Pull it: ollama pull {self._requested_model}"
            )

        # Your fine-tuned Orca model takes priority
        orca_models = [m for m in available if m.startswith("orca")]
        if orca_models:
            return sorted(orca_models)[0]

        # Best available open-weight model
        for preferred in PREFERRED_OPEN_MODELS:
            if preferred in available:
                return preferred

        # Any model will do
        if available:
            return available[0]

        raise RuntimeError(
            "No models found in Ollama.\n"
            "Install a model first:\n"
            "  ollama pull llama3.1:8b\n"
            "Or fine-tune your own:\n"
            "  orca train run --preset prosumer"
        )

    def _list_available(self) -> list[str]:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except httpx.ConnectError:
            raise RuntimeError(
                "Ollama is not running.\n"
                "Start it: ollama serve\n"
                "Install: curl -fsSL https://ollama.ai/install.sh | sh"
            )
        except Exception as e:
            raise RuntimeError(f"Cannot reach Ollama at {self.host}: {e}")

    def is_available(self) -> bool:
        try:
            httpx.get(f"{self.host}/api/tags", timeout=3).raise_for_status()
            return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            return self._list_available()
        except Exception:
            return []

    def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = 120.0,
        retries: int = 1,
        priority: str = "INTERACTIVE",
    ) -> str:
        """
        `priority` is a no-op here -- a raw Ollama HTTP call has no
        Gateway-level priority/concurrency concept to honor. Accepted
        anyway so this method's signature stays interface-compatible with
        orca.gateway.compat_brain.GatewayBrain.complete() (which DOES
        route it through real bounded-fairness scheduling), matching this
        class's own stated goal of every "brain" caller working unchanged
        regardless of which implementation it holds.

        Real problem this fixes: this method previously caught ONLY
        httpx.ConnectError — a real request timeout (httpx.TimeoutException)
        under load propagated as an unhandled exception straight to the
        caller, with zero retry. A live investigation this session found
        34% of generation calls timing out under sustained load in the eval
        harness at a SHORTER 60s timeout than this path's 120s — meaning
        this exact failure mode is real and reachable in production chat
        under similar load, not hypothetical. Retries once before raising a
        clear, catchable error, mirroring the same fix already applied to
        orca/train/eval.py and orca/train/redteam.py.
        """
        payload = self._build_payload(messages, system, temperature, max_tokens, stream=False)
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = httpx.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
                r.raise_for_status()
                return r.json()["message"]["content"]
            except httpx.ConnectError:
                raise RuntimeError("Ollama disconnected. Is 'ollama serve' still running?")
            except httpx.TimeoutException as e:
                last_error = e
                continue
        raise RuntimeError(f"Ollama request timed out after {retries + 1} attempt(s): {last_error}")

    def stream(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = 120.0,
        retries: int = 1,
    ) -> Iterator[str]:
        """
        Same timeout robustness as complete() (see its docstring), adapted
        for streaming: a retry is only safe BEFORE any content has been
        yielded to the caller — once real output has started, silently
        restarting the request would duplicate it. If a timeout hits after
        partial output, this raises a clear error instead of retrying.
        """
        payload = self._build_payload(messages, system, temperature, max_tokens, stream=True)
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            yielded_any = False
            try:
                with httpx.stream(
                    "POST", f"{self.host}/api/chat", json=payload, timeout=timeout
                ) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        if content := chunk.get("message", {}).get("content"):
                            yielded_any = True
                            yield content
                        if chunk.get("done"):
                            break
                return
            except httpx.ConnectError:
                raise RuntimeError("Ollama disconnected mid-stream.")
            except httpx.TimeoutException as e:
                last_error = e
                if yielded_any:
                    raise RuntimeError(f"Ollama stream timed out mid-response after partial output: {e}")
                continue
        raise RuntimeError(f"Ollama stream request timed out before any output after {retries + 1} attempt(s): {last_error}")

    def _build_payload(
        self,
        messages: list[dict],
        system: str | None,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        return {
            "model": self.model,
            "messages": all_messages,
            "stream": stream,
            "options": {
                "temperature": temperature or CONFIG.brain.temperature,
                "num_predict": max_tokens or CONFIG.brain.max_tokens,
                "top_p": CONFIG.brain.top_p,
                "num_ctx": CONFIG.brain.context_length,
            },
        }

    @property
    def name(self) -> str:
        try:
            return self.model
        except Exception:
            return "not connected"


# Single factory used everywhere
def get_brain(model: str | None = None) -> OrcaBrain:
    return OrcaBrain(model=model)
