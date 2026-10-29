// LANDMARK-01 B-01: what Stop is allowed to SAY depends on what the server announced for this request.
//   - a real upstream stream (stream event: delivery 'upstream', cancellable true) -> "model connection was closed ... not saved"; no cancel endpoint call
//   - no such announcement                                                          -> the original, modest "may still be completing" wording
// stopGeneration() is extracted verbatim from orca/serve/web/conversation.html and run against stubbed page state; the SSE `stream` handler is checked in the
// source (it lives inside sendMessage's closure, which cannot be extracted).
//
// Run with: node --test tests/frontend/test_b01_stop_upstream.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(__dirname, '../../orca/serve/web/conversation.html'), 'utf8');

function extractAsyncFunction(src, marker) {
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`marker not found: ${marker}`);
  let depth = 0, i = src.indexOf('{', start);
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) break;
  }
  return src.slice(start, i + 1);
}

function harness({ upstream, genId = null, cancellable = false, thinkingOnly = false }) {
  const calls = { fetch: [], interrupted: [], unavailable: [], abandoned: 0, removed: 0 };
  const lastAnswer = {
    querySelector: (sel) => (sel === '.thinking' && thinkingOnly ? {} : null),
    remove: () => { calls.removed++; },
  };
  const ctx = {
    isStreaming: true,
    _activeGenerationId: genId, _activeGenerationCancellable: cancellable, _activeStreamUpstream: upstream, _authToken: 't',
    document: { getElementById: () => ({ querySelector: () => lastAnswer }) },
    _abandonActiveStream: () => { calls.abandoned++; },
    markMessageInterrupted: (_div, reason) => calls.interrupted.push(reason),
    appendUnavailableNote: (reason) => calls.unavailable.push(reason),
    fetch: async (...a) => { calls.fetch.push(a); return { ok: true, json: async () => ({ state: 'cancelled' }) }; },
    _authHeaders: () => ({}),
    encodeURIComponent,
  };
  vm.createContext(ctx);
  vm.runInContext(extractAsyncFunction(source, 'async function stopGeneration()') + '\nthis.stopGeneration = stopGeneration;', ctx);
  return { ctx, calls };
}

test('Stop on a real upstream stream says the model connection was closed and the partial reply was not saved', async () => {
  const { ctx, calls } = harness({ upstream: true });
  await ctx.stopGeneration();
  assert.equal(calls.abandoned, 1, 'the browser read is ended immediately');
  assert.equal(calls.fetch.length, 0, 'there is no cancel endpoint to call: closing the connection IS the cancellation');
  assert.equal(calls.interrupted.length, 1);
  assert.match(calls.interrupted[0], /model connection was closed/);
  assert.match(calls.interrupted[0], /not saved/);
  assert.doesNotMatch(calls.interrupted[0], /may still be completing/);
});

test('Stop without an upstream announcement keeps the original modest wording and claims nothing confirmed', async () => {
  const { ctx, calls } = harness({ upstream: false });
  await ctx.stopGeneration();
  assert.equal(calls.fetch.length, 0);
  assert.match(calls.interrupted[0], /may still be completing on the server/);
  assert.doesNotMatch(calls.interrupted[0], /model connection was closed/);
});

test('Stop before any text was rendered removes the placeholder and explains, instead of marking nothing', async () => {
  const { ctx, calls } = harness({ upstream: true, thinkingOnly: true });
  await ctx.stopGeneration();
  assert.equal(calls.removed, 1);
  assert.equal(calls.interrupted.length, 0);
  assert.match(calls.unavailable[0], /model connection was closed/);
});

test('Stop when nothing is streaming does nothing', async () => {
  const { ctx, calls } = harness({ upstream: true });
  ctx.isStreaming = false;
  await ctx.stopGeneration();
  assert.equal(calls.abandoned, 0);
  assert.equal(calls.interrupted.length + calls.unavailable.length, 0);
});

test('the SSE reader records the stream announcement, and only an upstream+cancellable one', () => {
  assert.match(source, /ev\.type === 'stream'/);
  assert.match(source, /_activeStreamUpstream = ev\.delivery === 'upstream' && ev\.cancellable === true/);
  // reset for every new request, so a previous request's announcement can never colour the next Stop
  assert.match(source, /_activeGenerationCancellable = false;\s*\n\s*_activeStreamUpstream = false;/);
});
