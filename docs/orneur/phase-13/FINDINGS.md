# Phase 13.1 — Findings (supersedes Phase 13's FINDINGS.md for this closure)

Per spec §72: "a discovered failure is success of the red-team process.
Do not suppress it."

## Summary

| Metric | Count |
|---|---|
| NEW_ATTACKS_EXECUTED (this phase) | 55 (see per-campaign breakdown in `EVALUATION_V2.md`) |
| EXISTING_SECURITY_TESTS_REUSED | 733 (Phase 1-13's own suite, unmodified, reconfirmed green) |
| REAL_VULNERABILITIES_FOUND | 3 |
| REAL_VULNERABILITIES_FIXED | 2 |
| RESIDUAL_OPEN_FINDINGS | 1 (documented, `xfail`ed, not hidden) |
| FALSE_POSITIVES | 1 (RES-06/07 test-writing bugs caught and corrected before being counted — see below) |

## Real vulnerabilities

### Finding 1 — RAG source-independence never consulted (FIXED)

- **Category**: RAG_POISONING
- **Severity**: MEDIUM
- **Affected subsystem**: `orca.truth.state.compute_evidence_state`
- **Attack preconditions**: attacker can get 2+ mutually-derived
  (mirrored/syndicated) documents into a retrieval result set.
- **Attack input**: same text published under 2+ domains, one a
  subdomain of the other, one syndicated verbatim, one with explicit
  attribution.
- **Observed behavior (pre-fix)**: `EvidenceState.SUFFICIENT` reached
  purely from `citation_coverage_ratio`, with the computed
  `IndependenceState.LIKELY_DERIVED` flags on every source silently
  ignored.
- **Expected behavior**: an all-derived source set should not be treated
  as equivalent to genuinely independent corroboration.
- **Reproducibility**: REPRODUCIBLE (deterministic function, no timing
  dependency).
- **Root cause**: `annotate_independence()`'s output was write-only
  across the entire codebase — confirmed by exhaustive grep.
- **Fix**: `orca/truth/state.py` — downgrade SUFFICIENT to PARTIAL when
  2+ sources exist and all are `LIKELY_DERIVED`.
- **Regression test**: `tests/test_redteam_rag_deep.py::test_rag02_authority_spam_no_longer_reaches_sufficient_when_all_sources_are_mutually_derived`
- **CWE-like classification**: CWE-1188-adjacent (insecure default
  initialization of a resource that is never actually used to enforce
  the property its presence implies) — not a formal CWE mapping, offered
  loosely since no better-fitting entry was found; not fabricated as an
  authoritative CVE/CWE identifier.

### Finding 2 — Godmode canonicalizer recursion crash (FIXED)

- **Category**: RESOURCE_EXHAUSTION
- **Severity**: MEDIUM
- **Affected subsystem**: `orca.godmode.canonical.hash_arguments`/`canonicalize_arguments`, reachable from `issue_lease()`, `resolve_lease()`, `resolve_and_consume_lease()`.
- **Attack preconditions**: attacker can influence the shape of a lease's
  bound arguments (e.g. via a tool call whose arguments get hashed for
  exact-argument binding).
- **Attack input**: a dict nested 500 levels deep.
- **Observed behavior (pre-fix)**: uncaught `RecursionError` propagating
  out of the real Godmode authorization path.
- **Expected behavior**: a bounded, typed rejection — never an
  interpreter-level crash.
- **Reproducibility**: REPRODUCIBLE, deterministic (fails at any depth
  greater than Python's ambient recursion budget minus this call
  stack's own depth — empirically observed starting at depth 500 in this
  environment).
- **Root cause**: `_canonicalize_value()` recursed with no depth guard.
- **Fix**: explicit `_MAX_CANONICALIZATION_DEPTH = 64` counter, raising
  `ArgumentTooDeeplyNestedError` (a `ValueError` subclass).
- **Regression test**: `tests/test_redteam_resource_exhaustion.py::test_res01_deeply_nested_argument_payload_is_rejected_not_crashed`
- **CWE-like classification**: CWE-674 (Uncontrolled Recursion).

### Finding 3 — Godmode one-use lease cross-process race (DOCUMENTED, NOT FIXED)

- **Category**: RACE_CONDITION
- **Severity**: MEDIUM (current single-process-oriented deployment) /
  HIGH (if ever deployed multi-process/multi-worker without a fix)
- **Affected subsystem**: `orca.godmode.lease_store.consume_use`
- **Attack preconditions**: two OS processes with access to the same
  file-backed `ORCA_HOME`, both racing to consume the same one-use
  lease.
- **Observed behavior**: `consume_use()`'s atomicity guarantee
  (`threading.Lock`) is in-process only; a real
  `multiprocessing.Process`-based test shows both processes can read
  `uses_remaining == 1` before either writes `0` back, since there is no
  file-level lock on the read-modify-write.
- **Expected behavior**: exactly one process should succeed.
- **Reproducibility**: REPRODUCIBLE (confirmed directly; `xfail`ed
  rather than silently passed).
- **Root cause**: no `fcntl.flock`/equivalent advisory lock wraps the
  `get()`-then-`save()` critical section.
- **Fix status**: **NOT FIXED THIS PASS** — disclosed as residual risk.
  A correct fix needs real file-level locking, a more invasive change to
  a security-critical module than justified for a single newly-found
  issue within this qualification pass's scope.
- **Regression test**: `tests/test_redteam_toctou.py::test_toctou04_real_multiprocess_race_on_one_use_lease` (asserts and `xfail`s the reproduction so it can never silently regress into looking passed without investigation).
- **CWE-like classification**: CWE-362 (Concurrent Execution using
  Shared Resource with Improper Synchronization, "Race Condition").

## False positive (caught before being counted as a finding)

An initial hypothesis for RAG-06 (citation numeric mismatch) assumed the
lexical fallback would score near-zero overlap for a wildly wrong number
— running the actual test showed `overlap=0.80` (surrounding words
matched), `PARTIALLY_SUPPORTED`. This was NOT a security bug: reclassified
honestly as the same disclosed fallback limitation as RAG-04/05 (the
ceiling — never full SUPPORTED — still holds), and the test assertion was
corrected to match the REAL observed behavior rather than the original
(wrong) assumption. Recorded here as a false-positive-caught-during-
investigation, per spec §45's honesty requirement, not silently dropped.

## Severity table (real findings only)

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 3 (2 fixed, 1 documented residual) |
| LOW | 0 |

(The disclosed fallback-path limitations in RAG-04/05/06 are NOT counted
as vulnerabilities — they are pre-existing, honestly-labeled design
limitations of a degraded fallback path whose ceiling property was
verified to hold, not new bypasses.)
