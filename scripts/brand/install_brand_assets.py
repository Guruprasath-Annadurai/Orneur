#!/usr/bin/env python3
"""Install the founder-approved ORNEUR brand assets into orca/serve/web/brand/.

Usage: install_brand_assets.py <extracted-zip-dir>

The artwork is NOT redrawn. Files supplied by the founder are copied byte for
byte; the few derivatives (cropped wordmark, resized lockup, 1200x630 social
card) are produced mechanically from the official master with Pillow and each
derivation is recorded in ASSETS.json. Filenames carry the first 8 hex digits of
their own SHA-256 so they can be cached as immutable.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

MASTER_SHA256 = "4864b26b78103951fffd2ef5b2a65eaa36182885584a087aa4ea47f77b55dc9c"
OUT = Path(__file__).resolve().parents[2] / "orca" / "serve" / "web" / "brand"
BG = (3, 5, 10)
# Pixel boxes in the 1254x1254 master (left, top, right, bottom).
WORDMARK_BOX = (205, 705, 1050, 805)
LOCKUP_BOX = (107, 160, 1147, 920)

# (source file in the founder ZIP, stem, role, note)
SUPPLIED = [
    ("orneur_official_master.png", "orneur-official-master", "master", "Founder master artwork, unaltered"),
    ("orneur_icon_dark_master.png", "orneur-emblem-800", "emblem_master", "Founder-supplied emblem on native dark background"),
    ("orneur_icon_64.png", "orneur-emblem-64", "emblem_64", "Founder-supplied"),
    ("orneur_icon_192.png", "orneur-emblem-192", "emblem_192", "Founder-supplied"),
    ("orneur_icon_256.png", "orneur-emblem-256", "emblem_256", "Founder-supplied"),
    ("favicon.ico", "favicon", "favicon_ico", "Founder-supplied multi-size ICO (16-256)"),
    ("favicon-16x16.png", "favicon-16x16", "favicon_16", "Founder-supplied"),
    ("favicon-32x32.png", "favicon-32x32", "favicon_32", "Founder-supplied"),
    ("apple-touch-icon.png", "apple-touch-icon", "apple_touch_icon", "Founder-supplied 180x180"),
    ("android-chrome-192x192.png", "pwa-192", "pwa_192", "Founder-supplied"),
    ("android-chrome-512x512.png", "pwa-512", "pwa_512", "Founder-supplied"),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(src_dir: str) -> int:
    src = Path(src_dir)
    master = src / "orneur_official_master.png"
    if sha(master) != MASTER_SHA256:
        print("STOP: master digest differs from the founder-approved digest", file=sys.stderr)
        return 1
    if OUT.exists():
        for old in OUT.iterdir():
            old.unlink()
    OUT.mkdir(parents=True, exist_ok=True)
    assets = []

    def add(src_path: Path, stem: str, role: str, note: str, derived_from: str | None = None):
        digest = sha(src_path)
        ext = src_path.suffix
        name = f"{stem}.{digest[:8]}{ext}"
        shutil.copyfile(src_path, OUT / name)
        w = h = None
        if ext != ".ico":
            with Image.open(OUT / name) as im:
                w, h = im.size
        else:
            with Image.open(OUT / name) as im:
                w, h = im.size
        assets.append({"role": role, "file": name, "sha256": digest, "width": w, "height": h,
                       "note": note, "derived_from": derived_from})

    for fname, stem, role, note in SUPPLIED:
        add(src / fname, stem, role, note)

    tmp = OUT / "_tmp"
    tmp.mkdir()
    m = Image.open(master).convert("RGB")
    # Wordmark-only: a straight crop of the master's letter row, then a Lanczos resize.
    crop = m.crop(WORDMARK_BOX)
    wm = crop.resize((480, round(480 * crop.height / crop.width)), Image.LANCZOS)
    wm.save(tmp / "wm.png", optimize=True)
    add(tmp / "wm.png", "orneur-wordmark-480", "wordmark_480",
        f"Crop {WORDMARK_BOX} of the master (letter row only), Lanczos to 480 px wide", "orneur_official_master.png")
    wm.resize((240, round(240 * wm.height / wm.width)), Image.LANCZOS).save(tmp / "wm240.png", optimize=True)
    add(tmp / "wm240.png", "orneur-wordmark-240", "wordmark_240",
        "orneur-wordmark-480 (itself a Lanczos resize of the master letter-row crop) resized to 240 px wide",
        "orneur_official_master.png")
    # Primary lockup (emblem + wordmark + expansion + tagline): a straight crop of the master that
    # excludes the master's bottom row of secondary examples, then a Lanczos resize.
    lk = m.crop(LOCKUP_BOX)
    lk = lk.resize((640, round(640 * lk.height / lk.width)), Image.LANCZOS)
    lk.save(tmp / "lk.png", optimize=True)
    add(tmp / "lk.png", "orneur-lockup-640", "lockup_640",
        f"Crop {LOCKUP_BOX} of the master (primary lockup, no bottom examples), Lanczos to 640 px wide", "orneur_official_master.png")
    # Social card: master at native aspect, centred on a flat canvas of the master's own background colour.
    card = Image.new("RGB", (1200, 630), BG)
    lk_card = m.crop(LOCKUP_BOX)
    lk_card = lk_card.resize((round(590 * lk_card.width / lk_card.height), 590), Image.LANCZOS)
    card.paste(lk_card, ((1200 - lk_card.width) // 2, 20))
    card.save(tmp / "og.png", optimize=True)
    add(tmp / "og.png", "orneur-og-1200x630", "og_image",
        "Primary-lockup crop resized to 590 px high, centred on a flat (3,5,10) canvas", "orneur_official_master.png")
    shutil.rmtree(tmp)

    doc = {
        "schema": "orneur.brand-assets/1",
        "authority": "Founder-supplied ORNEUR logo is the sole authoritative visual identity.",
        "approved_master_sha256": MASTER_SHA256,
        "master_digest_note": ("The founder's directive quoted c861c074...; the supplied file hashes to the value above. "
                               "The founder explicitly accepted 4864b26b... as authoritative on 2026-10-11."),
        "no_vector_original": True,
        "no_transparency": "All installed rasters are opaque and carry the native dark background.",
        "assets": sorted(assets, key=lambda a: a["role"]),
    }
    (OUT / "ASSETS.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for a in doc["assets"]:
        print(a["role"], a["file"], a["width"], a["height"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
