# Phase 18 — Epistemic State Specification

Canonical architecture document for `orneur/intelligence/epistemic/`.
Phase 18 CONSUMES Phase 17 OCL (`orneur/intelligence/ocl/`) read-only —
it does not modify OCL's schema, does not redefine OCL enums, and does
not reopen any Phase 17 closure.

## Doctrine

Locked, non-negotiable:

- Epistemic state is an independently computed property of a cognitive
  proposition relative to explicit evidence, derivation structure,
  contradiction state, verification feasibility and an explicit
  assessment context.
- Provenance is not truth. Citation is not verification. Evidence
  reference is not evidence verification. Model confidence is not
  knowledge. Human input is not automatically fact. A deterministic-
  policy reference is not automatically epistemic truth merely because a
  model typed those words.
- Missing evidence is not falsehood. Contradiction must not be hidden by
  confidence. UNVERIFIABLE is not a synonym for UNKNOWN. KNOWN is not a
  synonym for "the model sounded certain."
- Raw chain-of-thought is not required, stored, or exposed — OCL never
  had a field for it, and Phase 18 adds none.
- Epistemic state grants NO authority: no execution, policy, Court,
  approval, verification-truth, model-promotion, tool-permission,
  budget, human-approval, or release-approval consequence follows from
  any Phase 18 object. See `test_epistemic_architecture.py` for the
  enforced import boundary.

## States

| State | Definition |
|---|---|
| `KNOWN` | A direct, qualified (trusted-tier, `VERIFIED`) evidence basis resolves the proposition in exactly one direction, with no qualified opposing basis. Does NOT mean the proposition is true — pair with `EpistemicPolarity` (`KNOWN`+`AFFIRMED` vs `KNOWN`+`REFUTED`). |
| `INFERRED` | No direct qualified basis, but an evidence-rooted derivation (via `SUPPORTS`/`DERIVED_FROM`/`FALSIFIES`) traces back to at least one qualified evidence root, with no qualified opposing basis. |
| `UNCERTAIN` | Some epistemically relevant signal exists (unverified/stale/unavailable/invalid/inconclusive evidence, pending or temporarily-unavailable verification, or an unqualified contradiction) but it is insufficient to resolve the proposition. |
| `DISPUTED` | Qualified support AND qualified refutation coexist (direct and/or derived) for the same proposition. |
| `UNKNOWN` | No usable epistemic basis exists at all — not a claim of falsehood. |
| `UNVERIFIABLE` | A `TRUSTED_DETERMINISTIC_VERIFIER`-tier `VerificationFeasibilityRecord` explicitly marks the target `STRUCTURALLY_UNVERIFIABLE`, and no qualified resolution already exists. High bar: a model, a failed tool call, or a `TRUSTED_TOOL_RESOLVER`-tier record cannot mint this state. |

## Polarity

`EpistemicPolarity`: `AFFIRMED`, `REFUTED`, `MIXED`, `UNRESOLVED`. Claim
direction, orthogonal to state quality — `KNOWN`+`AFFIRMED` and
`KNOWN`+`REFUTED` are both valid, equally "known" outcomes.

## Trust boundary

`EpistemicResolutionTrustContext` (`UNTRUSTED`, `TRUSTED_TOOL_RESOLVER`,
`TRUSTED_DETERMINISTIC_VERIFIER`) is supplied by the CALLER of
`resolver.assess_artifact()` as a required, strictly-typed keyword
argument — never parsed from a payload. `trust.is_valid_resolution_trust_context()`
uses `isinstance()`, not membership-by-value, so a bare Python string
equal to a member's `.value` is rejected. If `resolution_trust_context`
is `UNTRUSTED`, no `ResolvedEvidence` record — regardless of its own
`status`/`stance` fields — can establish `KNOWN` or seed an `INFERRED`
derivation. Only `TRUSTED_DETERMINISTIC_VERIFIER` may mint
`UNVERIFIABLE`.

## Evidence resolution contract

`ResolvedEvidence` and `VerificationFeasibilityRecord` (models.py) are
explicit, separately-typed parameters to `assess_artifact()` — never
derived from parsing an OCL atom's or artifact's `metadata`. This is the
structural mechanism (not a blocklist of key names) that makes
self-elevation via `metadata={"epistemic_state": "KNOWN", ...}`
impossible: there is no code path that reads `metadata` to build a
resolution record. `EvidenceResolutionStatus` (`VERIFIED`, `UNVERIFIED`,
`STALE`, `UNAVAILABLE`, `INVALID`) and `EvidenceStance` (`SUPPORTS`,
`REFUTES`, `INCONCLUSIVE`) are orthogonal — only `VERIFIED`+`SUPPORTS`/`REFUTES`
under a qualified trust context establishes a direct basis;
`VERIFIED`+`INCONCLUSIVE` never establishes direction; `INVALID`
invalidates that evidence's own basis, it does not refute the
proposition; staleness has no universal age heuristic — it is an
explicit status the trusted resolver reports, never computed from
`assessed_at` wall-clock age.

## Relation semantics

Not every `RelationKind` propagates epistemic effect. Only four are
rigorously reasoned through, in `enums.RELATION_EPISTEMIC_SEMANTICS`:

| Relation | Effect | Propagation direction |
|---|---|---|
| `SUPPORTS` | `SUPPORT` | source → target |
| `DERIVED_FROM` | `SUPPORT` | target (basis) → source (derived) |
| `FALSIFIES` | `REFUTATION` | source → target |
| `CONTRADICTS` | `CONFLICT` | symmetric, handled directly by the resolver's contradiction logic |

Every other `RelationKind` — including `CAUSES` and `CORRELATES_WITH`,
which must never automatically prove truth — defaults to
`RelationEffect.NONE` via `get_relation_semantics()`: fail closed, never
guess a relation's meaning.

## Evidence-rooted derivation and cycle safety

`graph.compute_evidence_rooted_reachability()` is a monotonic,
forward-only worklist BFS seeded exclusively from direct qualified
evidence roots (computed by the resolver before the graph pass runs).
An atom can only enter the support/refutation-reachable sets by walking
a relation edge FROM an atom already in the set. A cycle with no root
outside it therefore can never get any member added — this is the
mechanism, not a special-case cycle detector, that satisfies "no
circular self-validation." Complexity is O(V + E): each atom is
enqueued at most once per direction. Separately, OCL's own compiler
already forbids cycles in `DEPENDS_ON`/`DERIVED_FROM`/`SUPERSEDES`
(`ACYCLIC_RELATION_KINDS`), so a circular `DERIVED_FROM` graph cannot
even compile — defense in depth, verified in
`tests/epistemic/test_inference_graph.py`.

## Dispute rules

`DISPUTED` requires a QUALIFIED contradiction: both a qualified support
basis and a qualified refutation basis (direct or derived) on the same
atom. Two unsupported model assertions merely linked by a `CONTRADICTS`
relation, with neither side qualified, is "mere disagreement" — it
downgrades both atoms to `UNCERTAIN` with reason code
`UNQUALIFIED_CONTRADICTION`, never `DISPUTED`.

## Precedence

Applied per atom, after computing direct/derived support and refutation
membership:

1. Both support and refutation basis present → `DISPUTED`
2. Direct support only → `KNOWN` / `AFFIRMED`
3. Direct refutation only → `KNOWN` / `REFUTED`
4. Derived support only → `INFERRED` / `AFFIRMED`
5. Derived refutation only → `INFERRED` / `REFUTED`
6. Trusted structural feasibility says `STRUCTURALLY_UNVERIFIABLE` and no basis above applies → `UNVERIFIABLE`
7. Some other relevant-but-insufficient signal exists → `UNCERTAIN`
8. Nothing at all → `UNKNOWN`

This exactly matches the normative baseline
(`DISPUTED > KNOWN > INFERRED > UNVERIFIABLE > UNCERTAIN > UNKNOWN`),
derived from first principles and exercised against every required edge
case in `tests/epistemic/`.

## Overlay architecture and binding

`EpistemicOverlay` never lives as a field on `CognitiveArtifact` or
`CognitiveAtom` — it is a wholly separate object, produced only by
`resolver.assess_artifact()`, referencing its source by
`source_artifact_id` + `source_artifact_digest` (an OCL
`canonical.digest()` value). `resolver.verify_overlay_binding()` raises
`errors.SourceArtifactMismatch` if either field disagrees with the
artifact's current canonical identity — an overlay is never silently
reused against a mutated or different artifact.

## Canonicalization

`canonical.py` mirrors OCL's own chain exactly: sort every collection
deterministically by ID → recursively normalize dataclasses/enums/
mappings to JSON-safe primitives → `json.dumps(sort_keys=True,
separators=(",", ":"), allow_nan=False, ensure_ascii=False)` → SHA-256
hex digest over the UTF-8 bytes. Same semantic input (including
permuted collection order) always produces the same canonical bytes and
digest — verified in `test_canonicalization.py`.

## Diff

`diff.diff(a, b) -> EpistemicDiff` is representation/audit only — no
Phase 19 enforcement decision is made here. Epistemic state is
time/context-relative and explicitly NOT monotonically increasing: new
contradicting evidence can downgrade `KNOWN` to `DISPUTED`, exercised in
`test_epistemic_diff.py` alongside the other five required transitions.

## Non-goals (this phase)

- No hard enforcement, abstention policy, or integrity gate (Phase 19).
- No router/escalation integration to Genesis/Novus/Aeternum (Phase 20).
- No claim-level natural-language entailment verifier.
- No domain-global evidence-freshness policy.
- No cryptographic proof that a caller genuinely deserved the trust tier
  it claims — that is an invocation-boundary concern outside this
  package, exactly as OCL's own `CompilationTrustContext` doctrine
  states.

## Phase 19 handoff

Phase 19 may treat `EpistemicOverlay`/`EpistemicAssessment` as
read-only, versioned, replayable evidence for whatever integrity policy
it builds (abstention, downgrade-on-staleness, contradiction-resolution
obligations). It must call `verify_overlay_binding()` before trusting an
overlay against a given artifact, and must not itself grant authority
from a state value without a separate, explicit authorization decision.
