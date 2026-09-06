# Failure Memory (Phase 5)

`orca/memory/failure.py`. A future similar task should be able to
retrieve relevant prior failure knowledge — but a permanent failure
memory is never manufactured from an unverified guess (spec §22).

## Contract

```python
FailureMemoryRecord:
  task_context, attempted_strategy, failure_mode, root_cause, correction,
  regression_test_ref, verification_state: FailureVerificationState
```

## Verification is checked, not trusted at face value

`record_failure()` will not accept a caller's claimed
`VERIFIED_ROOT_CAUSE` unless the record actually carries **both** a
`root_cause` string **and** a `regression_test_ref`. If either is
missing, the claim is silently downgraded — to `PROBABLE` if a
`root_cause` exists without a regression test, or `UNVERIFIED` if
neither does:

```python
record_failure(..., root_cause="", verification_state=VERIFIED_ROOT_CAUSE)
# -> verification_state becomes UNVERIFIED, not VERIFIED_ROOT_CAUSE
```

Proven by
`tests/test_memory_contracts_arbiter.py::test_failure_memory_downgrades_unsubstantiated_claim`.
This is a hard bar deliberately matching the spec's own preference order:
"verified root cause, confirmed regression, explicit human diagnosis,
repeatable evidence" — otherwise `PROBABLE`/`UNVERIFIED`.

## Recall

`find_relevant()` is bounded, lexical relevance over a scope's failure
records (word-overlap scoring, capped candidate set) — a floor, not a
claim of semantic-similarity quality. A future phase could add
embedding-based ranking without changing the function's contract.
