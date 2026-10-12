#!/usr/bin/env python3
"""Generate docs/orneur/design/preview/index.html from docs/orneur/design/tokens.json.

The preview is a static, self-contained DESIGN MOCK (no scripts, no network requests, sample content only). Colours are injected from the
tested token file so the mock cannot drift from the accessibility contract. Run: python scripts/design/build_design_preview.py
"""
from __future__ import annotations

import json
import re
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
    def _item(t: str, a: bool) -> str:
        cls = "conv is-active" if a else "conv"
        cur = " aria-current='page'" if a else ""
        return f'<li><a href="#" class="{cls}"{cur}>{t}</a></li>'

    lis = "".join(_item(t, a) for t, a in items)
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


def slug(text: str) -> str:
    return re.sub(r"-+", "-", "".join(c if c.isalnum() else "-" for c in text.lower())).strip("-")


def frame(kind: str, theme: str, inner: str, uid: str, mobile: bool = False) -> str:
    inner = inner.replace("{id}", uid)
    label = f"{kind} · {'Light' if theme == 'light' else 'Dark'}"
    fid = slug(label)
    if mobile:
        return (f'<figure id="{fid}" class="device mobile theme-{theme}"><figcaption>{label}</figcaption><div class="screen"><header class="m-head">{icon("menu", "Open conversations")}'
                f'<span class="m-title">{EMBLEM}</span>{icon("plus", "New conversation")}</header><main class="main">{inner}</main></div></figure>')
    return (f'<figure id="{fid}" class="device desktop theme-{theme}"><figcaption>{label}</figcaption><div class="screen">{sidebar()}<main class="main">{inner}</main></div></figure>')


def panel(title: str, theme: str, inner: str) -> str:
    """A themed review panel (no app chrome) for component-state sheets."""
    return (f'<figure id="{slug(title)}-{theme}" class="panel-fig theme-{theme}"><figcaption>{title} · {"Light" if theme == "light" else "Dark"}</figcaption>'
            f'<div class="panel">{inner}</div></figure>')


MOBILE_CONVERSATION = f"""
<ol class="messages" aria-label="Conversation">
  <li class="msg user"><div class="bubble"><div class="attach"><span class="file-chip">PDF · msa_acme_v3.pdf</span></div>What changed in the data-retention terms?</div></li>
  <li class="msg assistant"><div class="content">
    <p>Post-termination retention grew from 30 to 90 days <a class="cite" href="#m1" aria-label="Source 1">1</a>, and v3 adds a de-identified-data clause <a class="cite" href="#m2" aria-label="Source 2">2</a>.</p>
    <div class="sources"><a id="m1" class="source" href="#"><span class="n">1</span> msa_acme_v3.pdf · p. 14</a><a id="m2" class="source" href="#"><span class="n">2</span> msa_acme_v3.pdf · p. 15</a></div>
    <div class="actions">{icon('copy', 'Copy response')}{icon('retry', 'Regenerate response')}</div>
  </div></li>
</ol>
<form class="composer" aria-label="Message composer" onsubmit="return false">
  {icon('clip', 'Attach a file')}
  <label class="sr-only" for="msg-{{id}}">Message</label><textarea id="msg-{{id}}" rows="1" placeholder="Ask anything"></textarea>
  <button type="button" class="send" aria-label="Send message"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">{ICON['send']}</svg></button>
</form>"""

_SVG_SEND = ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
             + ICON["send"] + "</svg>")
_SVG_STOP = ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
             + ICON["stop"] + "</svg>")


def composer(uid: str, state: str, text: str = "", placeholder: str = "Ask anything", chips: str = "", cls: str = "") -> str:
    if state == "stop":
        send = '<button type="button" class="send is-stop" aria-label="Stop generating">' + _SVG_STOP + "</button>"
    else:
        off = " disabled" if state in ("empty", "disabled") else ""
        send = '<button type="button" class="send" aria-label="Send message"' + off + ">" + _SVG_SEND + "</button>"
    dis = " disabled" if state == "disabled" else ""
    return ('<form class="composer ' + cls + '" aria-label="Message composer" onsubmit="return false">' + chips + icon("clip", "Attach a file")
            + '<label class="sr-only" for="msg-' + uid + '">Message</label><textarea id="msg-' + uid + '" rows="1" placeholder="' + placeholder + '"' + dis + ">"
            + text + "</textarea>" + send + "</form>")


_FILE_STATUS = {
    "uploading": ("Uploading… 62%", 62), "reading": ("Reading pages… 14 of 40", 35), "ready": ("Ready · searchable", None),
    "failed": ("Upload failed. Your message is saved.", None), "toolarge": ("Too large: the limit is 20 MB.", None), "unsupported": ("This file type isn't supported.", None),
}


def file_card(name: str, meta: str, state: str, action: str = "") -> str:
    msg, pct = _FILE_STATUS[state]
    bar = ""
    if pct is not None:
        bar = ('<div class="progress" role="progressbar" aria-label="' + ("Uploading" if state == "uploading" else "Reading document")
               + '" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + str(pct) + '"><span style="width:' + str(pct) + '%"></span></div>')
    bad = state in ("failed", "toolarge", "unsupported")
    alert = ' role="alert"' if bad else ""
    btn = '<button type="button" class="btn btn-secondary btn-sm">' + action + "</button>" if action else ""
    return ('<div class="filecard' + (" is-bad" if bad else "") + '"><span class="ftype" aria-hidden="true">' + name.rsplit(".", 1)[-1].upper()[:4] + "</span>"
            + '<div class="fbody"><div class="fname">' + name + '</div><div class="fmeta"' + alert + ">" + meta + " · " + msg + "</div>" + bar + "</div>" + btn + "</div>")


def composer_states(theme: str, uid) -> str:
    files = '<div class="composer-files">' + file_card("msa_v3.pdf", "2.1 MB", "uploading", "Cancel") + file_card("msa_v2.pdf", "1.8 MB", "ready", "Remove") + "</div>"
    rows = [
        ("Default (empty: send is disabled)", composer(f"c{next(uid)}", "empty")),
        ("Focused (3 px ring)", composer(f"c{next(uid)}", "ready", cls="is-focus", text="Draft a polite reply to the vendor")),
        ("With text (send is the single coral action)", composer(f"c{next(uid)}", "ready", text="Summarise the attached report in five bullets")),
        ("With attachments (uploading, ready)", composer(f"c{next(uid)}", "ready", text="Compare these", chips=files)),
        ("Streaming (stop replaces send)", composer(f"c{next(uid)}", "stop", placeholder="Reply, or stop the response")),
        ("Unavailable (read-only until reconnected)", composer(f"c{next(uid)}", "disabled", placeholder="You're offline. Your draft is kept.")),
    ]
    return "".join('<p class="state-label">' + t + "</p>" + c for t, c in rows)


SB_ITEMS = ["Retention terms: Acme MSA vs. v3", "Q4 launch checklist", "Explain the Raft leader election", "Draft: vendor security questionnaire"]


def sidebar_variant(label: str, items: list, *, search: str = "", hover: int = -1, focus: int = -1, active: int = 0, menu: int = -1, rename: int = -1,
                    empty: bool = False, confirm: int = -1) -> str:
    lis = []
    for i, t in enumerate(items):
        cls = "conv" + (" is-active" if i == active else "") + (" is-hover" if i == hover else "") + (" is-focus" if i == focus else "")
        cur = " aria-current='page'" if i == active else ""
        if i == rename:
            lis.append('<li><label class="sr-only" for="rn-' + slug(label) + '">Rename conversation</label><input id="rn-' + slug(label) + '" class="rename" value="' + t + '"></li>')
            continue
        if i == confirm:
            lis.append('<li class="confirm" role="alert"><span>Delete “' + t + '”?</span><span class="alert-actions"><button type="button" class="btn btn-sm danger">Delete</button>'
                       '<button type="button" class="btn btn-secondary btn-sm">Keep</button></span></li>')
            continue
        body = t
        if search and search.lower() in t.lower():
            a = t.lower().index(search.lower())
            body = t[:a] + "<mark>" + t[a:a + len(search)] + "</mark>" + t[a + len(search):]
        if search and search.lower() not in t.lower():
            continue
        lis.append('<li class="row"><a href="#" class="' + cls + '"' + cur + ">" + body + "</a></li>")
        if i == menu:
            lis.append('<li><ul class="menu" role="menu" aria-label="Conversation actions"><li role="none"><button role="menuitem" type="button">Rename</button></li>'
                       '<li role="none"><button role="menuitem" type="button">Export as Markdown</button></li>'
                       '<li role="none"><button role="menuitem" type="button" class="danger-text">Delete…</button></li></ul></li>')
    body = '<p class="empty-hist">No conversations yet.<br>Your chats will appear here.</p>' if empty else "<ul>" + "".join(lis) + "</ul>"
    return ('<nav class="sidebar static" aria-label="' + label + '"><div class="brand">' + EMBLEM + WORDMARK + "</div>"
            '<label class="search"><span class="sr-only">Search conversations</span><input type="search" placeholder="Search conversations" value="' + search + '"></label>'
            '<p class="group">' + label + "</p>" + body + "</nav>")


def sidebar_states(theme: str) -> str:
    cells = [
        sidebar_variant("Default · hover · focus", SB_ITEMS, hover=1, focus=2),
        sidebar_variant("Search results", SB_ITEMS, search="raft", active=-1),
        sidebar_variant("Row menu open", SB_ITEMS, menu=1, active=0),
        sidebar_variant("Renaming", SB_ITEMS, rename=1),
        sidebar_variant("Confirm delete", SB_ITEMS, confirm=1),
        sidebar_variant("Empty history", [], empty=True),
    ]
    return '<div class="state-grid sidebars">' + "".join(cells) + "</div>"


def code_and_files(theme: str) -> str:
    code = ('<div class="codeblock"><div class="codehead"><span class="lang">python</span><span class="spacer"></span>' + icon("copy", "Copy code")
            + '<button type="button" class="btn btn-secondary btn-sm" aria-pressed="true">Wrap lines</button></div>'
            '<pre class="code" aria-label="Code example"><code>def retention_days(contract: dict, *, include_backups: bool = False) -> int:\n'
            '    """Days customer data may be kept after termination; backups only when asked."""\n'
            '    base = contract["termination"]["delete_within_days"]\n'
            '    return base + (contract["backups"]["purge_days"] if include_backups else 0)</code></pre></div>'
            '<p class="state-label">A long unbroken line wraps instead of scrolling the page:</p>'
            '<pre class="code" aria-label="Long line example"><code>curl --fail --silent --show-error https://api.example.com/v1/documents/00000000-0000-0000-0000-000000000000/export?format=markdown&amp;include=citations</code></pre>')
    files = "".join([
        file_card("msa_acme_v3.pdf", "2.1 MB", "uploading", "Cancel"), file_card("board_deck.pptx", "8.4 MB", "reading", "Cancel"),
        file_card("notes.md", "12 KB", "ready", "Remove"), file_card("scan_final.pdf", "31 MB", "toolarge", "Choose another"),
        file_card("archive.zip", "4.2 MB", "unsupported", "Remove"), file_card("contract_v2.pdf", "1.8 MB", "failed", "Try again"),
    ])
    return '<h3 class="sheet-h">Code block</h3>' + code + '<h3 class="sheet-h">File attachment states</h3><div class="filestack">' + files + "</div>"


def system_states(theme: str, uid) -> str:
    loading = ('<ol class="messages" aria-label="Conversation"><li class="msg user"><div class="bubble">Summarise the attached report.</div></li>'
               '<li class="msg assistant"><div class="content"><div class="skeleton" aria-hidden="true"><span class="sk" style="width:92%"></span><span class="sk" style="width:78%"></span>'
               '<span class="sk" style="width:55%"></span></div><p class="status" role="status">Thinking… <button type="button" class="linklike">Stop</button></p></div></li></ol>')
    unavailable = ('<div class="notice warn" role="alert"><div><h4>This model isn\'t available right now.</h4>'
                   '<p>It isn\'t open for public use at the moment. Choose another model or try again later. Your message is saved.</p></div>'
                   '<button type="button" class="btn btn-secondary btn-sm">Choose a model</button></div>')
    signed_out = ('<div class="notice" role="alert"><div><h4>You were signed out.</h4><p>Sign in to continue. Your draft is kept on this device.</p></div>'
                  '<button type="button" class="btn btn-primary btn-sm">Sign in</button></div>')
    limit = ('<div class="notice" role="status"><div><h4>You\'ve reached today\'s message limit.</h4><p>It resets at 00:00 UTC. You can still read and export your conversations.</p></div>'
             '<button type="button" class="btn btn-secondary btn-sm">See plans</button></div>')
    offline = '<div class="notice" role="status"><div><h4>You\'re offline.</h4><p>Your draft is kept. You can send again when the connection returns.</p></div></div>'
    recover = ('<div class="alert" role="alert"><strong>That response didn\'t finish.</strong><span>The model took too long to answer. Your message and file are saved.</span>'
               '<div class="alert-actions"><button type="button" class="btn btn-primary btn-sm">Try again</button><button type="button" class="btn btn-secondary btn-sm">Dismiss</button></div></div>')
    empty = '<div class="empty small"><div class="empty-mark">' + EMBLEM + "</div><h2 class=\"greeting\">Hello chief, what's the plan today.</h2></div>"
    cells = [("Loading a response (skeleton; stop stays available)", loading), ("Model unavailable (API code model_unavailable)", unavailable),
             ("Session ended (password changed or token expired)", signed_out), ("Usage limit reached", limit), ("Offline", offline),
             ("Recoverable error", recover), ("Empty / first run", empty)]
    return '<div class="state-grid">' + "".join('<div><p class="state-label">' + t + "</p>" + c + "</div>" for t, c in cells) + "</div>"


def brand_sheet(theme: str) -> str:
    ladder = "".join('<span class="lad" style="--s:' + str(n) + 'px">' + EMBLEM + "<small>" + str(n) + "px</small></span>" for n in (16, 24, 32, 48, 64, 96))
    return ('<div class="brand-big"><div class="bigmark">' + EMBLEM + '</div><div class="bigword">' + WORDMARK + "</div></div>"
            '<p class="state-label">Emblem at small sizes (legibility check)</p><div class="ladder">' + ladder + "</div>")



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
/* ---- component-state sheets ---- */
.panel-fig{margin:0}.panel{border:1px solid var(--border-strong);border-radius:16px;padding:20px;background:var(--page);color:var(--text);display:grid;gap:12px;align-content:start}
.state-label{font-size:12px;letter-spacing:.02em;color:var(--text-secondary);margin:6px 0 0}.sheet-h{margin:6px 0 0;font-size:14px}
.state-grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr))}
.sidebar.static{width:auto;border:1px solid var(--border);border-radius:12px;min-height:0}
.conv.is-hover{background:color-mix(in srgb,var(--text) 7%,transparent)}.conv.is-focus{outline:3px solid var(--focus);outline-offset:-1px}
mark{background:color-mix(in srgb,var(--accent-fill) 35%,transparent);color:inherit;border-radius:3px;padding:0 1px}
.rename{width:100%;padding:9px 10px;border-radius:8px;border:2px solid var(--focus);background:var(--surface);color:var(--text);font:inherit;font-size:14px}
.menu{list-style:none;margin:2px 0 6px 10px;padding:6px;border:1px solid var(--border-strong);border-radius:10px;background:var(--raised);display:grid;gap:2px}
.menu button{width:100%;text-align:left;font:inherit;font-size:14px;padding:9px 10px;min-height:40px;border:0;border-radius:6px;background:transparent;color:var(--text);cursor:pointer}
.menu button:hover{background:color-mix(in srgb,var(--text) 8%,transparent)}.danger-text{color:var(--danger)!important}
.confirm{display:grid;gap:8px;padding:10px;border:1px solid var(--danger);border-radius:10px;font-size:14px;background:var(--surface)}
.btn-sm{min-height:36px;padding:6px 12px;font-size:13px}.btn.danger{background:transparent;color:var(--danger);border:1px solid var(--danger)}
.empty-hist{color:var(--text-secondary);font-size:14px;margin:8px 4px;line-height:1.5}
.composer.is-focus{outline:3px solid var(--focus);outline-offset:2px}.composer .send:disabled{opacity:.45;cursor:not-allowed}.composer textarea:disabled{cursor:not-allowed;opacity:.7}
.composer{flex-wrap:wrap}.composer-files{flex:0 0 100%;display:grid;gap:8px;padding:6px 4px 2px}
.filestack{display:grid;gap:10px}.filecard{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid var(--border-strong);border-radius:12px;background:var(--surface);font-size:13px}
.filecard.is-bad{border-color:var(--danger)}.ftype{flex:none;width:36px;height:36px;border-radius:8px;display:grid;place-items:center;background:var(--indigo);color:var(--on-indigo);font-size:10px;font-weight:700}
.fbody{flex:1;min-width:0}.fname{font-weight:600;overflow-wrap:anywhere}.fmeta{color:var(--text-secondary);font-size:12px;overflow-wrap:anywhere}.is-bad .fmeta{color:var(--danger)}
.progress{height:4px;border-radius:2px;background:color-mix(in srgb,var(--text) 14%,transparent);margin-top:6px;overflow:hidden}.progress span{display:block;height:100%;background:var(--accent-fill)}
.codeblock{border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--code-bg)}.codehead{display:flex;align-items:center;gap:6px;padding:2px 8px 2px 12px;border-bottom:1px solid var(--border);color:var(--text-secondary);font-size:12px}
.codeblock .code{margin:0;border:0;border-radius:0}.lang{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.spacer{flex:1}
.skeleton{display:grid;gap:10px;margin:4px 0 10px}.sk{display:block;height:12px;border-radius:6px;background:color-mix(in srgb,var(--text) 12%,transparent);animation:pulse 1.4s ease-in-out infinite}
@keyframes pulse{50%{opacity:.45}}@media (prefers-reduced-motion:reduce){.sk{animation:none}}
.linklike{font:inherit;background:none;border:0;padding:0;color:var(--accent-text);text-decoration:underline;cursor:pointer;min-height:24px}
.notice{border:1px solid var(--border-strong);border-radius:12px;padding:12px 14px;display:flex;gap:12px;align-items:center;justify-content:space-between;background:var(--surface);flex-wrap:wrap}
.notice.warn{border-color:var(--experimental)}.notice h4{margin:0 0 2px;font-size:14px}.notice p{margin:0;font-size:13px;color:var(--text-secondary)}
.empty.small{padding:16px 8px}.empty.small .emblem{width:44px;height:44px}.empty.small .greeting{font-size:20px}
.brand-big{display:grid;gap:28px;justify-items:start;padding:8px 0}.bigmark .emblem{width:240px;height:240px}.bigword .wordmark{width:min(100%,560px);height:auto;color:var(--text)}
.ladder{display:flex;align-items:flex-end;gap:24px;flex-wrap:wrap}.lad{display:grid;gap:4px;justify-items:center;color:var(--text-secondary)}.lad .emblem{width:var(--s);height:var(--s)}.lad small{font-size:11px}
.pkg{display:grid;gap:8px;padding:0;margin:0;list-style:none;counter-reset:p}.pkg li{counter-increment:p;display:flex;gap:10px;align-items:baseline}
.pkg li::before{content:counter(p);flex:none;width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700;background:#3A4B6B;color:#fff}
.decision{border:1px solid rgba(127,127,127,.45);border-radius:12px;padding:16px;margin:16px 0;display:grid;gap:6px}.decision h3{margin:0}.decision ul{margin:0;padding-left:20px}
/* ---- review page tables ---- */
.table-wrap{overflow:auto}table{border-collapse:collapse;font-size:13px;width:100%;min-width:640px}th,td{text-align:left;padding:6px 10px;border-bottom:1px solid rgba(127,127,127,.3)}
.num{font-variant-numeric:tabular-nums}.sw{display:inline-block;width:14px;height:14px;border-radius:3px;border:1px solid rgba(127,127,127,.6);vertical-align:-2px}
.ok{color:#2F6F52;font-weight:700}.bad{color:#B03626;font-weight:700}code{font-size:12px}
@media (prefers-color-scheme:dark){.ok{color:#6FC39A}.bad{color:#FF8A78}}
"""


def build() -> str:
    uid = iter(range(1, 400))
    light = ":root{}\n.theme-light{\n" + css_vars("light") + "\n" + LIGHT_EXTRA + "\n}\n.theme-dark{\n" + css_vars("dark") + "\n" + DARK_EXTRA + "\n}"
    themes = ("light", "dark")
    desk = "".join(frame("Desktop · conversation", t, CONVERSATION.replace("{id}", f"d{next(uid)}"), f"d{next(uid)}") for t in themes)
    states = "".join(frame("Desktop · streaming with stop", t, STREAMING, f"s{next(uid)}") for t in themes)
    mobconv = "".join(frame("Mobile · conversation", t, MOBILE_CONVERSATION, f"mc{next(uid)}", mobile=True) for t in themes)
    mob = "".join(frame("Mobile · first run (greeting)", t, EMPTY, f"m{next(uid)}", mobile=True) for t in themes)
    mob += "".join(frame("Mobile · recoverable error", t, ERROR, f"e{next(uid)}", mobile=True) for t in themes)
    brand = "".join(panel("Brand · emblem and wordmark", t, brand_sheet(t)) for t in themes)
    composers = "".join(panel("Composer states", t, composer_states(t, uid)) for t in themes)
    sidebars = "".join(panel("Sidebar and history", t, sidebar_states(t)) for t in themes)
    codefiles = "".join(panel("Code and attachments", t, code_and_files(t)) for t in themes)
    system = "".join(panel("System states", t, system_states(t, uid)) for t in themes)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ORNEUR design mock — Light and Dark</title>
<meta name="description" content="Static design mock for founder review. Sample content only; not a working interface.">
<style>{light}{PAGE_CSS}</style></head>
<body class="review"><div class="banner" role="note"><strong>Design mock for founder review.</strong> Sample content only. Nothing here is connected to a model or backend, and no model shown
is qualified for production. Generated from <code>docs/orneur/design/tokens.json</code>.</div>
<div class="wrap"><h1>ORNEUR — visual review package, Light and Dark</h1>
<p class="lede">Two official themes, the locked palette, and an interface that stays out of the way. The honest model label, citations you can open, and a visible stop control
are part of the design, not afterthoughts. Specification: <code>docs/orneur/design/ORNEUR_UI_DESIGN_SPEC.md</code>.</p>
<h2>What is in this package</h2>
<ol class="pkg"><li><a href="#desktop-conversation-dark">Dark desktop conversation</a></li><li><a href="#desktop-conversation-light">Light desktop conversation</a></li>
<li><a href="#mobile-conversation-dark">Dark mobile conversation</a></li><li><a href="#mobile-conversation-light">Light mobile conversation</a></li>
<li><a href="#brand-emblem-and-wordmark-dark">Full-size falcon emblem</a></li><li><a href="#brand-emblem-and-wordmark-light">Segmented-E ORNEUR wordmark</a></li>
<li><a href="#composer-states-dark">Chat composer and streaming states</a></li><li><a href="#sidebar-and-history-dark">Sidebar and conversation history</a></li>
<li><a href="#code-and-attachments-dark">Code block and file attachment states</a></li><li><a href="#system-states-dark">Empty, loading, error and model-unavailable states</a></li></ol>
<div class="decision"><h3>Changes to earlier brand decisions</h3><ul>
<li><strong>None</strong> to the locked palette (Slate Indigo #3A4B6B, Solar Coral #FF6B57, Pale Stone #E8E4DE, near-black dark surfaces), the greeting, or the two-theme rule.</li>
<li>Derived text colours exist only where the raw brand colour fails WCAG AA as text: Light accent text #B03626, Dark accent text #FF8A78 (measured below).</li>
<li><strong>SUPERSEDED:</strong> the falcon emblem and segmented-E wordmark below are earlier concepts. The founder-supplied official ORNEUR logo is locked (see docs/orneur/brand/BRAND_IDENTITY_LOCK.md); do not use this generator\'s marks.</li></ul></div>
<div class="decision"><h3>Proposed UX defaults (not approved)</h3><ul>
<li>First visit follows the system Dark/Light preference; a later choice persists.</li><li>ORNEUR is the primary product brand; model identity and lifecycle are one tap away and always truthful.</li>
<li>Experimental models are never shown as production-qualified. Build order after approval: tokens, app shell, secure chat, streaming/cancel/retry, history, files, research.</li></ul></div>
<h2 id="s-desktop">Desktop: a finished answer with citations</h2><div class="grid two">{desk}</div>
<h2>Desktop: a response in progress (stop is always one click)</h2><div class="grid two">{states}</div>
<h2>Mobile: a finished answer with citations</h2><div class="grid mob">{mobconv}</div>
<h2>Mobile: first run and error recovery</h2><div class="grid mob">{mob}</div>
<h2>Brand (SUPERSEDED concepts, kept for audit): falcon emblem and segmented-E wordmark</h2><div class="grid two">{brand}</div>
<h2>Composer and streaming states</h2><div class="grid two">{composers}</div>
<h2>Sidebar and conversation history</h2><div class="grid two">{sidebars}</div>
<h2>Code block and file attachments</h2><div class="grid two">{codefiles}</div>
<h2>Empty, loading, error and model-unavailable states</h2><div class="grid two">{system}</div>
<h2>Measured contrast (WCAG 2.2 AA)</h2><p class="lede">Every pair below is recomputed by <code>tests/test_design_tokens_contrast.py</code>. The raw brand colours are used for fills and accents;
text uses derived variants where the raw colour fails.</p>{swatches()}
</div></body></html>"""


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
