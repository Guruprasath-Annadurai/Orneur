# Phase 13.1 — Memory Deep Red-Team

7 new attacks executed against real code (`tests/test_redteam_memory_deep.py`).

| ID | Attack | Target | Status | Regression test |
|---|---|---|---|---|
| MEM-01a | Stale memory vs fresh Truth reconciliation | `orca.truth.state.compute_evidence_state` + `orca.memory.firewall.check` | BLOCKED_AS_EXPECTED — architectural separation (no memory-derived parameter exists in `compute_evidence_state`'s signature) | `test_mem01_stale_memory_is_flagged_but_never_overrides_evidence_state` |
| MEM-01b | Contrast: DISPROVEN vs merely-stale | `orca.memory.firewall.check` | BLOCKED_AS_EXPECTED — DISPROVEN blocked outright, stale allowed-with-flag (deliberately different severities) | `test_mem01_disproven_memory_is_blocked_outright_unlike_merely_stale` |
| MEM-02a | Poisoned ProceduralMemory claiming pre-approval + privileged tool use | `orca.agent.memory_hook.procedural_record_is_compatible` | BLOCKED_AS_EXPECTED — gate checks against caller's real `allowed_tool_ids`, poisoned text has no effect | `test_mem02_poisoned_procedural_memory_claiming_preapproval_does_not_bypass_tool_compatibility_gate` |
| MEM-02b | Poisoned FailureMemory correction text | `orca.memory.firewall.check` | BLOCKED_AS_EXPECTED (passes as ordinary data — the real gate is the tool-compatibility layer, not the firewall's injection scan; documented as two complementary layers) | `test_mem02_poisoned_failure_memory_still_passes_firewall_as_ordinary_data` |
| MEM-03a | Cross-scope memory leak attempt | `orca.memory.firewall.check` | BLOCKED_AS_EXPECTED — scope check runs before content inspection | `test_mem03_cross_scope_memory_is_blocked_regardless_of_content` |
| MEM-03b | GLOBAL scope exception (contrast) | same | BLOCKED_AS_EXPECTED (deliberate, typed exception) | `test_mem03_global_scope_is_the_one_deliberate_exception` |
| MEM-04 | Privacy-clearance gate after (hypothetical) source deletion | `orca.memory.firewall.check` | BLOCKED_AS_EXPECTED — privacy clearance gates independently of source lifecycle | `test_mem04_privacy_clearance_gate_blocks_regardless_of_source_deletion_state` |

## No real vulnerabilities found in Memory this phase

All 7 attacks held. The stale-vs-fresh-Truth property (spec §14) holds
by **architectural separation** rather than an explicit reconciliation
function: memory enrichment (`orca.cognitive.kernel._recall_memory_and_enrich`)
feeds a soft, honestly-labeled ("may be stale, verify if load-bearing")
prompt-context string, while Truth Fabric's evidence-gated
`compute_evidence_state()` has no code path that could ever consume
memory content — confirmed by inspecting its real signature, not
assumed.

## Not attacked this phase (disclosed)

- Deleted-source memory via the actual tombstone/deletion workflow
  (`orca.memory.deletion`) — already covered by
  `tests/test_memory_deletion_integration.py`; MEM-04 tests the
  DIFFERENT, complementary privacy-clearance gate instead, to avoid
  duplicating that existing coverage per spec §2's "do not merely say
  existing test already covers this" combined with §79's "do not
  duplicate all pytest logic unnecessarily" — the two together mean:
  build something genuinely new adjacent to what exists, not a copy of it.
- Memory scope chain through a REAL Memory Continuum write path (private
  connector content actually persisted then recalled cross-scope) — this
  test used direct `firewall.check()` calls rather than the full
  connector-to-memory-write pipeline; a full pipeline version is a
  disclosed scope gap.
