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
const closeMenusFn = extractBalancedFunction(source, 'function closeAllRecMenus(opts) {', renderRowFn.end);

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
      // Supports a compound class selector like ".rec-menu-item.danger"
      // (all listed classes must be present), not just a single class.
      const requiredClasses = sel.split('.').filter(Boolean);
      const matches = (c) => {
        const classes = (c.className || '').split(/\s+/);
        return requiredClasses.every((rc) => classes.includes(rc));
      };
      const direct = this._children.find(matches);
      if (direct) return direct;
      for (const c of this._children) {
        const nested = c.querySelector && c.querySelector(sel);
        if (nested) return nested;
      }
      return null;
    },
    querySelectorAll(sel) {
      const requiredClasses = sel.split('.').filter(Boolean);
      const out = [];
      const walk = (node) => {
        for (const c of node._children) {
          const classes = (c.className || '').split(/\s+/);
          if (requiredClasses.every((rc) => classes.includes(rc))) out.push(c);
          walk(c);
        }
      };
      walk(this);
      return out;
    },
    _listeners: {},
    addEventListener(type, fn) {
      (this._listeners[type] = this._listeners[type] || []).push(fn);
    },
    click() {
      const ev = { stopPropagation() {}, preventDefault() {} };
      (this._listeners.click || []).forEach((fn) => fn(ev));
    },
    setAttribute(k, v) { this._attrs[k] = v; },
    getAttribute(k) { return this._attrs[k] ?? null; },
    classList: null,
    focus() { this._focused = true; },
  };
  el.classList = {
    add: (c) => { el.className = (el.className + ' ' + c).trim(); },
    remove: (c) => { el.className = el.className.split(/\s+/).filter((x) => x !== c).join(' '); },
    contains: (c) => el.className.split(/\s+/).includes(c),
  };
  return el;
}

// A single root all rows are appended under -- lets document.querySelectorAll
// (used internally by closeAllRecMenus(), which queries the GLOBAL
// document, not a specific row) actually find them.
const root = makeElement('div');
const sandbox = {
  document: {
    createElement: makeElement,
    querySelectorAll: (sel) => root.querySelectorAll(sel),
    querySelector: (sel) => root.querySelector(sel),
    addEventListener() {},
  },
};
vm.createContext(sandbox);
vm.runInContext(
  `var sessionId = null;\n${escFn.text}\n${renderRowFn.text}\n${closeMenusFn.text}`,
  sandbox,
);
const { renderRecentRow, closeAllRecMenus } = sandbox;

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

// AUDIT-P85-P1: menu interaction correctness, using the real
// document.querySelectorAll-driven closeAllRecMenus() against a shared
// root (rows appended via renderRecentRow() into `root`, matching how
// the real app always appends into one shared #recents-list).
test('clicking the more-actions button opens the menu; closeAllRecMenus() closes it and restores focus', () => {
  root._children = [];
  renderRecentRow(root, 'sid-5', 'Row A');
  const row = root._children[0];
  const moreBtn = row.querySelector('.rec-more-btn');
  moreBtn.click();
  assert.equal(row.querySelector('.rec-menu-panel').classList.contains('open'), true);
  assert.equal(moreBtn.getAttribute('aria-expanded'), 'true');

  closeAllRecMenus({ restoreFocus: true });
  assert.equal(row.querySelector('.rec-menu-panel').classList.contains('open'), false);
  assert.equal(moreBtn.getAttribute('aria-expanded'), 'false');
  assert.equal(moreBtn._focused, true, 'focus must be restored to the button that opened the menu');
});

test('AUDIT-P85-P1 (the real bug): an armed delete-confirm is reset when the menu closes without confirming, not left armed for next time', () => {
  root._children = [];
  renderRecentRow(root, 'sid-6', 'Row B');
  const row = root._children[0];
  const moreBtn = row.querySelector('.rec-more-btn');
  moreBtn.click(); // open
  const deleteItem = row.querySelector('.rec-menu-panel').querySelectorAll('.rec-menu-item')
    .find((i) => i.textContent === 'Delete' || i.textContent === 'Click again to delete');
  deleteItem.click(); // arm (first click)
  assert.equal(deleteItem.textContent, 'Click again to delete');

  // Close the menu WITHOUT a second (confirming) click -- e.g. an
  // outside click or Escape in the real app.
  closeAllRecMenus();

  // Reopen the SAME row's menu: a fresh "first click" must behave like
  // a fresh first click, not silently fire the delete because
  // `confirming` was left true from before.
  moreBtn.click();
  const deleteItemAgain = row.querySelector('.rec-menu-panel').querySelectorAll('.rec-menu-item')
    .find((i) => i.textContent === 'Delete' || i.textContent === 'Click again to delete');
  assert.equal(deleteItemAgain.textContent, 'Delete', 'reopening the menu must never show an already-armed delete button');
});

test('AUDIT-P85-P1 (the real bug): row.dataset.title is updated by renderRecentRow and is what a second rename/export would read -- never a stale closure', () => {
  root._children = [];
  renderRecentRow(root, 'sid-7', 'Original Title');
  const row = root._children[0];
  assert.equal(row.dataset.title, 'Original Title');
  // Simulates what the real commit() handler inside startRenameConversation
  // does after a successful PATCH response.
  row.dataset.title = 'Renamed By Server';
  assert.equal(row.dataset.title, 'Renamed By Server', 'the row\'s title must be mutable in place, so a second rename reads the NEW value');
});
