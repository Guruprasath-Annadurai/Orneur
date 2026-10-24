# Orchestration and routing

The scheduler is `Orchestrator` in `orca/pretrain_foundation/agents.py`. `bind_handlers` registers twelve functions under the permission `governed`. Child permissions still cannot exceed the parent. That rule was already tested in `tests/test_cursor_agent_orchestration.py` and was not changed.

`select_team` returns only implemented roles whose task token was requested. A declared-only task such as `coding.patch` is listed in `blocked_unqualified`. The catalog size reported is 100. The selected count for falsify plus team select is 2.

`cancel` on a succeeded task does not change that task to cancelled. A later child that is still queued is cancelled. The new test `test_orchestrator_cancel_does_not_rewrite_a_succeeded_sibling` covers that case.

Routing is deterministic: the same task token resolves to the same role. There is no learned router and no model call.
