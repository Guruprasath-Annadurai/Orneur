"""
Phase 13 red-team harness -- a structured catalog of adversarial
campaigns, NOT a reimplementation of the existing 733-test authoritative
security suite (spec §79: "do not duplicate all pytest logic
unnecessarily"). Each CampaignRecord below links a category to the real
pytest files/tests that already exercise it, plus any NEW test file this
phase added. `orca/security/redteam/contracts.py` defines the
SecurityFinding contract for genuinely new discoveries; see
docs/orneur/phase-13/FINDINGS.md for the actual findings from this phase.
"""
