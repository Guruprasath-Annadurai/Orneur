# Foundation-X target architecture

The programme diagram is a target. The boxes below are what this branch actually runs.

`execute` in `orca/rag_x/kernel.py` is an in-process sequence: scope, capability check, mode selection, authorized retrieval, dedupe, packing, optional contradiction challenge, claim check, and an evidence manifest. It does not call the conversation shell or the C02 mission API.

Identity and authority for this kernel are `AuthorizedRetrievalScope` plus `Corpus.visible`. They are not a tenant directory service.

The model gateway step refuses `genesis`, `novus`, and `aeternum` with `model_not_trained`. The default backend id `synthetic-template-backend` only quotes an authoritative span. It is not a model.

Evidence verification is `verify_claim`: the claim string must occur inside an authoritative span. That is not a general truth proof.

Tool execution is `authorize_action` in `orca/rag_x/research.py`. Evidence text cannot satisfy the grant. C02 is unchanged.

Research feedback is `orca/foundation_x/feedback.py`. A proposal cannot accept itself and cannot name a protected acceptance or training path.

`orca.truth.contracts.RetrievalPlan` remains the Cognitive Kernel planner type. This branch does not replace it.
