"""LANDMARK-04 P1-A -- every local asset a UI page references must exist, and brand images must be the founder's SHA-256-verified files.

Finding (P1 visual, reproduced in a real-browser screenshot against main 0a4c518): ``/conversation`` -- the approved chat page -- showed a BROKEN IMAGE where the official logo belongs.
It referenced ``/static/b01_approved_assets/orneur_logo_horizontal.png``, a file from the superseded asset package that was never installed on main; the brand test only looked at
index/landing/trust, so nothing noticed. The page now uses the installed, hash-verified emblem + wordmark exactly as the other pages do.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "orca" / "serve" / "web"
PAGES = sorted(p.name for p in WEB.glob("*.html"))
REF = re.compile(r"""(?:src|href|srcset)\s*=\s*["']([^"']+)["']""")


def _local_refs(html: str):
    for m in REF.finditer(html):
        for part in m.group(1).split(","):
            url = part.strip().split(" ")[0]
            if url.startswith("/static/"):
                yield url.split("?")[0].split("#")[0]


@pytest.mark.parametrize("page", PAGES)
def test_every_static_reference_resolves(page):
    html = (WEB / page).read_text(encoding="utf-8")
    missing = [u for u in set(_local_refs(html)) if not (WEB / u[len("/static/"):]).is_file()]
    assert not missing, f"{page} references files that do not exist: {missing}"


def test_conversation_page_shows_the_official_brand_files_unchanged():
    html = (WEB / "conversation.html").read_text(encoding="utf-8")
    brand = [u for u in set(_local_refs(html)) if u.startswith("/static/brand/")]
    assert any("emblem" in u for u in brand) and any("wordmark" in u for u in brand), brand
    manifest = {a["file"]: a["sha256"] for a in json.loads((WEB / "brand" / "ASSETS.json").read_text())["assets"]}
    for u in brand:
        name = u.rsplit("/", 1)[1]
        assert name in manifest, f"{name} is not an installed founder asset"
        assert hashlib.sha256((WEB / "brand" / name).read_bytes()).hexdigest() == manifest[name]
    assert "b01_approved_assets" not in html
