# Phase 13 — Evaluation

## Red-team evaluation (spec §80)

Success/block rate by campaign, measured against attacks ACTUALLY
executed this phase (not fabricated aggregate scores):

| Campaign | New attacks executed | Blocks observed | Block rate |
|---|---|---|---|
| Prompt injection (retrieved content) | 1 | 1 | 100% |
| Authority escalation (Court→Godmode) | 1 | 1 | 100% |
| Protocol confusion (frontier_runtime cancellation) | 4 | 4 (all 4 produced the correct, distinct outcome) | 100% |

Every other campaign category listed in `orca/security/redteam/campaigns.py`
relies on pre-existing test evidence (682 tests across 79 pre-Phase-13
files, now 81 files / additional tests after this phase's two new files)
rather than a freshly measured rate this phase — see `ATTACK_SURFACE.md`
for the full per-category mapping.

## Full regression (spec §76-78)

| Suite | Result |
|---|---|
| Full deterministic application suite | **1397 passed, 0 failed, 40 deselected** |
| Authoritative security suite (81 files) | **739 passed, 0 failed, 1 deselected** |
| Live suite (`-m live_ollama_smoke`), baseline (before this phase's new tests) | 40 passed, 0 failed |
| Live suite (`-m live_ollama_smoke`), final (after this phase's new tests) | see `PHASE_13_CLOSURE.md` for the confirmed post-change result |
