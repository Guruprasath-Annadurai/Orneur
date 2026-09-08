"""
Phase 15.2 -- schema module consistency tests.

Live schema application/constraint enforcement was verified directly
against real Neon infrastructure (a temporary branch, then the
production branch of orneur-core/little-boat-61470844) via the Neon
MCP tools -- see docs/orneur/phase-15/PHASE15_EVIDENCE.md's Phase 15.2
checkpoint for the actual commands and results. That live verification
is more authoritative than a mocked/sqlite substitute would be, so
this file focuses on what a live-DB test can't easily catch: the
schema module's own internal consistency.
"""
from __future__ import annotations

import re

from orca.mission.schema import ALL_TABLES, SCHEMA_SQL

_CREATE_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+)")


def test_all_tables_matches_every_create_table_statement():
    """Regression guard: if a table is added to SCHEMA_SQL but someone
    forgets to add it to ALL_TABLES (or vice versa), this catches the
    drift immediately rather than letting a migration-verification
    step silently miss a table."""
    tables_in_sql = set(_CREATE_TABLE_RE.findall(SCHEMA_SQL))
    assert tables_in_sql == set(ALL_TABLES), (
        f"Mismatch between SCHEMA_SQL and ALL_TABLES.\n"
        f"In SQL but not ALL_TABLES: {tables_in_sql - set(ALL_TABLES)}\n"
        f"In ALL_TABLES but not SQL: {set(ALL_TABLES) - tables_in_sql}"
    )


def test_all_tables_has_no_duplicates():
    assert len(ALL_TABLES) == len(set(ALL_TABLES))


def test_all_tables_covers_every_spec_section_9_domain():
    """Spec section 9's minimum durable domains -- confirms none were
    silently dropped during schema design."""
    required_domains = {
        "missions", "mission_steps", "checkpoints", "requirements",
        "requirement_acceptance_criteria", "assumptions", "evidence",
        "model_invocations", "tool_invocations", "approvals",
        "authority_decisions", "relay_sessions", "devices",
        "operations", "production_proofs", "audit_events",
    }
    assert required_domains.issubset(set(ALL_TABLES))


def test_reserved_phase16_tables_are_present_but_clearly_marked():
    """Spec section 9 permits reserving storage for future Phase 16
    intelligence domains -- confirms they exist AND are named with the
    _reserved suffix so nothing could mistake them for implemented
    Phase 15 functionality."""
    reserved = {t for t in ALL_TABLES if t.endswith("_reserved")}
    assert reserved == {
        "epistemic_transitions_reserved",
        "escalations_reserved",
        "failure_genome_reserved",
        "outcome_memory_reserved",
        "capability_delta_reserved",
    }


def test_operations_table_has_idempotency_key_column():
    """Spec section 11's core requirement -- a stable, unique
    operation identifier is what makes duplicate-dangerous-action
    prevention possible. Live-verified as an enforced UNIQUE
    constraint against real Neon (see PHASE15_EVIDENCE.md); this test
    just guards against the column disappearing from the DDL text
    itself in a future edit."""
    operations_block = SCHEMA_SQL[SCHEMA_SQL.index("CREATE TABLE IF NOT EXISTS operations ("):]
    operations_block = operations_block[: operations_block.index(");")]
    assert "idempotency_key" in operations_block
    assert "UNIQUE" in operations_block
