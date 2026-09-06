# Evidence Graph (Phase 4)

`orca/truth/graph.py::EvidenceGraph` is a storage-independent, pure
in-memory graph. It is **not** `orca/brain/knowledge_graph.py`'s
`KnowledgeGraph` — that graph models semantic/entity relations between
concepts; this graph models provenance/support/contradiction
relationships between sources, evidence, claims, and citations (spec
§18, §39). They are deliberately separate abstractions and remain
untouched by each other in this phase.

## Shape

- **Nodes** (`EvidenceGraphNode`): typed by `EvidenceNodeType` —
  `SOURCE`, `EVIDENCE`, `CLAIM`, `CITATION` (see
  `orca/truth/contracts.py`). Adding a node twice is idempotent
  (`add_node` returns the existing node if already present).
- **Edges** (`EvidenceGraphEdge`): typed by `EvidenceEdgeType` — e.g.
  `DERIVED_FROM` (evidence → its source), `SAME_ORIGIN` (source →
  another source it's believed derived from). `add_edge` raises
  `ValueError` if either endpoint doesn't already exist as a node —
  the graph never silently creates a placeholder node for a dangling
  edge.

## Construction

`TruthFabric._build_graph(evidence, sources)` builds the graph after
retrieval and independence annotation:

1. One `SOURCE` node per `EvidenceSource`.
2. One `EVIDENCE` node per `Evidence`, with a `DERIVED_FROM` edge to its
   source.
3. A `SAME_ORIGIN` edge between sources when one source's
   `derived_from` list names another source already in this result set
   (provenance lineage — see [PROVENANCE.md](PROVENANCE.md)).

Claim/citation nodes are not added by `_build_graph` itself — they exist
in `TruthResult.claims`/`citation_verdicts` as flat lists after
`verify_answer()`, not wired into the graph in this phase. Linking
claims and citations into the same graph (so "which sources ultimately
support this specific sentence in the answer" is a graph traversal, not
a separate lookup) is a natural next-phase extension, not built here.

## Query surface

- `nodes` / `edges` — full lists.
- `edges_of_type(edge_type)` — filter by relationship type.
- `neighbors(node_id, edge_type=None)` — adjacent node ids, optionally
  filtered by edge type.
- `supporting_evidence_for(claim_node_id)` / `contradicting_claims_for(...)`
  — convenience wrappers over `neighbors()` for `SUPPORTS`/`CONTRADICTS`
  edges.

**Honest scope**: these query methods are real and tested
(`tests/test_truth_evidence_provenance_graph.py`), but claim verification
(`orca/truth/verification.py`) and contradiction detection
(`orca/truth/contradiction.py`) do not currently traverse the graph to do
their work — they operate directly on `Evidence`/`AtomicClaim` lists
(lexical overlap + a Gateway-routed judge call). No `SUPPORTS`/
`CONTRADICTS` edges are added to the graph by `_build_graph` today, so
`supporting_evidence_for`/`contradicting_claims_for` have nothing to
return yet. The graph's query surface is built ahead of that wiring
(spec §18's "foundation") so a later phase can route verification through
graph traversal without changing the graph's own interface.

No dedicated graph database is used or required. A later phase could add
a real persistence backend behind the same `add_node`/`add_edge`
interface without any caller changing — this is the deliberate reason
the class exists as a thin wrapper rather than exposing a dict directly.
