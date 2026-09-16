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

`DISPUTED` arises in two ways:

1. A single atom has both a qualified support basis and a qualified
   refutation basis (direct or derived) — e.g. one evidence resolution
   supports it, another refutes it.
2. A **qualified `CONTRADICTS` conflict**: see the truth table below.

Two unsupported model assertions merely linked by a `CONTRADICTS`
relation, with neither side qualified, is "mere disagreement" — it
downgrades both atoms to `UNCERTAIN` with reason code
`UNQUALIFIED_CONTRADICTION`, never `DISPUTED`.

### Qualified `CONTRADICTS` truth table

For a relation `A CONTRADICTS B`, each side's independently established
polarity (`AFFIRMED` = qualified support only, `REFUTED` = qualified
refutation only, `None` = no qualified basis at all,
`DISPUTED` = already both) determines the outcome
(`resolver._classify_contradicts_pairs`):

| A | B | Outcome |
|---|---|---|
| `AFFIRMED` | `AFFIRMED` | **Genuine qualified conflict** — both A and B are forced to `DISPUTED`/`MIXED` with reason `VERIFIED_CONTRADICTION`. Their independently-established bases cannot both be true given the `CONTRADICTS` relation; contradiction must not be hidden by confidence. |
| `AFFIRMED` | `REFUTED` | Compatible with the relation (A true, B false, they contradict — consistent). No action; both keep their own state. |
| `REFUTED` | `REFUTED` | Compatible ("not both true" is satisfied). `CONTRADICTS` must not invent truth about either side merely from the relation. No action. |
| qualified (`AFFIRMED`/`REFUTED`) | `None` | The qualified side is **not downgraded** merely because the other side is unsupported prose. The unsupported side gets reason `CONTRADICTED_BY_QUALIFIED_ATOM` → `UNCERTAIN` (not `UNKNOWN` — an established atom contradicting it is a real, epistemically relevant signal, unlike a bare unsupported assertion with zero signal). |
| `None` | `None` | Handled separately by the existing "mere disagreement" rule → `UNCERTAIN` / `UNQUALIFIED_CONTRADICTION` on both. |

## Precedence

Applied per atom, after computing direct/derived support and refutation
membership and the `CONTRADICTS` classification above:

1. Both support and refutation basis present, OR the atom is on the
   `AFFIRMED`+`AFFIRMED` side of a qualified `CONTRADICTS` pair → `DISPUTED`
2. Direct support only → `KNOWN` / `AFFIRMED`
3. Direct refutation only → `KNOWN` / `REFUTED`
4. Derived support only → `INFERRED` / `AFFIRMED`
5. Derived refutation only → `INFERRED` / `REFUTED`
6. Trusted structural feasibility says `STRUCTURALLY_UNVERIFIABLE` and no basis above applies → `UNVERIFIABLE`
7. Some other relevant-but-insufficient signal exists (including `UNQUALIFIED_CONTRADICTION` or `CONTRADICTED_BY_QUALIFIED_ATOM`) → `UNCERTAIN`
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
digest — verified in `test_canonicalization.py`, and, critically, also
verified for the **default, unfixed-`overlay_id` production invocation
path** in `test_determinism_closure.py` (see below) — the earlier
version of this claim was only proven for a test that explicitly pinned
`overlay_id="overlay-fixed"`, which did not exercise the real default
code path.

## Deterministic default `overlay_id` (closure)

**Reproduced defect**: prior code did
`overlay_id=overlay_id or str(uuid.uuid4())`. Two calls to
`assess_artifact()` with byte-identical artifact/evidence/context/
assessed_at inputs, neither passing `overlay_id`, produced two
different `overlay_id`s and therefore two different canonical digests —
a direct violation of the "same input → same overlay" doctrine that the
existing canonicalization test did not catch, because it always pinned
`overlay_id` explicitly.

**Fix**: `resolver._default_overlay_id(source_digest, context_digest,
assessed_at)` — `sha256("epistemic-overlay:{source_digest}:{context_digest}:{assessed_at}")` —
replaces the `uuid4()` default. It is a pure function of already-canonical
inputs: no wall-clock read, no randomness, no process identity. An
explicit `overlay_id` argument still overrides it. Verified in
`test_determinism_closure.py` (8 tests): identical default calls
produce identical `overlay_id`/canonical JSON/digest; changing
`assessment_context_id`, `assessed_at`, or `resolved_evidence` changes
the derived `overlay_id`; a direct counterfactual test demonstrates
`uuid4()` is non-deterministic (the exact property that made it unfit
as a canonical default).

## Feasibility record conflicts (closure)

**Reproduced defect**: prior code did
`feasibility_by_atom[record.target_atom_id] = record` in a plain loop —
the *last* `VerificationFeasibilityRecord` for a given atom silently
won. `[PENDING, STRUCTURALLY_UNVERIFIABLE]` for the same atom resolved
to `UNVERIFIABLE`; the reversed order `[STRUCTURALLY_UNVERIFIABLE,
PENDING]` resolved to `UNCERTAIN` — an order-dependent result from an
identical input *set*, violating fail-closed semantics.

**Fix**: `resolver._reject_conflicting_feasibility()` — at most one
`VerificationFeasibilityRecord` per `target_atom_id`; a second record
for the same atom, identical or not, raises
`errors.ConflictingVerificationFeasibility`. Verified in
`test_feasibility_conflicts.py` (7 tests), including both input
orderings failing identically and a same-digest check proving the
assessment-context canonicalization is itself order-independent for
non-conflicting records across different atoms.

## Strict field-type validation (closure)

**Reproduced defect**: `ResolvedEvidence`/`VerificationFeasibilityRecord`
are plain frozen dataclasses with no field-level type enforcement at
construction. A caller passing bare strings (`status="VERIFIED"`,
`stance="SUPPORTS"`, `feasibility="PENDING"`) instead of genuine enum
members did not raise — every `record.status is
EvidenceResolutionStatus.X` comparison in the resolver is simply
`False` for a plain string, so the record silently fell through to
`EpistemicReasonCode.EVIDENCE_INCONCLUSIVE` rather than being rejected.

**Fix**: `resolver._validate_and_normalize_resolved_evidence()` /
`_validate_and_normalize_feasibility_record()` validate every field
(`require_string`, `require_enum_member`, ISO-8601 timestamp check)
before any semantic use, for every record, unconditionally — called at
the top of `assess_artifact()`. Malformed fields raise
`errors.InvalidObjectType`/`errors.InvalidStructuredValue`, never a raw
`AttributeError`/`TypeError`/`KeyError`. Verified in
`test_type_boundary.py` (32 parametrized tests covering `None`, wrong
enum type, `int`, `bool`, wrong dataclass type, and malformed
timestamps for every closed-enum and string field on both record
types).

## Deep immutability of structured metadata (closure)

**Reproduced defect**: `resolver._freeze_metadata()` did
`MappingProxyType(dict(metadata))` — a shallow freeze. A nested
`{"nested": {"items": [1, 2]}}` metadata value left the inner dict and
list as the caller's own mutable objects; mutating
`metadata["nested"]["items"]` after `assess_artifact()` returned
silently changed the resulting overlay's canonical digest.

**Fix**: `freeze.validate_and_freeze()` recursively validates and
freezes every structured value reachable from overlay metadata AND from
`ResolvedEvidence`/`VerificationFeasibilityRecord` metadata: `dict` →
`MappingProxyType`, `list`/`tuple` → `tuple`, strings/ints/bools bounded
and passed through, non-finite floats and unsupported object types
rejected, depth/key-count/string-length bounded
(`limits.MAX_METADATA_DEPTH`/`MAX_METADATA_KEYS`/
`MAX_STRING_FIELD_LENGTH`). No object reachable from a constructed
`EpistemicOverlay` is mutable, and `validate_and_freeze()` never mutates
its input (verified separately). Sets/frozensets are explicitly
unsupported (fail closed) rather than given an undefined canonical
ordering. Verified in `test_deep_immutability.py` (8 tests), including
a direct digest-stability-after-caller-mutation test.

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
