# Production integration

There is no production integration on this branch.

`execute` can be called in-process with a `Corpus` and a `RetrievalRequest`. Nothing in the conversation shell (PR #81) or the C02 mission backend (PR #79) imports `orca.rag_x`. Those branches were not edited.

Until a later integration change exercises an authenticated application request through the existing backend, gate G9 stays blocked and this programme stays partial.

The synthetic template backend is not a serving stack. Native model ids are refused.
