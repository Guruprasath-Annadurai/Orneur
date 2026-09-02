# Truth Fabric — Architecture (Phase 4)

## Why not "query → vector database → LLM → citations"

That pipeline collapses retrieval, evidence, and verification into one
opaque call. Truth Fabric keeps them as separate, independently testable
stages, each with its own typed contract (`orca/truth/contracts.py`):

```
RetrievalPlan  →  Evidence + EvidenceSource  →  EvidenceGraph
                                              ↓
                          TruthResult (assess_evidence)
                                              ↓
                    [ answer generated via ModelGateway ]
                                              ↓
                     AtomicClaim → ClaimSupport → Contradiction
                                              ↓
                          TruthResult (verify_answer)
                                              ↓
                    CitationVerdict + EvidenceState
```

No stage silently substitutes for another. A pipeline that can't retrieve
anything doesn't pretend to verify; a verifier that can't confirm a claim
doesn't pretend the claim is cited.

## Two-phase design

`TruthFabric` (`orca/truth/truth_fabric.py`) exposes exactly two entry
points, deliberately not a single black-box call:

- **`assess_evidence(request, intent, complexity, doc_store=None, budget=None)`**
  — pre-generation. Builds a bounded `RetrievalPlan`
  (`orca/truth/planner.py`), retrieves from DENSE (DocStore)/SPARSE/WEB
  sources, annotates source independence, builds an `EvidenceGraph`, and
  computes a *preliminary* `EvidenceState` (coarse: "was anything found",
  not real citation coverage — that doesn't exist until there's an answer
  to check).
- **`verify_answer(answer_text, prior_result, budget=None, tier="nano")`**
  — post-generation. Extracts atomic claims from the model's *actual*
  output, verifies each against the evidence gathered in phase one,
  detects contradictions between claims, builds claim-linked citations,
  and computes the real citation-coverage ratio.

Both return a `TruthResult`. Nothing about phase two invents new
evidence — it only checks the phase-one evidence against what the model
actually said.

## CognitiveKernel integration

`orca/cognitive/kernel.py` splits a plan's operations three ways:

| Bucket | Operations | Handled by |
|---|---|---|
| `_KERNEL_EXECUTABLE_OPS` | ANSWER_DIRECTLY, REASON, RECALL_MEMORY | `_answer_directly` → ModelGateway |
| `_TRUTH_FABRIC_OPS` | RETRIEVE, SEARCH, VERIFY | `_answer_with_truth_fabric` → TruthFabric |
| everything else | USE_TOOL, DELEGATE_AGENT | deferred to the existing AgentLoop stack |

A plan routes through Truth Fabric only when it needs *nothing but*
`_TRUTH_FABRIC_OPS` (plus the always-present ANSWER_DIRECTLY, which stays
in the executable bucket and is called *by* `_answer_with_truth_fabric`
itself once evidence is assessed). Any plan that also needs USE_TOOL or
DELEGATE_AGENT falls through to the pre-existing serving stack unchanged
— Truth Fabric augments the Kernel's own executable path, it doesn't try
to replace tool-use or agent delegation.

For AUDIT_GRADE evidence requirements specifically: if the evidence
assessed pre-generation is already INSUFFICIENT/CONFLICTED/LOW_AUTHORITY,
or if post-generation verification still leaves `evidence_state !=
SUFFICIENT`, the Kernel abstains with `INSUFFICIENT_EVIDENCE` rather than
returning an unverified answer (spec §36).

## Gateway-routing discipline

Every *new* Truth Fabric LLM call (claim extraction, claim verification,
contradiction detection) goes through the single helper
`orca/truth/llm.py::gateway_json_call()` → `ModelGateway`. This is
deliberately narrower than "fix all RAG LLM calls" — the pre-existing
Deep RAG pipeline's own raw-`urllib` calls are audited and disclosed in
[CURRENT_TRUTH_PIPELINE.md](CURRENT_TRUTH_PIPELINE.md), not silently
rewritten in this phase (see [SECURITY.md](SECURITY.md)).

## Bounded everything

Every retrieval mode has hard document/passage/subquery/hop caps
(`orca/truth/planner.py`'s `MAX_*` constants) and an overall wall-clock
deadline (`OVERALL_DEADLINE_S` in `truth_fabric.py`). There is no
unbounded "keep researching until satisfied" loop — see
[RETRIEVAL_MODES.md](RETRIEVAL_MODES.md) for exact caps per mode, and
that document's honest note on which modes are fully executed today
versus planned-but-not-yet-looped (corrective re-querying).

## Honest uncertainty, by construction

- `IndependenceState.UNKNOWN` is the default; `INDEPENDENT` is never
  asserted by the lexical-similarity heuristic in
  `orca/truth/provenance.py` — only `LIKELY_DERIVED` or `UNKNOWN`.
- `ClaimSupportState.UNKNOWN`/`UNSUPPORTED` can never become a
  `CitationVerdictState.SUPPORTED` — `orca/truth/citation.py`'s
  `_SUPPORT_TO_VERDICT` table enforces this structurally, with a
  dedicated regression test.
- `SourceQuality` (`orca/truth/contracts.py`) is per-source and
  contextual, never a single permanent "truth score" for a domain.

## Reuse over duplication

- `orca.truth.contracts` imports `FreshnessLevel`/`EvidenceLevel` from
  `orca.cognitive.contracts` instead of parallel enums.
- `DuckDuckGoProvider` (`orca/truth/search_provider.py`) wraps the
  existing, real `orca/tools/web.py::search` rather than reimplementing
  search.
- `sanitize_extracted_text` (`orca/truth/fetch.py`) reuses and extends
  the injection-pattern approach already proven in
  `orca/tools/search_grounding.py`.
