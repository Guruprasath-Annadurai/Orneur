"""
GatewayBrain -- a drop-in replacement for orca.brain.providers.OrcaBrain's
interface, backed by ModelGateway instead of a direct Ollama/frontier HTTP
client. This is the ENTIRE serving-path cutover mechanism: AgentLoop,
ContextManager, and every other existing consumer of "brain" keep calling
the exact same methods (.complete, .stream, .is_available, .name, .model)
with the exact same signatures OrcaBrain already exposed -- only what
happens INSIDE those methods changes. No caller above this class needed
to change.
"""
from __future__ import annotations

import uuid
from typing import Iterator

from orca.gateway.contracts import InferenceRequest
from orca.gateway.errors import InferenceError
from orca.gateway.gateway import ModelGateway
from orca.gateway.sync_bridge import run_async_gen_in_thread, run_async_in_thread


class GatewayBrain:
    def __init__(
        self,
        gateway: ModelGateway,
        model_id: str,
        model_version: str | None = None,
        allow_experimental: bool = True,
    ):
        """
        allow_experimental defaults True here (unlike ModelGateway's own
        stricter default) because this class exists specifically to bridge
        TODAY's live serving path, which has never been gated by Phase 1's
        promotion system -- see docs/orneur/phase-2/LIVE_SERVING_CUTOVER.md's
        "one deliberate policy decision" section for the full reasoning.
        A caller that wants the strict production-only guarantee should
        call ModelGateway directly instead of going through this shim.
        """
        self._gateway = gateway
        self.model_id = model_id
        self.model_version = model_version
        self.allow_experimental = allow_experimental

    @property
    def model(self) -> str:
        return self.model_version or self.model_id

    @property
    def name(self) -> str:
        try:
            return self.model
        except Exception:
            return "not connected"

    def is_available(self) -> bool:
        try:
            self._gateway.resolve_deployment(self.model_id, self.model_version, self.allow_experimental)
            return True
        except InferenceError:
            return False

    def _build_request(self, messages: list[dict], system, temperature, max_tokens, timeout) -> InferenceRequest:
        return InferenceRequest(
            request_id=str(uuid.uuid4()),
            model_id=self.model_id,
            model_version=self.model_version,
            messages=messages,
            system=system,
            temperature=temperature if temperature is not None else 0.7,
            max_tokens=max_tokens or 1024,
            timeout_s=timeout,
        )

    def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = 120.0,
        retries: int = 1,
    ) -> str:
        request = self._build_request(messages, system, temperature, max_tokens, timeout)
        response = run_async_in_thread(lambda: self._gateway.generate(request, allow_experimental=self.allow_experimental))
        return response.output

    def stream(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = 120.0,
        retries: int = 1,
    ) -> Iterator[str]:
        request = self._build_request(messages, system, temperature, max_tokens, timeout)

        async def _agen():
            async for chunk in self._gateway.stream(request, allow_experimental=self.allow_experimental):
                if chunk.delta:
                    yield chunk.delta

        yield from run_async_gen_in_thread(_agen)
