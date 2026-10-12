#!/usr/bin/env python3
"""Install the founder-approved ORNEUR brand assets into orca/serve/web/brand/.

Usage: install_brand_assets.py <extracted ORNEUR_Official_Logo_CORRECTED.zip dir>

The artwork is NOT redrawn. Files supplied by the founder are copied byte for byte and each is
checked against the package's own ASSETS.json; the few web-size derivatives (wordmark 480/240,
lockup 640) are mechanical Lanczos resizes of the founder's exact crops and are recorded in
ASSETS.json. Filenames carry the first 8 hex digits of their own SHA-256 so they can be cached
as immutable. The installer refuses any master whose digest is not the approved one, and the
superseded master digest can never be accepted.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

MASTER_SHA256 = "c861c074a34dfd2a45a073b389be3f28a9ede26266b86fedac33f17d34518a1b"
SUPERSEDED_MASTER_SHA256 = ("4864b26b78103951fffd2ef5b2a65eaa36182885584a087aa4ea47f77b55dc9c",)
OUT = Path(__file__).resolve().parents[2] / "orca" / "serve" / "web" / "brand"

# (file in the founder ZIP, stem, role, note)
SUPPLIED = [
    ("orneur_official_master.png", "orneur-official-master", "master", "Founder master artwork, unaltered"),
    ("orneur_logo_lockup_exact_crop.png", "orneur-lockup-exact-crop", "lockup_crop", "Founder-supplied exact crop of the primary lockup"),
    ("orneur_wordmark_exact_crop.png", "orneur-wordmark-exact-crop", "wordmark_crop", "Founder-supplied exact crop of the wordmark row"),
    ("orneur_icon_dark_master.png", "orneur-emblem-530", "emblem_master", "Founder-supplied emblem on native dark background"),
    ("orneur_icon_64.png", "orneur-emblem-64", "emblem_64", "Founder-supplied"),
    ("orneur_icon_192.png", "orneur-emblem-192", "emblem_192", "Founder-supplied"),
    ("orneur_icon_256.png", "orneur-emblem-256", "emblem_256", "Founder-supplied"),
    ("favicon.ico", "favicon", "favicon_ico", "Founder-supplied multi-size ICO"),
    ("favicon-16x16.png", "favicon-16x16", "favicon_16", "Founder-supplied"),
    ("favicon-32x32.png", "favicon-32x32", "favicon_32", "Founder-supplied"),
    ("apple-touch-icon.png", "apple-touch-icon", "apple_touch_icon", "Founder-supplied 180x180"),
    ("android-chrome-192x192.png", "pwa-192", "pwa_192", "Founder-supplied"),
    ("android-chrome-512x512.png", "pwa-512", "pwa_512", "Founder-supplied"),
    ("orneur_social_1200x630.png", "orneur-social-1200x630", "og_image", "Founder-supplied social card"),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(src_dir: str) -> int:
    src = Path(src_dir)
    master = src / "orneur_official_master.png"
    digest = sha(master)
    if digest in SUPERSEDED_MASTER_SHA256:
        print("STOP: this master is the SUPERSEDED one", file=sys.stderr)
        return 1
    if digest != MASTER_SHA256:
        print("STOP: master digest differs from the founder-approved digest", file=sys.stderr)
        return 1
    if master.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        print("STOP: master is not a byte-preserved PNG", file=sys.stderr)
        return 1
    package = json.loads((src / "ASSETS.json").read_text())
    if package["official_master_sha256"] != MASTER_SHA256:
        print("STOP: package manifest names a different master", file=sys.stderr)
        return 1
    for name, want in package["files"].items():
        if sha(src / name) != want:
            print(f"STOP: {name} does not match the package manifest", file=sys.stderr)
            return 1

    if OUT.exists():
        for old in OUT.iterdir():
            old.unlink()
    OUT.mkdir(parents=True, exist_ok=True)
    assets = []

    def add(src_path: Path, stem: str, role: str, note: str, derived_from: str | None = None):
        d = sha(src_path)
        name = f"{stem}.{d[:8]}{src_path.suffix}"
        shutil.copyfile(src_path, OUT / name)
        with Image.open(OUT / name) as im:
            w, h = im.size
        assets.append({"role": role, "file": name, "sha256": d, "width": w, "height": h, "note": note, "derived_from": derived_from})

    for fname, stem, role, note in SUPPLIED:
        add(src / fname, stem, role, note)

    tmp = OUT / "_tmp"
    tmp.mkdir()
    wm = Image.open(src / "orneur_wordmark_exact_crop.png").convert("RGB")
    for w in (480, 240):
        wm.resize((w, round(w * wm.height / wm.width)), Image.LANCZOS).save(tmp / f"wm{w}.png", optimize=True)
        add(tmp / f"wm{w}.png", f"orneur-wordmark-{w}", f"wordmark_{w}",
            f"orneur_wordmark_exact_crop.png (founder-supplied) Lanczos-resized to {w} px wide", "orneur_wordmark_exact_crop.png")
    lk = Image.open(src / "orneur_logo_lockup_exact_crop.png").convert("RGB")
    lk.resize((640, round(640 * lk.height / lk.width)), Image.LANCZOS).save(tmp / "lk640.png", optimize=True)
    add(tmp / "lk640.png", "orneur-lockup-640", "lockup_640",
        "orneur_logo_lockup_exact_crop.png (founder-supplied) Lanczos-resized to 640 px wide", "orneur_logo_lockup_exact_crop.png")
    shutil.rmtree(tmp)

    doc = {
        "schema": "orneur.brand-assets/2",
        "authority": "Founder-supplied ORNEUR logo is the sole authoritative visual identity.",
        "approved_master_sha256": MASTER_SHA256,
        "superseded_master_sha256": list(SUPERSEDED_MASTER_SHA256),
        "superseded_note": ("4864b26b... was used by PR #39 before the founder's correction of 2026-10-12. It must never be the active master. "
                            "Observation: its RGB pixels are identical to the approved master (only the file bytes differ), and both differ from the "
                            "inline WebP image shown in the founder's directive."),
        "package_manifest_sha256": hashlib.sha256((src / "ASSETS.json").read_bytes()).hexdigest(),
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
