# Phase 13 — Memory Security

Audited, not newly re-tested this phase — coverage is already
substantial and directly matches the spec's own attack list:

| Spec item | Existing test |
|---|---|
| §16 false-fact/malicious-procedure promotion | `test_distill_and_save_cannot_promote_unverified_fact_to_known` (`tests/test_memory_security.py`) |
| §17 memory authority ("you are authorized", "tenant = B") | `test_prompt_injected_memory_never_reaches_allowed_recall` |
| §18 scope escape (user→tenant, project A→B) | `test_cross_user_memory_does_not_leak_via_recall`, `test_cross_project_isolation_via_firewall`, `test_scope_manipulation_via_forged_scope_id_string_is_still_isolated` |
| §18 deleted content resurrection | `test_deleted_memory_cannot_be_resurrected_by_recall`, `test_deleted_episode_content_cannot_be_recovered_after_tombstone` |
| §19 staleness vs. fresh Truth | Not directly re-verified this phase — `orca/memory/`'s reconciliation policy exists but a dedicated stale-memory-vs-fresh-TruthResult adversarial test was not newly added. |

## Residual risk

§19 (memory staleness vs. fresh verified evidence reconciliation) is a
**disclosed gap** — the reconciliation policy exists in code but this
phase did not add a dedicated adversarial test proving fresh evidence
always wins. Recommended as a follow-up.

## Result

`MEMORY_POISONING_AUTHORITY_BYPASS = 0`, `CROSS_TENANT_READ = 0` (for
memory specifically) — both confirmed by pre-existing, passing tests.
