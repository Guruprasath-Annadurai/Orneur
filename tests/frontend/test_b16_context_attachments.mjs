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
// session but had zero frontend UI before this phase.
//
// This file also covers the CTO's B-series final correction directive:
// a confirmed identity defect (removeAttachment() read doc_id from a
// closure-captured object that uploadAttachment() never updated, so
// removing a freshly-uploaded chip silently took the local-only branch
// instead of calling the real DELETE endpoint -- reproduced live, fixed
// here by reading doc_id from chip.dataset.docId, the single place
// uploadAttachment() actually writes it) plus the in-flight races the
// directive asked to be tested (remove-during-upload, account/
// conversation change during upload, concurrent uploads to a brand-new
// conversation). The directive's point C ("HTTP 403 retrieval_unauthorized
// versus HTTP 401 session expiry") does not match this backend: grepping
// the whole repo found zero occurrences of "retrieval_unauthorized", and
// live curl testing (see ORNEUR_B16_CORRECTION_AND_AUDIT.md) confirmed
// /api/docs/* never itself returns 401 -- an invalid/expired token against
// an owned session_id surfaces as 404 "session not found" via
// _get_session's ownership check. No test here fabricates 403/401
// handling that the backend does not actually produce.
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

test('uploadAttachment() detects an account change and a conversation change after the await', () => {
  const fnSrc = extractBalancedFunction(source, 'async function uploadAttachment(file) {').text;
  assert.ok(fnSrc.includes('myToken !== _authToken'), 'must detect an account change mid-upload');
  assert.ok(fnSrc.includes('sessionId !== mySidAtStart'), 'must detect a conversation switch mid-upload for an existing conversation');
});

test('uploadAttachment() detects a concurrent sibling upload winning the new-conversation session-adopt race', () => {
  const fnSrc = extractBalancedFunction(source, 'async function uploadAttachment(file) {').text;
  assert.ok(fnSrc.includes('data.session_id !== sessionId'), 'for a brand-new conversation (mySidAtStart null), two concurrent uploads each create their OWN new backend session -- a sibling whose own session_id does not match the adopted sessionId must not be silently treated as belonging to it');
});

test('uploadAttachment() cleans up an orphaned server-side document on account/conversation/concurrency shift and on a deferred remove request', () => {
  const fnSrc = extractBalancedFunction(source, 'async function uploadAttachment(file) {').text;
  assert.ok(fnSrc.includes('_deleteOrphanedUpload('), 'a successful upload that no longer belongs anywhere visible must be deleted server-side, not left as an invisible orphan');
  assert.ok(fnSrc.includes('chip._removeRequested'), 'must check whether the user asked to remove this chip while the upload was still in-flight');
});

test('uploadAttachment() handles 401 via the real session-expiry path (defense-in-depth; see loadAttachmentsForSession guard for why this does not fire on this backend today)', () => {
  const fnSrc = extractBalancedFunction(source, 'async function uploadAttachment(file) {').text;
  assert.ok(fnSrc.includes('_handleSessionExpired()'), 'a 401 during upload must route through the real session-expiry handler');
});

test('uploadAttachment() shows the real server error text on failure, never a fabricated message', () => {
  const fnSrc = extractBalancedFunction(source, 'async function uploadAttachment(file) {').text;
  assert.ok(fnSrc.includes('data.error'), 'the failed-state chip must display the server\'s own error message');
});

test('loadAttachmentsForSession() always re-fetches fresh, checks account identity too, and never fabricates 404-as-session-expiry', () => {
  const fnSrc = extractBalancedFunction(source, 'async function loadAttachmentsForSession() {').text;
  assert.ok(fnSrc.includes('/api/docs/list'), 'must call the real list endpoint');
  assert.ok(fnSrc.includes('if (!sessionId)'), 'a null sessionId (new conversation) must clear the chip list, not show a stale one');
  assert.ok(fnSrc.includes('myToken !== _authToken'), 'a stale response after a different account has since signed in must not repaint the current view');
  assert.ok(fnSrc.includes("r.status === 401"), 'kept for defense-in-depth consistency with the other authenticated call sites');
  assert.ok(!/404[\s\S]{0,80}_handleSessionExpired/.test(fnSrc), 'must NOT treat a 404 as session-expiry -- the same 404 also covers legitimate idle-session eviction with no auth problem at all');
});

test('removeAttachment() reads doc_id from chip.dataset.docId, never a second closure-captured object (the confirmed identity defect)', () => {
  const renderSrc = extractBalancedFunction(source, 'function renderAttachChip(doc) {').text;
  assert.ok(renderSrc.includes('removeAttachment(chip)'), 'the remove click handler must call removeAttachment with only the chip -- a second captured `doc` argument is exactly what caused the confirmed defect (uploadAttachment() updates chip.dataset.docId, never a second object)');
  const fnSrc = extractBalancedFunction(source, 'async function removeAttachment(chip) {').text;
  assert.ok(fnSrc.includes('chip.dataset.docId'), 'doc_id must be read from the chip itself, the single place uploadAttachment() writes it on success');
  assert.ok(fnSrc.includes('if (!docId)'), 'a chip with no doc_id yet (never finished uploading, or still uploading) takes the local-only branch');
  assert.ok(fnSrc.includes("method: 'DELETE'"), 'must call the real DELETE endpoint once a doc_id is known');
  assert.ok(fnSrc.includes('if (r.ok) chip.remove();'), 'a failed delete must leave the chip in place, never silently claim removal');
});

test('removeAttachment() marks a deferred removal request when the chip has no doc_id yet (upload still in-flight)', () => {
  const fnSrc = extractBalancedFunction(source, 'async function removeAttachment(chip) {').text;
  assert.ok(fnSrc.includes('chip._removeRequested = true'), 'clicking Remove while an upload is still pending must be remembered so the in-flight upload can clean up the now-orphaned document once it completes, rather than silently losing track of it');
});

test('.chip-state wraps instead of forcing horizontal overflow (the B16 CSS bug found and fixed live)', () => {
  const idx = source.indexOf('.attach-chip .chip-state{');
  assert.ok(idx !== -1, '.chip-state rule must exist');
  const rule = source.slice(idx, source.indexOf('}', idx) + 1);
  assert.ok(!rule.includes('flex-shrink:0'), 'flex-shrink:0 was the root cause of the live-reproduced overflow bug -- must not regress');
  assert.ok(rule.includes('white-space:normal'), 'a long real server error message must wrap within the chip');
});

// --- Behavioral tests against the real functions, with a minimal fake DOM + fake fetch ---

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
    remove() { el._removed = true; },
    setAttribute() {},
    addEventListener(evt, fn) { el[`_on_${evt}`] = fn; },
  };
  return el;
}

function buildSandbox({ fetchImpl }) {
  const container = makeFakeNode('div');
  const sandbox = {
    document: { getElementById: () => container, createElement: (tag) => makeFakeNode(tag) },
    fetch: fetchImpl,
    FormData: class { append() {} },
    sessionId: null,
    _authToken: 'tok-1',
    _authHeaders: () => ({ Authorization: 'Bearer tok-1' }),
    _handleSessionExpired: () => { sandbox._sessionExpiredCalled = true; },
    showActiveView: () => {},
    console,
  };
  return { sandbox, container };
}

function loadFns(sandbox) {
  const escSrc = extractBalancedFunction(source, 'function esc(t) {').text;
  const renderSrc = extractBalancedFunction(source, 'function renderAttachChip(doc) {').text;
  const deleteOrphanSrc = extractBalancedFunction(source, 'async function _deleteOrphanedUpload(docId, sidForDelete, tokenForAuth) {').text;
  const uploadSrc = extractBalancedFunction(source, 'async function uploadAttachment(file) {').text;
  const removeSrc = extractBalancedFunction(source, 'async function removeAttachment(chip) {').text;
  vm.createContext(sandbox);
  vm.runInContext(`${escSrc}\n${renderSrc}\n${deleteOrphanSrc}\n${uploadSrc}\n${removeSrc}`, sandbox);
}

test('renderAttachChip() builds a chip with filename, no state label when ready, and a working remove handler', () => {
  const { sandbox, container } = buildSandbox({ fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({}) }) });
  loadFns(sandbox);
  const chip = sandbox.renderAttachChip({ doc_id: 'd1', filename: 'report.pdf', state: 'ready' });
  assert.ok(chip.innerHTML.includes('report.pdf'));
  assert.equal(chip.classList.contains('failed'), false);
  assert.equal(chip.dataset.docId, 'd1');
  const removeBtn = chip._children.find((c) => c.className === 'attach-chip-remove');
  assert.ok(removeBtn, 'remove button must render');
});

test('renderAttachChip() marks a failed-state chip with the failed class', () => {
  const { sandbox } = buildSandbox({ fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({}) }) });
  loadFns(sandbox);
  const chip = sandbox.renderAttachChip({ filename: 'bad.exe', state: 'failed', error: 'Unsupported file type' });
  assert.equal(chip.classList.contains('failed'), true);
  assert.ok(chip.innerHTML.includes('Unsupported file type'));
});

test('FIXED: removing a chip immediately after a successful upload calls the real DELETE endpoint with the correct doc_id (confirmed identity defect)', async () => {
  const calls = [];
  const { sandbox, container } = buildSandbox({
    fetchImpl: async (url, opts) => {
      calls.push({ url, opts });
      if (url.includes('/api/docs/upload')) {
        return { ok: true, status: 200, json: async () => ({ doc_id: 'doc-123', filename: 'a.txt', chunks: 1, size_bytes: 5, session_id: 'sid-1' }) };
      }
      if (opts && opts.method === 'DELETE') {
        return { ok: true, status: 200, json: async () => ({ deleted: true, doc_id: 'doc-123' }) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    },
  });
  sandbox.sessionId = 'sid-1'; // an EXISTING conversation, so the upload does not itself change sessionId
  loadFns(sandbox);

  await sandbox.uploadAttachment({ name: 'a.txt' });
  const chip = container._children[0];
  assert.equal(chip.dataset.docId, 'doc-123', 'a successful upload must write the real doc_id onto the chip');

  // Simulate the user clicking Remove now, exactly as renderAttachChip() wires it: removeAttachment(chip) with no second argument.
  await sandbox.removeAttachment(chip);
  const deleteCall = calls.find((c) => c.opts && c.opts.method === 'DELETE');
  assert.ok(deleteCall, 'removing a freshly-uploaded chip must call the real DELETE endpoint -- before the fix, it took the local-only branch and never called this');
  assert.ok(deleteCall.url.includes('doc-123'), 'must delete the actual uploaded document, not a stale/empty id');
  assert.ok(chip._removed, 'the chip must be removed from the DOM once the server confirms deletion');
});

test('Remove clicked while upload is still pending: the chip disappears immediately, and the later-arriving successful upload is cleaned up server-side instead of becoming an invisible orphan', async () => {
  const calls = [];
  let resolveUpload;
  const uploadPromise = new Promise((resolve) => { resolveUpload = resolve; });
  const { sandbox, container } = buildSandbox({
    fetchImpl: async (url, opts) => {
      calls.push({ url, opts });
      if (url.includes('/api/docs/upload')) {
        await uploadPromise; // upload resolves AFTER the test clicks Remove below
        return { ok: true, status: 200, json: async () => ({ doc_id: 'doc-999', filename: 'slow.txt', chunks: 1, size_bytes: 5, session_id: 'sid-1' }) };
      }
      if (opts && opts.method === 'DELETE') {
        return { ok: true, status: 200, json: async () => ({ deleted: true, doc_id: 'doc-999' }) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    },
  });
  sandbox.sessionId = 'sid-1';
  loadFns(sandbox);

  const uploadDone = sandbox.uploadAttachment({ name: 'slow.txt' });
  const chip = container._children[0];
  assert.equal(chip.dataset.docId, '', 'doc_id is not known yet -- the upload has not resolved');

  await sandbox.removeAttachment(chip); // user clicks Remove while still uploading
  assert.ok(chip._removed, 'the chip must disappear immediately -- the user asked for it gone');
  assert.equal(chip._removeRequested, true);
  assert.equal(calls.some((c) => c.opts && c.opts.method === 'DELETE'), false, 'no DELETE yet -- there is no doc_id to delete; nothing server-side exists until the upload resolves');

  resolveUpload();
  await uploadDone;
  const deleteCall = calls.find((c) => c.opts && c.opts.method === 'DELETE');
  assert.ok(deleteCall, 'once the deferred upload completes server-side, the now-orphaned document must be deleted, not silently kept with no visible chip to remove it from');
  assert.ok(deleteCall.url.includes('doc-999'));
});

test('Account change during upload: a successful upload is cleaned up server-side, never silently attached to the new account\'s view', async () => {
  const calls = [];
  const { sandbox, container } = buildSandbox({
    fetchImpl: async (url, opts) => {
      calls.push({ url, opts });
      if (url.includes('/api/docs/upload')) {
        sandbox._authToken = 'tok-2'; // a different account signs in WHILE this upload is in flight
        return { ok: true, status: 200, json: async () => ({ doc_id: 'doc-acct', filename: 'a.txt', chunks: 1, size_bytes: 5, session_id: 'sid-1' }) };
      }
      if (opts && opts.method === 'DELETE') return { ok: true, status: 200, json: async () => ({ deleted: true }) };
      return { ok: false, status: 404, json: async () => ({}) };
    },
  });
  sandbox.sessionId = 'sid-1';
  loadFns(sandbox);
  await sandbox.uploadAttachment({ name: 'a.txt' });
  const chip = container._children[0];
  assert.ok(chip._removed, 'a chip for a document uploaded under the PRIOR account must not linger in the new account\'s view');
  const deleteCall = calls.find((c) => c.opts && c.opts.method === 'DELETE');
  assert.ok(deleteCall, 'the document that finished uploading under the old account must be deleted, not left as an orphan the new account can never see');
});

test('Conversation change during upload: a successful upload is cleaned up server-side, never silently attached to the new conversation', async () => {
  const calls = [];
  const { sandbox, container } = buildSandbox({
    fetchImpl: async (url, opts) => {
      calls.push({ url, opts });
      if (url.includes('/api/docs/upload')) {
        sandbox.sessionId = 'sid-OTHER'; // the user switches conversations WHILE this upload is in flight
        return { ok: true, status: 200, json: async () => ({ doc_id: 'doc-conv', filename: 'a.txt', chunks: 1, size_bytes: 5, session_id: 'sid-1' }) };
      }
      if (opts && opts.method === 'DELETE') return { ok: true, status: 200, json: async () => ({ deleted: true }) };
      return { ok: false, status: 404, json: async () => ({}) };
    },
  });
  sandbox.sessionId = 'sid-1';
  loadFns(sandbox);
  await sandbox.uploadAttachment({ name: 'a.txt' });
  const chip = container._children[0];
  assert.ok(chip._removed, 'a chip uploaded into conversation A must not linger once the user has switched to conversation B');
  const deleteCall = calls.find((c) => c.opts && c.opts.method === 'DELETE');
  assert.ok(deleteCall, 'the document attached to the conversation the user left must be deleted, not silently orphaned');
});

test('Concurrent uploads to a new conversation: the sibling whose own session_id loses the adopt race is cleaned up, not silently merged into the winner', async () => {
  const calls = [];
  let resolveA, resolveB;
  const pendingA = new Promise((r) => { resolveA = r; });
  const pendingB = new Promise((r) => { resolveB = r; });
  const { sandbox, container } = buildSandbox({
    fetchImpl: async (url, opts) => {
      calls.push({ url, opts });
      if (url.includes('/api/docs/upload')) {
        // Each independently-started upload gets its OWN new backend
        // session, exactly like two real concurrent requests each
        // calling _get_session(session_id=None, ...) before either has
        // returned.
        if (!opts._isB) {
          await pendingA;
          return { ok: true, status: 200, json: async () => ({ doc_id: 'doc-A', filename: 'a.txt', chunks: 1, size_bytes: 5, session_id: 'sid-WON' }) };
        }
        await pendingB;
        return { ok: true, status: 200, json: async () => ({ doc_id: 'doc-B', filename: 'b.txt', chunks: 1, size_bytes: 5, session_id: 'sid-LOST' }) };
      }
      if (opts && opts.method === 'DELETE') return { ok: true, status: 200, json: async () => ({ deleted: true }) };
      return { ok: false, status: 404, json: async () => ({}) };
    },
  });
  sandbox.sessionId = null; // both uploads start against a brand-new conversation, before either has resolved
  loadFns(sandbox);

  // Both start while sessionId is still null -- genuine concurrency, not
  // a sequential call where the second would already see the first's
  // adopted sessionId.
  const uploadA = sandbox.uploadAttachment({ name: 'a.txt' });
  const origFetch = sandbox.fetch;
  sandbox.fetch = (url, opts) => origFetch(url, { ...opts, _isB: true });
  const uploadB = sandbox.uploadAttachment({ name: 'b.txt' });
  sandbox.fetch = origFetch;

  resolveA();
  await uploadA; // A resolves first and adopts sid-WON
  assert.equal(sandbox.sessionId, 'sid-WON');

  resolveB();
  await uploadB; // B's own session_id (sid-LOST) now does not match the already-adopted sessionId

  const deleteCall = calls.find((c) => c.opts && c.opts.method === 'DELETE');
  assert.ok(deleteCall, 'the sibling upload that created its own separate session must be cleaned up, not silently left attached to a session_id the frontend no longer tracks');
  assert.ok(deleteCall.url.includes('doc-B'));
  assert.equal(container._children.filter((c) => !c._removed).length, 1, 'only the winning upload\'s chip remains visible');
});

test('loadAttachmentsForSession() discards a stale response after a different account has since signed in', async () => {
  const container = makeFakeNode('div');
  const sandbox = {
    document: { getElementById: () => container, createElement: (tag) => makeFakeNode(tag) },
    sessionId: 'sid-1',
    _authToken: 'tok-1',
    _authHeaders: () => ({ Authorization: 'Bearer tok-1' }),
    _handleSessionExpired: () => { sandbox._sessionExpiredCalled = true; },
    fetch: async () => {
      sandbox._authToken = 'tok-2'; // a different account signs in while this list request is in flight
      return { ok: true, status: 200, json: async () => ({ docs: [{ doc_id: 'd1', filename: 'should-not-render.txt' }] }) };
    },
  };
  const escSrc = extractBalancedFunction(source, 'function esc(t) {').text;
  const renderSrc = extractBalancedFunction(source, 'function renderAttachChip(doc) {').text;
  const loadSrc = extractBalancedFunction(source, 'async function loadAttachmentsForSession() {').text;
  vm.createContext(sandbox);
  vm.runInContext(`${escSrc}\n${renderSrc}\n${loadSrc}`, sandbox);
  await sandbox.loadAttachmentsForSession();
  assert.equal(container._children.length, 0, 'a response that arrives after a different account signed in must never repaint the view with the prior account\'s documents');
  assert.notEqual(sandbox._sessionExpiredCalled, true, 'this is an ownership-staleness guard, not a session-expiry event');
});

// --- CTO security addendum: confirmed "stale 401 signs out a newer
// account" defect (reproduced live: alice's pending upload, resolving
// 401 AFTER bob signed in, genuinely signed bob back out), plus honest
// orphan-cleanup response handling ---

test('FIXED (confirmed, reproduced live): a stale 401 from an abandoned request never signs out the account that is current now', async () => {
  const calls = [];
  let resolveUpload;
  const pendingUpload = new Promise((r) => { resolveUpload = r; });
  const { sandbox, container } = buildSandbox({
    fetchImpl: async (url, opts) => {
      calls.push({ url, opts });
      if (url.includes('/api/docs/upload')) {
        await pendingUpload; // resolves AFTER bob signs in below
        return { ok: false, status: 401, json: async () => ({ error: 'Invalid or expired token' }) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    },
  });
  sandbox.sessionId = 'sid-alice';
  sandbox._authToken = 'tok-alice';
  loadFns(sandbox);

  const uploadPromise = sandbox.uploadAttachment({ name: 'alice-doc.txt' }); // captures myToken = 'tok-alice'
  sandbox._authToken = 'tok-bob'; // bob signs in while alice's upload is still pending -- a genuine account change
  resolveUpload();
  await uploadPromise;

  assert.equal(sandbox._authToken, 'tok-bob', 'alice\'s abandoned request\'s 401 must not clear bob\'s current token');
  assert.notEqual(sandbox._sessionExpiredCalled, true, 'before the fix, _handleSessionExpired() ran unconditionally on 401 here, genuinely signing bob back out for a 401 that belonged to alice\'s already-abandoned request');
});

test('removeAttachment() also checks account identity (myToken), not only sessionId, before acting on the DELETE response', () => {
  const fnSrc = extractBalancedFunction(source, 'async function removeAttachment(chip) {').text;
  assert.ok(fnSrc.includes('myToken !== _authToken'), 'an explicit account-identity check must guard the DELETE response, not rely only on sessionId resetting to null on an account change as an indirect guarantee');
});

test('openQuickSwitch() captures and checks account identity before acting on its response (confirmed gap: this call site had NO identity check at all)', () => {
  const fnSrc = extractBalancedFunction(source, 'async function openQuickSwitch() {').text;
  assert.ok(fnSrc.includes('const myToken = _authToken;'), 'must capture the principal at request start');
  const fetchIdx = fnSrc.indexOf("fetch('/api/sessions?limit=8'");
  const check401Idx = fnSrc.indexOf('r.status === 401');
  const identityCheckIdx = fnSrc.indexOf('myToken !== _authToken');
  assert.ok(fetchIdx !== -1 && check401Idx !== -1 && identityCheckIdx !== -1);
  assert.ok(fetchIdx < identityCheckIdx && identityCheckIdx < check401Idx, 'the identity check must run between the fetch resolving and the 401 branch, exactly where the confirmed defect was: a stale request\'s 401 reaching _handleSessionExpired() unconditionally');
});

test('_deleteOrphanedUpload() inspects the real DELETE response instead of assuming success', async () => {
  const fnSrc = extractBalancedFunction(source, 'async function _deleteOrphanedUpload(docId, sidForDelete, tokenForAuth) {').text;
  assert.ok(fnSrc.includes('if (r.ok) return;'), 'must check the real response ok flag before treating the deletion as confirmed');
  assert.ok(fnSrc.includes("r.status === 404"), 'an already-gone document (404) is a legitimate non-failure outcome, not an error to report');
  assert.ok(fnSrc.includes('console.warn'), 'a genuine failure (401/403/500/network) must be surfaced somehow -- there is no UI surface left, so silently discarding it would hide a real orphaned document from ever being found');
});

test('_deleteOrphanedUpload(): a 200 response is treated as success, with no warning logged', async () => {
  const warnings = [];
  const sandbox = { fetch: async () => ({ ok: true, status: 200, json: async () => ({ deleted: true }) }), console: { warn: (...a) => warnings.push(a) } };
  const fnSrc = extractBalancedFunction(source, 'async function _deleteOrphanedUpload(docId, sidForDelete, tokenForAuth) {').text;
  vm.createContext(sandbox);
  vm.runInContext(fnSrc, sandbox);
  await sandbox._deleteOrphanedUpload('doc-1', 'sid-1', 'tok-1');
  assert.equal(warnings.length, 0);
});

test('_deleteOrphanedUpload(): a 404 (already gone) is treated as a non-failure, with no warning logged', async () => {
  const warnings = [];
  const sandbox = { fetch: async () => ({ ok: false, status: 404, json: async () => ({ error: 'not_found' }) }), console: { warn: (...a) => warnings.push(a) } };
  const fnSrc = extractBalancedFunction(source, 'async function _deleteOrphanedUpload(docId, sidForDelete, tokenForAuth) {').text;
  vm.createContext(sandbox);
  vm.runInContext(fnSrc, sandbox);
  await sandbox._deleteOrphanedUpload('doc-1', 'sid-1', 'tok-1');
  assert.equal(warnings.length, 0);
});

for (const status of [401, 403, 500]) {
  test(`_deleteOrphanedUpload(): a real ${status} failure is logged, never silently discarded as success`, async () => {
    const warnings = [];
    const sandbox = { fetch: async () => ({ ok: false, status, json: async () => ({ error: 'failed' }) }), console: { warn: (...a) => warnings.push(a) } };
    const fnSrc = extractBalancedFunction(source, 'async function _deleteOrphanedUpload(docId, sidForDelete, tokenForAuth) {').text;
    vm.createContext(sandbox);
    vm.runInContext(fnSrc, sandbox);
    await sandbox._deleteOrphanedUpload('doc-1', 'sid-1', 'tok-1');
    assert.equal(warnings.length, 1, `a ${status} must be logged as a real, unresolved cleanup failure`);
  });
}

test('_deleteOrphanedUpload(): a network failure (connection drop / cancellation surfaced as a rejected fetch) is logged, never silently discarded', async () => {
  const warnings = [];
  const sandbox = { fetch: async () => { throw new TypeError('Failed to fetch'); }, console: { warn: (...a) => warnings.push(a) } };
  const fnSrc = extractBalancedFunction(source, 'async function _deleteOrphanedUpload(docId, sidForDelete, tokenForAuth) {').text;
  vm.createContext(sandbox);
  vm.runInContext(fnSrc, sandbox);
  await assert.doesNotReject(() => sandbox._deleteOrphanedUpload('doc-1', 'sid-1', 'tok-1'));
  assert.equal(warnings.length, 1, 'a network-level failure must also be logged, not swallowed as if cleanup succeeded');
});
