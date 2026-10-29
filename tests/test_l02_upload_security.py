"""L02-02 upload parsing security: container pre-checks, parser isolation, duplicate / concurrent / quota handling.

The container (DOCX/ZIP) checks and the process supervisor are exercised with real archives and real child processes. Tests that need the third-party PDF/DOCX
parsers themselves live in tests/journey/test_l02_upload_parsers_live.py (those libraries are an optional extra that CI does not install).
"""
from __future__ import annotations

import asyncio
import io
import os
import struct
import sys
import threading
import time
import uuid
import zipfile

import pytest

from orca.docs import safe_extract, validation
from orca.docs.validation import UploadRejected
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401
from tests.test_product_flows_fake_ollama import fake  # noqa: F401


def _zip(members: dict[str, bytes], deflate=True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def _docx(extra: dict[str, bytes] | None = None) -> bytes:
    return _zip({"word/document.xml": b"<w:document/>", "[Content_Types].xml": b"<Types/>", **(extra or {})})


# ── container pre-checks ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_valid_looking_docx_package_passes_the_precheck():
    validation.validate_content("a.docx", _docx())


@pytest.mark.parametrize("name,data,code", [
    ("bomb.docx", _docx({"word/media/bomb.bin": b"\x00" * (6 * 1024 * 1024)}), "container_unsafe"),                      # ratio > 200, > 1 MiB
    ("many.docx", _docx({f"word/p{i}.xml": b"x" for i in range(2100)}), "container_unsafe"),                              # entry-count bomb
    ("trav.docx", _docx({"../../evil.xml": b"x"}), "container_unsafe"),
    ("abs.docx", _docx({"/etc/evil.xml": b"x"}), "container_unsafe"),
    ("notdoc.docx", _zip({"hello.txt": b"just a zip"}), "content_mismatch"),
    ("fake.docx", b"PK\x03\x04 this is not a real zip central directory", "content_mismatch"),
    ("noheader.docx", b"plain text", "content_mismatch"),
])
def test_hostile_docx_containers_are_refused_before_any_parser_runs(name, data, code):
    with pytest.raises(UploadRejected) as e:
        validation.validate_content(name, data)
    assert e.value.code == code


def test_encrypted_member_flag_is_refused():
    raw = bytearray(_docx())
    # set general-purpose bit 0 (encrypted) in the first local header AND the central directory entry
    for sig in (b"PK\x03\x04", b"PK\x01\x02"):
        i = raw.find(sig)
        off = 6 if sig == b"PK\x03\x04" else 8
        raw[i + off] |= 0x01
    with pytest.raises(UploadRejected) as e:
        validation.validate_content("enc.docx", bytes(raw))
    assert e.value.code == "container_unsafe"


@pytest.mark.parametrize("data,code", [
    ("héllo wörld ünïcode".encode("utf-16"), "unsupported_encoding"),
    (b"fine text " * 50 + b"\xff\xfe\xfa invalid " + b"more text " * 50, "unsupported_encoding"),
])
def test_unsupported_encodings_get_a_meaningful_refusal(data, code):
    with pytest.raises(UploadRejected) as e:
        validation.validate_content("note.txt", data)
    assert e.value.code == code and "UTF-8" in str(e.value)


# ── the supervisor (real child processes) ───────────────────────────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


def test_a_hung_parser_is_killed_at_the_deadline_with_its_children():
    child = [sys.executable, "-c", "import os,time,subprocess; subprocess.Popen(['sleep','60']); open('/tmp/l02-hang-pid','w').write(str(os.getpid())); time.sleep(60)"]
    t0 = time.monotonic()
    with pytest.raises(UploadRejected) as e:
        run(safe_extract.extract_isolated("x.pdf", b"data", timeout_s=1.5, _argv=child))
    took = time.monotonic() - t0
    assert e.value.code == "extraction_timeout" and took < 5
    time.sleep(0.3)
    pid = int(open("/tmp/l02-hang-pid").read())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_memory_hungry_parser_is_contained(monkeypatch):
    monkeypatch.setattr(safe_extract, "MEM_BYTES", 256 * 1024 * 1024)
    child = [sys.executable, "-c", "x = bytearray(2*1024*1024*1024); print('{\"ok\": true, \"text\": \"allocated\"}')"]
    with pytest.raises(safe_extract.ExtractFailed):
        run(safe_extract.extract_isolated("x.pdf", b"data", _argv=child))


def test_a_parser_that_floods_output_is_cut_off(monkeypatch):
    monkeypatch.setattr(safe_extract, "MAX_OUT_BYTES", 1024 * 1024)
    child = [sys.executable, "-c", "import sys; sys.stdout.write('x' * (8*1024*1024))"]
    with pytest.raises(UploadRejected) as e:
        run(safe_extract.extract_isolated("x.pdf", b"data", _argv=child))
    assert e.value.code == "document_too_large"


def test_crashing_and_garbage_children_are_failures_not_server_errors():
    for code in ("import sys; sys.exit(3)", "import os; os.abort()", "print('not json')", "import sys; sys.stdout.write('')"):
        with pytest.raises(safe_extract.ExtractFailed):
            run(safe_extract.extract_isolated("x.pdf", b"data", _argv=[sys.executable, "-c", code]))


def test_a_well_behaved_child_returns_its_text():
    child = [sys.executable, "-c", "import sys,json; sys.stdin.buffer.readline(); d=sys.stdin.buffer.read(); print(json.dumps({'ok':True,'text':d.decode()}))"]
    assert run(safe_extract.extract_isolated("x.pdf", b"hello extracted", _argv=child)) == "hello extracted"


def test_the_real_worker_reports_a_missing_parser_as_unavailable_not_as_a_crash():
    """Without the optional parsers (the CI configuration) a DOCX is "unavailable", never a crash; with them installed, a package that is not parseable is a clean
    ExtractFailed. Either way the worker process absorbs it."""
    import importlib.util

    if importlib.util.find_spec("docx") is None:
        with pytest.raises(safe_extract.ExtractUnavailable):
            run(safe_extract.extract_isolated("a.docx", _docx()))
    else:
        with pytest.raises(safe_extract.ExtractFailed):
            run(safe_extract.extract_isolated("a.docx", _docx()))


# ── route behaviour ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _up(client, h, name, data, sid=None):
    return client.post("/api/docs/upload", files={"file": (name, data, "application/octet-stream")}, params={"session_id": sid} if sid else {}, headers=h)


def test_route_refuses_a_docx_bomb_and_a_missing_parser_is_a_clean_422(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    r = _up(client, h, "bomb.docx", _docx({"word/media/b.bin": b"\x00" * (6 * 1024 * 1024)}))
    assert r.status_code == 422 and r.json()["code"] == "container_unsafe"
    r = _up(client, h, "ok.docx", _docx())
    assert r.status_code == 422 and r.json()["code"] == "extractor_unavailable" and "Traceback" not in r.text


def test_identical_uploads_are_deduplicated(client, fake):
    from orca.docs.store import list_docs

    t, _ = _signup(client)
    h = _hdr(t)
    a = _up(client, h, "a.txt", b"the same bytes in this conversation")
    sid = a.json()["session_id"]
    b = _up(client, h, "renamed.txt", b"the same bytes in this conversation", sid=sid)
    assert b.status_code == 200 and b.json()["doc_id"] == a.json()["doc_id"] and b.json()["duplicate"] is True
    assert len(list_docs(sid)) == 1 and client.get("/api/docs/list", params={"session_id": sid}, headers=h).json()["total_chunks"] == a.json()["chunks"]


def test_concurrent_identical_uploads_leave_one_document_and_no_orphan_chunks(client, fake):
    from orca.docs.store import DocStore, list_docs

    t, _ = _signup(client)
    h = _hdr(t)
    sid = _up(client, h, "seed.txt", b"seed document").json()["session_id"]
    out = []

    def go():
        out.append(_up(client, h, "same.txt", b"identical concurrent payload " * 5, sid=sid))

    ts = [threading.Thread(target=go) for _ in range(6)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    assert all(r.status_code == 200 for r in out)
    assert len({r.json()["doc_id"] for r in out}) == 1
    docs = list_docs(sid)
    assert len(docs) == 2
    raw = DocStore(sid, enforce_registry=False)
    assert raw.count() == sum(d["chunk_count"] for d in docs), "chunks written by losing concurrent uploads must be removed"


def test_concurrent_distinct_uploads_cannot_exceed_the_document_cap(client, fake, monkeypatch):
    from orca.docs.store import DocStore, list_docs

    monkeypatch.setattr(validation, "MAX_DOCS_PER_SESSION", 3)
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _up(client, h, "seed.txt", b"seed document zero").json()["session_id"]
    out = []

    def go(i):
        out.append(_up(client, h, f"d{i}.txt", f"distinct document number {i} {uuid.uuid4()}".encode(), sid=sid))

    ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    ok = [r for r in out if r.status_code == 200]
    refused = [r for r in out if r.status_code == 422]
    assert len(ok) == 2 and len(refused) == 6 and all(r.json()["code"] == "too_many_documents" for r in refused)
    docs = list_docs(sid)
    assert len(docs) == 3
    assert DocStore(sid, enforce_registry=False).count() == sum(d["chunk_count"] for d in docs), "refused uploads left chunks behind"


def test_account_storage_quota_spans_conversations(client, fake, monkeypatch):
    monkeypatch.setattr(validation, "MAX_DOCS_PER_USER", 2)
    t, _ = _signup(client)
    h = _hdr(t)
    assert _up(client, h, "a.txt", b"first document in conversation one").status_code == 200
    assert _up(client, h, "b.txt", b"second document in conversation two").status_code == 200
    r = _up(client, h, "c.txt", b"third document in conversation three")
    assert r.status_code == 413 and r.json()["code"] == "storage_quota_exceeded"
    u2, _ = _signup(client)
    assert _up(client, _hdr(u2), "x.txt", b"another account is unaffected").status_code == 200
