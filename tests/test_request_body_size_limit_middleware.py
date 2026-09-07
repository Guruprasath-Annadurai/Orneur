"""
Phase 14C.1 Gap 3: the original `request_size_limit_middleware` (a
Content-Length pre-check) only caught a request that honestly reported
its size upfront -- a request with no Content-Length header (chunked
transfer-encoding) or a false/smaller Content-Length could still have
its full oversized body read into memory, since nothing counted the
actual bytes arriving on the wire.

`RequestBodySizeLimitMiddleware` (`orca/serve/api.py`) is a pure ASGI
middleware, registered as the OUTERMOST middleware in the app (added
last -- Starlette wraps in reverse registration order), that wraps the
raw `receive` callable and counts bytes as they actually arrive,
regardless of what the client claims. These tests exercise the
middleware class directly against a minimal Starlette app (not the
full orca app) so boundary conditions can be tested precisely and
fast, without needing to actually send tens of megabytes over the
wire.
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from orca.serve.api import RequestBodySizeLimitMiddleware

MAX_BYTES = 100


def _make_app() -> Starlette:
    async def echo(request):
        body = await request.body()
        return PlainTextResponse(f"received {len(body)} bytes")

    app = Starlette(routes=[Route("/echo", echo, methods=["POST"])])
    app.add_middleware(RequestBodySizeLimitMiddleware, max_bytes=MAX_BYTES)
    return app


def test_content_length_below_limit_passes():
    client = TestClient(_make_app())
    resp = client.post("/echo", content=b"x" * (MAX_BYTES - 1))
    assert resp.status_code == 200, resp.text
    assert resp.text == f"received {MAX_BYTES - 1} bytes"


def test_content_length_above_limit_rejected_413():
    client = TestClient(_make_app())
    resp = client.post("/echo", content=b"x" * (MAX_BYTES * 2))
    assert resp.status_code == 413, resp.text
    assert "too large" in resp.json()["error"]


def test_content_length_exactly_at_boundary_passes():
    client = TestClient(_make_app())
    resp = client.post("/echo", content=b"x" * MAX_BYTES)
    assert resp.status_code == 200, resp.text
    assert resp.text == f"received {MAX_BYTES} bytes"


def test_content_length_boundary_plus_one_rejected_413():
    client = TestClient(_make_app())
    resp = client.post("/echo", content=b"x" * (MAX_BYTES + 1))
    assert resp.status_code == 413, resp.text


def test_no_content_length_below_limit_passes():
    """Streamed body (generator content) carries no Content-Length header
    at all -- the exact case the old Content-Length-only check missed."""
    def gen():
        yield b"x" * 10
        yield b"x" * 10

    client = TestClient(_make_app())
    resp = client.post("/echo", content=gen())
    assert resp.status_code == 200, resp.text
    assert "content-length" not in {k.lower() for k in resp.request.headers.keys()}
    assert resp.text == "received 20 bytes"


def test_no_content_length_chunked_multiframe_above_limit_rejected_413():
    """Many small chunks whose CUMULATIVE size exceeds the limit -- proves
    the counter is tracking actual bytes across multiple receive() calls,
    not just checking a single chunk's size."""
    def gen():
        for _ in range(30):
            yield b"x" * 10  # 300 bytes total, well over MAX_BYTES

    client = TestClient(_make_app())
    resp = client.post("/echo", content=gen())
    assert resp.status_code == 413, resp.text
    assert "content-length" not in {k.lower() for k in resp.request.headers.keys()}


def test_normal_get_request_unaffected():
    """No body at all -- must never be rejected."""
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/ok", ok, methods=["GET"])])
    app.add_middleware(RequestBodySizeLimitMiddleware, max_bytes=MAX_BYTES)
    client = TestClient(app)
    resp = client.get("/ok")
    assert resp.status_code == 200, resp.text
