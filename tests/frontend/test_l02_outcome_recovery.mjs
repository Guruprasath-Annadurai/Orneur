// LANDMARK-02 L02-03: after a dropped connection the page must say only what the SERVER reported about the request, and must not invite a duplicate send.
// fetchTurnOutcome / reconcileOutcome / stopGeneration are extracted verbatim from orca/serve/web/conversation.html and run against stubbed page state.
//
// Run with: node --test tests/frontend/test_l02_outcome_recovery.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(__dirname, '../../orca/serve/web/conversation.html'), 'utf8');

function extractFunction(src, marker) {
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`marker not found: ${marker}`);
  let depth = 0, i = src.indexOf('{', start);
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) break;
  }
  return src.slice(start, i + 1);
}

function page({ outcomes, token = 't' }) {
  const calls = { fetch: [], notes: [], opened: [], expired: 0 };
  const queue = [...outcomes];
  const ctx = {
    _authToken: token, _authHeaders: () => ({ Authorization: 'Bearer t' }), encodeURIComponent,
    _handleSessionExpired: () => { calls.expired++; },
    appendUnavailableNote: (msg, opts) => calls.notes.push({ msg, retry: !!(opts && opts.retryText) }),
    openSession: async (sid, title) => { calls.opened.push(sid); },
    document: { getElementById: (id) => (id === 'conv-title' ? { textContent: 'T' } : { querySelector: () => null }) },
    setTimeout: (fn) => { fn(); return 0; },                       // no real waiting in the test
    fetch: async (url, init) => {
      calls.fetch.push({ url, method: (init && init.method) || 'GET' });
      const next = queue.length > 1 ? queue.shift() : queue[0];
      if (next === 'THROW') throw new Error('network');
      return { status: next.http || 200, ok: (next.http || 200) < 400, json: async () => next.body };
    },
  };
  vm.createContext(ctx);
  vm.runInContext([extractFunction(source, 'async function fetchTurnOutcome('), extractFunction(source, 'async function reconcileOutcome(')].join('\n') +
    '\nthis.reconcileOutcome = reconcileOutcome; this.fetchTurnOutcome = fetchTurnOutcome;', ctx);
  return { ctx, calls };
}

test('committed: the saved conversation is shown and the page says it was saved - no failure message, no retry offered', async () => {
  const { ctx, calls } = page({ outcomes: [{ body: { state: 'committed', session_id: 'S1' } }] });
  await ctx.reconcileOutcome('k', 'hello');
  assert.deepEqual(calls.opened, ['S1']);
  assert.match(calls.notes[0].msg, /were saved/);
  assert.equal(calls.notes[0].retry, false);
});

test('not committed / superseded / never received: says nothing was saved and offers Retry', async () => {
  for (const state of ['not_committed', 'superseded', 'unknown']) {
    const { ctx, calls } = page({ outcomes: [{ body: { state } }] });
    await ctx.reconcileOutcome('k', 'hello');
    assert.match(calls.notes[0].msg, /Nothing|did not save/i, state);
    assert.equal(calls.notes[0].retry, true, state);
    assert.deepEqual(calls.opened, [], state);
  }
});

test('cancelled is reported as confirmed only when the server says cancelled', async () => {
  const { ctx, calls } = page({ outcomes: [{ body: { state: 'cancelled' } }] });
  await ctx.reconcileOutcome('k', 'hello');
  assert.match(calls.notes[0].msg, /server confirmed/);
});

test('still running: polls, then tells the user to wait - and does NOT offer Retry (it could duplicate the turn)', async () => {
  const { ctx, calls } = page({ outcomes: [{ body: { state: 'running' } }] });
  await ctx.reconcileOutcome('k', 'hello');
  assert.equal(calls.fetch.length, 8, 'bounded polling');
  assert.match(calls.notes[0].msg, /still working/);
  assert.equal(calls.notes[0].retry, false);
});

test('running then committed: the poll picks up the final state', async () => {
  const { ctx, calls } = page({ outcomes: [{ body: { state: 'running' } }, { body: { state: 'running' } }, { body: { state: 'committed', session_id: 'S2' } }] });
  await ctx.reconcileOutcome('k', 'hello');
  assert.equal(calls.fetch.length, 3);
  assert.deepEqual(calls.opened, ['S2']);
});

test('outcome unreadable (503 or network): says it cannot confirm, tells the user to check, and does NOT offer Retry', async () => {
  for (const o of [{ http: 503, body: { state: 'outcome_unknown' } }, 'THROW']) {
    const { ctx, calls } = page({ outcomes: [o] });
    await ctx.reconcileOutcome('k', 'hello');
    assert.match(calls.notes[0].msg, /could not confirm/);
    assert.equal(calls.notes[0].retry, false);
  }
});

test('an expired login during reconciliation is handled as an expired login, not as a failed turn', async () => {
  const { ctx, calls } = page({ outcomes: [{ http: 401, body: {} }] });
  await ctx.reconcileOutcome('k', 'hello');
  assert.equal(calls.expired, 1);
  assert.equal(calls.notes.length, 0);
});

test('the page asks the server (GET /api/turns/<key>) on both drop paths of sendMessage, only for signed-in users', () => {
  const eof = source.indexOf("await reconcileOutcome(myIdempotencyKey, text); // L02-03: ask the server what happened");
  const net = source.indexOf("await reconcileOutcome(myIdempotencyKey, text); // L02-03: a network error is not the same");
  assert.ok(eof > 0 && net > 0, 'both the EOF-without-done path and the thrown-error path reconcile');
  assert.match(source.slice(eof - 200, eof), /if \(_authToken\)/);
  assert.match(source.slice(net - 200, net), /if \(_authToken\)/);
  assert.match(source, /_activeRequestKey = myIdempotencyKey;/);
});

function stopHarness({ key, outcome }) {
  const calls = { fetch: [], notes: [], opened: [], abandonedAt: -1 };
  const lastAnswer = { querySelector: () => null, remove() {} };
  const ctx = {
    isStreaming: true, _activeGenerationId: null, _activeGenerationCancellable: false, _activeStreamUpstream: true, _activeRequestKey: key, _authToken: 't',
    document: { getElementById: () => ({ querySelector: () => lastAnswer }) },
    _abandonActiveStream: () => { calls.abandonedAt = calls.fetch.length; },
    markMessageInterrupted: () => {}, appendUnavailableNote: (m) => calls.notes.push(m),
    fetchTurnOutcome: async () => outcome, openSession: (sid) => calls.opened.push(sid),
    fetch: async (url, init) => { calls.fetch.push({ url, method: init && init.method, keepalive: init && init.keepalive }); return { ok: true, json: async () => ({}) }; },
    _authHeaders: () => ({}), encodeURIComponent,
  };
  vm.createContext(ctx);
  vm.runInContext(extractFunction(source, 'async function stopGeneration()') + '\nthis.stopGeneration = stopGeneration;', ctx);
  return { ctx, calls };
}

test('Stop tells the server (POST /api/turns/<key>/cancel, keepalive) BEFORE the local connection is closed', async () => {
  const { ctx, calls } = stopHarness({ key: 'req-1', outcome: { state: 'cancelled' } });
  await ctx.stopGeneration();
  await new Promise((r) => setImmediate(r));
  assert.equal(calls.fetch[0].url, '/api/turns/req-1/cancel');
  assert.equal(calls.fetch[0].method, 'POST');
  assert.equal(calls.fetch[0].keepalive, true);
  assert.equal(calls.abandonedAt, 1, 'the cancel request was issued before the stream was abandoned');
});

test('Stop that lost the race to the commit corrects the "not saved" sentence and shows the saved conversation', async () => {
  const { ctx, calls } = stopHarness({ key: 'req-2', outcome: { state: 'committed', session_id: 'S9' } });
  await ctx.stopGeneration();
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  assert.ok(calls.notes.some((m) => /already finished and was saved/.test(m)));
  assert.deepEqual(calls.opened, ['S9']);
});

test('Stop with no request key (anonymous) sends no cancel request and keeps the existing wording path', async () => {
  const { ctx, calls } = stopHarness({ key: null, outcome: { state: 'unknown' } });
  await ctx.stopGeneration();
  assert.equal(calls.fetch.length, 0);
});

// ── L02-04: the sign-in / sign-up handlers must show what the server said, never "[object Object]", and must not treat a verification-required signup as a session ──
test('sign-in and sign-up handlers print structured refusals as text and handle verification_required without a session', () => {
  assert.match(source, /typeof d\.detail === 'string' \? d\.detail : \(d\.detail && d\.detail\.error\) \|\| d\.error/);
  const signup = extractFunction(source, 'async function doSignup()');
  const guard = signup.indexOf("d.status === 'verification_required'");
  const success = signup.indexOf('onAuthSuccess(d)');
  assert.ok(guard > 0 && success > guard, 'the verification_required branch must return before onAuthSuccess');
});
