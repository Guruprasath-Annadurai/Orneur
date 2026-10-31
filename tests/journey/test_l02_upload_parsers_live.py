"""L02-02 -- the REAL third-party PDF/DOCX parsers (pypdf, pdfminer.six, python-docx) behind the isolated extractor, fed hostile files.

Evidence class: LIVE_PARSER (real parsers, real child processes, in-process app). These libraries are the optional ``docs`` extra, which CI does not install, so this
module is workstation-only and FAILS (never skips) when they are absent.

Run:  ORNEUR_L02_DOC_LIBS=/tmp/l02-doclibs PYTHONPATH=.:/tmp/l02-doclibs pytest tests/journey/test_l02_upload_parsers_live.py -p no:cacheprovider -v
      (install once:  uv pip install --target /tmp/l02-doclibs pypdf python-docx pdfminer.six)
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401
from tests.test_product_flows_fake_ollama import fake  # noqa: F401

EVIDENCE = Path(os.environ.get("ORNEUR_L02_EVIDENCE_DIR", "/tmp/orneur-l02-evidence"))


def record(name, data):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"l02_parsers_live_{name}.json").write_text(json.dumps({"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **data}, indent=2))


@pytest.fixture(autouse=True)
def _need_parsers():
    missing = [m for m in ("pypdf", "docx", "pdfminer") if importlib.util.find_spec(m) is None]
    assert not missing, f"capability missing: {missing}; see the module docstring (PYTHONPATH must include the parser directory)"


def _up(client, h, name, data, sid=None):
    return client.post("/api/docs/upload", files={"file": (name, data, "application/octet-stream")}, params={"session_id": sid} if sid else {}, headers=h)


def _pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


def _docx(text: str, external: str | None = None) -> bytes:
    import docx

    d = docx.Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    raw = buf.getvalue()
    if external:
        import zipfile

        src, out = zipfile.ZipFile(io.BytesIO(raw)), io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == "word/_rels/document.xml.rels":
                    data = data.replace(b"</Relationships>", f'<Relationship Id="rIdX" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{external}" TargetMode="External"/></Relationships>'.encode())
                z.writestr(info, data)
        raw = out.getvalue()
    return raw


def test_real_pdf_and_docx_are_extracted_indexed_and_cited(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    r = _up(client, h, "notes.pdf", _pdf("The Calvin cycle occurs in the stroma of the chloroplast."))
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    r2 = _up(client, h, "memo.docx", _docx("Quarterly retention policy: ninety days after termination."), sid=sid)
    assert r2.status_code == 200, r2.text
    from orca.docs.store import DocStore

    st = DocStore(sid, enforce_registry=True)
    assert any("stroma" in c["text"] for c in st.retrieve("Calvin cycle stroma chloroplast"))
    assert any("ninety days" in c["text"] for c in st.retrieve("retention policy ninety days"))
    record("real_pdf_docx", {"pdf_chunks": r.json()["chunks"], "docx_chunks": r2.json()["chunks"], "parsers": "pypdf/pdfminer.six/python-docx (third-party)"})


def test_docx_with_an_external_reference_is_never_dereferenced(client, fake):
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200); self.end_headers()
        do_POST = do_HEAD = do_GET

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        t, _ = _signup(client)
        r = _up(client, _hdr(t), "ext.docx", _docx("Hello external world.", external=f"http://127.0.0.1:{srv.server_address[1]}/canary.png"))
        assert r.status_code == 200, r.text
        time.sleep(1.0)
    finally:
        srv.shutdown()
    assert hits == [], f"the parser fetched an external reference: {hits}"
    record("external_reference", {"requests_received_by_canary_server": len(hits)})


@pytest.mark.parametrize("name,data", [
    ("truncated.pdf", _pdf("hello world")[:120]),
    ("garbage.pdf", b"%PDF-1.7\n" + os.urandom(4096)),
    ("loop.pdf", b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 1 0 R >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"),
    ("nul.pdf", b"%PDF-1.4\n" + b"\x00" * 100_000),
])
def test_malformed_pdfs_end_as_clean_refusals_quickly(client, fake, name, data):
    t, _ = _signup(client)
    t0 = time.monotonic()
    r = _up(client, _hdr(t), name, data)
    took = time.monotonic() - t0
    assert r.status_code in (200, 422) and took < 25 and "Traceback" not in r.text, (r.status_code, r.text[:200], took)
    if r.status_code == 422:
        assert r.json().get("code") in ("extraction_failed", "no_text", "content_mismatch", "extraction_timeout", "extractor_unavailable")
    record(f"malformed_{name}", {"status": r.status_code, "code": r.json().get("code") if r.status_code != 200 else "accepted", "seconds": round(took, 2)})


def test_a_flate_bomb_pdf_does_not_hurt_the_server(client, fake):
    """A PDF whose content stream is ~300 MB of zeros once inflated (compressed to ~300 KB)."""
    bomb = zlib.compress(b"\x00" * (300 * 1024 * 1024), 9)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(bomb) + bomb + b"\nendstream"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    t, _ = _signup(client)
    t0 = time.monotonic()
    r = _up(client, _hdr(t), "bomb.pdf", bytes(out))
    took = time.monotonic() - t0
    assert r.status_code in (200, 422) and took < 30, (r.status_code, r.text[:200], took)
    # the server is still healthy and serving
    assert client.get("/livez").status_code == 200
    record("flate_bomb", {"compressed_bytes": len(bomb), "inflates_to_mb": 300, "status": r.status_code, "code": r.json().get("code") if r.status_code != 200 else "accepted", "seconds": round(took, 2)})
