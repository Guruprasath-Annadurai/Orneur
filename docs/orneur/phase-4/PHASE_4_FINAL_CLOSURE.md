# Phase 4.1 Final Closure — Truth Fabric Production Closure

Builds on [PHASE_4_CLOSURE.md](PHASE_4_CLOSURE.md) (Phase 4's own
closure report). This document covers only what Phase 4.1 changed.

## Gaps closed this phase

1. **Corrective retrieval — now real.** `orca/truth/corrective.py` +
   `TruthFabric.assess_evidence()`'s loop. See
   [CORRECTIVE_RETRIEVAL.md](CORRECTIVE_RETRIEVAL.md).
2. **Safe full-page fetch — now reachable.** `TruthFabric._retrieve()`
   calls `fetch_document()` for `RAG_5_RESEARCH`'s top web result. See
   [SAFE_FETCH_CUTOVER.md](SAFE_FETCH_CUTOVER.md).
3. **Evidence-vs-evidence contradiction — now real.**
   `detect_evidence_contradictions()` with temporal reconciliation. See
   [CONTRADICTION_ENGINE.md](CONTRADICTION_ENGINE.md).
4. **Raw-urllib legacy bypass — one caller migrated, the rest
   deliberately still open.** `web_ingest.py` migrated off `fetch_page()`.
   The Deep RAG pipeline's Ollama-host-only `ModelGateway` bypass remains
   open — see [LIVE_RETRIEVAL_AUDIT.md](LIVE_RETRIEVAL_AUDIT.md)'s
   disposition section for why this is a disclosed, deliberate scope
   boundary rather than an oversight.
5. **Bandit tooling gap — fixed as a real environment/robustness issue,**
   not suppressed. `bandit` was already a declared, installed dependency;
   `orca/tools/security.py` now resolves it relative to `sys.executable`'s
   own venv instead of depending on the invoking shell's PATH.

## A bug found, not asked for, and fixed: `/api/stream`'s Truth Fabric bypass

Auditing every live retrieval path (spec §2) surfaced a genuine
production bug pre-dating this phase: `orca/serve/api.py`'s streaming
chat endpoint discarded a Truth-Fabric-verified, citation-checked Kernel
answer in favor of the legacy Gateway-bypassing Deep RAG pipeline
whenever a session had **any** document loaded — regardless of whether
the Kernel's own answer actually used that evidence. This is precisely
backwards: it silently disabled Truth Fabric for exactly the request
class it exists to serve. Fixed by making `use_kernel_direct` check
`cognitive_result.evidence_state is not None` (i.e., "did Truth Fabric
actually produce this answer") in addition to the original "no documents
loaded" condition. See [LIVE_RETRIEVAL_AUDIT.md](LIVE_RETRIEVAL_AUDIT.md)
for the full trace.

## Test suite

- 3 new test files (`test_truth_corrective_contradiction_counter_evidence.py`,
  `test_truth_safe_fetch_cutover.py`), 1 rewritten (`test_web_ingest.py`
  migrated off `fetch_page`), plus updates to `test_truth_fabric_retrieval_modes.py`
  (3-tuple `_retrieve` return) and a new AUDIT_GRADE-success live test in
  `test_cognitive_kernel_truth_fabric_integration.py`.
- Full non-live suite: **all green, 0 failures** (up from Phase 4's 1
  pre-existing environment failure, now fixed at the root cause).
- Truth Fabric live-Ollama suite: all passing, including the new
  AUDIT_GRADE success/abstention Kernel-level tests.

## Claim verifier false positive (spec §19)

Reproduced, diagnosed (prompt/schema issue on the judge's handling of
comparative claims, not claim/evidence segmentation), and partially
fixed via an explicit rule + worked example added to the judge prompt.
The fix measurably reduces the failure rate on repeated real
reproduction but does **not** eliminate it — real nano-tier model
non-determinism on this specific reasoning pattern remains a disclosed,
retained limitation. Full detail and honest before/after in
[EVALUATION_V2.md](EVALUATION_V2.md).

## STRICT vs AUDIT_GRADE (spec §24)

Both use `RetrievalPlanner`'s bounded retrieval, but diverge at the
Kernel:

| | STRICT | AUDIT_GRADE |
|---|---|---|
| Pre-generation abstention | Only on INSUFFICIENT/CONFLICTED/LOW_AUTHORITY | Same |
| Post-generation gate | None beyond the pre-generation check — a STRICT answer can complete even if the final `EvidenceState` degrades (e.g. to `PARTIAL` or `INSUFFICIENT`) after generation | Requires `EvidenceState == SUFFICIENT` **and** a `RAN` counter-evidence attempt, or abstains |
| Counter-evidence | Never run | Always attempted (bounded, one query) |

This means STRICT genuinely tolerates more post-generation uncertainty
than AUDIT_GRADE, as spec §24 requires — verified directly by the live
Kernel test suite: `test_strict_evidence_request_answers_via_truth_fabric_with_doc_store`
completes even without a hard post-generation gate, while
`test_audit_grade_request_with_strong_evidence_can_succeed` only
completes when the stronger AUDIT_GRADE gate is satisfied.

## Hallucination judge disposition (spec §22)

Unchanged from Phase 4: `orca/docs/hallucination_check.py::check_grounding`
remains dead code (zero callers), its prompt-design role fully
superseded by the Gateway-routed `orca/truth/verification.py::verify_claim`.
No ambiguity — it is not imported, called, or referenced by any live
path, Truth Fabric or legacy.

## `UNEXPECTED_UNSAFE_FETCH_BYPASS` / `UNEXPECTED_TRUTH_BYPASS`

Both **= 0** — see [LIVE_RETRIEVAL_AUDIT.md](LIVE_RETRIEVAL_AUDIT.md)'s
dedicated sections for the full audit trail.

## No raw chain-of-thought stored

`CorrectiveRound.reason`/`evidence_gap` and every contradiction's
`temporal_context`/`reason` are short, structured strings the judge calls
themselves return in JSON — never a full reasoning trace, never the raw
text of a `thinking` block. Verified by inspection of every new
dataclass field added this phase (`orca/truth/contracts.py`).

## Commits this phase

1. `Phase 4.1: real corrective retrieval, evidence contradiction, counter-evidence`
2. (this closure commit) remaining documentation + evaluation harness v2

## READY TO ADVANCE TO PHASE 5: YES

Every acceptance gate in spec §40 that this phase's own scope covers is
met: corrective retrieval executes and is bounded; multi-hop and
corrective share one budget; evidence-vs-evidence contradiction exists
with temporal reconciliation; the counter-evidence hook exists, is
bounded, and is honest about not-run/budget-exhausted; source
independence stays conservative (still never asserts `INDEPENDENT`); the
claim verifier's known false positive is reproduced and measurably
(if not completely) improved, with the residual retained as a documented
limitation; citation/claim evaluation was rerun honestly with real
numbers, including two new AUDIT_GRADE cases; unsupported citations
remain structurally impossible to promote to supported; AUDIT_GRADE has
an explicit, stronger gate than STRICT and both succeed and abstain
correctly in live tests; document-only authority is correctly scoped
(user-uploaded documents count as primary evidence for claims about
their own content, not globally); cancellation and resource limits are
unchanged from Phase 4's already-tested behavior (the new corrective/
counter-evidence operations reuse the same `asyncio.wait_for`/budget-
consumption machinery, not a new unbounded path); and both bypass counts
are zero. The one deliberately-still-open item (the Deep RAG pipeline's
`ModelGateway` bypass) is disclosed, not hidden, and is a
non-security-critical observability gap, not a live vulnerability.

**STOP AFTER PHASE 4.1 — awaiting explicit human approval before any
Memory Continuum (Phase 5) work begins.**
