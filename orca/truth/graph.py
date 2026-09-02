"""
EvidenceGraph foundation (Phase 4 spec §18) -- storage-independent, pure
in-memory abstraction. Explicitly NOT the same thing as
orca/brain/knowledge_graph.py's KnowledgeGraph (semantic/entity relations)
-- this graph's edges are provenance/support/contradiction relationships
(spec §39). No dedicated graph database required; a later phase may add a
real persistence backend behind the same add_node/add_edge interface
without callers changing.
"""
from __future__ import annotations

from orca.truth.contracts import EvidenceEdgeType, EvidenceGraphEdge, EvidenceGraphNode, EvidenceNodeType, _new_id


class EvidenceGraph:
    def __init__(self):
        self.graph_id = _new_id("egraph")
        self._nodes: dict[str, EvidenceGraphNode] = {}
        self._edges: list[EvidenceGraphEdge] = []

    def add_node(self, node_id: str, node_type: EvidenceNodeType, label: str = "") -> EvidenceGraphNode:
        node = self._nodes.get(node_id) or EvidenceGraphNode(node_id=node_id, node_type=node_type, label=label)
        self._nodes[node_id] = node
        return node

    def add_edge(self, from_id: str, to_id: str, edge_type: EvidenceEdgeType, weight: float = 1.0) -> None:
        if from_id not in self._nodes or to_id not in self._nodes:
            raise ValueError(f"add_edge requires both nodes to already exist: {from_id!r} -> {to_id!r}")
        self._edges.append(EvidenceGraphEdge(from_id=from_id, to_id=to_id, edge_type=edge_type, weight=weight))

    @property
    def nodes(self) -> list[EvidenceGraphNode]:
        return list(self._nodes.values())

    @property
    def edges(self) -> list[EvidenceGraphEdge]:
        return list(self._edges)

    def edges_of_type(self, edge_type: EvidenceEdgeType) -> list[EvidenceGraphEdge]:
        return [e for e in self._edges if e.edge_type == edge_type]

    def neighbors(self, node_id: str, edge_type: EvidenceEdgeType | None = None) -> list[str]:
        return [
            e.to_id for e in self._edges
            if e.from_id == node_id and (edge_type is None or e.edge_type == edge_type)
        ]

    def supporting_evidence_for(self, claim_node_id: str) -> list[str]:
        return self.neighbors(claim_node_id, EvidenceEdgeType.SUPPORTS)

    def contradicting_claims_for(self, claim_node_id: str) -> list[str]:
        return self.neighbors(claim_node_id, EvidenceEdgeType.CONTRADICTS)
