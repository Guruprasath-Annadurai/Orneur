# Phase 13 — Agent / Tool Security

## Existing coverage (audited, confirmed present)

- Adversarial plans (invent tool, invent capability, self-approve,
  recursive delegation): `tests/test_agent_plan_security.py`,
  `tests/test_agent_delegation.py`, `tests/test_agent_subagent_cancellation.py`.
- Tool argument attacks (type confusion, path encoding, oversized args):
  `tests/test_tools_security_scan.py`, `tests/test_tools_file_sandbox.py`.
- Filesystem attacks (traversal, symlink escape): `tests/test_tools_file_sandbox.py`,
  `tests/test_mcp_fs_server_sandbox.py`.
- Shell/process attacks (chaining, injection): `tests/test_run_shell_sandbox.py`,
  `tests/test_code_sandbox_safety.py`.

## New this phase

`tests/test_redteam_cross_layer_chains.py::
test_retrieved_prompt_injection_reaching_world_state_does_not_grant_a_new_capability`
— see `PROMPT_INJECTION.md` for the full writeup. This is the first test
in the repository proving, behaviorally (not just structurally), that a
SECOND action requiring an ungranted capability is denied on the SAME
runtime instance even after the runtime has already processed and
"believed" (stored as fact) an injected claim that authority was granted.

## Result

`AGENT_TOOL_AUTHORITY_BYPASS = 0`.
