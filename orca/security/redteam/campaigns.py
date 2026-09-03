"""
Phase 13 campaign catalog -- maps each closed campaign category to the
REAL evidence for it: pre-existing, already-passing security test files
(Phase 1-12.1's own work) plus genuinely new test files added this phase.
Per spec §79, this deliberately does not re-implement any of the 733
pre-existing security-suite assertions; it indexes them.

`build_catalog()` is pure data assembly -- no test execution happens
here. Actual pass/fail counts come from running pytest against the files
listed (see docs/orneur/phase-13/EVALUATION.md for the real numbers from
the run this phase performed).
"""
from __future__ import annotations

from orca.security.redteam.contracts import CampaignCategory, CampaignRecord


def build_catalog() -> list[CampaignRecord]:
    return [
        CampaignRecord(
            category=CampaignCategory.PROMPT_INJECTION,
            existing_test_files=[
                "tests/test_agent_adversarial_phrases.py",
                "tests/test_moderation_jailbreak.py",
                "tests/test_redteam_jailbreak_trials.py",
                "tests/test_memory_security.py",  # test_prompt_injected_memory_never_reaches_allowed_recall
            ],
            new_test_files=["tests/test_redteam_cross_layer_chains.py"],
            notes="New work this phase: retrieved-content injection composed with real AgentRuntime capability enforcement (3-layer chain), not just isolated pattern-matching.",
        ),
        CampaignRecord(
            category=CampaignCategory.AUTHORITY_ESCALATION,
            existing_test_files=[
                "tests/test_godmode_boundaries.py",
                "tests/test_society_authority_security.py",
                "tests/test_deliberation_security.py",
                "tests/test_memory_authority_security.py",
            ],
            new_test_files=["tests/test_redteam_cross_layer_chains.py"],
            notes="New work: behavioral (not just structural/import-boundary) proof that a Court ACCEPT verdict built from connector-sourced injected content cannot reach Godmode issuance.",
        ),
        CampaignRecord(
            category=CampaignCategory.TENANT_ESCAPE,
            existing_test_files=[
                "tests/test_connector_tenant_isolation.py",
                "tests/test_memory_security.py",
                "tests/test_simulation_security.py",  # test_cross_tenant_simulation_blocked_for_connectors
            ],
        ),
        CampaignRecord(
            category=CampaignCategory.RAG_POISONING,
            existing_test_files=[
                "tests/test_truth_fetch_security.py",
                "tests/test_truth_safe_fetch_cutover.py",
            ],
            notes="Source-independence/citation-confusion (spec §12-15) audited but not newly tested this phase -- see FINDINGS.md's disclosed scope limitations.",
        ),
        CampaignRecord(
            category=CampaignCategory.MEMORY_POISONING,
            existing_test_files=[
                "tests/test_memory_security.py",
                "tests/test_memory_authority_security.py",
                "tests/test_memory_deletion_integration.py",
                "tests/test_memory_retrieval_consolidation_firewall.py",
                "tests/test_memory_reflex_agent_scoping.py",
                "tests/test_memory_reflex_procedural_failure_authority.py",
            ],
        ),
        CampaignRecord(
            category=CampaignCategory.TOOL_INJECTION,
            existing_test_files=[
                "tests/test_agent_plan_security.py",
                "tests/test_agent_security.py",
                "tests/test_tools_security_scan.py",
                "tests/test_tools_file_sandbox.py",
                "tests/test_code_sandbox_safety.py",
                "tests/test_run_shell_sandbox.py",
                "tests/test_mcp_fs_server_sandbox.py",
            ],
        ),
        CampaignRecord(
            category=CampaignCategory.CONNECTOR_ATTACK,
            existing_test_files=[
                "tests/test_connector_security.py",
                "tests/test_connector_authority_regressions.py",
                "tests/test_connector_tenant_isolation.py",
                "tests/test_connector_rate_limit_and_budget.py",
                "tests/test_connector_lifecycle_audit.py",
                "tests/test_connectors_fast_path.py",
            ],
        ),
        CampaignRecord(
            category=CampaignCategory.GODMODE_ATTACK,
            existing_test_files=[
                "tests/test_godmode_security.py",
                "tests/test_godmode_boundaries.py",
                "tests/test_godmode_exact_argument_binding.py",
                "tests/test_godmode_concurrency_and_e2e.py",
                "tests/test_godmode_fast_path.py",
            ],
            notes="Lease forgery (§34), use-count race (§35), kill-switch attacks (§36), file-scope attacks (§37) all already have real, passing coverage from Phase 10/10.1 -- confirmed by direct file inspection this phase, not re-derived.",
        ),
        CampaignRecord(
            category=CampaignCategory.SIMULATION_ATTACK,
            existing_test_files=["tests/test_simulation_security.py", "tests/test_simulation_qualification_11_2.py"],
            notes="Result forgery, sandbox escape, staleness, cross-tenant, Godmode race (§38-42) all already have real, passing coverage from Phase 11/11.1/11.2 -- confirmed by direct file inspection.",
        ),
        CampaignRecord(
            category=CampaignCategory.LEARNING_POISONING,
            existing_test_files=[
                "tests/test_learning_phase12.py",
                "tests/test_learning_eval_harness.py",
                "tests/test_learning_registry_isolation.py",
                "tests/test_learning_training_experiment.py",
            ],
            notes="Curriculum poisoning, tenant training leak, holdout exposure, dataset mutation, checkpoint supply chain, training authority (§43-50) all already have real, passing coverage from Phase 12/12.1.",
        ),
        CampaignRecord(
            category=CampaignCategory.RESOURCE_EXHAUSTION,
            existing_test_files=[
                "tests/test_budget_invariants.py",
                "tests/test_budget_manipulation_security.py",
                "tests/test_society_budget_ledger.py",
                "tests/test_connector_rate_limit_and_budget.py",
            ],
            notes="Branch/plan bounds (MAX_SIMULATION_BRANCHES, MAX_SIMULATION_ACTIONS) covered by Phase 11/11.1 simulation tests, not re-listed here to avoid duplication.",
        ),
        CampaignRecord(
            category=CampaignCategory.RACE_CONDITION,
            existing_test_files=[
                "tests/test_godmode_concurrency_and_e2e.py",
                "tests/test_simulation_qualification_11_2.py",
                "tests/test_gateway_chaos.py",
            ],
        ),
        CampaignRecord(
            category=CampaignCategory.SUPPLY_CHAIN,
            existing_test_files=["tests/test_learning_phase12.py", "tests/test_registry_id_sanitization.py"],
        ),
        CampaignRecord(
            category=CampaignCategory.SECRETS_EXFILTRATION,
            existing_test_files=[
                "tests/test_agent_secret_and_trace_security.py",
                "tests/test_connector_security.py",
                "tests/test_pii_redact.py",
                "tests/test_serve_dlp.py",
            ],
        ),
        CampaignRecord(
            category=CampaignCategory.PROTOCOL_CONFUSION,
            existing_test_files=["tests/test_gateway_test_isolation.py", "tests/test_gateway_circuit_breaker.py"],
            new_test_files=["tests/test_frontier_runtime_cancellation.py"],
            notes="New this phase: the frontier_runtime.py cancellation-vs-timeout investigation (spec §23-24) -- see FINDINGS.md.",
        ),
        CampaignRecord(
            category=CampaignCategory.STATE_CORRUPTION,
            existing_test_files=["tests/test_gateway_chaos.py", "tests/test_ops_backup.py"],
        ),
    ]
