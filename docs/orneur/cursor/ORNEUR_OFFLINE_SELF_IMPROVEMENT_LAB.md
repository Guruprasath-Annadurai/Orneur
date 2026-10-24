# Offline self-improvement

`deny_self_promotion` constructs a `PromotionProposal` only when `decided_by` is neither `produced_by` nor `candidate_id`. The proposal's `applied` field is false. A candidate that names itself as the decider returns `promoted: false` and does not raise into a live config change.

What a candidate still cannot do here: approve itself, change weights, deploy, mint a grant, edit the acceptance ledger, rename a reviewer, spend, or ingest private user data.

There is no sandbox that applies a code patch, no frozen-evaluation promotion, and no rollout. Capability D29 stays DESIGNED. The equation comparison is a measurement of handlers, not a tournament winner.
