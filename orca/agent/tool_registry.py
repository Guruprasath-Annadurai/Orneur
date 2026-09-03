"""
Canonical ToolRegistry (Phase 8 spec §8-9). Wraps the EXISTING, sound tool
primitives in `orca.tools`/`orca.truth.fetch` with real security metadata
(`ToolSpec`) instead of a bare name->function map -- tool NAME alone never
defines security (spec §8's explicit instruction), `ToolSpec.required_capabilities`/
`side_effect_class`/`risk_class` do.
"""
from __future__ import annotations

import time

from orca.agent.contracts import ActionRiskLevel, Capability, SideEffectClass, ToolInvocation, ToolResult, ToolSpec


class AgentToolRegistry:
    def __init__(self):
        self._specs: dict[str, ToolSpec] = {}
        self._fns: dict[str, callable] = {}

    def register(self, spec: ToolSpec, fn) -> None:
        self._specs[spec.tool_id] = spec
        self._fns[spec.tool_id] = fn

    def get_spec(self, tool_id: str) -> ToolSpec | None:
        return self._specs.get(tool_id)

    def all_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        """
        Direct invocation -- callers of THIS registry are expected to be
        the Agent Runtime's own authorized execution step
        (orca.agent.runtime), never a model directly (spec §13). This
        method itself does not check authorization -- that is the Policy
        Engine's job, evaluated BEFORE this is ever called.
        """
        spec = self._specs.get(invocation.tool_id)
        if spec is None:
            return ToolResult(invocation_id=invocation.invocation_id, tool_id=invocation.tool_id, success=False, error_class="UNKNOWN_TOOL", output=f"Unknown tool: {invocation.tool_id}")
        fn = self._fns[invocation.tool_id]
        start = time.monotonic()
        try:
            output = fn(**invocation.arguments)
            latency_ms = (time.monotonic() - start) * 1000
            return ToolResult(invocation_id=invocation.invocation_id, tool_id=invocation.tool_id, success=True, output=str(output), latency_ms=latency_ms)
        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return ToolResult(invocation_id=invocation.invocation_id, tool_id=invocation.tool_id, success=False, error_class=type(e).__name__, output=str(e), latency_ms=latency_ms)


def _read_file_tool(path: str, lines: int | None = None) -> str:
    from orca.tools import _read_file
    return _read_file(path, lines)


def _write_file_tool(path: str, content: str) -> str:
    from orca.tools import _write_file
    return _write_file(path, content)


def _shell_tool(command: str) -> str:
    from orca.tools.code import run_shell
    return run_shell(command).format()


def _web_search_tool(query: str, n: int = 5) -> str:
    from orca.tools.search_grounding import search_and_ground
    return search_and_ground(query, n=n)[0]


def build_agent_tool_registry() -> AgentToolRegistry:
    """
    The Phase 8 canonical registry. Reuses the EXISTING, already-secured
    tool primitives (`orca.tools`) rather than reimplementing path
    sandboxing / shell allowlisting / SSRF protection a second time --
    only the security METADATA (ToolSpec) is new.
    """
    registry = AgentToolRegistry()

    registry.register(
        ToolSpec(
            tool_id="read_file", description="Read a file inside the sandboxed workspace directory.",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}, "lines": {"type": "integer"}}, "required": ["path"]},
            required_capabilities=frozenset({Capability.FILE_READ}),
            side_effect_class=SideEffectClass.READ_ONLY, risk_class=ActionRiskLevel.LOW,
            timeout_s=10.0, idempotent=True, filesystem_scope="workspace",
        ),
        _read_file_tool,
    )
    registry.register(
        ToolSpec(
            tool_id="write_file", description="Write a file inside the sandboxed workspace directory.",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
            required_capabilities=frozenset({Capability.FILE_WRITE}),
            side_effect_class=SideEffectClass.REVERSIBLE_WRITE, risk_class=ActionRiskLevel.MEDIUM,
            timeout_s=10.0, idempotent=False, filesystem_scope="workspace",
        ),
        _write_file_tool,
    )
    registry.register(
        ToolSpec(
            tool_id="shell", description="Run one allowlisted, read-oriented shell command (no pipes/chaining).",
            input_schema={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
            required_capabilities=frozenset({Capability.PROCESS_EXECUTION}),
            side_effect_class=SideEffectClass.READ_ONLY, risk_class=ActionRiskLevel.MEDIUM,
            timeout_s=30.0, idempotent=True,
        ),
        _shell_tool,
    )
    registry.register(
        ToolSpec(
            tool_id="web_search", description="Search the web for current information.",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}, "n": {"type": "integer"}}, "required": ["query"]},
            required_capabilities=frozenset({Capability.NETWORK_READ}),
            side_effect_class=SideEffectClass.READ_ONLY, risk_class=ActionRiskLevel.LOW,
            timeout_s=15.0, idempotent=True, network_required=True,
        ),
        _web_search_tool,
    )
    return registry
