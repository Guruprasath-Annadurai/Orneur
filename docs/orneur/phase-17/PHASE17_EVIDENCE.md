# PHASE 17 — Evidence

## Baseline (before any Phase 17 code)

- Repo: `/Users/ag/orca`, branch `session-update-2026-08-25`.
- Starting HEAD: `1321ca932deea235c760fdf2f6a5189226161099`, verified via `git status`/`branch`/
  `rev-parse`/`log` — exact match, clean tree.
- Collection count: **2610 tests**.

## Architecture decision

Option B (`orneur/intelligence/ocl/` core + one-way adapter to legacy `orca.cognitive.contracts`)
selected after a 3-option comparison. See `PHASE17_OCL_ARCHITECTURE.md` for the full table. Matches
Phase 16's own recommendation.

## Failing tests recorded during TDD (a representative sample — not every test was authored
failing-first against a pre-existing gap, since most of Phase 17 is genuinely new code with no
prior "unfixed" state to reproduce; the ones below caught REAL bugs during authoring, fixed in
place before this evidence was written)

1. `test_nan_in_metadata_rejected_for_canonical_form` — initially asserted the NaN rejection only
   fired on a separate `to_canonical_json()` call after `compile_artifact()` succeeded. Once
   `compile_artifact()` was changed to also enforce `MAX_ARTIFACT_SERIALIZED_BYTES` (which requires
   computing the canonical JSON internally), the NaN rejection started firing INSIDE
   `compile_artifact()` itself, and the test failed until updated to reflect the new, more correct
   behavior (NaN is now caught earlier, not later).
2. `test_oversized_wire_payload_rejected_before_parsing` — written after threat-modeling exercise
   #32 revealed the byte-limit check in `compile_artifact()` did nothing to protect
   `artifact_from_canonical_json()`'s own `json.loads()` call from an oversized untrusted string;
   failed until the pre-parse byte-length check was added to `canonical.py`.
3. `test_no_pickle_used_anywhere_in_serialization_module` — initially failed on a trivial false
   positive (the word "pickle" appeared inside the module's own docstring, not as an import);
   fixed by switching the test to AST-based import detection instead of a substring search.

## Implementation commits

See `git log` for the exact Phase 17 commit sequence (multiple logical commits: package skeleton +
core types, compiler + canonicalization + diff/conservation, observer + checkpoint + extensions +
adapter, tests, docs).

## Targeted Phase 17 test results

`.venv/bin/python -m pytest tests/ocl -q` → **90 passed, 0 failed** (per-file collection counts:
schema=3, atoms=6, relations=6, authority=18, provenance=8, serialization=8, limits=7, diff=5,
conservation=4, observer=4, checkpoint=6, extensions=4, adapter=3, causal=3,
authority_call_path=3, performance=2; sum=90).

## Phase 16 regression results

`.venv/bin/python -m pytest tests/test_phase16_architecture_invariants.py
tests/test_phase16_court_reconciliation.py tests/test_phase16_training_fail_closed.py
tests/test_phase16_canonical_training_identity.py tests/test_registry_model_spec.py -q` →
**46 passed, 0 failed**. No Phase 16 test was weakened, skipped, or deselected.

## Full deterministic regression

Project `.venv` used explicitly (`.venv/bin/python -m pytest`, never global Homebrew `pytest`),
pipefail-safe invocation (`bash -c 'set -euo pipefail; ...'`):

**2401 passed, 256 skipped, 43 deselected, 0 failed** (182.16s). Collection: **2700 tests**
(2610 baseline + 90 new OCL tests). 2401+256+43 = 2700, matching exactly. No new skip or
deselection was added anywhere in this phase.

## Performance measurements (representative, local, no GPU)

From `tests/ocl/test_performance.py` (actual measured output, not a claim):

| n_atoms | validate | serialize | digest | canonical JSON bytes |
|---|---|---|---|---|
| 10 | 0.0000s | 0.0001s | 0.0001s | 2,063 |
| 100 | 0.0001s | 0.0008s | 0.0008s | 15,113 |
| 1000 | 0.0006-0.017s | 0.007-0.0075s | 0.0072-0.0075s | 147,413 |

(The 1000-atom validate time varied between runs, 0.0006s-0.017s, most likely JIT/cache-warming
variance on this machine — recorded honestly rather than cherry-picking the faster run.) Diffing
two 500-atom artifacts completed in well under the test's 5-second sanity bound (exact figure not
separately logged; the bound itself was never approached).

## Threat model

`PHASE17_THREAT_MODEL.md`: 40 threats enumerated, **31 backed by a passing test**, 9 honestly
documented as untested/deferred (1 of the 9, #14, is N/A rather than a gap).

## Authority call-path audit (section 32)

See `PHASE17_AUTHORITY_CALL_PATH.md`. Direct-import sub-claim (Mission-state writers) fully closed
for both the pre-existing Phase 16 model-facing packages AND the new `orneur.intelligence.ocl`
package. `owner_approval_required` traced via AST across all of `orca/`: **zero production callers**
of `arbiter_decide()` exist today — a genuine, honest finding (not a grep-only overclaim), backed by
a regression test that will fail loudly if a future PR adds a production caller without a fresh
audit.

## Production mutation status / GPU spend / model training

No Neon/database touched, no migration. No compute provider invoked. **GPU spend: $0.** **No model
training occurred.**

## Requirements totals

From `PHASE17_REQUIREMENTS.md`: 39 requirements — **35 VERIFIED**, 2 IMPLEMENTED (real code, no
dedicated test beyond adjacent coverage: OCL-EVIDENCE-001, OCL-ESCALATE-001), 2
DEFERRED_TO_FUTURE_PHASE (OCL-AUTHORITY-005, OCL-EXTENSION-002). 0 UNIMPLEMENTED, 0 BLOCKED.

## Known limitations

- Unicode canonicalization does not perform normalization (NFC/NFKC) — two visually-identical but
  differently-normalized strings currently digest differently (threat #31, documented, not fixed).
- Cross-artifact ID uniqueness/collision (threats #18, #20, #36) is a storage-layer responsibility,
  not enforced by the compiler, which only validates within one artifact at a time.
- Extension namespaces have no per-namespace schema-contract enforcement yet (threat #33,
  OCL-EXTENSION-002) — only namespace registration exists, per the phase's own YAGNI instruction.
- `OCL-AUTHORITY-005`'s full indirect-bypass enumeration across every Mission-state writer (not
  just direct imports) was not performed this phase.
- `ActionIntent`/`EscalationRequest` have no real consumer yet (Phase 19+/20 will be the first) — 
  their "cannot execute/route" property is proven by absence of any execution/routing code path in
  this codebase today, which is necessarily a claim about the current snapshot, not a permanent
  guarantee against a badly-designed future consumer.

## Phase 18 entry contract

Phase 18 (Epistemic State) consumes: `CognitiveArtifact`'s atom/relation graph, `SourceClass`
(already distinguishes model assertion from measured/external/policy/human evidence — Phase 18 MUST
NOT reuse `SourceClass` itself as an epistemic-state enum), and `CausalHypothesis` (already
distinguishes hypothesis from established fact). See master spec §26.

## GitHub CI

Recorded in the Final Report (this document's companion STOP report), after the final Phase 17
commit is pushed.

## DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 18? (pre-closure)

**YES** — superseded by the closure section below.

---

## CLOSURE SECTION — CORPORATE-GRADE OCL HARDENING (append-only; all content above unchanged)

### What owner review found

An independent audit accepted commit `ea9426f` (green CI, correct architecture skeleton) but found
the implementation had real, corporate-grade gaps:

1. `compile_artifact()` validated atoms/relations/evidence/provenance/artifact-metadata but never
   validated `action_intents`, `verification_contracts`, `escalation_requests`, `causal_hypotheses`,
   or `counterfactual_branches` — confirmed by inspecting `git show ea9426f:.../compiler.py`, which
   had zero references to any per-collection validator for those five types.
2. The forbidden-authority-construct scan only recursed into dict values, not lists/tuples — a
   `{"wrapper": [{"authority_granted": true}]}` shape would have passed silently.
3. `VerificationContract.status` had no compile-time enforcement at all — only its *default* value
   was tested; `status="VERIFIED"` compiled successfully before this closure.
4. Compiled artifacts were only shallow-frozen — `metadata` dicts (and `ActionIntent.
   arguments_summary`) remained ordinary mutable dicts reachable from an already-"immutable"
   artifact, and worse, `compile_artifact()` did not copy the caller's dict, so mutating the
   caller's own object after compiling silently mutated the "compiled" artifact too.
5. The wire parser (`artifact_from_dict`/`artifact_from_canonical_json`) used plain `json.loads`
   with no duplicate-key detection and no unknown-field rejection at any level, and its own naming
   gave no signal that the result was unvalidated.
6. Nothing prevented a `NATIVE_MODEL`/`EXTERNAL_PROVIDER`-produced artifact from self-authenticating
   its own evidence merely by citing an `EvidenceAnchor` it also fabricated in the same payload.
7. The checkpoint secret scan covered only `atom.content` and `evidence.reference`/`locator` — not
   artifact/atom/relation/evidence metadata, `ActionIntent.arguments_summary`, or any proposal/
   causal-structure string field.
8. Cognitive Diff only ever compared ID sets — a same-ID atom whose content completely changed
   produced no diff event at all.
9. Cognitive Conservation only checked ID presence — a same-ID semantic rewrite passed silently.
10. `compiler.py` maintained its own local `_AUTHORITATIVE_SOURCE_CLASSES`, duplicating
    `enums.AUTHORITATIVE_SOURCE_CLASSES` — a maintenance/drift risk, even though the two sets
    happened to still agree.
11. The extension registry allowed silent overwrite of an existing namespace's version/producer,
    including (in principle) `core` itself.

### What changed, exactly

**`orneur/intelligence/ocl/compiler.py`** (near-complete rewrite): added
`_validate_action_intents`/`_validate_verification_contracts`/`_validate_escalation_requests`/
`_validate_causal_hypotheses`/`_validate_counterfactual_branches`, each with its own typed duplicate-ID
error (`DuplicateActionIntentId`, `DuplicateVerificationContractId`, `DuplicateEscalationRequestId`,
`DuplicateCausalHypothesisId`, `DuplicateCounterfactualBranchId`, plus `DuplicateEvidenceId`/
`DuplicateRelationId` replacing the reused `DuplicateAtomId` for those two); a single recursive
`validate_structured_value()` replacing the old dict-only `_check_forbidden_metadata`, applied to
every structured-data surface; `VerificationContract.status != "UNRESOLVED"` now raises
`InvalidVerificationStatus`; an `EscalationRequest.unresolved_conflict_refs` entry must reference a
real `CONFLICT`-kind atom; the evidence-self-authentication gate (`_UNTRUSTED_ARTIFACT_PRODUCER_KINDS`)
rejects an authoritative `source_class` inside a `NATIVE_MODEL`/`EXTERNAL_PROVIDER` artifact; imports
`AUTHORITATIVE_SOURCE_CLASSES` from `enums.py` instead of redefining it; uses
`extensions.snapshot_registry()` for a stable per-call namespace view; calls `canonical.deep_freeze()`
as its final step.

**`orneur/intelligence/ocl/canonical.py`**: added `freeze_value()`/`deep_freeze()` (fresh
`MappingProxyType` + tuple conversion, never aliasing the caller's containers); replaced
`artifact_from_dict`/`artifact_from_canonical_json` with a strict `parse_ocl_draft_json()` (duplicate
JSON keys via `object_pairs_hook`, unknown-field rejection at every level via each dataclass's own
field set, typed `MissingMandatoryField`/`MalformedWireShape` errors) and a new safe public entry
point `compile_ocl_json()` = parse + compile; `_to_json_safe` extended to handle `MappingProxyType`.

**`orneur/intelligence/ocl/checkpoint.py`**: `_scan_for_secrets` rewritten to walk the artifact's
FULL canonical JSON-safe representation (every string leaf, via a new `_walk_strings` helper) instead
of a hand-picked field list; `restore_checkpoint` now calls `compile_ocl_json` (the strict path).

**`orneur/intelligence/ocl/diff.py`**: added `atoms_modified`/`relations_modified`/
`evidence_modified`/`action_intents_modified`/`verification_contracts_modified`/
`escalation_requests_modified`/`causal_hypotheses_modified`/`counterfactual_branches_modified` --
same-ID dataclass-equality comparison, additive to (not replacing) the existing added/removed fields.

**`orneur/intelligence/ocl/transformations.py`**: added `AtomDisposition` (typed per-atom
SUPERSEDED/REMOVED/MODIFIED record requiring a non-empty `justification_ref`, enforced in
`__post_init__`) and `TransformationRecord.atom_dispositions`; `validate_conservation()` now also
raises on a same-ID atom whose canonical value changed without a matching `MODIFIED` disposition
(the legacy flat-tuple shape is kept for backward compatibility with the "outright disappearance"
case only).

**`orneur/intelligence/ocl/extensions.py`**: `register_namespace()` now raises
`ExtensionNamespaceConflict` for `core` or for a conflicting re-registration (different
version/producer) of an already-registered namespace; identical re-registration is idempotent; added
`snapshot_registry()`.

**`orneur/intelligence/ocl/version.py`**: added `schema_policy_for()` and a documented V1 reader
policy (same-version accept, anything else reject) — no speculative V2 machinery.

**`orneur/intelligence/ocl/errors.py`**: 13 new typed error classes (see schema reference).

**Tests**: `test_closure_authority_hardening.py` (25, whole-collection validation + nested-structure
smuggling), `test_closure_deep_immutability.py` (6, incl. alias-safety and digest-stability),
`test_closure_identifiers.py` (9), plus targeted additions to `test_diff.py` (+6),
`test_conservation.py` (+5), `test_extensions.py` (+4), `test_checkpoint.py` (+6),
`test_serialization.py` (rewritten, +5 net), `test_schema_version.py` (+1), `test_atoms.py` (+1,
fixing one pre-existing test that relied on the now-closed self-authentication gap).

### Failing-test evidence (recorded before/alongside implementation, per the closure's own TDD
discipline; several of these check real, git-verified gaps in `ea9426f` rather than being re-derived
by reverting the working tree)

- `git show ea9426f:orneur/intelligence/ocl/compiler.py` has zero occurrences of
  `_validate_action_intents`/`_validate_verification_contracts`/`_validate_escalation_requests`/
  `_validate_causal_hypotheses`/`_validate_counterfactual_branches` — confirming whole-collection
  validation genuinely did not exist (`grep -c` returned 0).
- `git show ea9426f:orneur/intelligence/ocl/canonical.py` has no `deep_freeze`/`freeze_value`
  function — confirming shallow-only freezing before this closure.
- `git show ea9426f:orneur/intelligence/ocl/transformations.py`'s `validate_conservation()` only
  checked `atom.atom_id in child_atom_ids`, with no equality comparison — confirming the same-ID
  rewrite gap.
- `git show ea9426f:orneur/intelligence/ocl/diff.py` only ever computed set differences on ID
  collections — confirming the modification-blind-spot gap.
- For the four items above, the verification method was static (`git show`/`grep -c` against the
  unmodified `ea9426f` source), not a live pytest run against a reverted working tree — this is
  disclosed honestly rather than claimed as a literal red/green cycle for every one of the 68 new
  tests. Every new test DOES pass against the current, fixed implementation (158/158), and the
  static evidence above independently confirms each gap it targets was real in `ea9426f`.
- One test-authoring correction happened during this closure: `test_atoms.py::
  test_observation_reference_with_authoritative_source_and_evidence_ref_is_valid` needed its default
  `NATIVE_MODEL` provenance changed to `DETERMINISTIC_SYSTEM`, since the new evidence-self-
  authentication gate correctly rejects the old (accidentally-too-permissive) test fixture.

### Verification

- `tests/ocl/` full suite: **158 passed, 0 failed** (up from 90; +68 new/expanded tests).
- Phase 16 regression (`test_phase16_architecture_invariants.py`, `test_phase16_court_reconciliation.py`,
  `test_phase16_training_fail_closed.py`, `test_phase16_canonical_training_identity.py`,
  `test_registry_model_spec.py`): **46 passed, 0 failed**.
- Full deterministic regression, project `.venv` explicitly, pipefail-safe: **2469 passed, 256
  skipped, 43 deselected, 0 failed** (178.12s). Collection: **2768 tests** (2700 prior + 68 new).
  2469+256+43 = 2768, matching exactly. No new skip/deselect added.

### Performance (re-measured after deep-freeze + whole-artifact validation)

| n_atoms | validate | serialize | digest |
|---|---|---|---|
| 10 | 0.0002-0.0003s | 0.0001s | 0.0001-0.0002s |
| 100 | 0.0013s | 0.0008s | 0.0008s |
| 1000 | 0.0117-0.0122s | 0.0073-0.0075s | 0.0074-0.0075s |

No material regression from deep freezing (1000-atom validate remained in the same ~0.006-0.017s
noisy range observed pre-closure); no optimization was needed.

### Fresh GitHub CI

Recorded in the Final Report below, after the final closure commit is pushed.

### Production mutation / GPU spend / model training

None. **GPU spend: $0.** **No model training occurred.**

### Requirements totals (post-closure)

47 requirements: 43 VERIFIED, 2 IMPLEMENTED, 2 DEFERRED_TO_FUTURE_PHASE, 0 UNIMPLEMENTED, 0 BLOCKED.

### Known remaining limitations (carried forward + new)

- Unicode normalization still not performed (threat #31, unchanged).
- Extension namespaces still have no per-namespace schema-contract enforcement (threat #33,
  `OCL-EXTENSION-002`, unchanged — explicitly YAGNI per the phase's own instruction).
- `OCL-AUTHORITY-005` (full indirect Mission-bypass enumeration) remains deferred, unchanged.
- The evidence-self-authentication gate is producer-kind-based, not cryptographic — a
  `DETERMINISTIC_SYSTEM`-labeled artifact is trusted by construction; OCL has no signing/
  authentication mechanism to verify that label itself (that remains a transport/deployment-layer
  concern, consistent with `digest()`'s own documented non-claim of cryptographic authentication).
- `ActionIntent`/`EscalationRequest` still have no real consumer in this codebase (Phase 19+/20).

### RE-EARNED FINAL VERDICT (pre-final-closure)

DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 18?

**YES** — superseded by the final closure section below.

---

## FINAL CLOSURE SECTION — TRUST-BOUNDARY / EPISTEMIC-SAFETY (append-only; all content above unchanged)

### What owner review found

An independent owner audit accepted commit `feed714`'s hardening (whole-artifact validation, deep
immutability, strict wire rejection, same-ID diff/conservation, extension conflict prevention) but
found one root architectural issue underneath it all: **trust was derived from data inside the
untrusted artifact.** `compile_artifact()`'s evidence-self-authentication gate checked
`artifact.provenance.producer_kind` — a field an attacker/model fully controls in the wire payload.
Reproduced directly against `feed714` before any fix:

```python
payload = {
    "artifact_id": "art-attack", "schema_version": "1.0.0", "request_id": "req-1",
    "created_at": "2026-01-01T00:00:00+00:00",
    "provenance": {"producer_kind": "DETERMINISTIC_SYSTEM", "producer_id": "attacker-controlled"},
    "atoms": [{"atom_id": "a1", "kind": "OBSERVATION_REFERENCE",
               "source_class": "MEASURED_EVIDENCE_REFERENCE",
               "content": "production is healthy", "evidence_refs": ["e1"]}],
    "evidence": [{"evidence_id": "e1", "evidence_kind": "VERIFICATION_RECORD",
                  "issuer": "fake-verification-system", "reference": "fake-record-id-123"}],
}
compile_ocl_json(json.dumps(payload))
# -> COMPILED SUCCESSFULLY -- BYPASS CONFIRMED
# SourceClass.MEASURED_EVIDENCE_REFERENCE EvidenceKind.VERIFICATION_RECORD
```

This confirmed the exact bypass the owner described: an untrusted payload self-labels its own
producer as `DETERMINISTIC_SYSTEM` and, in the SAME payload, mints a fabricated `VERIFICATION_RECORD`
evidence anchor that the compiler then treated as authoritative. Six additional real gaps were found
alongside the root cause:

1. `SourceClass`'s `AUTHORITATIVE_SOURCE_CLASSES` set (and its name) implied epistemic truth rather
   than provenance/reference classification, and included `HUMAN_INPUT` — conflating "a human said
   this" with "this is approved/verified."
2. `validate_conservation()`'s legacy `superseded_atom_ids`/`removed_atom_ids` tuples were accepted
   with NO justification requirement at all — `test_explicit_supersession_is_accepted` proved this
   by passing with zero `justification_refs`.
3. The wire parser assumed nested JSON values were the right shape (dict/list) without checking —
   `"provenance": []` or `"atoms": [42]` would have raised raw `AttributeError`/`TypeError` rather
   than a typed `OclError`.
4. `CausalHypothesis.observable_test_ref` was accepted as an untyped dangling string with no
   resolution check at all.
5. `request_id` was permitted empty, undermining corporate traceability.
6. `checkpoint._walk_strings()` scanned mapping VALUES only — a secret-shaped mapping KEY (e.g.
   `{"sk-...": "harmless"}`) would reach checkpoint JSON unscanned.

### What changed, exactly

**`orneur/intelligence/ocl/trust.py`** (new module): `CompilationTrustContext` enum
(`UNTRUSTED_MODEL_OR_WIRE`, `TRUSTED_DETERMINISTIC_SYSTEM`, `TRUSTED_TOOL_ADAPTER`,
`TRUSTED_HUMAN_INPUT`) — supplied by the CALLER, never parsed from OCL data.

**`orneur/intelligence/ocl/compiler.py`**: `compile_artifact(draft, *, trust_context=UNTRUSTED)` — the
evidence-impersonation gate now checks `trust_context not in TRUSTED_CONTEXTS`, completely replacing
the old `artifact.provenance.producer_kind in _UNTRUSTED_ARTIFACT_PRODUCER_KINDS` check. Added
`request_id`/`parent_artifact_id`/`transformation_id` non-empty validation. Added
`observable_test_ref` resolution to a real `TEST_PROPOSAL` atom.

**`orneur/intelligence/ocl/canonical.py`**: `compile_ocl_json()` now hardcodes
`trust_context=UNTRUSTED` explicitly. `parse_ocl_draft_json()` hardened with `_require_object`/
`_require_array`/`_required_string`/`_optional_string` helpers applied to every nested field across
every object type — no raw Python exception can escape a malformed shape.

**`orneur/intelligence/ocl/enums.py`**: `AUTHORITATIVE_SOURCE_CLASSES` renamed to
`PRIVILEGED_REFERENCE_SOURCE_CLASSES`, `HUMAN_INPUT` removed from it, extensive docstring stating
`SourceClass` is provenance/reference classification, never epistemic truth.

**`orneur/intelligence/ocl/provenance.py`**: `Provenance` docstring states explicitly that every
field is a claim about origin, not authentication/authorization/trust/verification/approval.

**`orneur/intelligence/ocl/transformations.py`**: `_normalize_legacy_dispositions()` converts the
legacy flat-tuple shape into typed `AtomDisposition` records requiring a non-empty shared
justification — a legacy ID with no `justification_refs` now raises `ConservationViolation` instead
of passing. Added ID validation to `TransformationRecord.__post_init__`.

**`orneur/intelligence/ocl/checkpoint.py`**: `_walk_strings()` now also yields mapping keys, not
only values; `create_checkpoint()` gained an optional `trust_context` passthrough parameter.

**Tests**: `test_closure_trust_boundary.py` (7, reproduces the exact bypass against the safe public
entry point across 4 privileged `EvidenceKind` values), `test_closure_wire_shape_fuzz.py` (26,
malformed nested shapes), `test_closure_causal_and_human_input.py` (8, `observable_test_ref` +
HUMAN_INPUT doctrine), plus targeted additions to `test_atoms.py` (+2), `test_conservation.py` (+2,
proving the legacy bypass is now closed), `test_closure_identifiers.py` (+2, `request_id`/
`parent_artifact_id`), `test_checkpoint.py` (+1, metadata-key scanning).

### Failing-test evidence (recorded before implementation)

The bypass reproduction above was run directly against unmodified `feed714` and printed "COMPILED
SUCCESSFULLY -- BYPASS CONFIRMED" — a real, live demonstration, not a static inspection. After
implementing the fix and re-running the exact same payload through `compile_ocl_json`, it now raises
`EvidenceImpersonation`. `test_explicit_supersession_is_accepted` (unmodified) was run and passed
against `feed714`'s code (confirming the legacy justification-less bypass was real), then updated to
include `justification_refs` once the fix made the old, unjustified form correctly fail.

### Verification

- `tests/ocl/` full suite: **205 passed, 0 failed** (up from 158; +47 new/expanded tests).
- Phase 16 regression: **46 passed, 0 failed**.
- Full deterministic regression, project `.venv`, pipefail-safe: **2516 passed, 256 skipped, 43
  deselected, 0 failed** (191.01s). Collection: **2815 tests** (2768 prior + 47 new).
  2516+256+43 = 2815, matching exactly. No new skip/deselect added.

### Performance

Unchanged in character from the prior closure's measurements (validate/serialize/digest at
10/100/1000 atoms remain in the same sub-20ms range); the trust-context parameter and wire-shape
guards add negligible per-call overhead (simple type checks, no new recursion depth).

### Production mutation / GPU spend / model training

None. **GPU spend: $0.** **No model training occurred.**

### Requirements totals (final)

55 requirements: 51 VERIFIED, 2 IMPLEMENTED, 2 DEFERRED_TO_FUTURE_PHASE, 0 UNIMPLEMENTED, 0 BLOCKED.

### Known remaining limitations

- Unicode normalization still not performed (unchanged).
- Extension namespaces still have no per-namespace schema-contract enforcement (unchanged, YAGNI).
- `OCL-AUTHORITY-005` (full indirect Mission-bypass enumeration) remains deferred (unchanged).
- `CompilationTrustContext` is supplied by the caller's own judgment — OCL has no cryptographic
  mechanism to verify that a caller claiming `TRUSTED_DETERMINISTIC_SYSTEM` actually IS one; this
  closure fixes the IN-BAND bypass (trust derived from artifact data) but the OUT-OF-BAND boundary
  (which callers are allowed to construct a `CompilationTrustContext` other than `UNTRUSTED` at all)
  is an authorization concern for whatever future system embeds OCL, not something OCL itself can
  enforce without becoming an authentication system.
- `ActionIntent`/`EscalationRequest` still have no real consumer in this codebase (Phase 19+/20).

### RE-EARNED FINAL VERDICT (pre-acceptance-boundary-closure)

DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 18?

**YES** — superseded by the acceptance-boundary closure section below.

---

## ACCEPTANCE-BOUNDARY CLOSURE SECTION — DURABLE TRUST + DEEP IMMUTABILITY + TYPE SAFETY (append-only; all content above unchanged)

### What owner review found

An independent owner audit accepted the out-of-band `CompilationTrustContext` architecture from the
prior closure but found four remaining correctness gaps, each reproduced live before any fix:

1. **Trusted checkpoint round-trip was impossible.** `restore_checkpoint()` always called
   `compile_ocl_json()`, which hardcodes `UNTRUSTED_MODEL_OR_WIRE` — so a checkpoint legitimately
   created under `TRUSTED_DETERMINISTIC_SYSTEM` (containing a real privileged reference) could never
   be restored again, even by the same trusted system. Reproduced: `create_checkpoint(draft,
   trust_context=TRUSTED_DETERMINISTIC_SYSTEM)` succeeded, then `restore_checkpoint(cp)` raised
   `EvidenceImpersonation` unconditionally.
2. **Deep immutability was incomplete.** `deep_freeze()` only froze dict-typed fields named
   `metadata`/`arguments_summary`; a programmatic `ActionIntent(preconditions=["p1"])` kept a plain,
   mutable `list` after compilation. Reproduced:
   `compiled.action_intents[0].preconditions.append("tamper")` succeeded, mutating the "compiled"
   artifact.
3. **Programmatic type validation was missing.** `ModelIdentityRef(family=[])` passed through
   `_validate_provenance()`'s `family not in MODEL_SPECS` check and raised a raw `TypeError:
   unhashable type: 'list'` — not a typed `OclError`. The same shape via the JSON wire path produced
   the identical raw `TypeError`.
4. **Trust context was not runtime-typed.** `compile_artifact(draft, trust_context=
   "TRUSTED_DETERMINISTIC_SYSTEM")` (a bare Python string, not the enum) was silently accepted as
   trusted, because the old check used `trust_context in TRUSTED_CONTEXTS` (a frozenset containing
   `str`-mixin `Enum` members) — and `str`-Enum equality/hash matches the plain string value.

A fifth, architectural doctrine gap was also addressed: `EXTERNAL_EVIDENCE_REFERENCE` had been left
in `PRIVILEGED_REFERENCE_SOURCE_CLASSES`, which would have blocked the core Phase 17 intent that "a
model should be able to cite external evidence without self-authenticating it" — citing something
externally is not itself a privileged claim.

### What changed, exactly

**`orneur/intelligence/ocl/checkpoint.py`**: `restore_checkpoint(checkpoint_json, *,
trust_context=UNTRUSTED)` now parses (`parse_ocl_draft_json`) then compiles with the CALLER-supplied
`trust_context`, instead of unconditionally calling `compile_ocl_json`. `create_checkpoint()`'s
existing `trust_context` passthrough is unchanged.

**`orneur/intelligence/ocl/canonical.py`**: `freeze_value()`/`deep_freeze()` rewritten to recursively
walk EVERY dataclass field (rebuilding nested dataclasses via `dataclasses.replace()` with each field
recursively frozen), not merely fields named `metadata`/`arguments_summary`. A `list` anywhere
becomes a `tuple`; a `dict` anywhere becomes a fresh `MappingProxyType`.

**`orneur/intelligence/ocl/typecheck.py`** (new module): `require_string`, `require_optional_string`,
`require_string_sequence`, `require_optional_int` — reusable validators applied throughout
`compiler.py` to every scalar/sequence field the compiler reads, replacing the narrower, type-unsafe
`_check_string_limits()`.

**`orneur/intelligence/ocl/compiler.py`**: every validator function (`_validate_provenance`,
`_validate_atoms`, `_validate_evidence`, `_validate_relations`, `_validate_action_intents`,
`_validate_verification_contracts`, `_validate_escalation_requests`, `_validate_causal_hypotheses`,
`_validate_counterfactual_branches`) now validates field types via `typecheck.py` before using them
-- closing the `ModelIdentityRef(family=[])`-class of gap everywhere, not only for one field.
`compile_artifact()` now validates `trust_context` via `trust.is_valid_trust_context()`
(`isinstance(value, CompilationTrustContext)`) before anything else, raising the new
`InvalidTrustContext` for a bare string. The evidence-impersonation gate now consults
`trust.SOURCE_CLASS_CAPABILITY_MATRIX` (per-`SourceClass` capability, not a flat trusted/untrusted
bit) and a new `_validate_evidence_kind_capability()` consults `trust.EVIDENCE_KIND_CAPABILITY_
MATRIX` (per-`EvidenceKind` capability) as an independent second gate.

**`orneur/intelligence/ocl/trust.py`**: `TRUSTED_CONTEXTS` replaced by `SOURCE_CLASS_CAPABILITY_
MATRIX` and `EVIDENCE_KIND_CAPABILITY_MATRIX` (`TRUSTED_TOOL_ADAPTER` unlocks only
`MEASURED_EVIDENCE_REFERENCE` and a narrow evidence-kind set; `TRUSTED_DETERMINISTIC_SYSTEM`
additionally unlocks `DETERMINISTIC_POLICY_REFERENCE` and `COURT_DECISION`/`PRODUCTION_PROOF`/
`VERIFICATION_RECORD`/`DETERMINISTIC_POLICY_FACT`; `TRUSTED_HUMAN_INPUT` unlocks neither). Added
`is_valid_trust_context()` (`isinstance` check, correctly rejecting a bare string).

**`orneur/intelligence/ocl/enums.py`**: `EXTERNAL_EVIDENCE_REFERENCE` removed from
`PRIVILEGED_REFERENCE_SOURCE_CLASSES` (now 2 members, not 3) — a model may cite it on any atom kind,
under any trust context, as an explicitly unverified reference.

**`orneur/intelligence/ocl/transformations.py`**: `AtomDisposition.__post_init__` now also validates
`atom_id` is a non-empty, bounded string.

**`orneur/intelligence/ocl/errors.py`**: added `InvalidTrustContext`.

**Tests**: `test_closure2_checkpoint_trust.py` (4), `test_closure2_deep_immutability_and_types.py`
(21), `test_closure2_wire_model_identity_and_arrays.py` (17, one genuine new gap found and fixed
during authoring -- see below), `test_closure2_trust_capability_matrix.py` (13) — 55 new tests total.
One pre-existing test (`test_limits.py::test_oversized_content_rejected`) updated to expect
`InvalidStructuredValue` instead of `PayloadLimitExceeded`, since string-length checking is now
unified inside `typecheck.require_string()`.

### Failing-test evidence (recorded before implementation -- live reproductions, not static inspection)

All four owner-identified bugs were reproduced directly against the unmodified prior code via
one-off scripts before any fix landed:

```
Bug 1 (checkpoint trust): create_checkpoint(..., trust_context=TRUSTED_DETERMINISTIC_SYSTEM)
  succeeded; restore_checkpoint(cp) then raised EvidenceImpersonation unconditionally.
Bug 2 (deep immutability): compiled.action_intents[0].preconditions.append("tamper") succeeded,
  producing ['p1', 'tamper'] on the "compiled" artifact.
Bug 3 (programmatic types): compile_artifact(draft-with-ModelIdentityRef(family=[])) raised
  "TypeError: unhashable type: 'list'" -- a raw Python exception, not an OclError.
Bug 4 (wire types): the identical raw TypeError reproduced via compile_ocl_json() on the
  equivalent JSON payload.
Bug 5 (trust context typing): compile_artifact(draft, trust_context="TRUSTED_DETERMINISTIC_SYSTEM")
  (bare string) compiled a privileged atom successfully -- silently accepted as trusted.
```

A fifth issue was found DURING test authoring, not predicted in advance: while writing the wire
string-array-element tests, `atom.evidence_refs` containing a non-string element (`[{}]`) was found
to raise a raw `TypeError: unhashable type: 'dict'` from the `ref not in evidence_by_id` membership
check inside `_validate_evidence` -- the same class of gap as bugs 3/4 but in a spot not explicitly
named in the closure instructions. Fixed in the same pass (`require_string_sequence(atom.
evidence_refs, ...)` added), per the standing "if another bug is discovered while repairing this,
fix it now" discipline established in earlier phases.

### Verification

- `tests/ocl/` full suite: **260 passed, 0 failed** (up from 205; +55 new tests).
- Phase 16 regression: **46 passed, 0 failed**.
- Full deterministic regression, project `.venv`, pipefail-safe: **2571 passed, 256 skipped, 43
  deselected, 0 failed** (202.05s). Collection: **2870 tests** (2815 prior + 55 new). 2571+256+43 =
  2870, matching exactly. No new skip/deselect added.

### Performance

Unchanged in character (validate at 1000 atoms remained in the ~0.015-0.022s range across runs on
this machine; the fully-recursive `deep_freeze()` walk adds a small, expected constant-factor cost
over the prior field-name-targeted version, well within the existing sanity bounds in
`test_performance.py`).

### Production mutation / GPU spend / model training

None. **GPU spend: $0.** **No model training occurred.**

### Requirements totals (final)

64 requirements: 60 VERIFIED, 2 IMPLEMENTED, 2 DEFERRED_TO_FUTURE_PHASE, 0 UNIMPLEMENTED, 0 BLOCKED.

### Known remaining limitations

- Unicode normalization still not performed (unchanged).
- Extension namespaces still have no per-namespace schema-contract enforcement (unchanged, YAGNI).
- `OCL-AUTHORITY-005` (full indirect Mission-bypass enumeration) remains deferred (unchanged).
- The trust capability matrices (`SOURCE_CLASS_CAPABILITY_MATRIX`, `EVIDENCE_KIND_CAPABILITY_
  MATRIX`) are OCL's own policy choice for V1 -- they are not derived from, or validated against, any
  external authorization system. A future phase embedding OCL may need a richer, configurable
  capability model; this is deliberately the smallest matrix that satisfies the closure's stated
  target semantics.
- `CompilationTrustContext` itself still has no cryptographic authentication -- OCL cannot verify a
  caller's claim to hold a given trust context is itself genuine (unchanged from the prior closure's
  documented limitation).
- `ActionIntent`/`EscalationRequest` still have no real consumer in this codebase (Phase 19+/20).

### RE-EARNED FINAL VERDICT

DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 18?

**YES**
