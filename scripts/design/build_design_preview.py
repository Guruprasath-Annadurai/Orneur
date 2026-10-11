#!/usr/bin/env python3
"""Generate docs/orneur/design/preview/index.html from docs/orneur/design/tokens.json.

The preview is a static, self-contained DESIGN MOCK (no scripts, no network requests, sample content only). Colours are injected from the
tested token file so the mock cannot drift from the accessibility contract. Run: python scripts/design/build_design_preview.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKENS = json.loads((ROOT / "docs/orneur/design/tokens.json").read_text())
OUT = ROOT / "docs/orneur/design/preview/index.html"


def css_vars(theme: str) -> str:
    return "\n".join(f"  --{k.replace('_', '-')}: {v};" for k, v in TOKENS["themes"][theme].items())


def lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


EMBLEM = """<svg class="emblem" viewBox="0 0 48 48" role="img" aria-label="ORNEUR emblem: an abstract falcon in a stoop, built from three facets and four nodes">
  <path d="M6 12 L22 34 L20 18 Z" fill="var(--indigo)"/>
  <path d="M42 12 L26 34 L28 18 Z" fill="var(--indigo)"/>
  <path d="M24 6 L28 18 L24 41 L20 18 Z" fill="var(--emblem-core)"/>
  <g stroke="var(--emblem-line)" stroke-width="1" fill="none"><path d="M6 12 L24 6 L42 12"/><path d="M20 18 L28 18"/></g>
  <g fill="var(--accent-fill)"><circle cx="24" cy="6" r="2.6"/></g>
  <g fill="var(--emblem-node)"><circle cx="6" cy="12" r="2"/><circle cx="42" cy="12" r="2"/><circle cx="24" cy="41" r="2"/></g>
</svg>"""

# ORNEUR with a segmented E: a spine plus three floating bars, each separated by a 2-unit gap.
WORDMARK = """<svg class="wordmark" viewBox="0 0 206 32" role="img" aria-label="ORNEUR">
  <g fill="none" stroke="currentColor" stroke-width="5" stroke-linejoin="bevel" stroke-linecap="butt">
    <rect x="2.5" y="2.5" width="21" height="27" rx="10.5"/>
    <path transform="translate(36 0)" d="M3 29.5V2.5h12a7.5 7.5 0 0 1 0 15H3M13 17.5l9 12"/>
    <path transform="translate(72 0)" d="M3 29.5V2.5l20 27V2.5"/>
    <path transform="translate(144 0)" d="M3 2.5v17a10 10 0 0 0 20 0v-17"/>
    <path transform="translate(180 0)" d="M3 29.5V2.5h12a7.5 7.5 0 0 1 0 15H3M13 17.5l9 12"/>
  </g>
  <g transform="translate(108 0)">
    <rect x="3" y="0" width="5" height="32" fill="currentColor"/>
    <rect x="10" y="0" width="14" height="5.5" fill="var(--accent-fill)"/>
    <rect x="10" y="13.25" width="11" height="5.5" fill="var(--accent-fill)"/>
    <rect x="10" y="26.5" width="14" height="5.5" fill="var(--accent-fill)"/>
  </g>
</svg>"""

ICON = {
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "clip": '<path d="M20 11.5l-7.8 7.8a5 5 0 0 1-7-7L13 4.6a3.3 3.3 0 0 1 4.7 4.7l-7.8 7.8a1.7 1.7 0 0 1-2.4-2.4l7-7"/>',
    "send": '<path d="M12 19V6M6 11l6-6 6 6"/>',
    "stop": '<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
    "retry": '<path d="M4 12a8 8 0 1 0 3-6.2M4 4v4h4"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.2-4.2"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
}


def icon(name: str, label: str) -> str:
    return (f'<button type="button" class="icon-btn" aria-label="{label}"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" '
            f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICON[name]}</svg></button>')


def sidebar(active: bool = True) -> str:
    items = [("Retention terms: Acme MSA vs. v3", True), ("Q4 launch checklist", False), ("Explain the Raft leader election", False),
             ("Draft: vendor security questionnaire", False)]
    lis = "".join(f'<li><a href="#" class="conv{" is-active" if a else ""}"{" aria-current=\'page\'" if a else ""}>{t}</a></li>' for t, a in items)
    return f"""<nav class="sidebar" aria-label="Conversations">
      <div class="brand">{EMBLEM}{WORDMARK}</div>
      <button type="button" class="btn btn-primary btn-block">{ICON['plus'] and ''}New conversation</button>
      <label class="search"><span class="sr-only">Search conversations</span><input type="search" placeholder="Search conversations"></label>
      <p class="group">Today</p><ul>{lis}</ul>
      <div class="sidebar-foot"><span class="avatar" aria-hidden="true">C</span><span>Chief</span>{icon('gear', 'Settings')}</div>
    </nav>"""


CONVERSATION = f"""
<header class="thread-head"><h2 class="thread-title">Retention terms: Acme MSA vs. v3</h2>
  <span class="model-chip" title="No ORNEUR model has been qualified for production yet."><span class="dot" aria-hidden="true"></span>Orneur Novus · experimental · not yet qualified</span></header>
<ol class="messages" aria-label="Conversation">
  <li class="msg user"><div class="bubble"><div class="attach"><span class="file-chip">PDF · msa_acme_v3.pdf</span><span class="file-chip">PDF · msa_acme_v2.pdf</span></div>
    Compare the data-retention terms in these two contracts and flag anything unusual.</div></li>
  <li class="msg assistant"><div class="content">
    <p>Both agreements keep customer data for the life of the contract, but they differ in three places:</p>
    <ul>
      <li><strong>Post-termination retention.</strong> v2 deletes within 30 days; v3 extends this to 90 days <a class="cite" href="#s1" aria-label="Source 1">1</a>.</li>
      <li><strong>Backups.</strong> v3 adds an exception for encrypted backups, with no stated purge date <a class="cite" href="#s2" aria-label="Source 2">2</a>.</li>
      <li><strong>Unusual:</strong> v3 allows use of de-identified data for “service improvement”, which v2 did not <a class="cite" href="#s2" aria-label="Source 2">2</a>.</li>
    </ul>
    <pre class="code" aria-label="Suggested redline"><code>§9.4  Upon termination, Provider shall delete Customer Data within thirty (30) days,
      including backups within ninety (90) days.</code></pre>
    <div class="sources"><a id="s1" class="source" href="#"><span class="n">1</span> msa_acme_v3.pdf · §9.2, p. 14</a><a id="s2" class="source" href="#"><span class="n">2</span> msa_acme_v3.pdf · §9.5–9.6, p. 15</a></div>
    <div class="actions">{icon('copy', 'Copy response')}{icon('retry', 'Regenerate response')}<span class="hint">Sample content. Citations point to your uploaded files.</span></div>
  </div></li>
</ol>
<form class="composer" aria-label="Message composer" onsubmit="return false">
  {icon('clip', 'Attach a file')}
  <label class="sr-only" for="msg-{{id}}">Message</label>
  <textarea id="msg-{{id}}" rows="1" placeholder="Ask anything"></textarea>
  <button type="button" class="send" aria-label="Send message"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">{ICON['send']}</svg></button>
</form>
<p class="fineprint">ORNEUR can be wrong. Check important information against the cited sources.</p>
"""

EMPTY = """
<div class="empty"><div class="empty-mark">""" + EMBLEM + """</div>
  <h2 class="greeting">Hello chief, what's the plan today.</h2>
  <ul class="starters" aria-label="Suggestions">
    <li><button type="button" class="chip">Summarise a document</button></li><li><button type="button" class="chip">Research a question with sources</button></li>
    <li><button type="button" class="chip">Review my code</button></li></ul></div>
<form class="composer" aria-label="Message composer" onsubmit="return false">
  """ + icon("clip", "Attach a file") + """
  <label class="sr-only" for="msg-{id}">Message</label><textarea id="msg-{id}" rows="1" placeholder="Ask anything"></textarea>
  <button type="button" class="send" aria-label="Send message"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">""" + ICON["send"] + """</svg></button>
</form>"""

STREAMING = """
<ol class="messages" aria-label="Conversation"><li class="msg user"><div class="bubble">Find three primary sources on RAFT leader election timing.</div></li>
<li class="msg assistant"><div class="content"><p>Searching and reading sources<span class="caret" aria-hidden="true"></span></p>
<p class="status" role="status">Reading 2 of 5 sources · you can stop at any time</p></div></li></ol>
<form class="composer" aria-label="Message composer" onsubmit="return false">
  <label class="sr-only" for="msg-{id}">Message</label><textarea id="msg-{id}" rows="1" placeholder="Reply, or stop the response"></textarea>
  <button type="button" class="send is-stop" aria-label="Stop generating"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">""" + ICON["stop"] + """</svg></button>
</form>"""

ERROR = """
<ol class="messages" aria-label="Conversation"><li class="msg user"><div class="bubble">Summarise the attached report.</div></li>
<li class="msg assistant"><div class="content"><div class="alert" role="alert"><strong>That response didn't finish.</strong>
<span>The model took too long to answer. Your message and file are saved.</span><div class="alert-actions"><button type="button" class="btn btn-primary">Try again</button><button type="button" class="btn btn-secondary">Dismiss</button></div></div></div></li></ol>"""


def frame(kind: str, theme: str, inner: str, uid: str, mobile: bool = False) -> str:
    inner = inner.replace("{id}", uid)
    label = f"{kind} · {'Light' if theme == 'light' else 'Dark'}"
    if mobile:
        return (f'<figure class="device mobile theme-{theme}"><figcaption>{label}</figcaption><div class="screen"><header class="m-head">{icon("menu", "Open conversations")}'
                f'<span class="m-title">{EMBLEM}</span>{icon("plus", "New conversation")}</header><main class="main">{inner}</main></div></figure>')
    return (f'<figure class="device desktop theme-{theme}"><figcaption>{label}</figcaption><div class="screen">{sidebar()}<main class="main">{inner}</main></div></figure>')


def swatches() -> str:
    out = []
    for theme in ("light", "dark"):
        t = TOKENS["themes"][theme]
        rows = []
        for p in TOKENS["pairs"]:
            if theme == "light" and p["fg"] == "accent_fill":
                continue
            r = ratio(t[p["fg"]], t[p["bg"]])
            rows.append(f'<tr><td><span class="sw" style="background:{t[p["fg"]]}"></span> {p["fg"]} <code>{t[p["fg"]]}</code></td>'
                        f'<td><span class="sw" style="background:{t[p["bg"]]}"></span> {p["bg"]} <code>{t[p["bg"]]}</code></td><td>{p["role"]}</td>'
                        f'<td class="num">{r:.2f}:1</td><td class="num">≥ {p["min"]}</td><td class="{"ok" if r >= p["min"] else "bad"}">{"pass" if r >= p["min"] else "FAIL"}</td></tr>')
        out.append(f'<h3>{theme.capitalize()} theme: measured contrast</h3><div class="table-wrap"><table><thead><tr><th scope="col">Foreground</th><th scope="col">Background</th>'
                   f'<th scope="col">Role</th><th scope="col">Ratio</th><th scope="col">Needs</th><th scope="col">Result</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    return "".join(out)


LIGHT_EXTRA = "  --emblem-core: var(--indigo);\n  --emblem-line: var(--border-strong);\n  --emblem-node: var(--indigo);"
DARK_EXTRA = "  --emblem-core: #9FB0D1;\n  --emblem-line: var(--border-strong);\n  --emblem-node: #9FB0D1;"

PAGE_CSS = """
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;background:#F6F4F0;color:#141821}
@media (prefers-color-scheme:dark){body.review{background:#0E1116;color:#E8E4DE}}
.review{padding:0 16px 64px}.wrap{max-width:1280px;margin:0 auto}
.banner{background:#141821;color:#E8E4DE;padding:12px 16px;font-size:14px}.banner strong{color:#FF8A78}
h1{font-size:28px;line-height:1.2;margin:32px 0 8px}h2{font-size:20px;margin:40px 0 12px}h3{font-size:16px;margin:24px 0 8px}
.lede{max-width:70ch;color:inherit;opacity:.85}
.grid{display:grid;gap:24px}.grid.two{grid-template-columns:repeat(auto-fit,minmax(min(100%,560px),1fr))}.grid.mob{grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));justify-items:center}
figure.device{margin:0}figcaption{font-size:13px;font-weight:600;margin:0 0 8px;opacity:.8}
.screen{border:1px solid var(--border-strong);border-radius:16px;overflow:hidden;background:var(--page);color:var(--text);display:flex;min-height:640px}
.mobile .screen{flex-direction:column;width:min(100%,340px);min-height:620px}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
/* ---- product chrome (scoped to the two official themes) ---- */
.sidebar{width:248px;flex:none;background:var(--sidebar);padding:16px;display:flex;flex-direction:column;gap:12px;border-right:1px solid var(--border)}
.sidebar ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:minmax(0,1fr);gap:2px}.group{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--text-secondary);margin:8px 0 0}
.brand{display:flex;align-items:center;gap:10px;color:var(--text)}.brand .emblem{width:30px;height:30px}.brand .wordmark{height:16px;width:auto;color:var(--text)}
.conv{display:block;padding:9px 10px;border-radius:8px;color:var(--text);text-decoration:none;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.conv:hover{background:color-mix(in srgb,var(--text) 7%,transparent)}.conv.is-active{background:var(--surface);box-shadow:inset 3px 0 0 var(--accent-fill)}
.search input{width:100%;padding:9px 10px;border-radius:8px;border:1px solid var(--border-strong);background:var(--surface);color:var(--text);font:inherit;font-size:14px}
.sidebar-foot{margin-top:auto;display:flex;align-items:center;gap:10px;font-size:14px}.sidebar-foot .icon-btn{margin-left:auto}
.avatar{width:28px;height:28px;border-radius:50%;background:var(--indigo);color:var(--on-indigo);display:grid;place-items:center;font-size:13px;font-weight:600}
.main{flex:1;min-width:0;display:flex;flex-direction:column;padding:16px 20px;gap:12px}
.mobile .main{padding:12px 14px}.m-head{display:flex;align-items:center;justify-content:space-between;padding:8px 8px;border-bottom:1px solid var(--border);background:var(--page)}
.m-title .emblem{width:28px;height:28px;display:block}
.thread-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:space-between}.thread-title{font-size:16px;margin:0}
.model-chip{display:inline-flex;align-items:center;gap:8px;font-size:12px;padding:5px 10px;border-radius:999px;border:1px solid var(--border-strong);background:var(--surface);color:var(--experimental)}
.model-chip .dot{width:8px;height:8px;border-radius:50%;background:var(--experimental)}
.messages{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:minmax(0,1fr);gap:18px;flex:1;align-content:start;overflow:auto;max-width:760px;width:100%;margin-inline:auto}
.msg{min-width:0}.msg.user{display:flex;justify-content:flex-end}.bubble{background:var(--indigo);color:var(--on-indigo);padding:11px 14px;border-radius:16px 16px 4px 16px;max-width:88%;font-size:15px}
.attach{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.file-chip{font-size:12px;padding:3px 8px;border-radius:6px;background:color-mix(in srgb,var(--on-indigo) 16%,transparent)}
.content{font-size:15px}.content p{margin:0 0 10px}.content ul{margin:0 0 12px;padding-left:20px}.content li{margin:4px 0}
a.cite{display:inline-grid;place-items:center;min-width:20px;height:20px;padding:0 5px;border-radius:6px;background:var(--raised);border:1px solid var(--border-strong);color:var(--accent-text);font-size:12px;font-weight:700;text-decoration:none;vertical-align:1px}
pre.code{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%;margin:0 0 12px;padding:12px 14px;background:var(--code-bg);color:var(--code-text);border-radius:10px;border:1px solid var(--border);overflow:auto;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.sources{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}.source{display:inline-flex;gap:8px;align-items:center;font-size:13px;padding:6px 10px;border-radius:8px;background:var(--surface);border:1px solid var(--border);color:var(--text);text-decoration:none}
.source .n{display:grid;place-items:center;width:18px;height:18px;border-radius:5px;background:var(--indigo);color:var(--on-indigo);font-size:11px;font-weight:700}
.actions{display:flex;align-items:center;gap:4px;color:var(--text-secondary)}.hint{font-size:12px;margin-left:8px}
.icon-btn{width:44px;height:44px;display:inline-grid;place-items:center;border:0;background:transparent;color:inherit;border-radius:10px;cursor:pointer}.icon-btn svg{width:20px;height:20px}
.icon-btn:hover{background:color-mix(in srgb,var(--text) 8%,transparent)}
.composer{display:flex;align-items:flex-end;gap:4px;max-width:760px;width:100%;margin-inline:auto;padding:6px 8px;border-radius:16px;background:var(--surface);border:1px solid var(--border-strong);color:var(--text-secondary)}
.composer textarea{flex:1;border:0;outline:0;background:transparent;color:var(--text);font:inherit;font-size:15px;resize:none;padding:11px 6px;min-height:44px}
.composer textarea::placeholder{color:var(--text-secondary)}
.send{width:44px;height:44px;border-radius:12px;border:0;background:var(--accent-fill);color:var(--on-accent);display:grid;place-items:center;cursor:pointer}.send svg{width:22px;height:22px}
.send.is-stop{background:var(--text);color:var(--page)}
.fineprint{margin:0;text-align:center;font-size:12px;color:var(--text-secondary)}
.btn{font:inherit;font-size:14px;font-weight:600;padding:10px 14px;min-height:44px;border-radius:10px;border:1px solid transparent;cursor:pointer}
.btn-primary{background:var(--accent-fill);color:var(--on-accent)}.btn-secondary{background:transparent;color:var(--text);border-color:var(--border-strong)}.btn-block{width:100%}
button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.empty{flex:1;display:grid;place-content:center;justify-items:center;gap:18px;text-align:center;padding:24px 8px}.empty-mark .emblem{width:64px;height:64px}
.greeting{font-size:28px;line-height:1.2;margin:0;font-weight:650;letter-spacing:-.01em}.mobile .greeting{font-size:23px}
.starters{list-style:none;padding:0;margin:0;display:flex;gap:8px;flex-wrap:wrap;justify-content:center}
.chip{font:inherit;font-size:14px;padding:9px 14px;min-height:44px;border-radius:999px;border:1px solid var(--border-strong);background:var(--surface);color:var(--text);cursor:pointer}
.caret{display:inline-block;width:8px;height:1.1em;margin-left:3px;background:var(--accent-fill);vertical-align:text-bottom;animation:blink 1.1s steps(2,start) infinite}
@keyframes blink{to{visibility:hidden}}@media (prefers-reduced-motion:reduce){.caret{animation:none}}
.status{font-size:13px;color:var(--text-secondary)}
.alert{border:1px solid var(--danger);border-radius:12px;padding:14px;display:grid;gap:8px;background:var(--surface)}.alert strong{color:var(--danger)}.alert-actions{display:flex;gap:8px;flex-wrap:wrap}
@media (max-width:760px){.desktop .sidebar{display:none}}
/* ---- review page tables ---- */
.table-wrap{overflow:auto}table{border-collapse:collapse;font-size:13px;width:100%;min-width:640px}th,td{text-align:left;padding:6px 10px;border-bottom:1px solid rgba(127,127,127,.3)}
.num{font-variant-numeric:tabular-nums}.sw{display:inline-block;width:14px;height:14px;border-radius:3px;border:1px solid rgba(127,127,127,.6);vertical-align:-2px}
.ok{color:#2F6F52;font-weight:700}.bad{color:#B03626;font-weight:700}code{font-size:12px}
@media (prefers-color-scheme:dark){.ok{color:#6FC39A}.bad{color:#FF8A78}}
"""


def build() -> str:
    uid = iter(range(1, 100))
    light = ":root{}\n.theme-light{\n" + css_vars("light") + "\n" + LIGHT_EXTRA + "\n}\n.theme-dark{\n" + css_vars("dark") + "\n" + DARK_EXTRA + "\n}"
    desk = ""
    for theme in ("light", "dark"):
        desk += frame("Desktop · conversation", theme, CONVERSATION.replace("{id}", f"d{next(uid)}"), f"d{next(uid)}")
    states = ""
    for theme in ("light", "dark"):
        states += frame("Desktop · streaming with stop", theme, STREAMING, f"s{next(uid)}")
    mob = ""
    for theme in ("light", "dark"):
        mob += frame("Mobile · first run (greeting)", theme, EMPTY, f"m{next(uid)}", mobile=True)
    for theme in ("light", "dark"):
        mob += frame("Mobile · recoverable error", theme, ERROR, f"e{next(uid)}", mobile=True)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ORNEUR design mock — Light and Dark</title>
<meta name="description" content="Static design mock for founder review. Sample content only; not a working interface.">
<style>{light}{PAGE_CSS}</style></head>
<body class="review"><div class="banner" role="note"><strong>Design mock for founder review.</strong> Sample content only. Nothing here is connected to a model or backend, and no model shown
is qualified for production. Generated from <code>docs/orneur/design/tokens.json</code>.</div>
<div class="wrap"><h1>ORNEUR — conversation screens, Light and Dark</h1>
<p class="lede">Two official themes, the locked palette, and an interface that stays out of the way. The honest model label, citations you can open, and a visible stop control
are part of the design, not afterthoughts. Specification: <code>docs/orneur/design/ORNEUR_UI_DESIGN_SPEC.md</code>.</p>
<h2>Desktop: a finished answer with citations</h2><div class="grid two">{desk}</div>
<h2>Desktop: a response in progress (stop is always one click)</h2><div class="grid two">{states}</div>
<h2>Mobile: first run and error recovery</h2><div class="grid mob">{mob}</div>
<h2>Measured contrast (WCAG 2.2 AA)</h2><p class="lede">Every pair below is recomputed by <code>tests/test_design_tokens_contrast.py</code>. The raw brand colours are used for fills and accents;
text uses derived variants where the raw colour fails.</p>{swatches()}
</div></body></html>"""


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
