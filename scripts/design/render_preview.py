#!/usr/bin/env python3
"""Render docs/orneur/design/preview/index.html to PNGs and audit what actually rendered.

Needs the `playwright` package and a Chromium (PLAYWRIGHT_BROWSERS_PATH, or /opt/pw-browsers); it never downloads a browser. Run after
`python scripts/design/build_design_preview.py`:

    python scripts/design/render_preview.py

For every themed figure it writes <id>.png beside the preview and then checks, from the browser's COMPUTED styles (not from the tokens):
  * WCAG contrast of every visible text node against its effective background (4.5:1; 3:1 for text >= 24 px or >= 18.66 px bold);
  * horizontal overflow of the page at a 375 px viewport (responsiveness);
  * text clipped inside overflow:hidden boxes.
Exit status is non-zero if any check fails; the report is written to RENDER_AUDIT.txt.
"""
from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PREVIEW = ROOT / "docs/orneur/design/preview/index.html"
OUT = PREVIEW.parent

AUDIT_JS = r"""
() => {
  const parse = (c) => {
    let m = c.match(/rgba?\(([^)]+)\)/);
    if (m) { const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    m = c.match(/color\(srgb ([^)]+)\)/);
    if (m) { const p = m[1].split(/[ \/]+/).filter(Boolean).map(Number); return [p[0]*255, p[1]*255, p[2]*255, p.length > 3 ? p[3] : 1]; }
    return null;
  };
  const over = (top, bottom) => { const a = top[3]; return [0,1,2].map(i => top[i]*a + bottom[i]*(1-a)).concat([1]); };
  const lum = (c) => { const f = v => { v/=255; return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055, 2.4); }; return .2126*f(c[0]) + .7152*f(c[1]) + .0722*f(c[2]); };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05); };
  const bgOf = (el) => {
    const stack = [];
    for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c[3] > 0) { stack.push(c); if (c[3] >= 1) break; } }
    let base = [255,255,255,1];
    for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base);
    return base;
  };
  const failures = [], seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode, text = n.textContent.trim();
    if (!text) continue;
    const el = n.parentElement;
    if (!el || !el.closest('.theme-light, .theme-dark')) continue;       // only the product mock, not the review page chrome
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) continue;
    if (el.closest('.sr-only')) continue;
    let fg = parse(cs.color); if (!fg) continue;
    const bg = bgOf(el); fg = over([fg[0], fg[1], fg[2], fg[3] * (parseFloat(cs.opacity) || 1)], bg);
    const px = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const need = (px >= 24 || (px >= 18.66 && bold)) ? 3 : 4.5;
    const dis = el.closest('textarea:disabled, button:disabled'); if (dis) continue;      // disabled controls are exempt (WCAG 1.4.3)
    const ph = el.tagName === 'TEXTAREA';
    const got = ratio(fg, bg);
    if (got < need) {
      const key = (el.className || el.tagName) + '|' + text.slice(0, 24) + '|' + got.toFixed(2);
      if (!seen.has(key)) { seen.add(key); failures.push(`${el.closest('figure')?.id || '?'} :: "${text.slice(0, 40)}" ${got.toFixed(2)}:1 (needs ${need}) <${el.tagName.toLowerCase()} class="${el.className}">`); }
    }
  }
  return failures;
}
"""

OVERFLOW_JS = r"""
() => {
  const out = [];
  const w = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > w + 1) out.push(`PAGE scrolls horizontally: ${document.documentElement.scrollWidth}px > ${w}px`);
  for (const el of document.querySelectorAll('.theme-light *, .theme-dark *')) {
    if (el.closest('.sr-only') || el.closest('table')) continue;
    const cs = getComputedStyle(el);
    if (!['hidden', 'clip'].includes(cs.overflowX)) continue;
    if (cs.textOverflow === 'ellipsis') continue;                                  // deliberate, announced truncation (long titles)
    if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) out.push(`${el.closest('figure')?.id || '?'} :: clipped <${el.tagName.toLowerCase()} class="${el.className}"> ${el.scrollWidth}>${el.clientWidth}`);
  }
  return out;
}
"""


def chromium_path() -> str | None:
    for pattern in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome", "/opt/pw-browsers/chromium/chrome-linux/chrome"):
        found = sorted(glob.glob(pattern))
        if found:
            return found[-1]
    return None


def main() -> int:
    report: list[str] = []
    bad = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium_path(), args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=1)
        page.emulate_media(reduced_motion="reduce")                                  # static frames: no blink/pulse in screenshots
        page.goto(PREVIEW.as_uri())
        ids = page.eval_on_selector_all("figure[id]", "els => els.map(e => e.id)")
        for fid in ids:
            page.locator(f"#{fid}").screenshot(path=str(OUT / f"{fid}.png"))
        report.append(f"rendered {len(ids)} figures")
        fails = page.evaluate(AUDIT_JS)
        report += [f"CONTRAST {f}" for f in fails]
        bad += len(fails)
        page.set_viewport_size({"width": 375, "height": 900})
        page.goto(PREVIEW.as_uri())
        over = page.evaluate(OVERFLOW_JS)
        report += [f"OVERFLOW@375 {o}" for o in over]
        bad += len(over)
        page.set_viewport_size({"width": 1400, "height": 1000})
        page.goto(PREVIEW.as_uri())
        over = page.evaluate(OVERFLOW_JS)
        report += [f"OVERFLOW@1400 {o}" for o in over]
        bad += len(over)
        browser.close()
    report.append("RESULT: " + ("PASS" if bad == 0 else f"FAIL ({bad} findings)"))
    (OUT / "RENDER_AUDIT.txt").write_text("\n".join(report) + "\n")
    print("\n".join(report))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
