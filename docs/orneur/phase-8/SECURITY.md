# Agent Runtime Security (Phase 8 spec §16, §41-44, §67)

## Tool output is data, never authority (spec §16)

`ToolResult`/`Observation` carry no `capability`/`entitlement`/`authorized`
field at all (checked structurally,
`tests/test_agent_security.py::test_tool_output_cannot_grant_capability`).
A tool output string containing "ignore prior instructions", "you now
have admin access", etc. has literally nowhere to write that would change
authority -- `AgentRuntime._to_observation()` only ever extracts
`facts`/`status`/`error` as plain strings destined for WorldState's
provenance-tagged fact list, never re-parsed as a command.

## Filesystem security (spec §41)

Reuses `orca.tools._resolve_in_workspace` unchanged -- `..` traversal,
absolute-path escape, and symlink escape are all rejected via
`Path.resolve()` + `relative_to()`. Tested directly:
`test_filesystem_path_traversal_is_rejected`,
`test_filesystem_absolute_path_escape_is_rejected`.

## Shell security (spec §42)

Reuses `orca.tools.code.run_shell` unchanged -- a real command allowlist
(`_ALLOWED_SHELL_COMMANDS`), no pipes/chaining, subprocess-based (never
`shell=True`), 30s timeout. Tested directly with an explicit prompt-
injection framing:
`test_prompt_injection_in_tool_arguments_cannot_bypass_shell_allowlist`.

## Network / SSRF security (spec §43)

Reuses `orca.tools.web._is_ssrf_risk` (private/loopback/link-local/
metadata/reserved rejection, fail-closed on unresolvable hosts) and
`orca.tools.search_grounding`'s reuse of `orca.truth.fetch`'s
SSRF-hardened `fetch_document()`. Tested directly against a real cloud
metadata endpoint and localhost:
`test_ssrf_attempt_is_rejected_by_the_reused_ssrf_check`.

## Secret protection (spec §44)

No current tool declares `Capability.SECRET_USE` or `secrets_required=True`
-- a normal agent run cannot touch secrets at all today (tested:
`test_no_current_tool_requires_secret_use_by_default`). No secret-manager
integration is built this phase (explicitly deferred, per spec §44's own
"do not implement broad secret-manager integration unless existing
infrastructure supports it" -- none does yet).

## Capability escalation / policy bypass / approval forgery (spec §67)

- Capability escalation: `check_capabilities()` is a pure set-membership
  check with no override path; delegation's non-escalation invariant is
  enforced at construction time (`CapabilityEscalationError`).
- Policy bypass: `evaluate_policy()` is the only path to `ALLOW`; a higher
  "score" or a permissive-looking framing cannot skip the capability
  check that runs first (`test_capability_check_cannot_be_bypassed_by_a_higher_policy_score`).
- Approval forgery: see `APPROVALS.md` -- no code path sets
  `authorized=True` from anything but `_authorize()`'s own
  `PolicyDecision`-derived value (`ActionAuthorization(` appears exactly
  once outside `execute()`, tested structurally).
- Trace authorization: `AgentTrace` carries no raw-chain-of-thought field
  (checked structurally,
  `test_agent_trace_has_no_raw_chain_of_thought_field`).

## Role/model injection (carried forward, unchanged)

Court/Society's own role-injection defenses (Phase 6/7, unchanged) remain
in force for anything Agent Runtime composes with -- Phase 8 adds no new
model-role-injection surface of its own since `evaluate_policy()`/
`check_capabilities()` never read model output text at all.

## What Phase 8 does NOT add (explicitly, per spec §62-64)

No enterprise connectors (Slack/Drive/Salesforce/GitHub-enterprise/DB
connectors), no Godmode/elevated-capability lease/admin override, no
Simulation Chamber. `orca/agent/`'s four built-in tools are the ONLY
production tool adapters this phase registers.
