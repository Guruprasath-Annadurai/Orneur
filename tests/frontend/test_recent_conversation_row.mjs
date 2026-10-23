// AUDIT-UIPROG-B06/B07/B08/B09 regression test. Extracts and runs the
// EXACT shipped esc()/renderRecentRow()/closeAllRecMenus() straight out
// of orca/serve/web/conversation.html at test time (same brace-balanced
// vm technique as the other tests/frontend/*.mjs files) -- no hand-copy.
//
// Scope note (honest, disclosed limitation): this covers the row's DOM
// structure and the XSS-safety of rendering untrusted title/snippet text
// into it (both come from the server, but a title is caller-settable via
// PATCH .../title, so it must be treated as untrusted on render). The
// async fetch-driven behaviors (rename PATCH, export GET+blob-download,
// delete DELETE, debounced search) were verified end-to-end against the
// real running backend in a real browser this session -- see the
// engineering report for the captured evidence (signup -> real send ->
// rename -> search with snippet -> export -> delete, each checked
// against the actual persisted/deleted server state, not just the DOM).
//
// Run with: node tests/frontend/test_recent_conversation_row.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE_PATH = path.join(__dirname, '../../orca/serve/web/conversation.html');
const source = fs.readFileSync(SOURCE_PATH, 'utf8');

function extractBalancedFunction(src, startMarker, fromIndex) {
  const start = src.indexOf(startMarker, fromIndex);
  if (start === -1) throw new Error(`marker not found in conversation.html: ${startMarker}`);
  const braceOpen = src.indexOf('{', start);
  let depth = 0;
  let i = braceOpen;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth--;
      if (depth === 0) break;
    }
  }
  return { text: src.slice(start, i + 1), end: i + 1 };
}

const escFn = extractBalancedFunction(source, 'function esc(t) {', 0);
const renderRowFn = extractBalancedFunction(source, 'function renderRecentRow(list, sid, title, snippet) {', escFn.end);
const closeMenusFn = extractBalancedFunction(source, 'function closeAllRecMenus() {', renderRowFn.end);

// --- Minimal hand-rolled DOM stub, same pattern as
// test_streaming_completion_truth.mjs's makeElement -----------------
function makeElement(tag) {
  const el = {
    tagName: tag,
    _children: [],
    _html: '',
    className: '',
    textContent: '',
    style: {},
    dataset: {},
    _attrs: {},
    get innerHTML() { return this._html; },
    set innerHTML(v) {
      this._html = v;
      this._children = [];
      const classMatches = [...v.matchAll(/class="([^"]+)"/g)];
      for (const m of classMatches) {
        for (const cls of m[1].split(/\s+/)) {
          const frag = makeElement('span');
          frag.className = cls;
          this._children.push(frag);
        }
      }
    },
    appendChild(child) { this._children.push(child); return child; },
    remove() { this._removed = true; },
    querySelector(sel) {
      const cls = sel.replace(/^\./, '');
      const direct = this._children.find((c) => (c.className || '').split(/\s+/).includes(cls));
      if (direct) return direct;
      for (const c of this._children) {
        const nested = c.querySelector && c.querySelector(sel);
        if (nested) return nested;
      }
      return null;
    },
    querySelectorAll(sel) {
      const cls = sel.replace(/^\./, '').replace(/\.open$/, '');
      const wantsOpen = sel.endsWith('.open');
      const out = [];
      const walk = (node) => {
        for (const c of node._children) {
          const classes = (c.className || '').split(/\s+/);
          if (classes.includes(cls) && (!wantsOpen || classes.includes('open'))) out.push(c);
          walk(c);
        }
      };
      walk(this);
      return out;
    },
    addEventListener() {},
    setAttribute(k, v) { this._attrs[k] = v; },
    getAttribute(k) { return this._attrs[k] ?? null; },
    classList: null,
    focus() {},
  };
  el.classList = {
    add: (c) => { el.className = (el.className + ' ' + c).trim(); },
    remove: (c) => { el.className = el.className.split(/\s+/).filter((x) => x !== c).join(' '); },
    contains: (c) => el.className.split(/\s+/).includes(c),
  };
  return el;
}

const sandbox = {
  document: { createElement: makeElement, querySelectorAll: () => [], addEventListener() {} },
};
vm.createContext(sandbox);
vm.runInContext(
  `var sessionId = null;\n${escFn.text}\n${renderRowFn.text}\n${closeMenusFn.text}`,
  sandbox,
);
const { renderRecentRow } = sandbox;

test('a plain recent-conversation row has exactly the 4 expected menu actions, in order', () => {
  const list = makeElement('div');
  renderRecentRow(list, 'sid-1', 'My conversation');
  const row = list._children[0];
  const items = row.querySelectorAll('.rec-menu-item');
  assert.deepEqual(items.map((i) => i.textContent), ['Rename', 'Export as Markdown', 'Export as JSON', 'Delete']);
});

test('a malicious conversation title cannot inject markup into the row (XSS safety)', () => {
  const list = makeElement('div');
  const evilTitle = '<img src=x onerror=alert(1)>';
  const evilSnippet = '</span><script>alert(2)</script>';
  renderRecentRow(list, 'sid-2', evilTitle, evilSnippet);
  const row = list._children[0];
  const btn = row.querySelector('.rec');
  assert.ok(!btn.innerHTML.includes('<img'), 'title must not render as a live <img> tag: ' + btn.innerHTML);
  assert.ok(!btn.innerHTML.includes('<script>'), 'snippet must not render as a live <script> tag: ' + btn.innerHTML);
  assert.ok(btn.innerHTML.includes('&lt;img'), 'the raw title text must still be visible, just escaped');
});

test('a row with no snippet renders the title as plain text, not the two-line snippet layout', () => {
  const list = makeElement('div');
  renderRecentRow(list, 'sid-3', 'Plain title, no search context');
  const row = list._children[0];
  const btn = row.querySelector('.rec');
  assert.equal(btn.textContent, 'Plain title, no search context');
});

test('the more-actions button carries an accessible name naming the actual conversation', () => {
  const list = makeElement('div');
  renderRecentRow(list, 'sid-4', 'Quarterly planning');
  const row = list._children[0];
  const moreBtn = row.querySelector('.rec-more-btn');
  assert.equal(moreBtn.getAttribute('aria-label'), 'More actions for "Quarterly planning"');
  assert.equal(moreBtn.getAttribute('aria-haspopup'), 'true');
  assert.equal(moreBtn.getAttribute('aria-expanded'), 'false');
});
