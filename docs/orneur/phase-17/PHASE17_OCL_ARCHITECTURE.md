# PHASE 17 — OCL Architecture

## Architecture option comparison (section 27)

| | A: extend `orca/cognitive/contracts.py` directly | B: `orneur/intelligence/ocl/` core + adapters to `orca.*` | C: `orca/ocl/` native package, migrate namespace later |
|---|---|---|---|
| Dependency direction | OCL semantics become entangled with the Cognitive Kernel's own internal planning types (`IntentPlan`, `CognitiveBudget`, ...) | OCL depends on nothing in `orca.*` except read-only references (`orca.registry.model_spec`, `orca.learning.sanitize`); `orca.*` depends on OCL only through the one-way adapter | Same dependency direction as B, but the package still lives under the legacy `orca` namespace |
| Legacy coupling | High — `contracts.py` is imported by 58 test files and the Cognitive Kernel; any OCL-shaped addition risks becoming load-bearing for existing planning behavior it was never designed for | Low — a genuinely new package, zero legacy consumers to break | Low, same as B |
| Test impact | Every OCL test would sit alongside/inside the existing, heavily-depended-upon `test_cognitive_*.py` suite, raising the chance of an accidental coupling | New `tests/ocl/` directory, fully isolated | Same |
| Migration cost | None now, but conflates two different concerns (bounded intent/complexity/budget classification vs. a typed evidence-bearing cognitive graph) permanently | Low — a thin adapter (`adapters.py`) is the only integration surface, easy to extend or retire | Low, but the `orca` namespace prefix would need an eventual rename if ORNEUR's own namespace is the long-term destination anyway |
| Corporate maintainability | Poor — one file gaining unrelated responsibilities is exactly the kind of drift enterprise infrastructure should avoid | Good — one clearly-scoped package | Good |
| Public-standard future | Weak — a future OCL spec extraction would have to be surgically carved out of `orca.cognitive` | Strong — `orneur.intelligence.ocl` is already the shape of a standalone, extractable package | Adequate, but the extracted package would carry a legacy `orca.` name into any future public spec |
| Ability to support Phase 18-33 | Constrained by `orca/cognitive`'s existing bounded-classifier design | OCL's own graph/provenance/authority model is free to evolve independently | Same as B |
| Risk of architecture drift | High | Low | Low-medium (two native namespaces, `orca` and `orneur`, coexisting indefinitely without a clear rule for which new code goes where) |

**Decision: Option B.** This matches Phase 16's own recommendation
(`PHASE16_CANONICAL_ARCHITECTURE.md`'s architecture-option table) and is confirmed against the
current code: `orca/cognitive/contracts.py` is untouched, `orneur/intelligence/ocl/` is a new,
independent package, and `orneur/intelligence/ocl/adapters.py` is the sole, one-way, read-only
bridge to the legacy `CognitiveResult` type. No broad ORCA→ORNEUR migration was performed or
attempted.

## Package structure (actually implemented; YAGNI applied against the spec's suggested list)

```
orneur/
  __init__.py
  intelligence/
    __init__.py
    ocl/
      __init__.py         -- public export surface
      version.py          -- OCL_SCHEMA_VERSION + support check
      errors.py            -- typed OclError subclasses (stable codes)
      limits.py             -- validation size limits
      enums.py               -- AtomKind, RelationKind, SourceClass, ProducerKind,
                                 EvidenceKind, TransformationOperation, ObserverView
      provenance.py           -- ModelIdentityRef, Provenance
      evidence.py              -- EvidenceAnchor
      graph.py                  -- CognitiveAtom, CognitiveRelation
      proposals.py               -- ActionIntent, VerificationContract, EscalationRequest
      causal.py                   -- CausalHypothesis, CounterfactualBranch
      artifact.py                  -- CognitiveArtifact
      transformations.py            -- TransformationRecord + conservation validation
      compiler.py                    -- compile_artifact() -- the only accept/reject boundary
      canonical.py                    -- canonicalize(), digest(), wire (de)serialization
      diff.py                          -- CognitiveDiff, diff()
      observer.py                       -- project() -- 6 named views
      extensions.py                      -- namespace registry
      checkpoint.py                       -- create_checkpoint()/restore_checkpoint()
      adapters.py                          -- legacy CognitiveResult -> OCL draft (one-way)
```

`ids.py` and a separate `causal.py`/`counterfactual.py` split from the spec's suggested list were
merged where the spec's own suggested modules would have been single-digit-line files (IDs are
plain caller-supplied strings validated by the compiler, not a dedicated ID-generation module;
`CounterfactualBranch` lives with `CausalHypothesis` since both are tiny and tightly related).

## What this architecture does NOT do

- It does not replace or modify `orca/cognitive/contracts.py`, `orca/mission/cognitive_court.py`,
  or any Phase 15/16 deterministic system.
- It does not add a second model-identity vocabulary — `ModelIdentityRef.family`/`lifecycle_state`
  are validated against the real `orca.registry.model_spec.MODEL_SPECS`/`LifecycleState` at compile
  time (see `compiler.py::_validate_provenance`).
- It does not add a second secrets-handling mechanism — `checkpoint.py` reuses
  `orca.learning.sanitize.sanitize_for_candidate`.
- It does not implement OCL as "just JSON" — the typed dataclass/enum model in `graph.py`,
  `proposals.py`, `causal.py`, `artifact.py` is the semantic model; JSON is only the wire format
  produced by `canonical.py`.
