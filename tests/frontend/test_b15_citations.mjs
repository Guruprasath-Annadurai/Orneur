// B15 Citations & Sources regression tests.
//
// Source: docs/B15_IMPLEMENTATION_CONTRACT.md (ORNEUR_B15_FINAL_LOCK_AND_HANDOFF.zip,
// SHA-256 8c0403ab872766a1c6212756c7032575e62221e1391174da21c30897b87189fb,
// verified via references/verification/verify_handoff.py: 30/30 + 41/41,
// zero failures). The contract's own schema (SourceCitationView, with
// tenant/access/integrity/revocation/claim-support fields) is explicitly
// "a proposed schema to adapt, not an assertion of existing API." The
// REAL backend schema (orca/serve/citations.py, orneur.sources/1) is
// simpler: {ref, kind, filename, doc_id, url, locator, excerpt,
// excerpt_sha256, retrieved_at, cited_in_answer} per source, plus a
// {schema, retrieval_performed, grounding, source_count, retrieved_at}
// summary. This phase builds the UI around exactly that real shape and
// deliberately does NOT fabricate the richer contract concepts the
// backend doesn't compute (access/integrity/revocation/claim-anchor
// support assessment) -- the tests below guard against inventing them.
//
// Run with: node --test tests/frontend/test_b15_citations.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE_PATH = path.join(__dirname, '../../orca/serve/web/conversation.html');
const source = fs.readFileSync(SOURCE_PATH, 'utf8');

function extractBalancedFunction(src, startMarker, fromIndex = 0) {
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

// --- Structural guards ---

test('renderSourcesPanel() never invents access/integrity/revocation/support fields the real backend does not compute', () => {
  const fnSrc = extractBalancedFunction(source, 'function renderSourcesPanel(div, sources) {').text;
  for (const forbidden of ['.access', '.integrity', '.support', 'revoked', 'Revoked', 'Verified by', 'claimAnchor']) {
    assert.ok(!fnSrc.includes(forbidden), `must not render a "${forbidden}" field -- orca/serve/citations.py's real orneur.sources/1 schema has no such field, and the B15 contract itself calls its own richer schema "a proposed schema to adapt, not an assertion of existing API"`);
  }
  for (const real of ['s.kind', 's.filename', 's.url', 's.locator', 's.excerpt', 's.cited_in_answer', 's.ref']) {
    assert.ok(fnSrc.includes(real), `must source the panel from the real backend field ${real}`);
  }
});

test('the sources list visibility is controlled by a class, not a base display style that would out-specify [hidden] (reproduced live before this fix)', () => {
  const idx = source.indexOf('.sources-list{');
  assert.ok(idx !== -1);
  const baseRule = source.slice(idx, source.indexOf('}', idx) + 1);
  assert.ok(!baseRule.includes('display:flex'), 'the base .sources-list rule must not force display:flex -- reproduced live as the sources panel rendering fully expanded by default, out-specifying [hidden]');
  assert.ok(source.includes('.sources-list.open{display:flex}'), 'must have a dedicated .open class as the authoritative visibility toggle, matching the same fix already applied to B05\'s .model-details');
});

test('renderSourcesPanel() renders nothing at all when sources is empty or absent -- no citations means no fabricated UI', () => {
  const fnSrc = extractBalancedFunction(source, 'function renderSourcesPanel(div, sources) {').text;
  assert.ok(/if \(!sources \|\| !sources\.length\) return;/.test(fnSrc), 'must early-return with zero DOM changes when there are no real sources');
});

test('mdToHtml() only converts a [Ref] bracket into a citation marker when a matching source.ref actually exists', () => {
  const fnSrc = extractBalancedFunction(source, 'function mdToHtml(md, sources) {').text;
  assert.ok(fnSrc.includes('byRef.get(ref)'), 'must look up the ref against the real sources array');
  assert.ok(fnSrc.includes('if (!s) return whole;'), 'an unmatched bracket must be left as literal text, never turned into a fabricated reference');
});

test('source URLs are sanitized through the existing _sanitizeLinkHref() before being rendered as a link', () => {
  const fnSrc = extractBalancedFunction(source, 'function renderSourcesPanel(div, sources) {').text;
  assert.ok(fnSrc.includes('_sanitizeLinkHref(s.url)'), 'must reuse the already-tested link-scheme sanitizer, not a new unvetted one');
});

test('openSession() binds each reloaded message to its OWN persisted sources, not the live/latest conversation state', () => {
  const openSessionSrc = extractBalancedFunction(source, 'async function openSession(sid, title) {').text;
  assert.ok(openSessionSrc.includes('m.meta && Array.isArray(m.meta.sources)'), 'must read sources from this specific message\'s own persisted meta, confirmed real via orca/serve/conversations.py');
});

// --- Behavioral tests against the real functions, with a minimal fake DOM ---

function makeFakeNode(tag) {
  const el = {
    tagName: tag || 'DIV',
    _children: [],
    className: '',
    textContent: '',
    _html: '',
    id: '',
    dataset: {},
    _attrs: {},
    hidden: false,
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; },
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => el.classList._set.add(x)); },
      remove(...c) { c.forEach((x) => el.classList._set.delete(x)); },
      contains(c) { return el.classList._set.has(c); },
      toggle(c, force) { const on = force === undefined ? !el.classList._set.has(c) : force; if (on) el.classList._set.add(c); else el.classList._set.delete(c); return on; },
    },
    setAttribute(k, v) { el._attrs[k] = v; },
    appendChild(child) { el._children.push(child); return child; },
    querySelector(sel) {
      const wantDataRef = sel.match(/^\[data-ref="([^"]+)"\]$/);
      const stack = [...el._children];
      while (stack.length) {
        const node = stack.shift();
        if (wantDataRef && node.dataset.ref === wantDataRef[1]) return node;
        stack.push(...(node._children || []));
      }
      return null;
    },
    querySelectorAll(sel) {
      if (sel === '.cite-marker') return []; // no inline markers in these panel-only tests
      return [];
    },
    addEventListener(evt, fn) { el[`_on_${evt}`] = fn; },
    scrollIntoView() {},
  };
  return el;
}

test('renderSourcesPanel() renders one row per source with the real fields, and toggling the summary shows/hides the list', () => {
  const fnSrc = extractBalancedFunction(source, 'function renderSourcesPanel(div, sources) {').text;
  const divUidSrc = extractBalancedFunction(source, 'function div_uid(div) {').text;
  const escSrc = extractBalancedFunction(source, 'function esc(t) {').text;
  const sanitizeSrc = extractBalancedFunction(source, 'function _sanitizeLinkHref(rawUrl) {').text;

  const sandbox = {
    document: { createElement: (tag) => makeFakeNode(tag) },
  };
  vm.createContext(sandbox);
  vm.runInContext(`var _sourceDivCounter = 0;\nvar _sourceDivIds = new WeakMap();\n${escSrc}\n${sanitizeSrc}\n${divUidSrc}\n${fnSrc}`, sandbox);

  const div = makeFakeNode('div');
  const sources = [
    { ref: 'D1', kind: 'uploaded_document', filename: 'quarterly-report.pdf', locator: { type: 'chunk', chunk_index: 3 }, excerpt: 'Revenue grew 12% year over year.', cited_in_answer: true },
    { ref: 'D2', kind: 'web_page', url: 'https://example.com/article', locator: { type: 'opaque', value: '' }, excerpt: 'Background context only.', cited_in_answer: false },
  ];
  sandbox.renderSourcesPanel(div, sources);

  const panel = div._children.find((c) => c.className === 'sources-panel');
  assert.ok(panel, 'must append a sources panel when sources exist');
  const toggle = panel._children.find((c) => c.className === 'sources-toggle');
  const list = panel._children.find((c) => c.className === 'sources-list');
  assert.ok(toggle && list);
  assert.equal(list.hidden, true, 'the list must be closed by default, per the contract\'s "unobtrusive... closed by default"');
  assert.equal(toggle.textContent, 'Sources (1 cited, 1 more consulted)');

  toggle._on_click();
  assert.equal(list.hidden, false, 'clicking the toggle must open the list');
  assert.equal(toggle._attrs['aria-expanded'], 'true');

  assert.equal(list._children.length, 2);
  const row1 = list._children[0];
  assert.ok(row1._html.includes('quarterly-report.pdf'));
  assert.ok(row1._html.includes('Cited'));
  assert.ok(row1._html.includes('Chunk 3'));
  const row2 = list._children[1];
  assert.ok(row2._html.includes('https://example.com/article'));
  assert.ok(row2._html.includes('Consulted, not cited'));
});

test('renderSourcesPanel() summary honestly distinguishes "consulted, not cited" when nothing was actually cited', () => {
  const fnSrc = extractBalancedFunction(source, 'function renderSourcesPanel(div, sources) {').text;
  const divUidSrc = extractBalancedFunction(source, 'function div_uid(div) {').text;
  const escSrc = extractBalancedFunction(source, 'function esc(t) {').text;
  const sanitizeSrc = extractBalancedFunction(source, 'function _sanitizeLinkHref(rawUrl) {').text;
  const sandbox = { document: { createElement: (tag) => makeFakeNode(tag) } };
  vm.createContext(sandbox);
  vm.runInContext(`var _sourceDivCounter = 0;\nvar _sourceDivIds = new WeakMap();\n${escSrc}\n${sanitizeSrc}\n${divUidSrc}\n${fnSrc}`, sandbox);
  const div = makeFakeNode('div');
  sandbox.renderSourcesPanel(div, [{ ref: 'D1', kind: 'uploaded_document', filename: 'a.pdf', excerpt: 'x', cited_in_answer: false }]);
  const panel = div._children.find((c) => c.className === 'sources-panel');
  const toggle = panel._children.find((c) => c.className === 'sources-toggle');
  assert.equal(toggle.textContent, 'Sources consulted (1, not directly cited)', 'must never imply something was cited when grounding says otherwise');
});

test('an unsafe source URL (javascript:) is rejected the same way the rest of this file rejects unsafe links, never rendered as a clickable href', () => {
  const fnSrc = extractBalancedFunction(source, 'function renderSourcesPanel(div, sources) {').text;
  const divUidSrc = extractBalancedFunction(source, 'function div_uid(div) {').text;
  const escSrc = extractBalancedFunction(source, 'function esc(t) {').text;
  const sanitizeSrc = extractBalancedFunction(source, 'function _sanitizeLinkHref(rawUrl) {').text;
  const sandbox = { document: { createElement: (tag) => makeFakeNode(tag) } };
  vm.createContext(sandbox);
  vm.runInContext(`var _sourceDivCounter = 0;\nvar _sourceDivIds = new WeakMap();\n${escSrc}\n${sanitizeSrc}\n${divUidSrc}\n${fnSrc}`, sandbox);
  const div = makeFakeNode('div');
  sandbox.renderSourcesPanel(div, [{ ref: 'D1', kind: 'web_page', url: 'javascript:alert(1)', excerpt: '', cited_in_answer: true }]);
  const panel = div._children.find((c) => c.className === 'sources-panel');
  const list = panel._children.find((c) => c.className === 'sources-list');
  const row = list._children[0];
  assert.ok(!row._html.includes('<a href'), 'an unsafe scheme must never become a real <a href>');
  assert.ok(row._html.includes('link removed'));
});
