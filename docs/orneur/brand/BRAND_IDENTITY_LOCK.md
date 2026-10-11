# ORNEUR Brand Identity Lock

**FINAL BRAND RULE (founder, 2026-10-11): the founder-supplied ORNEUR logo is the sole authoritative visual identity. No AI-generated replacement is permitted.**
This document is NON_NORMATIVE engineering evidence for a UI-asset change. It authorizes no deployment, training or architectural change.

## 1. Source and digest
| | |
|---|---|
| Authoritative master | `orneur_official_master.png` (1254×1254, opaque) from the founder's ZIP |
| SHA-256 | `4864b26b78103951fffd2ef5b2a65eaa36182885584a087aa4ea47f77b55dc9c` |
| Digest quoted in the directive | `c861c074a34dfd2a45a073b389be3f28a9ede26266b86fedac33f17d34518a1b` — **did not match any supplied file** |
| Resolution | The founder was told of the mismatch and, in writing, accepted `4864b26b…` as the authoritative file (session record, 2026-10-11). |

**Observation for the founder (not acted on).** The ZIP master differs visually from the logo image pasted into the directive: it carries a bottom row of secondary
examples (emblem, app tile, compact lockup), a different composition, and a more muted palette (sampled slate ≈ `#4D5F85`-range and pale-stone ≈ `#E2DCD9`, versus ≈ `#5675A3` and ≈ `#FAF8F6`
in the pasted image). Both are the same design, but they are not the same pixels. The ZIP's README says its master is "unaltered". If the brighter pasted rendering is what you intend, send that file and
the assets here will be regenerated with one command (`scripts/brand/install_brand_assets.py`).

## 2. Asset directory and inventory — `orca/serve/web/brand/` (served at `/static/brand/`)
Existing structure respected: the product's UI lives in `orca/serve/web/` (there is no `frontend/` tree). Every filename carries the first 8 hex digits of its own SHA-256 and is served
`Cache-Control: public, max-age=31536000, immutable`. `ASSETS.json` is the machine-readable inventory (role, file, SHA-256, size, derivation).

| File | Role | Size | Origin | SHA-256 |
|---|---|---|---|---|
| `orneur-official-master.4864b26b.png` | master | 1254×1254 | supplied byte-for-byte | `4864b26b78103951…` |
| `orneur-emblem-800.d810e3c2.png` | emblem master | 800×800 | supplied byte-for-byte | `d810e3c200ff82d1…` |
| `orneur-emblem-64.30ad3075.png` | header/footer emblem | 64×64 | supplied byte-for-byte | `30ad3075b60e9180…` |
| `orneur-emblem-192.cf49c361.png` | emblem (hi-DPI) | 192×192 | supplied byte-for-byte | `cf49c361d22c2b74…` |
| `orneur-emblem-256.9175ced1.png` | emblem (hi-DPI) | 256×256 | supplied byte-for-byte | `9175ced15c151fe8…` |
| `favicon.82fee6a0.ico` | favicon (16–256) | multi | supplied byte-for-byte | `82fee6a0b1832411…` |
| `favicon-16x16.4bb4003b.png` | favicon | 16×16 | supplied byte-for-byte | `4bb4003b6cbda713…` |
| `favicon-32x32.56369742.png` | favicon | 32×32 | supplied byte-for-byte | `563697424479b737…` |
| `apple-touch-icon.ca25451e.png` | Apple touch icon | 180×180 | supplied byte-for-byte | `ca25451e3a0044b3…` |
| `pwa-192.cf49c361.png` | PWA icon | 192×192 | supplied byte-for-byte | `cf49c361d22c2b74…` |
| `pwa-512.7361eaa0.png` | PWA icon | 512×512 | supplied byte-for-byte | `7361eaa04157ca26…` |
| `orneur-wordmark-480.a1c79b07.png` | wordmark only | 480×57 | **derived**: straight crop of the master's letter row, Lanczos resize | `a1c79b079a7c1851…` |
| `orneur-wordmark-240.fb81e8f4.png` | wordmark only (1×) | 240×28 | **derived** from the 480 file | `fb81e8f4ff7869f9…` |
| `orneur-lockup-640.418dcae1.png` | primary lockup (login, welcome) | 640×468 | **derived**: crop of the master that excludes its bottom examples, Lanczos resize | `418dcae18873703d…` |
| `orneur-og-1200x630.af67bb4e.png` | social card | 1200×630 | **derived**: lockup crop centred on a flat canvas of the master's own background colour | `af67bb4eebbc7915…` |

Derivation is mechanical (Pillow crop/resize, boxes recorded in `scripts/brand/install_brand_assets.py`); nothing is redrawn, recoloured, thresholded or made transparent. The installer refuses to run
if the master digest differs from the approved value. Not installed: `orneur_compact_lockup.png` (380×190, too low-resolution to display), `.jpg` variants, `orneur_wordmark_with_taglines.png` (superseded by the crop above), duplicate sizes.

## 3. Active logo references replaced
| File | Was | Now |
|---|---|---|
| `orca/serve/web/index.html` header | inline 28×28 placeholder SVG + text "ORNEUR" in JetBrains Mono | official emblem (64/192/256 srcset, 32 px) + official wordmark image |
| `index.html` sign-in/sign-up | CSS text wordmark `.auth-wordmark` | official primary lockup, 240 px |
| `index.html` welcome screen | CSS text wordmark `.welcome-wordmark` | official primary lockup, 320 px |
| `landing.html` nav and footer | same inline placeholder SVG + text | official emblem + wordmark image |
| `trust.html` nav and footer | same inline placeholder SVG + text | official emblem + wordmark image |
| all three pages `<head>` | no favicon, manifest or social metadata | favicon `.ico`/16/32, Apple touch icon, `/manifest.webmanifest`, `theme-color`, Open Graph and Twitter image |
| `orca/serve/api.py` | — | `/favicon.ico`, `/apple-touch-icon.png`, `/manifest.webmanifest` (revalidated, `no-cache`); `/static/brand/*.<hash>.*` immutable |

The chat role label "ORNEUR" in message bubbles is text, not a logo, and is unchanged.

**Superseded, kept for audit (not rewritten):** `docs/orneur/design/ORNEUR_UI_DESIGN_SPEC.md` (banner added; Q1 resolved), `docs/orneur/design/preview/` and `scripts/design/build_design_preview.py`
(falcon/segmented-E concepts labelled superseded; PNGs untouched), `docs/DESIGN_BRIEF.md` and `docs/LOGO_DESIGN_PROMPT.md` (retired orca-mark guidance). The earlier Claude-generated falcon and the orca marks exist in no active page.

## 4. Themes
The running product is a single dark UI today; the Dark/Light switch exists only in the unapproved PR #29 design proposal. The official artwork is an opaque raster with its own dark background and is shown
identically in both cases: no inversion, recolouring, filter, shadow, border or animation (`tests/test_brand_assets.py` enforces this on the CSS rules). When a Light theme ships, the logo stays on its native dark tile.
Where a tile sits on a card slightly different from `#03050A` a faint rectangle is visible (login card, nav); this is the honest consequence of a non-transparent source.

## 5. Evidence
- Tests: `tests/test_brand_assets.py` — approved-digest check, per-file hash/size/name, required icon sizes, every page reference resolves, no placeholder path or `.brand-text`/`.logo-text` left, width/height never stretch or upscale the file, logo CSS free of effects, opacity, server routes and cache headers.
- Screenshots (`docs/orneur/brand/evidence/`): landing, app (sign-in), trust at desktop 1440, tablet 820 and mobile 390, each rendered with `prefers-color-scheme` dark and light in Chromium; every logo image loaded (no broken or missing); layout overflow check at 390 px (a first pass overflowed by 27 px with the wordmark and was fixed by dropping to emblem-only below 400 px).
- `icon-preview-sheet.png`: 16, 32, 180, 192 and 512 px icons.

## 6. Limitations
1. **No vector or transparent original.** Rasters only; small sizes are the founder's own downscales and the 16 px favicon is a soft blur of the emblem (the README warns about this).
2. **Not verified:** Safari/WebKit, a real phone home screen (PWA install), and a real browser favicon-tab refresh. Only Chromium (headless) was available; the manifest, icon links and no-cache favicon route are tested, not observed on a device.
3. Open Graph/Twitter image URLs are root-relative; crawlers generally need an absolute URL, which depends on the deployed hostname (a configuration decision).
4. Wordmark below 400 px viewport width is hidden in the landing/trust navigation (emblem remains) because the lockup did not fit beside the sign-in buttons.
5. CI was not run before this document was written; see the PR for results.
