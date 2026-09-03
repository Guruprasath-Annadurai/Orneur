# Phase 13 — Trust Boundaries

Explicit trust transitions, per spec §5.

| Boundary | Trusted fields | Untrusted fields | Validation | Authorization | Failure behavior |
|---|---|---|---|---|---|
| user → Kernel | session/tenant identity from auth layer | message content | schema validation, moderation | entitlement check (`orca/auth/store.py`) | 402/deny, never silently downgraded to a trusted path |
| retrieved content → Truth Fabric | none — all retrieved text is evidence, never instruction | full document text, URLs | injection-pattern scanning (`orca.truth.fetch`), citation structural checks | N/A (evidence, not authority) | excluded from EvidenceGraph, not silently trusted |
| memory → planner | scope/tenant metadata from Memory Continuum's own store | recalled fact text | firewall query (scope-checked), consolidation gating | scope isolation (`orca/memory/`) | excluded from recall if scope mismatched |
| model output → AgentRuntime | none — model text is a proposal, never a grant | tool selection reasoning, claimed capabilities | schema-validated tool call structure | `check_capabilities()` against the runtime's own frozenset | `CAPABILITY_MISSING`/`POLICY_DENIED` |
| tool result → WorldState | tool_id, side_effect_class (from ToolSpec, code-defined) | the actual returned content | none beyond becoming an ordinary `known_fact` string | N/A — WorldState facts are data, never authority (confirmed this phase, `test_redteam_cross_layer_chains.py`) | content stored as-is, no special interpretation |
| connector → AgentRuntime | `ConnectorIdentity`/`ConnectorInstance` (registry-issued) | document/message payloads | tenant-scoped lookup, capability check | `Capability.CONNECTOR_READ`/`CONNECTOR_WRITE` per action | denied before tool execution |
| approval → CapabilityLease | `issuer: LeaseIssuerClass` (closed enum, caller-supplied) | `approval.approved_by`/`reason` (free text) | `issue_lease()`'s structural guards (wildcard rejection, duration cap, exact-argument binding) | issuer must be HUMAN_APPROVAL/SYSTEM_POLICY/ADMIN_POLICY | `LeaseIssuanceError`, fail-closed |
| simulation → execution gate | `result_hash` (HMAC-signed by Chamber) | predicted effects, blast radius (attacker-visible but not attacker-writable post-signing) | signature verification | `evaluate_execution_gate()` never itself authorizes | `INVALID_SIMULATION_STATE`-shaped rejection |
| FailureEvent → curriculum compiler | `verification_state` (set only by `pipeline.verify_event()`), `root_cause` | `input_reference`/`evidence_reference` excerpts | triage rule table (deterministic) | training destination derived from `privacy_class`, never from event text | `HUMAN_REVIEW`/`RUNTIME_BUG`/`DISMISS` |
| dataset → training backend | `checksum`, `approval_state=APPROVED` | record content | `verify_against_files()`, freeze-immutability check | `DatasetManifest.approve()` rejects model identities | `DatasetFrozenError`/checksum mismatch raised |

## Summary property

No row above allows an **untrusted** field to become the **authorization**
decision for that boundary — every boundary's actual gate is a
code-defined, closed-type value (an enum, a signature, a capability
frozenset) that untrusted content cannot write to, only read alongside.
This is the property every attack campaign in this phase tested against.
