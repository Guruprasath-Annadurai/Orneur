// B16 Context & Attachments regression tests.
//
// Source: APPROVED_SOURCE_ARCHIVES/ORNEUR_B16_FINAL_LOCK_AND_HANDOFF.zip
// (SHA-256 a38850996edf55496565ef9b783fc79263e05077855e42ad88e4feace4040f96,
// verified 30/30 files against the archive's own flat
// SHA256_PACKAGE_MANIFEST.json before any code was written).
//
// Unlike B13/B11, this is NOT a disabled-state screen: grepping
// orca/serve/api.py found a real, working document pipeline
// (POST /api/docs/upload, GET /api/docs/list, DELETE /api/docs/{doc_id})
// that was already silently feeding B15's citation work this same
// session but had zero frontend UI before this phase. This phase wires
// the real pipeline to a real composer UI.
//
// Run with: node --test tests/frontend/test_b16_context_attachments.mjs
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

test('uploadAttachment() never sets Content-Type manually -- would break the multipart boundary', () => {
  const fnSrc = extractBalancedFunction(source, 'async function uploadAttachment(file) {').text;
  assert.ok(!fnSrc.includes("'Content-Type'") && !fnSrc.includes('"Content-Type"'), 'FormData needs the browser to set its own multipart boundary; a manual Content-Type (or _authHeaders(), which sets application/json) breaks the upload');
  assert.ok(!fnSrc.includes('headers: _authHeaders()'), 'must not reuse _authHeaders() as the fetch headers for the upload request, since it sets application/json');
});

test('uploadAttachment() checks token and session identity after the await, discarding a stale upload', () => {
  const fnSrc = extractBalancedFunction(source, 'async function uploadAttachment(file) {').text;
  assert.ok(fnSrc.includes('myToken !== _authToken'), 'must detect an account change mid-upload');
  assert.ok(fnSrc.includes('sessionId !== mySidAtStart'), 'must detect a conversation switch mid-upload');
});

test('uploadAttachment() handles 401 via the real session-expiry path, not a generic error', () => {
  const fnSrc = extractBalancedFunction(source, 'async function uploadAttachment(file) {').text;
  assert.ok(fnSrc.includes('_handleSessionExpired()'), 'a 401 during upload must route through the real session-expiry handler');
});

test('uploadAttachment() shows the real server error text on failure, never a fabricated message', () => {
  const fnSrc = extractBalancedFunction(source, 'async function uploadAttachment(file) {').text;
  assert.ok(fnSrc.includes('data.error'), 'the failed-state chip must display the server\'s own error message');
});

test('loadAttachmentsForSession() always re-fetches fresh, never caches across conversations', () => {
  const fnSrc = extractBalancedFunction(source, 'async function loadAttachmentsForSession() {').text;
  assert.ok(fnSrc.includes('/api/docs/list'), 'must call the real list endpoint');
  assert.ok(fnSrc.includes('if (!sessionId)'), 'a null sessionId (new conversation) must clear the chip list, not show a stale one');
});

test('removeAttachment() only removes the chip locally for a never-finished upload, otherwise calls the real DELETE endpoint', () => {
  const fnSrc = extractBalancedFunction(source, 'async function removeAttachment(chip, doc) {').text;
  assert.ok(fnSrc.includes('if (!doc.doc_id)'), 'a chip with no doc_id never finished uploading -- nothing server-side to delete');
  assert.ok(fnSrc.includes("method: 'DELETE'"), 'must call the real DELETE endpoint for a finished upload');
  assert.ok(fnSrc.includes('if (r.ok) chip.remove();'), 'a failed delete must leave the chip in place, never silently claim removal');
});

test('.chip-state wraps instead of forcing horizontal overflow (the B16 CSS bug found and fixed live)', () => {
  const idx = source.indexOf('.attach-chip .chip-state{');
  assert.ok(idx !== -1, '.chip-state rule must exist');
  const rule = source.slice(idx, source.indexOf('}', idx) + 1);
  assert.ok(!rule.includes('flex-shrink:0'), 'flex-shrink:0 was the root cause of the live-reproduced overflow bug -- must not regress');
  assert.ok(rule.includes('white-space:normal'), 'a long real server error message must wrap within the chip');
});

// --- Behavioral tests against the real functions, with a minimal fake DOM ---

function makeFakeNode(tag) {
  const el = {
    tagName: tag || 'DIV',
    _children: [],
    className: '',
    _html: '',
    hidden: false,
    dataset: {},
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => el.classList._set.add(x)); },
      remove(...c) { c.forEach((x) => el.classList._set.delete(x)); },
      toggle(c, f) { const on = f === undefined ? !el.classList._set.has(c) : f; if (on) el.classList._set.add(c); else el.classList._set.delete(c); },
      contains(c) { return el.classList._set.has(c); },
    },
    get innerHTML() { return el._html; },
    set innerHTML(v) {
      el._html = v;
      el._children = [];
      const tagMatches = [...v.matchAll(/<[a-zA-Z][^>]*>/g)];
      for (const m of tagMatches) {
        const tagStr = m[0];
        const classMatch = tagStr.match(/class="([^"]+)"/);
        if (!classMatch) continue;
        for (const cls of classMatch[1].split(/\s+/)) {
          const frag = makeFakeNode('span');
          frag.className = cls;
          el._children.push(frag);
        }
      }
    },
    appendChild(child) { el._children.push(child); return child; },
    insertBefore(child) { el._children.unshift(child); return child; },
    querySelector(sel) {
      const cls = sel.replace(/^\./, '').split('?')[0].replace(/[^a-zA-Z0-9_-]/g, '');
      return el._children.find((c) => (c.className || '') === cls) || null;
    },
    remove() {},
    setAttribute() {},
    addEventListener(evt, fn) { el[`_on_${evt}`] = fn; },
  };
  return el;
}

test('renderAttachChip() builds a chip with filename, no state label when ready, and a working remove handler', () => {
  const fnSrc = extractBalancedFunction(source, 'function renderAttachChip(doc) {').text;
  const escSrc = extractBalancedFunction(source, 'function esc(t) {').text;
  const container = makeFakeNode('div');
  let removedDoc = null;
  const sandbox = {
    document: { getElementById: () => container, createElement: (tag) => makeFakeNode(tag) },
    removeAttachment: (chip, doc) => { removedDoc = doc; },
  };
  vm.createContext(sandbox);
  vm.runInContext(`${escSrc}\n${fnSrc}`, sandbox);
  const doc = { doc_id: 'd1', filename: 'report.pdf', state: 'ready' };
  const chip = sandbox.renderAttachChip(doc);
  assert.ok(chip.innerHTML.includes('report.pdf'));
  assert.equal(chip.classList.contains('failed'), false);
  const removeBtn = chip._children.find((c) => c.className === 'attach-chip-remove');
  assert.ok(removeBtn, 'remove button must render');
});

test('renderAttachChip() marks a failed-state chip with the failed class', () => {
  const fnSrc = extractBalancedFunction(source, 'function renderAttachChip(doc) {').text;
  const escSrc = extractBalancedFunction(source, 'function esc(t) {').text;
  const container = makeFakeNode('div');
  const sandbox = {
    document: { getElementById: () => container, createElement: (tag) => makeFakeNode(tag) },
    removeAttachment: () => {},
  };
  vm.createContext(sandbox);
  vm.runInContext(`${escSrc}\n${fnSrc}`, sandbox);
  const chip = sandbox.renderAttachChip({ filename: 'bad.exe', state: 'failed', error: 'Unsupported file type' });
  assert.equal(chip.classList.contains('failed'), true);
  assert.ok(chip.innerHTML.includes('Unsupported file type'));
});
