# Failure genome

Status: DESIGNED. No failure-genome store was added.

A later record, if built, needs: triggering input, handler name, observed failure, security impact, corrective proposal, regression test id, and resolution state. It must not copy user conversations into a training corpus.

This pass records failures as handler return values and `EvidenceContractError`. Those results live in the pytest process and are not a durable genome. `PromotionProposal` cannot be applied by the producer, so a failure does not become a silent change to authority or weights.
