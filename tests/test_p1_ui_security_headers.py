"""LANDMARK-04 P1 -- the browser UI pages are served with a Content-Security-Policy and clickjacking protection.

Finding (P2, reproduced against main 0a4c518): ``/conversation`` and ``/app`` carried no CSP and no frame-ancestors / X-Frame-Options, so any site could frame the signed-in
application (clickjacking), and nothing limited where an injected script could send data. The approved conversation page loads no third-party resources, so its policy is strict
about network destinations (connect-src 'self'), plugins, <base> and form targets; script/style stay 'unsafe-inline' because the approved page is built with inline code (a nonce
migration is a tracked follow-up, see the register).
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(isolated_home):
    from orca.serve.api import app

    return TestClient(app)


def _csp(resp):
    return {d.split()[0]: d.split()[1:] for d in resp.headers["content-security-policy"].split(";") if d.strip()}


def test_conversation_page_has_a_strict_csp_and_cannot_be_framed(client):
    r = client.get("/conversation")
    assert r.status_code == 200
    csp = _csp(r)
    assert csp["frame-ancestors"] == ["'none'"] and r.headers["x-frame-options"] == "DENY"
    assert csp["connect-src"] == ["'self'"], "the page may only talk to its own origin"
    assert csp["object-src"] == ["'none'"] and csp["base-uri"] == ["'none'"] and csp["form-action"] == ["'self'"]
    assert "'unsafe-eval'" not in r.headers["content-security-policy"]
    assert not re.search(r"https?://", r.headers["content-security-policy"]), "the approved page needs no third-party origin"


@pytest.mark.parametrize("path", ["/", "/app", "/trust"])
def test_other_ui_pages_are_framing_protected_and_have_a_csp(client, path):
    r = client.get(path)
    assert r.status_code == 200
    csp = _csp(r)
    assert csp["frame-ancestors"] == ["'none'"] and r.headers["x-frame-options"] == "DENY"
    assert csp["object-src"] == ["'none'"] and csp["base-uri"] == ["'none'"]
    assert "'unsafe-eval'" not in r.headers["content-security-policy"]


def test_api_responses_are_not_cached_when_they_carry_credentials(client):
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x" * 12})
    assert "no-store" in r.headers.get("cache-control", "")
