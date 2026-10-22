# Evidence, graph, and citations

`verify_claim` supports a claim only when the claim text is contained in an authoritative span. A summary chunk with `authoritative=False` cannot be the only support. The raptor-mode test covers that refusal.

Entity edges in `mode=graph` and `mode=multi-hop` are neighbor links. The graph note `entity-graph-is-not-support` records that an entity edge is not a citation. Multi-hop adds a second document only when an in-tenant entity edge reaches a visible document. A foreign-tenant edge is ignored.

Contradictions are `KEY=value` pairs with different values. Non-overlapping validity is marked `temporal` and does not by itself block an answer. Overlapping disagreements return `contradictory` when the challenge pass is on.

`orca.truth` already has an evidence graph. This kernel does not write into it.
