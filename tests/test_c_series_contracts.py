"""C-series routes stay unmounted.

Library, connectors, schedules, notifications, and a workspace resource
are contracts only. A 404 is the contract, not a missing handler to fill in.
"""
from __future__ import annotations

from tests.test_g006_tenant_isolation import client  # noqa: F401

_ABSENT = (
    ("GET", "/api/workspaces"),
    ("POST", "/api/workspaces"),
    ("GET", "/api/library"),
    ("POST", "/api/library/items"),
    ("GET", "/api/connectors"),
    ("POST", "/api/connectors"),
    ("GET", "/api/schedules"),
    ("POST", "/api/schedules"),
    ("GET", "/api/notifications"),
    ("POST", "/api/notifications"),
    ("GET", "/api/projects"),
    ("GET", "/api/plugins"),
    ("GET", "/api/skills"),
)


def test_unapproved_product_routes_are_absent(client):
    listed = client.get("/api/sessions")
    assert listed.status_code == 200, listed.text
    for method, path in _ABSENT:
        response = client.request(method, path)
        assert response.status_code == 404, f"{method} {path} -> {response.status_code} {response.text}"
