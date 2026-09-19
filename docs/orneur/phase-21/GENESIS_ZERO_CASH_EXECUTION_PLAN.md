# Genesis Zero-Cash Execution Plan

**Phase 21B.4.10.** Owner cash constraint: **₹0**. This document
records the current, live-reverified Modal billing state and restates
every other zero-cash compute option's status — no compute was
started, no account was created, no top-up occurred.

## Live-reverified Modal billing (`modal billing summary --json`, 2026-09-19)

```
metered_cost:  $0.04000000
billed_cost:   $0E-8  (i.e. $0.00)
credits applied: -$0.04000000
metered_cost_breakdown:
  ephemeral_apps:  $0.03921463
  deployed_apps:   $0.00101405
  volumes:         $0.00
  llm_tokens:      $0.00
```

**Billed cost remains $0.00** — every cent of metered usage across this
entire project's Modal work (Phase 21B.4.6 through 21B.4.9.2) continues
to be fully absorbed by the workspace's included credits. No spend this
phase added to the metered total (no compute was run).

## Spend-limit evidence: what is programmatically reverifiable vs. what is not

**The `modal billing` CLI (`report` / `summary` / `rates`) does not
expose the workspace's spend-limit setting.** This phase attempted only
these supported CLI commands — no private or unsupported API was
probed, consistent with the owner's explicit prohibition. Therefore:

- **Previously owner-verified dashboard state** (Phase 21B.4.7A): the
  owner set the Modal workspace's spend limit to $0 via the Modal
  dashboard UI, and this was confirmed live at that time via the
  billing summary/rates CLI showing `billed_cost: $0.00` consistent
  with a hard $0 ceiling. This dashboard-level setting is **not**
  re-checked this phase (no CLI/API path exists to do so), and this
  phase does not claim to have reprogrammatically reverified it — the
  claim that follows is scoped to what the CLI can actually show.
- **Current supported CLI billing evidence** (this phase): `billed_cost:
  $0.00` and `metered_cost: $0.04` remain consistent with the spend
  limit still being in effect, but this is INDIRECT evidence (a $0
  billed cost is also what a workspace with a much higher, unused spend
  limit would show) — it does not, by itself, prove the $0 limit is
  still configured. The owner's own dashboard remains the authoritative
  source for that specific setting.

## Modal — primary zero-cash compute source

- Workspace: `guruprasath-annadurai` (Starter plan), $30/month included
  compute, unchanged.
- Status: qualified and live-verified across many prior phases
  (Phase 21B.4.6 through 21B.4.9.2) for trusted GPU inference (basic
  CUDA/BF16/FP8, and a real vLLM 0.6.3.post1 load+generate cycle).
- **No candidate-specific smoke run was attempted this phase** — Stage 0
  (`GENESIS_CANDIDATE_EXECUTION_QUALIFICATION.md`) is identity/license/
  runtime research only, performed via small HTTP metadata calls to the
  Hugging Face Hub API (never Modal, never a weight download).
- No persistent Modal Volumes were created this phase (owner spec §17's
  explicit "no persistent Modal Volumes" instruction) — the registry's
  candidate identity data lives entirely in this repository's
  version-controlled JSON, not in any Modal-side storage.

## Race Engineering (secondary compute source, unchanged research-only status)

Per Phase 21B.4.8's own note: Race's current live GPU inventory/rates
were researched but never checked against actual spend requirements in
enough detail to declare it sufficient, and no balance/spend/top-up has
occurred. **Unchanged this phase** — no new research, no top-up, no
spend.

## Lightning AI (unqualified, unchanged)

Remains `NOT_QUALIFIED` (Phase 21B.4.5's account-creation capability
boundary) unless the owner has separately and legitimately completed
account access since. No such completion was reported or verified this
phase — status unchanged.

## Hard prohibitions this phase honored (restated for the record)

No top-up, no purchase, no wallet-cash spend, no paid-instance creation,
no paid frontier API call, no full-weight download, no GPU launch. Owner
cash spent this phase: **$0.00 / ₹0**.
