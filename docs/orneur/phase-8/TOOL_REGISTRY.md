# Tool Registry (Phase 8 spec §8-9)

`orca.agent.tool_registry.AgentToolRegistry` wraps `ToolSpec` metadata
around the EXISTING, already-secured tool primitives in `orca.tools` --
tool NAME never defines security; `ToolSpec.required_capabilities`/
`side_effect_class`/`risk_class` do.

## Registered tools and their real classification

| tool_id | Side effect | Risk | Required capability | Reused primitive |
|---|---|---|---|---|
| `read_file` | `READ_ONLY` | `LOW` | `FILE_READ` | `orca.tools._read_file` (sandboxed to `WORKSPACE_DIR`) |
| `write_file` | `REVERSIBLE_WRITE` | `MEDIUM` | `FILE_WRITE` | `orca.tools._write_file` (same sandbox) |
| `shell` | `READ_ONLY` | `MEDIUM` | `PROCESS_EXECUTION` | `orca.tools.code.run_shell` (allowlisted binaries, 30s timeout) |
| `web_search` | `READ_ONLY` | `LOW` | `NETWORK_READ` | `orca.tools.search_grounding.search_and_ground` (reuses `orca.truth.fetch`'s injection-pattern sanitization) |

No tool primitive was reimplemented -- Phase 8 adds ONLY the `ToolSpec`
metadata layer on top.

## Side-effect classification (spec §9)

`SideEffectClass`: `READ_ONLY / REVERSIBLE_WRITE / IRREVERSIBLE_WRITE /
EXTERNAL_SIDE_EFFECT / DESTRUCTIVE`. `AgentAction.expected_side_effect` is
checked against the tool's OWN declared `side_effect_class` at
authorization time -- a mismatch (the resolved operation turning out
riskier than planned) is detected and re-evaluated under the ACTUAL class,
never silently executed under the planned, lower one (spec §40, tested:
`test_destructive_action_approval_cannot_be_faked_by_a_prior_allow`).

## Tool input validation (spec §14)

Each tool's OWN existing validation is reused, not duplicated:
`_resolve_in_workspace` rejects unknown paths/traversal/symlink escape;
`run_shell` rejects non-allowlisted binaries and pipe/chain syntax;
`_is_ssrf_risk` (available for network tools) rejects private/loopback/
link-local/metadata/reserved targets. `AgentToolRegistry.invoke()` itself
does not re-implement these checks -- it calls the underlying, already-
tested function directly.

## Tool output validation (spec §15)

`ToolResult` carries no `capability`/`entitlement`/`admin` field at all
(checked structurally,
`tests/test_agent_security.py::test_tool_output_cannot_grant_capability`)
-- there is no field a tool's return string could ever populate that
would change an agent's authority, lifecycle, or identity, regardless of
what the tool output SAYS.
