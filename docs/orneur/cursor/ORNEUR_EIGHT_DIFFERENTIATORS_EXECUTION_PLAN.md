# Eight differentiators

Dependency order used in this pass: evidence span, then epistemic transition, then falsifier and arbiter, then team selection, then authority and denial, then promotion refusal, then cost. Each one reuses `Orchestrator` rather than a second scheduler.

| Differentiator | Reuse | New code | Single-agent baseline | What the test showed |
|---|---|---|---|---|
| Proof-carrying answers | none | `EvidenceSpan`, `Claim` | a claim with no span stays UNKNOWN | digest mismatch cannot become VERIFIED |
| Falsification and arbitration | proof types | `falsify_claim`, `arbitrate_claims` | classifier leaves `2+2=5` as OBSERVED | falsifier returns REFUTED; arbiter does not count votes |
| Dynamic teams | role registry | `select_team`, `team_benchmark` | one handler | ten handlers match three on the equation and use more calls |
| Epistemic state | `Claim` | `transition` | producer state OBSERVED | producer cannot set VERIFIED |
| Denial receipts | authority gate | `DenialReceipt` | no receipt when the path permits | receipt scope is the guarded path only; it is not a signature |
| Authority and revocation | `Orchestrator.tick` | `decide_authority` | permit does not execute | a grant mutated to revoked before the tick is denied |
| Offline promotion refusal | none | `PromotionProposal` | candidate decides for itself and is refused | `applied` stays false |
| Cost accounting | none | `account_cost` | missing price | total stays UNKNOWN, not zero |

Threat common to all eight: the handler and the test share a process, so this is not an independent trust boundary. Acceptance criteria for a later qualification pass are a separate verifier identity, a signed or externally anchored receipt, and a comparison against a real model baseline. This pass did not spend and did not call a provider. Resource cost of the tests is one local pytest process.

No differentiator is classified as demonstrated superiority over another vendor. See the prior-art note.
