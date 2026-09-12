# PHASE 16 — Intelligence-Specific Threat Model

Format: Threat → Existing control → Missing control → Future owning phase → Phase-16 blocker (Y/N).
A "Missing control" is documented honestly as missing — it is never marked as existing because a
future phase intends to build it.

1. Model self-promotes its own checkpoint → Existing: `ModelRegistry.promote()` is the sole write
   path and requires a `PROMOTABLE` `EvaluationReport` → Missing: no automated block yet if a
   future caller constructs a fake `EvaluationReport` in-process → Phase 22 → N
2. Model output treated as authorization → Existing: `orca/agent/policy.py` is the sole authorizer,
   verified to not import `orca.deliberation` → Missing: no runtime assertion firing if a future
   change wires Court output into a decision path → Phase 17 (contract-level enforcement) → N
   (INV-NATIVE-002 test added this phase mitigates regression)
3. Router silently substitutes an unavailable checkpoint → Existing:
   `RoutingReason.ARTIFACT_UNAVAILABLE`/`AETERNUM_ABSENT` make this explicit → Missing: none found
   → N/A → N
4. Router escalates to Aeternum as default preference → Existing: escalation direction is
   Genesis→Novus→Aeternum by design → Missing: no automated test currently proves the router never
   *defaults* to Aeternum for ordinary tasks → Phase 20 → N
5. Legacy `orca/variants/` "god-mode"/"apex orchestrator" code path reintroduced as a shortcut →
   Existing: 0 test references, not called from the live routing path → Missing: no removal yet →
   Deprecate before Phase 17 (this phase's own recommendation) → **Y (soft) — flagged, not blocking, no evidence of live use**
6. `orca/brain/memory.py::SemanticMemory`'s shared-key pattern reused for a new global-state feature
   → Existing: none (it is architecturally exposed) → Missing: no lint/test currently forbids new
   process-wide shared cache keys → Phase 26 boundary rule (documented, not enforced) → N
7. External-provider (frontier) response mislabeled as a native Genesis/Novus/Aeternum output →
   Existing: `frontier_runtime.py` is structurally separate from `ollama_runtime.py` → Missing: no
   automated test asserts a frontier response can never carry a native `ModelSpec` identity → Phase
   17 entry-contract validation → N
8. Training code mutates the active checkpoint registry outside `promote()` → Existing:
   `promote()` is the only registry mutation entry point found → Missing: no test enumerates every
   writer of `registry_state.json` to prove exhaustiveness → Phase 18 → N
9. Memory (Phase 5 Continuum) bypasses `firewall.py` → Existing: `firewall.py`'s stated purpose
   ("No recalled memory reaches [output] without...") → Missing: not independently re-verified this
   phase (full-file read deferred) → Phase 26 audit → N
10. Court writes an approval directly to Mission → Existing: zero `orca.mission` imports found in
    `orca/deliberation` → Missing: none found → N/A → N
11. Model orchestration (`orca/agent`) bypasses Mission's operation lifecycle for a real
    side-effecting action → Existing: zero `orca.mission` imports in `orca/agent` (agent triggers
    actions through tool_registry/policy, not Mission directly — Mission is a Relay/API-layer
    concern per Phase 15) → Missing: not verified that the Relay layer itself always requires
    Mission before invoking agent side effects (out of Phase 16 scope, Phase 15's own domain) → N
12. A future PR renames `LifecycleState` values to match an external spec, breaking 24 dependent
    test files silently → Existing: none — this is a process/discipline threat, not a code one →
    Missing: a change-review checklist → Ongoing (§22's own "why is this necessary" test is the
    control) → N
13. `mcp` package supply-chain break (recurrence of the 15.15 root cause) → Existing: pinned
    `mcp>=1.0.0,<2.0.0` in `pyproject.toml`, `test_mcp_fs_server_sandbox.py` runs unconditionally in
    CI → Missing: none currently → N/A → N
14. CI false-green recurrence (pipefail regression) → Existing: `scripts/ci/run_deterministic_tests.sh`
    + `tests/test_ci_pytest_fail_closed.py`'s structural+behavioral tests → Missing: none found →
    N/A → N
15. A Phase 17 OCL implementation calls a model and treats its raw text as a policy fact → Existing:
    none yet (OCL doesn't exist) → Missing: the assertion/measured-fact/policy-fact/evidence type
    distinction is only conceptual today (§11) → Phase 17 (must implement before OCL ships) → **Y — this is exactly what Phase 17's entry contract must close before OCL semantics are written**
16. Twin Distillation (future) trains on unsanitized model output → Existing: `orca/learning/sanitize.py`
    exists as a precedent pattern → Missing: not yet wired to any Twin Distillation code (doesn't
    exist) → Phase 24 → N
17. Failure Genome (future) admits a failure candidate without security review → Existing:
    `orca/learning/security.py` guards exist for the current Phase 12 pipeline → Missing: not yet
    connected to a "Failure Genome" concept (doesn't exist) → Phase 25 → N
18. Outcome Memory (future) becomes another process-wide shared cache like `all_sessions_summary` →
    Existing: the Phase 15.15 incident is documented precedent → Missing: no enforced lint yet →
    Phase 26 (binding rule recorded in canonical architecture doc) → N
19. Capability Delta Ledger (future) is used to auto-grant escalation without human review →
    Existing: none (doesn't exist) → Missing: everything — pure future concern → Phase 27 → N
20. Governed self-improvement loop bypasses six-hour governance window (Phase 15 Relay concept) →
    Existing: Relay's six-hour governance is a Phase 15 primitive, unrelated code paths → Missing:
    no self-improvement loop exists to test against → Phase 30+ → N
21. A model requests tool execution and the tool registry executes without capability check →
    Existing: `orca/agent/tool_registry.py` "Wraps the EXISTING, sound tool..." plus
    `orca/agent/capability.py` → Missing: not independently re-verified this phase → Phase 19 → N
22. Evaluation harness (`eval_harness.py` per package) is gamed by weakening its own assertions to
    pass → Existing: Phase 15's explicit anti-test-gaming discipline, still in force this phase →
    Missing: none found this phase (no harness was touched) → N/A → N
23. A future contributor adds a checkpoint-lookup call with no hermetic-test seam, reintroducing the
    Phase 15.15 CI-hermeticity class of bug → Existing: established pattern
    (`checkpoint_lookup=...` injectable parameter, `monkeypatch.setattr` fallback) documented in
    `tests/test_society_router.py` and now 8 other files → Missing: no repo-wide lint enforcing the
    pattern → Ongoing discipline → N
24. Public model naming leaks parameter count (e.g., "Genesis 3B") → Existing: `display_name` field
    already omits it → Missing: no test asserts this at the presentation layer (none exists yet) →
    Phase 17+ UI work → N
25. A future PR reintroduces `orca/variants/`'s "god-mode" framing into new native-model code →
    Existing: this document's SAFE_TO_DEPRECATE classification → Missing: not yet actually
    deprecated/removed (deferred per cost-control and non-destructive-rewrite discipline) → Before
    Phase 17 gate → **Y (soft, tracked as REQ-NATIVE-* below, not a hard blocker since no live use exists)**
26. Aeternum's "absence" is silently reinterpreted as "just needs a bigger download" by a future
    contributor, triggering a large paid GPU/training spend without owner authorization → Existing:
    `mark_family_absent("aeternum")` is explicit and documented as by-design → Missing: no
    automated spend-gate exists in code (this is a process control, per §28) → Ongoing (owner
    approval required) → N
27. Frontier (external) API keys/credentials leak into a native-model training dataset → Existing:
    `orca/learning/sanitize.py` (PII/secret sanitization before candidate admission) → Missing: not
    verified this phase against frontier-specific credential shapes → Phase 18 → N
28. Escalation engine (`orca/society/escalation.py`) is called with role confusion (wrong
    CognitiveRole) leading to an under-qualified model handling a high-risk task → Existing:
    `role_requirements.py` declares requirements per role → Missing: not independently re-verified
    this phase → Phase 20 → N
29. A future Phase 17 implementation adds telemetry that logs raw model chain-of-thought as if it
    were a policy fact in an audit trail → Existing: none (doesn't exist yet) → Missing: the
    assertion-vs-fact contract (§11) → Phase 17 → **Y — same root issue as #15**
30. Multiple agents (future Model Society expansion) reach contradictory Court verdicts and the
    contradiction is silently resolved by picking the more permissive one → Existing:
    `disagreement.py` ("Disagreement as a structured signal... Never majority...") → Missing: not
    independently re-verified this phase → Phase 20/24 → N

**Phase 16 blockers found: none that are hard blockers.** Three items (5, 15/29, 25) are flagged
as things Phase 17 must resolve as part of its own entry-contract work, not things Phase 16 itself
must implement (Phase 16 is audit-only per its own scope restriction).
