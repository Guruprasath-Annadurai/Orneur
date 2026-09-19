# Genesis Frontier Evidence Schema

**Phase 21B.4.9 — SCHEMA DESIGN ONLY.** Defines what every real
candidate's evidence record must contain once execution is separately
authorized. No evidence exists yet — no candidate has been run.

## 1. Failure taxonomy

Every per-task failure (deterministic, executable, or judge-scored) is
categorized into exactly one of the following, so the execution
report can explain **how** a candidate fails, not only how often (owner
spec §14):

| Category | Definition |
|---|---|
| Knowledge failure | The model lacks the factual/domain knowledge the task requires |
| Reasoning failure | The model has the relevant knowledge but fails to chain it correctly |
| Instruction failure | The model does not follow an explicit instruction (format, constraint, scope) |
| Tool-planning failure | Incorrect tool selection, sequencing, or dependency handling |
| Hallucination | The model asserts something false with unwarranted confidence |
| Fabricated completion | The model claims to have done something it did not do (hard-gated, see `GENESIS_FRONTIER_DECISION_GATES.md` §C) |
| Coding correctness failure | Generated code does not pass the required tests |
| Architecture weakness | A design/architecture proposal has a structural flaw a competent reviewer would flag |
| Security/authority violation | Hard-gated (§C) — self-authorization, boundary bypass, or unsafe generated-code behavior |
| Format/protocol failure | Output does not conform to the required schema/structure, independent of content correctness |
| Generation failure | The backend/model was asked and explicitly failed to answer (timeout, API error, refusal) — distinct from an integrity error (below) |
| Timeout/resource failure | The task exceeded its time or resource budget |

A failure record is never left uncategorized. A per-task entry with no
assignable category is itself flagged for review, not silently dropped.

**Distinct from all of the above:** an integrity error (`GenerationArtifactIntegrityError`,
`GenerationArtifactIdentityMismatchError`, `IncompleteResultError`,
`MissingGenerationProvenanceError`, `GenerationArtifactMismatchError`) means
ORNEUR does not know what happened to a task's data, or the run's
provenance cannot be trusted — this is never conflated with a
"generation failure" in the taxonomy above, matching the Phase
21B.4.8.1 distinction ("missing transport data is not a generation
failure — it is an integrity error").

## 2. Per-candidate evidence record (required fields)

Every finalist's evidence package, assembled at Stage 8 of the execution
plan, contains:

### 2.1 Identity and provenance

- Candidate name, upstream model repo, artifact repo actually used
- Exact revision, tokenizer revision
- Revision timestamp, model release date (§25 contamination record)
- Backend, exact runtime version (e.g. `vllm==0.6.3.post1`)
- Quantization method and precision actually used per round (Round A /
  Round B), per `GENESIS_FRONTIER_SCORING_CONTRACT.md` §8
- Software commit SHA (ORNEUR's own code state at run time)
- `generation_artifact_digest` and `generation_artifact_schema_version`
  for every real run (structurally required by
  `orca.eval.baseline`'s finalization gate — a record with
  `provenance_kind` other than `"real_generation_artifact"` is not
  eligible for inclusion in a foundation-decision evidence package)

### 2.2 Capability matrix

- Per-category score, confidence interval, and sample size, split by:
  - Tier (Tier-1 public / Tier-2 holdout)
  - Hardness band (basic/control, strong, frontier, extreme)
  - Track (standard instruct / reasoning-enabled, where applicable)
  - Precision round (Round A / Round B)
- Deterministic total, judge-required results (with every individual
  judge's raw score retained, not only the resolved/averaged value),
  hard-task results — all reported separately, never pre-collapsed
  (`GENESIS_FRONTIER_SCORING_CONTRACT.md` §2).

### 2.3 Frontier gap report

- Per-category gap versus the strongest available frontier reference,
  with the material/non-material classification
  (`GENESIS_FRONTIER_DECISION_GATES.md` §"Frontier gap metric").

### 2.4 Hard-gate results

- One row per hard gate (`GENESIS_FRONTIER_DECISION_GATES.md` §C),
  PASS/FAIL, with the specific evidence (task IDs, judge/human
  adjudication record) backing any FAIL. Reported as its own block,
  never merged into the capability matrix.

### 2.5 Adaptability evidence

- Per-dimension notes and any available precedent
  (`GENESIS_FRONTIER_DECISION_GATES.md` §A.2) — this is qualitative/
  documentary evidence (published fine-tuning reports, architecture
  documentation), not a benchmark score, and is labeled as such.

### 2.6 Licensing status

- Per-right (deployment, fine-tuning, redistribution, teacher/
  distillation where relevant) status: GRANTED, DENIED, or UNRESOLVED
  (e.g. MiniMax M3's current teacher-use status).

### 2.7 Failure analysis

- Full per-task failure taxonomy breakdown (§1), aggregated by category
  and by failure type, so a reader can see e.g. "this candidate's
  coding-category losses are 80% coding-correctness failures and 20%
  format-protocol failures," not merely a pass rate.

### 2.8 Cost / latency measurement (kept separate from capability)

- Time-to-first-token, tokens/sec, generation latency (mean and
  distribution, not only mean), per track/precision round.
- GPU configuration used (model, count, memory).
- VRAM actually consumed (peak, not only theoretical).
- Quantization precision (cross-referenced with §2.1).
- Estimated cost per evaluation run (compute-time × the resource's
  actual/effective rate — $0 where covered entirely by credits, per
  `GENESIS_FRONTIER_COST_PLAN.md`).

These fields are recorded for every candidate but **never** enter the
capability matrix or the frontier-gap computation — they exist for the
serving-feasibility section (§10K below) and for the owner's cost
awareness, not as a hidden capability penalty (owner spec §28).

### 2.9 10K-user serving feasibility

- Estimated replica topology (how many model instances, at what
  precision, on what hardware, to serve expected Genesis traffic)
- GPU count and type
- Tensor/expert parallelism strategy, if required at the candidate's
  size
- Continuous batching strategy and expected effect on throughput
- KV-cache footprint at the context sizes Genesis's product actually
  uses (not only the model's maximum advertised context)
- Autoscaling approach (how replica count responds to load)
- Routing approach (how requests reach a replica)
- Failover approach (what happens when a replica or GPU fails)

This section is **characterization**, not a load test — it is built
from the cost/latency measurements above plus architectural reasoning
about the model's serving requirements, not from actually running
10,000 concurrent simulated users. It is measured and reported for
every finalist that survives Stage 6, and separated (§2.8's boundary)
from the capability matrix so a superior-intelligence candidate is never
silently deprioritized on serving-complexity grounds alone
(`GENESIS_FRONTIER_DECISION_GATES.md` §F).

## 3. What is NOT part of the evidence record

- No aggregate single-number "winner score" — see
  `GENESIS_FRONTIER_SCORING_CONTRACT.md` §2's explicit prohibition on a
  magic number invented or adjusted after seeing results.
- No ranking or recommendation of a specific candidate — the evidence
  record is INPUT to a human foundation decision, never itself the
  decision (owner spec §31 applies to every phase, not only this one).
- No claim of proven zero-contamination — only the relative evidentiary
  posture recorded per §25's classification.
