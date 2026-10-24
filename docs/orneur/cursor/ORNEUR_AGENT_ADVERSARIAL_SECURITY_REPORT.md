# Adversarial checks in this pass

Covered by `tests/test_agent_role_registry.py` and the existing orchestrator tests:

| Attempt | Result |
|---|---|
| Producer sets VERIFIED | `EvidenceContractError` |
| Evidence text does not support the claim | `EvidenceContractError` |
| Falsifier id equals producer id | `EvidenceContractError` |
| Cross-tenant memory read | `allowed: false` |
| Self-approval of promotion | `promoted: false`, `applied: false` |
| Untrusted directive text | not admitted, authority unchanged |
| Training, GPU, or spend flag | denied, locks unchanged |
| Grant revoked after submit and before tick | `DENIED`, `executed: false` |
| Unknown price | `UNKNOWN` |
| Cancel after success | succeeded task stays succeeded |
| Child permission wider than parent | existing test still denies it |

Not covered, and still open: producer and verifier collusion beyond the id check, forged signatures, symlink replacement, checkpoint substitution, duplicate irreversible side effects, recursive delegation bombs, and leakage of a private eval set. The verifier fails closed when the verification contract is unmet. An agent's own confidence field is not read and is not proof.

Capability C27 in the advanced list is this denial record. Acceptance-register C27 is a different, unmet recovery row.
