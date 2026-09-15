"""
Evidence-rooted reachability. This is the mechanism that satisfies the
hard "no circular self-validation" invariant: propagation is a
monotonic, forward-only worklist BFS that can only ADD an atom to the
support/refutation-reachable sets by walking a relation edge FROM an
atom that is already in the set. An atom can only ever enter a
reachable set by tracing back to a DIRECT qualified evidence root
(computed separately in resolver.py, before this function runs) --
never from another atom that is itself only reachable through the same
unrooted cycle. A cycle with no root simply never gets any member
added, because there is nothing outside the cycle to seed the BFS.

Complexity: O(V + E) -- each atom is enqueued (thus each relation edge
examined) at most twice per direction (once for support, once for
refutation), independent of how many times a cycle would otherwise be
revisited.
"""
from __future__ import annotations

from collections import defaultdict, deque

from orneur.intelligence.epistemic.enums import RelationEffect, get_relation_semantics
from orneur.intelligence.ocl.graph import CognitiveRelation


def compute_evidence_rooted_reachability(
    relations: tuple[CognitiveRelation, ...],
    direct_support_roots: frozenset[str],
    direct_refutation_roots: frozenset[str],
) -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """Returns (support_reachable, refutation_reachable): each maps
    atom_id -> frozenset of the direct-neighbor atom_ids that fed its
    membership (used to populate derived_support_atom_refs /
    derived_refutation_atom_refs -- NOT necessarily the ultimate root,
    just the immediate derivation link, matching Phase 17's evidence_refs
    style of "reference, don't re-derive the whole chain").

    An atom already in a direct root set is also present in the
    returned mapping (with an empty contributor set), so callers can
    test membership uniformly via `atom_id in support_reachable`.
    """
    support_forward, support_reverse, refutation_forward = _build_indexes(relations)

    support_reachable = _bfs(direct_support_roots, support_forward, support_reverse)
    refutation_reachable = _bfs_refutation(
        direct_support_roots, direct_refutation_roots, support_reachable, refutation_forward,
    )
    return support_reachable, refutation_reachable


def _build_indexes(relations: tuple[CognitiveRelation, ...]):
    """Index relations once, by effect, so BFS is pure adjacency lookups."""
    support_forward: dict[str, list[str]] = defaultdict(list)   # SUPPORTS: src -> tgt
    support_reverse: dict[str, list[str]] = defaultdict(list)   # DERIVED_FROM: tgt(basis) -> src(derived)
    falsifies_forward: dict[str, list[str]] = defaultdict(list)  # FALSIFIES: src -> tgt

    for relation in relations:
        semantics = get_relation_semantics(relation.kind)
        if semantics.effect is RelationEffect.SUPPORT:
            if semantics.propagates_from_source_to_target:
                support_forward[relation.source_atom_id].append(relation.target_atom_id)
            else:
                # "A DERIVED_FROM B": B (target) is A's (source's) basis.
                # If B becomes established, A inherits that basis.
                support_reverse[relation.target_atom_id].append(relation.source_atom_id)
        elif semantics.effect is RelationEffect.REFUTATION:
            falsifies_forward[relation.source_atom_id].append(relation.target_atom_id)
        # CONFLICT and NONE contribute no reachability edges here --
        # CONFLICT (CONTRADICTS) is handled directly in resolver.py.

    return support_forward, support_reverse, falsifies_forward


def _bfs(
    roots: frozenset[str],
    support_forward: dict[str, list[str]],
    support_reverse: dict[str, list[str]],
) -> dict[str, frozenset[str]]:
    reachable: dict[str, set[str]] = {atom_id: set() for atom_id in roots}
    queue: deque[str] = deque(roots)
    while queue:
        current = queue.popleft()
        neighbors = list(support_forward.get(current, ())) + list(support_reverse.get(current, ()))
        for neighbor in neighbors:
            if neighbor not in reachable:
                reachable[neighbor] = set()
                queue.append(neighbor)
            reachable[neighbor].add(current)
    return {atom_id: frozenset(contributors) for atom_id, contributors in reachable.items()}


def _bfs_refutation(
    direct_support_roots: frozenset[str],
    direct_refutation_roots: frozenset[str],
    support_reachable: dict[str, frozenset[str]],
    falsifies_forward: dict[str, list[str]],
) -> dict[str, frozenset[str]]:
    """Refutation reaches an atom either directly (a root), or because a
    FALSIFIES edge originates from an atom that is (directly or derived)
    support-reachable -- i.e. that atom is itself established, so it
    falsifies its target. FALSIFIES does not chain past that single
    hop in this closed vocabulary (no RelationKind here means
    "refutation implies further refutation")."""
    reachable: dict[str, set[str]] = {atom_id: set() for atom_id in direct_refutation_roots}
    for established_atom_id in support_reachable:
        for target_atom_id in falsifies_forward.get(established_atom_id, ()):
            reachable.setdefault(target_atom_id, set()).add(established_atom_id)
    return {atom_id: frozenset(contributors) for atom_id, contributors in reachable.items()}
