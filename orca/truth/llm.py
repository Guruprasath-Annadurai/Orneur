"""
Shared Gateway-routed LLM call helper for Truth Fabric's judge-style
operations (claim extraction, claim verification, contradiction
detection). Every Truth Fabric model call goes through ModelGateway via
this one function -- unlike the pre-existing orca/docs/*.py modules audited
in CURRENT_TRUTH_PIPELINE.md, which bypass it with raw urllib.request.
This is the module that keeps that mistake from being repeated in new code.
"""
from __future__ import annotations

import json
import re


async def gateway_json_call(prompt: str, system: str, tier: str = "nano", max_tokens: int = 400, priority: str = "BACKGROUND", gateway=None) -> dict | list | None:
    """
    Resolves `tier` through the EXISTING registry/wiring bridge
    (orca/serve/registry.py, orca/gateway/wiring.py -- unchanged), calls
    ModelGateway.generate() directly (this function is async; callers in a
    sync context should use orca.gateway.sync_bridge.run_async_in_thread,
    exactly like GatewayBrain does), and best-effort parses the first
    JSON object OR array found in the response. Returns None on any
    failure (unparseable response, model unavailable, etc.) -- callers
    must treat None as "could not determine," never crash the pipeline.
    """
    try:
        from orca.gateway.contracts import InferenceRequest, RequestPriority
        from orca.gateway.wiring import brain_for_tier_resolution, get_shared_gateway
        from orca.serve.registry import resolve_tier_backend

        gw = gateway or get_shared_gateway()
        resolution = resolve_tier_backend(tier)
        brain = brain_for_tier_resolution(resolution, gateway=gw)
        request = InferenceRequest(
            request_id=f"truth-{id(prompt)}", model_id=brain.model_id, model_version=brain.model_version,
            messages=[{"role": "user", "content": prompt}], system=system, max_tokens=max_tokens,
            temperature=0.1, priority=RequestPriority(priority),
        )
        response = await gw.generate(request, allow_experimental=brain.allow_experimental)
        raw = response.output
    except Exception:
        return None

    return _extract_json(raw)


def _extract_json(raw: str) -> dict | list | None:
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer) + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except (json.JSONDecodeError, ValueError):
                continue
    return None
