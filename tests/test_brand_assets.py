"""Founder-locked ORNEUR brand identity: exact-source, presence, reference and serving checks."""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

import pytest

from tests.test_g006_tenant_isolation import client  # noqa: F401  (fixture re-export)

WEB = Path(__file__).resolve().parents[1] / "orca" / "serve" / "web"
BRAND = WEB / "brand"
APPROVED_MASTER_SHA256 = "4864b26b78103951fffd2ef5b2a65eaa36182885584a087aa4ea47f77b55dc9c"
PAGES = ("index.html", "landing.html", "trust.html")


def _png_info(path: Path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    width, height, _depth, color_type = struct.unpack(">IIBB", data[16:26])
    return width, height, color_type


def _ico_sizes(path: Path):
    data = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    return {(data[6 + 16 * i] or 256, data[7 + 16 * i] or 256) for i in range(count)}


def _assets():
    return {a["role"]: a for a in json.loads((BRAND / "ASSETS.json").read_text())["assets"]}


def test_master_is_the_founder_approved_file_byte_for_byte():
    a = _assets()["master"]
    data = (BRAND / a["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == APPROVED_MASTER_SHA256 == a["sha256"]
    assert json.loads((BRAND / "ASSETS.json").read_text())["approved_master_sha256"] == APPROVED_MASTER_SHA256


def test_every_listed_asset_exists_with_matching_hash_name_and_dimensions():
    for role, a in _assets().items():
        path = BRAND / a["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == a["sha256"], role
        assert re.search(rf"\.{digest[:8]}\.(png|ico)$", a["file"]), role
        if path.suffix == ".png":
            assert _png_info(path)[:2] == (a["width"], a["height"]), role
    assert {p.name for p in BRAND.iterdir()} == {a["file"] for a in _assets().values()} | {"ASSETS.json"}


def test_required_icon_sizes():
    sizes = {r: (a["width"], a["height"]) for r, a in _assets().items()}
    assert sizes["favicon_16"] == (16, 16) and sizes["favicon_32"] == (32, 32)
    assert sizes["apple_touch_icon"] == (180, 180)
    assert sizes["pwa_192"] == (192, 192) and sizes["pwa_512"] == (512, 512)
    assert sizes["og_image"] == (1200, 630)
    assert {(16, 16), (32, 32)} <= _ico_sizes(BRAND / _assets()["favicon_ico"]["file"])


def test_pages_reference_only_existing_official_assets_and_have_icon_links():
    names = {a["file"] for a in _assets().values()}
    for page in PAGES:
        html = (WEB / page).read_text()
        refs = set(re.findall(r"/static/brand/([A-Za-z0-9_.\-]+)", html))
        assert refs, page
        assert refs <= names, (page, refs - names)
        for needle in ('rel="icon"', 'rel="apple-touch-icon"', 'rel="manifest"', 'property="og:image"', 'name="twitter:image"'):
            assert needle in html, (page, needle)


def test_old_placeholder_marks_are_gone_from_the_running_app():
    for page in PAGES:
        html = (WEB / page).read_text()
        assert "M4 20 Q6 14" not in html, page  # the inline placeholder emblem path
        assert 'class="brand-text"' not in html and 'class="logo-text"' not in html, page
        assert "auth-wordmark" not in html.split("</style>", 1)[1] and "welcome-wordmark" not in html.split("</style>", 1)[1], page
        for banned in ("falcon", "orca-logo"):
            assert banned not in html.lower(), (page, banned)


def test_logo_images_declare_dimensions_matching_their_files_aspect_ratio():
    by_file = {a["file"]: a for a in _assets().values()}
    seen = 0
    for page in PAGES:
        for tag in re.findall(r"<img[^>]+/static/brand/[^>]+>", (WEB / page).read_text()):
            src = re.search(r'src="/static/brand/([^"]+)"', tag).group(1)
            w = int(re.search(r'width="(\d+)"', tag).group(1))
            h = int(re.search(r'height="(\d+)"', tag).group(1))
            assert re.search(r'alt="[^"]+"', tag), tag
            a = by_file[src]
            assert abs((w / h) / (a["width"] / a["height"]) - 1) < 0.03, (page, src, w, h)  # no stretching
            assert w <= a["width"] and h <= a["height"], (page, src)  # never upscaled past native size
            seen += 1
    assert seen >= 9


def test_logo_css_never_alters_the_artwork():
    css = "".join(re.findall(r"<style>(.*?)</style>", (WEB / "index.html").read_text(), re.S))
    block = re.findall(r"\.(?:logo-icon|logo-wordmark|brand-lockup|auth-lockup|welcome-lockup)\s*\{[^}]*\}", css)
    assert block
    for rule in block:
        for forbidden in ("filter", "box-shadow", "drop-shadow", "border", "animation", "transform", "opacity", "mix-blend"):
            assert forbidden not in rule, rule


def test_installed_images_are_opaque():
    """No transparency is claimed or introduced: only the master carries an alpha channel, and it is fully opaque."""
    for role, a in _assets().items():
        if a["file"].endswith(".ico"):
            continue
        color_type = _png_info(BRAND / a["file"])[2]
        if role != "master":
            assert color_type == 2, role  # RGB, no alpha
    Image = pytest.importorskip("PIL.Image")
    with Image.open(BRAND / _assets()["master"]["file"]) as im:
        assert im.getchannel("A").getextrema() == (255, 255)


def test_server_serves_favicon_manifest_and_immutable_assets(client):
    a = _assets()
    r = client.get("/favicon.ico")
    assert r.status_code == 200 and r.content == (BRAND / a["favicon_ico"]["file"]).read_bytes()
    assert r.headers["cache-control"] == "no-cache"
    r = client.get("/apple-touch-icon.png")
    assert r.status_code == 200 and r.content == (BRAND / a["apple_touch_icon"]["file"]).read_bytes()
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200
    doc = m.json()
    assert doc["name"] == "ORNEUR" and {i["sizes"] for i in doc["icons"]} == {"192x192", "512x512"}
    for icon in doc["icons"]:
        got = client.get(icon["src"])
        assert got.status_code == 200 and got.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/static/brand/ASSETS.json").headers.get("cache-control") != "public, max-age=31536000, immutable"
    for path in ("/", "/app", "/trust"):
        html = client.get(path).text
        assert "/static/brand/" in html and "/manifest.webmanifest" in html
