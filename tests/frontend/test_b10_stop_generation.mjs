// B10 Streaming & Stop regression tests.
//
// Source: docs/B10_IMPLEMENTATION_CONTRACT.md (ORNEUR_B10_FINAL_LOCK_AND_HANDOFF.zip,
// SHA-256 9920792a3112c98350a8e4d36e394df6d97ac2446c6ddb02c78a4ec4f75d9a06,
// verified against the archive's own verify_handoff.py, 53/53 files +
// 37/37 screenshots passing). B10's own "Critical race" section and its
// repeated warnings ("A mere HTTP 200 on a cancel request acceptance is
// not proof work stopped", "never claim 'Stopped'") are the reason this
// phase deliberately reuses the SAME honest "interrupted" semantics
// already established for a genuine dropped connection, rather than
// inventing a confirmed-"Stopped" terminal state the real /api/stream
// handler cannot back up -- grepped orca/serve/api.py: no
// request.is_disconnected() check and no dedicated cancel endpoint with
// a server-acknowledged terminal state exist for this route.
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

test('the /api/stream backend has no observed cancel-confirmation path -- stopGeneration() must not claim a confirmed "Stopped" state', () => {
  const apiPath = path.join(__dirname, '../../orca/serve/api.py');
  const api = fs.readFileSync(apiPath, 'utf8');
  const streamRouteIdx = api.indexOf('@app.post("/api/stream")');
  assert.ok(streamRouteIdx !== -1);
  const routeBody = api.slice(streamRouteIdx, streamRouteIdx + 6000);
  assert.ok(!routeBody.includes('is_disconnected'), 'if a disconnect check is added later, stopGeneration()\'s honest-limitation comment and copy must be revisited, not left claiming an unconfirmed stop');
});

test('stopGeneration() never sets the string "Stopped" as a standalone terminal claim', () => {
  const stopSrc = extractBalancedFunction(source, 'function stopGeneration() {').text;
  // The word "stopped" (lowercase, as part of an honest, hedged sentence)
  // is fine and expected; a bare capitalized "Stopped" terminal label,
  // the exact overclaim the contract repeatedly warns against, must not
  // appear.
  assert.ok(!/[^a-zA-Z]Stopped[^a-zA-Z]/.test(stopSrc) && !stopSrc.includes("'Stopped'") && !stopSrc.includes('"Stopped"'), 'must not present an unconfirmed client-side abort as a confirmed server-side "Stopped" state');
  assert.ok(stopSrc.includes('confirmed') || stopSrc.includes('may still be completing'), 'must honestly hedge that backend cancellation is not confirmed');
});

test('_abandonActiveStream() is reused by stopGeneration(), not a second parallel cancellation mechanism', () => {
  const stopSrc = extractBalancedFunction(source, 'function stopGeneration() {').text;
  assert.ok(stopSrc.includes('_abandonActiveStream()'), 'must reuse the existing, already-tested abort mechanism rather than duplicating one');
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

test('stopGeneration() removes the thinking placeholder and appends an honest note when no content ever arrived', () => {
  const stopSrc = extractBalancedFunction(source, 'function stopGeneration() {').text;
  const lastAnswer = { html: '', hasThinking: true, hasMsgBody: false, removed: false };
  let notedMessage = null;
  const sandbox = {
    isStreaming: true,
    document: { getElementById: (id) => (id === 'reading-container' ? makeFakeContainer(lastAnswer) : null) },
    _abandonActiveStream: () => { sandbox.isStreaming = false; },
    appendUnavailableNote: (msg) => { notedMessage = msg; },
    markMessageInterrupted: () => { throw new Error('must not be called when there was never any content'); },
  };
  vm.createContext(sandbox);
  vm.runInContext(stopSrc, sandbox);
  sandbox.stopGeneration();
  assert.equal(lastAnswer.removed, true, 'the empty thinking placeholder must be removed, not marked, since there is no partial content to preserve');
  assert.ok(notedMessage && notedMessage.includes('stopped'), 'must show an honest note that generation was stopped client-side');
});

test('stopGeneration() marks partial content as interrupted (reusing the existing honest badge) rather than removing it', () => {
  const stopSrc = extractBalancedFunction(source, 'function stopGeneration() {').text;
  const lastAnswer = { html: 'partial', hasThinking: false, hasMsgBody: true, removed: false };
  let markedEl = null, markedReason = null;
  const sandbox = {
    isStreaming: true,
    document: { getElementById: (id) => (id === 'reading-container' ? makeFakeContainer(lastAnswer) : null) },
    _abandonActiveStream: () => { sandbox.isStreaming = false; },
    appendUnavailableNote: () => { throw new Error('must not discard partial content with a generic note'); },
    markMessageInterrupted: (el, reason) => { markedEl = el; markedReason = reason; },
  };
  vm.createContext(sandbox);
  vm.runInContext(stopSrc, sandbox);
  sandbox.stopGeneration();
  assert.equal(lastAnswer.removed, false, 'partial content must be preserved, not removed');
  assert.ok(markedEl && markedEl._html === 'partial', 'must mark the actual answer element that holds the partial content');
  assert.ok(markedReason && markedReason.toLowerCase().includes('stopped'), 'the interrupted badge must honestly say this was a stop, not a generic dropped connection');
});

test('stopGeneration() is a no-op when nothing is streaming', () => {
  const stopSrc = extractBalancedFunction(source, 'function stopGeneration() {').text;
  let abandonCalled = false;
  const sandbox = {
    isStreaming: false,
    document: { getElementById: () => { throw new Error('must not touch the DOM when there is nothing to stop'); } },
    _abandonActiveStream: () => { abandonCalled = true; },
  };
  vm.createContext(sandbox);
  vm.runInContext(stopSrc, sandbox);
  sandbox.stopGeneration();
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
