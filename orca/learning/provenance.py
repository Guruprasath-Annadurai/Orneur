"""
Failure provenance / lineage (spec §6, §24, §62 "Learning Flight Recorder").

Every FailureEvent and every derived artifact keeps a reference chain back
to its real source -- never an orphan training sample. This module builds
and validates that chain; it does not itself fetch full source content
(that stays in the owning subsystem -- TruthResult, SimulationResult,
CourtCase, etc.) since a FailureEvent must not carry raw private content
(spec §4, §12).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LineageNode:
    node_type: str      # e.g. "FailureEvent", "CurriculumCandidate", "DatasetManifest", "TrainingRun", "Checkpoint", "EvalRun", "PromotionDecision"
    node_id: str
    parent_refs: list[str] = field(default_factory=list)   # node_ids this was derived from


@dataclass
class LineageGraph:
    """Spec §62: links FailureEvent -> CurriculumCandidate -> DatasetManifest
    -> TrainingRun -> Checkpoint -> EvalRun -> PromotionDecision into one
    lineage graph. A simple adjacency-list, file-independent structure --
    persistence is the caller's job (e.g. appended to the audit log)."""
    nodes: dict[str, LineageNode] = field(default_factory=dict)

    def add(self, node_type: str, node_id: str, parent_refs: list[str] | None = None) -> LineageNode:
        node = LineageNode(node_type=node_type, node_id=node_id, parent_refs=list(parent_refs or []))
        self.nodes[node_id] = node
        return node

    def ancestors(self, node_id: str) -> list[str]:
        """Full transitive closure of parent_refs, no cycles assumed (each
        node type in this pipeline is created strictly after its parents)."""
        seen: set[str] = set()
        stack = list(self.nodes.get(node_id, LineageNode("", node_id)).parent_refs)
        while stack:
            ref = stack.pop()
            if ref in seen:
                continue
            seen.add(ref)
            parent = self.nodes.get(ref)
            if parent:
                stack.extend(parent.parent_refs)
        return sorted(seen)

    def has_orphan(self, node_id: str) -> bool:
        """A training-relevant node (anything but a raw FailureEvent, which
        is the root of the chain) with zero parent_refs is an orphan --
        spec §6's 'no orphan training sample without provenance.'"""
        node = self.nodes.get(node_id)
        if node is None:
            return True
        if node.node_type == "FailureEvent":
            return False
        return len(node.parent_refs) == 0
