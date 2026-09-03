"""
Connector sync/deletion/revocation lifecycle (Phase 9 spec §51-53).
Request-driven, bounded -- no background sync engine required by this
phase's architecture (spec §51's own "do not require full background
sync engine if current architecture is request-driven").
"""
from __future__ import annotations

from orca.connectors.contracts import ConnectorSyncState


class SimpleSyncStateStore:
    """Per-connector-instance sync cursor + tombstone tracking."""

    def __init__(self):
        self._states: dict[str, ConnectorSyncState] = {}

    def get(self, connector_instance_id: str) -> ConnectorSyncState:
        return self._states.setdefault(connector_instance_id, ConnectorSyncState(connector_instance_id=connector_instance_id))

    def tombstone(self, connector_instance_id: str, object_id: str) -> None:
        """Spec §52: a deleted/revoked remote object must not keep being
        served from cache/index -- tombstoning it here is the real
        invalidation signal a cache/vector-index lookup must check."""
        state = self.get(connector_instance_id)
        if object_id not in state.tombstoned_object_ids:
            state.tombstoned_object_ids.append(object_id)

    def is_tombstoned(self, connector_instance_id: str, object_id: str) -> bool:
        return object_id in self.get(connector_instance_id).tombstoned_object_ids

    def filter_out_tombstoned(self, connector_instance_id: str, results: list[dict], id_field: str = "id") -> list[dict]:
        state = self.get(connector_instance_id)
        return [r for r in results if r.get(id_field) not in state.tombstoned_object_ids]


class PermissionRevocationTracker:
    """
    Spec §53: if connector permissions change, cached/indexed content
    must not remain accessible under stale authorization. Tracks a
    monotonic `permission_version` per connector instance -- any cached
    entry recorded against an OLDER version is treated as invalid,
    forcing a recheck rather than serving stale-permission content.
    """

    def __init__(self):
        self._versions: dict[str, int] = {}

    def current_version(self, connector_instance_id: str) -> int:
        return self._versions.get(connector_instance_id, 0)

    def revoke(self, connector_instance_id: str) -> int:
        new_version = self.current_version(connector_instance_id) + 1
        self._versions[connector_instance_id] = new_version
        return new_version

    def is_stale(self, connector_instance_id: str, cached_at_version: int) -> bool:
        return cached_at_version < self.current_version(connector_instance_id)
