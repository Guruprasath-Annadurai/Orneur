# Phase 13 — RAG Poisoning

## Scope of this phase's work

Spec §12-15 (duplicated/SEO-spam documents dominating EvidenceGraph,
source-independence, citation confusion, temporal truth attacks)
represent a genuinely large, dedicated body of work — Truth Fabric's
evidence-graph/citation/contradiction machinery
(`orca/truth/contracts.py`'s `EvidenceGraph`, `orca/truth/citation_check.py`
via `orca/docs/citation_check.py`, `orca.truth.corrective_contradiction`)
already has real, passing security-relevant coverage
(`tests/test_truth_fetch_security.py`, `tests/test_truth_safe_fetch_cutover.py`,
`tests/test_truth_evidence_provenance_graph.py`,
`tests/test_truth_corrective_contradiction_counter_evidence.py`), audited
and confirmed present.

**Disclosed limitation**: this phase did not add NEW adversarial tests for
source-independence-under-cloning (§13), citation-index-swap/negation-
reversal-style structural attacks (§14), or the temporal-truth injection
scenarios (§15). This is a genuine scope gap, not a claim of completeness
— building bespoke poisoned-document corpora and verifying
`EvidenceGraph`'s independence-scoring behavior under them is
substantial, dedicated work better suited to its own focused pass than a
sub-item of an already-large Phase 13.

## What is already structurally true (from existing tests, confirmed by reading, not re-derived)

- Retrieved content never becomes an instruction (`orca.truth.fetch`'s
  injection-pattern scanning excludes suspicious content outright).
- SSRF-style redirection into internal-network documents is blocked
  (`tests/test_web_ssrf_guard.py`).

## Residual risk

Source-independence and citation-confusion attacks on Truth Fabric are an
**open, disclosed residual risk** for this phase — recommended as a
focused follow-up, not carried forward silently.
