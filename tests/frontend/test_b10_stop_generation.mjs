// B10 Streaming & Stop regression tests.
//
// Source: docs/B10_IMPLEMENTATION_CONTRACT.md (ORNEUR_B10_FINAL_LOCK_AND_HANDOFF.zip,
// SHA-256 9920792a3112c98350a8e4d36e394df6d97ac2446c6ddb02c78a4ec4f75d9a06,
// verified against the archive's own verify_handoff.py, 53/53 files +
// 37/37 screenshots passing). B10's own "Critical race" section and its
// repeated warnings ("A mere HTTP 200 on a cancel request acceptance is
// not proof work stopped", "never claim 'Stopped'") originally led to a
// purely local, honest "interrupted" implementation, since no cancel
// endpoint existed in this backend at the time.
//
// INTEGRATION (2026-10-24, Phase B): Cursor's PR #92/#93 added real
// generation tracking (GET /api/generations/{id}, POST .../cancel).
// stopGeneration() now calls the real cancel endpoint and confirms the
// terminal state via a real GET before ever using the word "confirmed"
// -- still never claiming a bare "Stopped" state, and still falling
// back to the exact original honest local-abort-only message whenever
// no real generation id was ever issued (the frontier passthrough path)
// or the backend itself marked the run not cancellable (a replayed
// answer).
//
// Run with: node --test tests/frontend/test_b10_stop_generation.mjs
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

// --- Structural guards: the contract's own repeated instruction ---

test('INTEGRATION: the backend now has real cancel-confirmation infrastructure, and stopGeneration() uses it rather than ignoring it', () => {
  const apiPath = path.join(__dirname, '../../orca/serve/api.py');
  const api = fs.readFileSync(apiPath, 'utf8');
  const streamRouteIdx = api.indexOf('@app.post("/api/stream")');
  assert.ok(streamRouteIdx !== -1);
  const routeBody = api.slice(streamRouteIdx, streamRouteIdx + 20000);
  assert.ok(routeBody.includes('is_disconnected'), 'this is the exact condition the original test warned would make the honest-limitation copy stale -- confirms it has happened and the implementation below must account for it');
  assert.ok(api.includes('@app.get("/api/generations/{generation_id}")') && api.includes('@app.post("/api/generations/{generation_id}/cancel")'), 'real generation tracking and cancel routes must exist for stopGeneration() to use');
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  assert.ok(stopSrc.includes('/cancel') && stopSrc.includes('/api/generations/'), 'stopGeneration() must call the real cancel endpoint when a cancellable generation id is known');
});

test('stopGeneration() never sets the string "Stopped" as a standalone terminal claim', () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  // The word "stopped" (lowercase, as part of an honest, hedged sentence)
  // is fine and expected; a bare capitalized "Stopped" terminal label,
  // the exact overclaim the contract repeatedly warns against, must not
  // appear.
  assert.ok(!/[^a-zA-Z]Stopped[^a-zA-Z]/.test(stopSrc) && !stopSrc.includes("'Stopped'") && !stopSrc.includes('"Stopped"'), 'must not present an unconfirmed client-side abort as a confirmed server-side "Stopped" state');
  assert.ok(stopSrc.includes('confirmed') || stopSrc.includes('may still be completing'), 'must honestly hedge that backend cancellation is not confirmed');
});

test('stopGeneration() treats cancel_accepted alone as insufficient -- confirms via a real GET before ever using the word "confirmed"', () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  const cancelIdx = stopSrc.indexOf('/cancel');
  const getIdx = stopSrc.indexOf("fetch(`/api/generations/${encodeURIComponent(genId)}`");
  assert.ok(cancelIdx !== -1 && getIdx !== -1 && cancelIdx < getIdx, 'the cancel POST must be followed by a confirming GET, matching the contract\'s explicit "cancel_accepted:true is not proof the worker stopped" warning');
});

test('stopGeneration() falls back to the exact original local-only message when no cancellable generation id exists (frontier path / replayed answer)', () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  assert.ok(stopSrc.includes('!genId || !cancellable'), 'must explicitly guard the real-cancellation path behind both a known generation id AND the backend\'s own cancellable flag -- never invent server cancellation for a replayed/frontier answer');
});

test('_abandonActiveStream() is reused by stopGeneration(), not a second parallel cancellation mechanism', () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  assert.ok(stopSrc.includes('_abandonActiveStream()'), 'must reuse the existing, already-tested abort mechanism rather than duplicating one -- the local connection always ends immediately regardless of whether server confirmation is also sought');
});

test('the send control reaches the 44x44 CSS-px touch target on narrow viewports without resizing the visible glyph', () => {
  const idx = source.indexOf("@media(max-width:650px){.send::before{content:'';position:absolute;inset:-6px}}");
  assert.ok(idx !== -1, 'a -6px inset on a 32px control reaches 44px without changing the visible icon size -- the exact gap the B10 contract names ("Previous visual prototypes show 36px Stop control... production hit target... must meet accessibility standards")');
});

// --- Behavioral tests against the real functions, with a minimal fake DOM ---

function makeFakeContainer(lastAnswerHtml) {
  const children = [];
  if (lastAnswerHtml) {
    children.push({
      tagName: 'DIV',
      _html: lastAnswerHtml.html,
      querySelector: (sel) => {
        if (sel === '.thinking') return lastAnswerHtml.hasThinking ? {} : null;
        if (sel === '.msg-body') return lastAnswerHtml.hasMsgBody ? { querySelector: () => null, appendChild: () => {} } : null;
        return null;
      },
      remove: () => { lastAnswerHtml.removed = true; },
    });
  }
  return {
    querySelector: (sel) => (sel === '.answer:last-child' ? children[0] || null : null),
  };
}

function baseSandbox(overrides) {
  return Object.assign({
    _activeGenerationId: null,
    _activeGenerationCancellable: false,
    _authToken: 'tok-1',
    _authHeaders: () => ({ Authorization: 'Bearer tok-1' }),
    fetch: async () => { throw new Error('no cancellable generation id -- fetch must not be called'); },
  }, overrides);
}

test('stopGeneration() removes the thinking placeholder and appends an honest note when no content ever arrived (no real generation id)', async () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  const lastAnswer = { html: '', hasThinking: true, hasMsgBody: false, removed: false };
  let notedMessage = null;
  const sandbox = baseSandbox({
    isStreaming: true,
    document: { getElementById: (id) => (id === 'reading-container' ? makeFakeContainer(lastAnswer) : null) },
    _abandonActiveStream: () => { sandbox.isStreaming = false; },
    appendUnavailableNote: (msg) => { notedMessage = msg; },
    markMessageInterrupted: () => { throw new Error('must not be called when there was never any content'); },
  });
  vm.createContext(sandbox);
  vm.runInContext(stopSrc, sandbox);
  await sandbox.stopGeneration();
  assert.equal(lastAnswer.removed, true, 'the empty thinking placeholder must be removed, not marked, since there is no partial content to preserve');
  assert.ok(notedMessage && notedMessage.includes('stopped'), 'must show an honest note that generation was stopped client-side');
});

test('stopGeneration() marks partial content as interrupted (reusing the existing honest badge) rather than removing it (no real generation id)', async () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  const lastAnswer = { html: 'partial', hasThinking: false, hasMsgBody: true, removed: false };
  let markedEl = null, markedReason = null;
  const sandbox = baseSandbox({
    isStreaming: true,
    document: { getElementById: (id) => (id === 'reading-container' ? makeFakeContainer(lastAnswer) : null) },
    _abandonActiveStream: () => { sandbox.isStreaming = false; },
    appendUnavailableNote: () => { throw new Error('must not discard partial content with a generic note'); },
    markMessageInterrupted: (el, reason) => { markedEl = el; markedReason = reason; },
  });
  vm.createContext(sandbox);
  vm.runInContext(stopSrc, sandbox);
  await sandbox.stopGeneration();
  assert.equal(lastAnswer.removed, false, 'partial content must be preserved, not removed');
  assert.ok(markedEl && markedEl._html === 'partial', 'must mark the actual answer element that holds the partial content');
  assert.ok(markedReason && markedReason.toLowerCase().includes('stopped'), 'the interrupted badge must honestly say this was a stop, not a generic dropped connection');
});

test('stopGeneration() falls back to the local-only message even with a generation id, when the backend marked it not cancellable (replayed answer)', async () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  const lastAnswer = { html: 'partial', hasThinking: false, hasMsgBody: true, removed: false };
  let markedReason = null;
  const sandbox = baseSandbox({
    isStreaming: true,
    _activeGenerationId: 'gen-123',
    _activeGenerationCancellable: false, // replayed Truth Fabric answer
    document: { getElementById: (id) => (id === 'reading-container' ? makeFakeContainer(lastAnswer) : null) },
    _abandonActiveStream: () => { sandbox.isStreaming = false; },
    markMessageInterrupted: (el, reason) => { markedReason = reason; },
  });
  vm.createContext(sandbox);
  vm.runInContext(stopSrc, sandbox);
  await sandbox.stopGeneration();
  assert.ok(markedReason && markedReason.includes('confirmed stop is not available'), 'must never invent server cancellation for a non-cancellable (replayed) generation, even though a real generation id exists');
});

test('stopGeneration(): real cancellable generation, server confirms "cancelled" -- the only path allowed to say "confirmed"', async () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  const lastAnswer = { html: 'partial', hasThinking: false, hasMsgBody: true, removed: false };
  let markedReason = null;
  const calls = [];
  const sandbox = baseSandbox({
    isStreaming: true,
    _activeGenerationId: 'gen-456',
    _activeGenerationCancellable: true,
    document: { getElementById: (id) => (id === 'reading-container' ? makeFakeContainer(lastAnswer) : null) },
    _abandonActiveStream: () => { sandbox.isStreaming = false; },
    markMessageInterrupted: (el, reason) => { markedReason = reason; },
    fetch: async (url, opts) => {
      calls.push(url);
      if (url.includes('/cancel')) return { ok: true, status: 200, json: async () => ({ cancel_accepted: true, code: 'cancel_requested', state: 'running' }) };
      return { ok: true, status: 200, json: async () => ({ generation_id: 'gen-456', state: 'cancelled', terminal: true }) };
    },
  });
  vm.createContext(sandbox);
  vm.runInContext(stopSrc, sandbox);
  await sandbox.stopGeneration();
  assert.equal(calls.length, 2, 'must call cancel, then a confirming GET');
  assert.ok(markedReason && markedReason.includes('confirmed cancellation'), 'only a real GET showing state:"cancelled" may use the word "confirmed"');
});

test('stopGeneration(): cancel_accepted alone (state still "running" on the confirming GET) must not be presented as a confirmed stop', async () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  const lastAnswer = { html: 'partial', hasThinking: false, hasMsgBody: true, removed: false };
  let markedReason = null;
  const sandbox = baseSandbox({
    isStreaming: true,
    _activeGenerationId: 'gen-789',
    _activeGenerationCancellable: true,
    document: { getElementById: (id) => (id === 'reading-container' ? makeFakeContainer(lastAnswer) : null) },
    _abandonActiveStream: () => { sandbox.isStreaming = false; },
    markMessageInterrupted: (el, reason) => { markedReason = reason; },
    fetch: async (url) => {
      if (url.includes('/cancel')) return { ok: true, status: 200, json: async () => ({ cancel_accepted: true, code: 'cancel_requested', state: 'running' }) };
      return { ok: true, status: 200, json: async () => ({ generation_id: 'gen-789', state: 'running', terminal: false }) }; // heartbeat still current
    },
  });
  vm.createContext(sandbox);
  vm.runInContext(stopSrc, sandbox);
  await sandbox.stopGeneration();
  assert.ok(markedReason && !markedReason.includes('confirmed cancellation'), 'cancel_accepted:true is explicitly not proof the worker stopped -- must not claim a confirmed stop');
  assert.ok(markedReason && markedReason.includes('has not yet confirmed'), 'must honestly say confirmation is still pending');
});

test('stopGeneration(): generation actually completed before the cancel reached the server -- shown honestly, not labeled "stopped" as if cancellation worked', async () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  const lastAnswer = { html: 'partial', hasThinking: false, hasMsgBody: true, removed: false };
  let markedReason = null;
  const sandbox = baseSandbox({
    isStreaming: true,
    _activeGenerationId: 'gen-done',
    _activeGenerationCancellable: true,
    document: { getElementById: (id) => (id === 'reading-container' ? makeFakeContainer(lastAnswer) : null) },
    _abandonActiveStream: () => { sandbox.isStreaming = false; },
    markMessageInterrupted: (el, reason) => { markedReason = reason; },
    fetch: async (url) => {
      if (url.includes('/cancel')) return { ok: true, status: 200, json: async () => ({ cancel_accepted: false, code: 'generation_already_terminal' }) };
      return { ok: true, status: 200, json: async () => ({ generation_id: 'gen-done', state: 'completed', terminal: true }) };
    },
  });
  vm.createContext(sandbox);
  vm.runInContext(stopSrc, sandbox);
  await sandbox.stopGeneration();
  assert.ok(markedReason && markedReason.includes('finished generating'), 'must say the run actually completed, not that it was stopped');
});

test('stopGeneration() is a no-op when nothing is streaming', async () => {
  const stopSrc = extractBalancedFunction(source, 'async function stopGeneration() {').text;
  let abandonCalled = false;
  const sandbox = baseSandbox({
    isStreaming: false,
    document: { getElementById: () => { throw new Error('must not touch the DOM when there is nothing to stop'); } },
    _abandonActiveStream: () => { abandonCalled = true; },
  });
  vm.createContext(sandbox);
  vm.runInContext(stopSrc, sandbox);
  await sandbox.stopGeneration();
  assert.equal(abandonCalled, false);
});

test('updateSendEnabled() swaps the control to Stop mode while streaming, always enabled', () => {
  const updateSendSrc = extractBalancedFunction(source, 'function updateSendEnabled() {').text;
  const btn = { _classes: new Set(), title: '', innerHTML: '', _attrs: {},
    classList: { add: (c) => btn._classes.add(c), remove: (c) => btn._classes.delete(c), toggle: (c, f) => { if (f) btn._classes.add(c); else btn._classes.delete(c); }, contains: (c) => btn._classes.has(c) },
    setAttribute: (k, v) => { btn._attrs[k] = v; } };
  const input = { value: '' };
  const composerEl = { querySelector: (sel) => (sel === '#msg-input' ? input : sel === '#send-btn' ? btn : null) };
  const sandbox = { composerEl, isStreaming: true, selectedModelVariant: null, SEND_ICON_SVG: 'SEND', STOP_ICON_SVG: 'STOP' };
  vm.createContext(sandbox);
  vm.runInContext(updateSendSrc, sandbox);
  sandbox.updateSendEnabled();
  assert.equal(btn._classes.has('disabled'), false, 'the Stop control must stay clickable even with no text/model selected');
  assert.equal(btn._classes.has('stop-mode'), true);
  assert.equal(btn._attrs['aria-label'], 'Stop generating response');
});
