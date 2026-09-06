# Current Agent/Tool Runtime Audit (Phase 8 spec §3)

## `orca/brain/agent.py::AgentLoop`

**PARTIAL/UNAUTHORIZED (the exact "give the model tools and let it loop"
pattern spec §1 targets).** `_plan()` asks the model (via `self.brain`,
one Brain object per session, chosen once at construction from the
caller's `model_variant`) whether/which tools to call; `_execute_tools()`
calls `self.tools.call(tool_name, args)` directly -- no capability check,
no policy decision, no authorization boundary between model output and
tool execution. Bounded by `MAX_TOOL_ROUNDS = 6` (real, existing bound --
**REAL**). No WorldState integration (tool results go straight into the
conversation transcript as a string, never a typed `Observation`).
Reflection (`_reflect()`) is REAL/MODEL_ONLY (already classified in
Phase 6's own audit) -- unrelated to tool authorization.

## `orca/variants/ultra.py::OrcaUltra`

**PARTIAL/UNAUTHORIZED**, same pattern -- `_run_agent()` constructs an
`AgentLoop` per subtask and calls `.run()`, inheriting the same
direct-model-to-tool path. Bounded (`max_retries=2`, per Phase 6's own
audit) -- **REAL** for its own retry loop, but no capability/policy layer
either.

## `orca/tools/__init__.py::ToolRegistry`/`Tool`

**LEGACY (name→function registry, no security metadata).** `Tool` carries
only `name`/`description`/`fn`/`params` (a bare JSON-schema-shaped dict
for the MODEL's benefit, never validated against on the way IN or OUT).
`ToolRegistry.call()` catches exceptions and stringifies them -- no
`ToolResult`/`Observation` contract, no side-effect classification, no
declared required capability, no risk class, no timeout declared at the
registry level (individual tools enforce their own, inconsistently).

## `orca/tools/code.py::run_python`/`run_shell`/`run_code`

**REAL, SECURE (for what it does).** `run_shell()` enforces a real
allowlist (`_ALLOWED_SHELL_COMMANDS`), a real `TIMEOUT = 30` seconds,
subprocess-based execution (not `shell=True`/string interpolation). No
capability/policy layer sits in front of it, but the primitive itself is
sound -- a genuine SECURE building block Phase 8 reuses rather than
rebuilding, per spec's "do not rewrite working tool infrastructure
blindly."

## `orca/tools/__init__.py::_resolve_in_workspace`/`_read_file`/`_write_file`

**REAL, SECURE.** Rejects `..` traversal, absolute paths outside
`WORKSPACE_DIR`, and symlink escapes (via `Path.resolve()` +
`relative_to()`). No capability/policy layer in front, same as above --
a sound primitive to reuse.

## `orca/tools/web.py::_is_ssrf_risk`/`fetch_page`

**REAL, SECURE, but DEAD (per the module's own comment).** SSRF
validation (private/loopback/link-local/reserved/multicast rejection,
fail-closed on unresolvable hosts) exists and is correct, but
`fetch_page()` has zero callers anywhere in the codebase today (confirmed
by the module's own docstring comment). `orca/truth/fetch.py`'s own,
separate SSRF-hardened `fetch_document()` (Phase 4.1, the "safe-fetch
cutover") is the ACTUALLY-wired equivalent used by Truth Fabric's
`RAG_5_RESEARCH` mode -- Phase 8's Agent Runtime tool adapters reuse THAT
one, not `orca.tools.web`, to avoid a second, unwired SSRF implementation.

## `orca/mcp/fs_server.py`

**REAL, SECURE, separate surface.** An MCP filesystem server with its own
`_safe_path()` sandboxing, exercised by `tests/test_mcp_fs_server_sandbox.py`.
A genuinely different execution surface (MCP protocol, not this codebase's
AgentLoop/ToolRegistry) -- out of Phase 8's scope to unify; noted as an
existing, independently-secured sandbox pattern to match, not replace.

## `orca/tools/search_grounding.py::search_and_ground`/`sanitize_fetched_content`

**REAL, SECURE.** Already reuses `orca.truth.fetch.sanitize_extracted_text`
for injection-pattern scanning of fetched web content before it reaches a
model prompt -- the SAME reuse discipline Phase 6/7 established. A sound
tool-output-sanitization primitive.

## Capability/Policy/Authorization layer

**MISSING entirely.** No `Capability`, `CapabilityDecision`,
`PolicyDecision`, or `ActionAuthorization` concept exists anywhere before
this phase. `ToolRegistry.call()` IS the authorization boundary today --
i.e., there is none; any tool the model's plan JSON names gets called
directly with whatever arguments the model supplied (validated only by
each tool's own internal checks, e.g. `_resolve_in_workspace`'s path
check, `run_shell`'s allowlist).

## WorldState integration

**MISSING.** No tool call result is ever converted into a typed
`Observation` or fed into `orca.deliberation.contracts.WorldState`.
Tool output becomes a plain string appended to `AgentTrace.tool_calls`
and the conversation transcript.

## Delegation / subagent spawning

**DEAD/MISSING.** `OrcaUltra._run_agent()` constructs independent
`AgentLoop` instances per subtask (a form of task decomposition), but
there is no `DelegationRequest`/`DelegationResult` contract, no
capability-subset enforcement, no depth limit, no fanout limit -- each
subtask's `AgentLoop` gets the SAME full tool registry as the parent,
which is itself unauthorized (see above), so there is nothing to
"non-escalate" from today; this is a real, disclosed gap Phase 8 closes.

## Budget integration

**PARTIAL.** `MAX_TOOL_ROUNDS`/`max_retries` are real hard caps, but
neither AgentLoop nor OrcaUltra consumes `CognitiveBudget.TOOL_CALLS` or
`AGENT_CALLS` at all -- these dimensions exist in
`orca.cognitive.contracts.BudgetDimension` (Phase 3) but have had zero
real consumers until this phase.

## Summary of what Phase 8 changes

A NEW `orca/agent/` package is introduced as the first production Agent
Runtime, sitting BETWEEN the model and the EXISTING, sound tool
primitives (`orca.tools.code.run_shell`, `orca.tools.__init__._read_file`/
`_write_file`, `orca.truth.fetch.fetch_document`) -- reusing them, not
rewriting them. `AgentLoop`/`OrcaUltra` are NOT torn out or redesigned;
Phase 8 adds the missing Capability/Policy/Observation/WorldState layer as
a new, opt-in execution path, and makes a narrow, additive
TOOL_REASONER-routing touchpoint available to `AgentLoop` without
changing its default, currently-tested behavior (see `AGENT_RUNTIME.md`'s
"Legacy AgentLoop migration" section for the exact scope and why a full
migration is not forced this phase).
