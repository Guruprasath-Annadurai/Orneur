# ORNEUR Brand Identity Lock

**FINAL BRAND RULE (founder): the founder-supplied ORNEUR logo is the sole authoritative visual identity. No AI-generated replacement is permitted.**
NON_NORMATIVE engineering evidence for a UI-asset change. It authorizes no deployment, training or architectural change.

## 1. Source and digest (corrected 2026-10-12)
| | |
|---|---|
| Authoritative master | `orneur_official_master.png` from `ORNEUR_Official_Logo_CORRECTED.zip` (1254×1254 RGBA PNG, fully opaque) |
| SHA-256 | `c861c074a34dfd2a45a073b389be3f28a9ede26266b86fedac33f17d34518a1b` — **verified equal** to the founder-approved digest |
| Format check | PNG signature present (byte-preserved PNG, not a WebP/JPEG re-encoding) |
| Package manifest | all 22 package files hash to the digests in the package's own `ASSETS.json` (manifest SHA-256 `169a418d8f4ef099abde10fd6f38ef2f93e095d98d0a36e45cb7475edd6f5f05`) |
| **Superseded master** | `4864b26b78103951fffd2ef5b2a65eaa36182885584a087aa4ea47f77b55dc9c` (the ZIP master first used in PR #39). Recorded in `ASSETS.json` under `superseded_master_sha256`; the installer and `tests/test_brand_assets.py` refuse it as an active master. |

**Observation (information only, no action taken).** The approved master and the superseded master have **identical RGB pixels** (mean absolute difference 0.0); only the file bytes
(container/metadata) differ. Both differ visibly from the inline WebP shown in the directive (mean abs. difference ≈ 19.7/255: the WebP is brighter and has no bottom row of secondary examples).
The assets here are exactly the founder's package; if the WebP rendering is what the founder sees as the logo, then neither ZIP master reproduces it pixel-for-pixel.

## 2. Asset directory and inventory — `orca/serve/web/brand/` (served at `/static/brand/`)
The product's UI lives in `orca/serve/web/` (no `frontend/` tree exists). Every filename carries the first 8 hex digits of its own SHA-256 and is served `Cache-Control: public, max-age=31536000, immutable`; `ASSETS.json` is the machine-readable inventory.

| File | Role | Size | Origin | SHA-256 |
|---|---|---|---|---|
| `apple-touch-icon.edc2b62d.png` | apple_touch_icon | 180×180 | supplied byte-for-byte | `edc2b62de2020b14ed80bd8f7e85a9f7c158cf6832cf6c936d1e6deea7c319f7` |
| `orneur-emblem-192.40a30f86.png` | emblem_192 | 192×192 | supplied byte-for-byte | `40a30f8602c8058761785ae9981bd766dcb3263157bca1808603c69231ab03b6` |
| `orneur-emblem-256.5b8e8b28.png` | emblem_256 | 256×256 | supplied byte-for-byte | `5b8e8b28814969a4634418f572959d83a532643ba1a07c65e72dfd0517c4532d` |
| `orneur-emblem-64.7ade6284.png` | emblem_64 | 64×64 | supplied byte-for-byte | `7ade628454bc22635e793a1456472f80c286842d3b2e1f8cfc4220ff5232320c` |
| `orneur-emblem-530.1d344e9d.png` | emblem_master | 530×530 | supplied byte-for-byte | `1d344e9df6f8c741c060c8438246f5ce2174caf26bf6890235bb693092d7593f` |
| `favicon-16x16.d261e4ff.png` | favicon_16 | 16×16 | supplied byte-for-byte | `d261e4ff3e80587799378ba466cdc973ba216ab56a08d4c4e280066674d2fc7a` |
| `favicon-32x32.c86b0334.png` | favicon_32 | 32×32 | supplied byte-for-byte | `c86b033421816c43d84118c9635f6237f7d674acb285e6f0886ed00506a59b62` |
| `favicon.f62543e5.ico` | favicon_ico | 16×16 | supplied byte-for-byte | `f62543e59b9958fbfec2e990e98cb084bc01b1ebcc75bdcfd056d5017ffa3233` |
| `orneur-lockup-640.c4f0bf12.png` | lockup_640 | 640×474 | **derived** (orneur_logo_lockup_exact_crop.png, Lanczos) | `c4f0bf1221db971810161d7a6a1c58d71c8158a5ce6c54818fe27ca6382334f3` |
| `orneur-lockup-exact-crop.a6c44de7.png` | lockup_crop | 985×730 | supplied byte-for-byte | `a6c44de7b8586c683bc073d4f7bebb1c856be288cb18dbf1e22655baf99c02a9` |
| `orneur-official-master.c861c074.png` | master | 1254×1254 | supplied byte-for-byte | `c861c074a34dfd2a45a073b389be3f28a9ede26266b86fedac33f17d34518a1b` |
| `orneur-social-1200x630.6452caac.png` | og_image | 1200×630 | supplied byte-for-byte | `6452caaca0d5a0a9c2f785f764556304d6028ab747949d04ee24483b61147995` |
| `pwa-192.40a30f86.png` | pwa_192 | 192×192 | supplied byte-for-byte | `40a30f8602c8058761785ae9981bd766dcb3263157bca1808603c69231ab03b6` |
| `pwa-512.f5651347.png` | pwa_512 | 512×512 | supplied byte-for-byte | `f5651347a67d9909d854dec772901e419aea4bd89cfe58c56fcf2917c0d081fe` |
| `orneur-wordmark-240.9a2ab2a8.png` | wordmark_240 | 240×27 | **derived** (orneur_wordmark_exact_crop.png, Lanczos) | `9a2ab2a87fa2305f5060ecc1237e75c4fd4bbc03cefa26e10ef2662fa4544c37` |
| `orneur-wordmark-480.d89f850e.png` | wordmark_480 | 480×54 | **derived** (orneur_wordmark_exact_crop.png, Lanczos) | `d89f850efe219f4586904f0806968f3e169adbe157e9adb0366b7f41c787af20` |
| `orneur-wordmark-exact-crop.a374b14f.png` | wordmark_crop | 945×106 | supplied byte-for-byte | `a374b14f52c7a5f1b14dea41acae5e91d6644f92a8a02944595054cf27a690de` |

Derivation is mechanical (Pillow resize of the founder's own exact crops; nothing redrawn, recoloured, thresholded or made transparent). `scripts/brand/install_brand_assets.py` verifies the master and every package file against the package manifest and refuses the superseded master.
Not installed: `.jpg` variants, `orneur_icon_16/32/180/512/1024` duplicates or unused sizes (hash-identical copies of installed favicons/touch/PWA files are omitted).

## 3. Active references replaced
All active references in `index.html` (header emblem + wordmark, sign-in/sign-up lockup, welcome-screen lockup), `landing.html` and `trust.html` (nav and footer emblem + wordmark), plus every head-level favicon, Apple touch icon, manifest icon and Open Graph/Twitter image, now point at the corrected, content-hashed files.
The 15 files installed from the superseded package are deleted from the tree and listed in `tests/test_brand_assets.py::SUPERSEDED_FILES`; the test fails if any is present on disk or referenced by a page.
Earlier (first-round) replacements still hold: inline placeholder SVGs and CSS text wordmarks are gone; the earlier falcon/segmented-E concepts, orca briefs and design-generator output are labelled SUPERSEDED (`docs/orneur/design/`, `docs/DESIGN_BRIEF.md`, `docs/LOGO_DESIGN_PROMPT.md`) and left intact for audit.
New routes: `/favicon.ico`, `/apple-touch-icon.png`, `/manifest.webmanifest` (revalidated, `no-cache`).

## 4. Themes
The running product is one dark UI; the Dark/Light switch exists only in the unapproved PR #29 design proposal. **Light theme is not implemented and was not tested** (an OS `prefers-color-scheme: light` render of the same dark page is not a Light theme, so no such screenshots are included).
The artwork is an opaque raster with its own dark background and is shown unchanged: no inversion, recolouring, filter, shadow, border or animation (enforced by tests on the logo CSS).

## 5. Evidence
- Tests (`tests/test_brand_assets.py`): approved digest, PNG signature, superseded digest never active, per-file hash/size/name, icon sizes, page references resolve, no superseded file referenced or present, no placeholder marks, no stretching/upscaling, no effects on logo CSS, opacity, server routes and cache headers.
- Screenshots (`docs/orneur/brand/evidence/`, Chromium, dark): landing, app sign-in (the authentication surface) and trust at desktop 1440, tablet 820 and mobile 390; every brand image loaded (no broken images) and rendered at its declared size; no horizontal overflow at 390 px (the landing/trust wordmark is hidden below 400 px nav width, emblem remains).
- `icon-preview-sheet.png`: 16, 32, 180, 192 and 512 px icons.

## 6. Limitations
1. **No vector or transparent original.** Rasters only; the 16 and 32 px favicons are the founder's downscales of detailed artwork and cannot retain its fine detail (the 16 px icon is a coarse blur of the emblem).
2. The package's `favicon.ico` contains a single 16×16 image; the 32×32 PNG and 180/192/512 icons cover larger contexts.
3. The social card is the founder's supplied 1200×630, which includes the master's bottom row of secondary examples. Its URL is root-relative; crawlers need an absolute URL, which depends on the deployed hostname.
4. Not verified: Safari/WebKit, a real phone home-screen install, a real browser favicon-tab refresh, and the signed-in header (it is covered by DOM/image-load checks and the same assets, but not by a post-login screenshot).
5. The wordmark crop is downscaled to ~116 px wide in navigation (≈8× smaller than the source row), so its thin strokes are soft at 1× pixel density.
