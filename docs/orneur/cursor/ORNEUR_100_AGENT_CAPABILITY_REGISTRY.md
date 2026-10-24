# 100-agent capability registry

Parent orchestrator: `orca/pretrain_foundation/agents.py`. This registry does not replace it.

Source: `orca/pretrain_foundation/role_registry.py`. `load_roles()` returns 100 versioned contracts, 10 groups of 10. Twelve have `implemented=True` and `qualification_state=IMPLEMENTED_SYNTHETIC`. None is `QUALIFIED`. None is production authorized.

| Group | Count | Implemented in this pass |
|---|---|---|
| orchestration | 10 | team-selector, deadline-controller |
| research | 10 | none |
| retrieval | 10 | none |
| reasoning | 10 | none |
| coding | 10 | none |
| verification | 10 | claim-classifier, independent-falsifier, contradiction-arbiter |
| security | 10 | authority-gate, denial-recorder, injection-screener, self-promotion-denier |
| memory | 10 | tenant-isolator |
| model | 10 | training-lock-watcher, cost-accountant |
| product | 10 | none |

A declared role is not a working agent. `IMPLEMENTED_SYNTHETIC` is not an independently qualified expert. No native model is attached. `model_dependency` is `none`.

Test: `python3 -m pytest -q tests/test_agent_role_registry.py tests/test_cursor_agent_orchestration.py` — 18 passed.
