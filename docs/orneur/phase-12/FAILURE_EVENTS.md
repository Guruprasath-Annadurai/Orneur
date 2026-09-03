# Phase 12 — FailureEvent Contract

`orca/learning/contracts.py::FailureEvent`.

## Fields (spec §4)

`failure_id`, `source_system`, `failure_type`, `timestamp`, `tenant_id`,
`model_id`, `checkpoint_id`, `role`, `task_trace_id`, `input_reference`,
`output_reference`, `evidence_reference`, `severity`, `confidence`,
`privacy_class`, `security_class`, `reproducibility`, `root_cause`,
`verification_state`, `status`, `provenance_refs`.

**No raw chain-of-thought field exists on this dataclass, deliberately**
(spec §4's explicit prohibition). `input_reference`/`output_reference`/
`evidence_reference` are references — an ID, a hash, or a short bounded
excerpt (see `signals.py`'s `[:200]` truncation on every excerpt field) —
never full transcripts, documents, or connector payloads (spec §12).

## Failure types (spec §5)

19 bounded values in `FailureType`. This is a closed enum, not a
free-form string — adding a new type is a deliberate code change with its
own triage rule, never emitted dynamically from unstructured text.

## Verification (spec §7)

`VerificationState`: `UNVERIFIED | VERIFIED | CONTESTED | DISMISSED`.
`orca.learning.pipeline.verify_event()` is the only function that
transitions an event to `VERIFIED`, and it takes the real confirmation
result as an explicit boolean parameter — never a model's own
self-assessment. `triage()` refuses to produce `TRAINING_CANDIDATE` or
`EVAL_CANDIDATE` for anything but `VERIFIED`; `CONTESTED` and
`UNVERIFIED` both route to `HUMAN_REVIEW`.

## Reproducibility (spec §8)

`ReproducibilityState`: `REPRODUCIBLE | INTERMITTENT | ENVIRONMENTAL |
NON_REPRODUCIBLE | UNKNOWN`. Combined with `root_cause`, this is what lets
triage reject "fixing" an infrastructure blip as if it were a cognition
failure — see `ROOT_CAUSE = INFRASTRUCTURE_FAILURE` below.

## Root cause (spec §9)

`RootCauseClass`: `MODEL_FAILURE | RETRIEVAL_FAILURE | MEMORY_FAILURE |
TOOL_FAILURE | POLICY_FAILURE | RUNTIME_FAILURE | DATA_FAILURE |
INFRASTRUCTURE_FAILURE | TEST_FAILURE | UNKNOWN`.

`NON_TRAINING_ROOT_CAUSES = {RUNTIME_FAILURE, INFRASTRUCTURE_FAILURE,
TEST_FAILURE}` is checked explicitly in `triage.py` — these three always
produce `FailureDisposition.RUNTIME_BUG`, never a training or eval
candidate, regardless of verification state. **This is the canonical
Phase 11.2 Gateway-timeout lesson made structural**: that investigation
found a real `asyncio.wait_for()`/`CancelledError` interaction bug that
looked like a live-suite "cognition" flake but was pure infrastructure —
under Phase 12's triage rules, that exact failure signature would be
classified `INFRASTRUCTURE_FAILURE` and routed to `RUNTIME_BUG`, never
curriculum, on the first pass.

## Provenance (spec §6)

See `PROVENANCE.md`/`DATASET_LINEAGE.md`. `provenance_refs` on the event
itself is a light pointer list; the authoritative structure is
`orca.learning.provenance.LineageGraph`, built by the pipeline as events
become candidates.
