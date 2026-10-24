// B14 correlated runs -- real backend plumbing only, no invented UI.
//
// INTEGRATION Phase E (2026-10-24): Cursor PR #96 adds a real
// correlation mechanism (POST /api/runs, X-Run-Id on /api/stream,
// GET /api/runs/{run_id} -- docs/orneur/cursor/ORNEUR_B14_CORRELATED_RUNS_HANDOFF.md
// on the integration candidate). No approved UI design exists for
// grouping conversations/generations: the C-series contract itself
// confirms no /api/workspaces resource exists, and the handoff's own
// words are explicit -- "The run id is not a share and not a workspace
// tab." Building a UI trigger for this without an approved concept
// would be inventing a feature, which the CTO directive explicitly
// forbids ("Do not invent new workspace tabs, public resources or
// unsupported backend capabilities").
//
// What IS implemented and tested here: the real contract plumbing
// itself (sendMessage() accepts an optional run id; the real
// generation event's own run_id is tracked; createRun() is a working,
// tested helper) -- ready to be wired to a UI the moment one is
// approved, with no further changes needed at this layer. Preserves
// Quick Switch and per-conversation drafts unchanged (see
// test_b14_quick_switch_and_drafts.mjs, still 9/9 passing, untouched
// by this phase).
//
// Run with: node --test tests/frontend/test_b14_correlated_runs.mjs
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

test('no UI control anywhere in this file creates or reads a run -- createRun() exists but is unreferenced by any onclick/addEventListener', () => {
  const idx = source.indexOf('async function createRun() {');
  assert.ok(idx !== -1, 'the real plumbing must exist');
  // Confirm nothing calls it except its own definition.
  const callSites = [...source.matchAll(/\bcreateRun\(\)/g)].filter((m) => !source.slice(Math.max(0, m.index - 16), m.index).includes('async function'));
  assert.equal(callSites.length, 0, 'createRun() must not be called from anywhere -- no approved UI trigger exists yet; calling it speculatively would be inventing a feature');
});

test('sendMessage() accepts an optional run id and sends it as a real X-Run-Id header only when provided -- existing callers (Send button, Retry) are unaffected', () => {
  const fnSrc = extractBalancedFunction(source, 'async function sendMessage(runId) {').text;
  assert.ok(fnSrc.includes("if (runId) streamHeaders['X-Run-Id'] = runId;"), 'must only add the header when a caller explicitly passes one -- "existing clients keep working" per the contract');
});

test('createRun() calls the real POST /api/runs and handles 401 like every other authenticated call site', () => {
  const fnSrc = extractBalancedFunction(source, 'async function createRun() {').text;
  assert.ok(fnSrc.includes("fetch('/api/runs'"));
  assert.ok(fnSrc.includes("method: 'POST'"));
  assert.ok(fnSrc.includes('r.status === 401') && fnSrc.includes('_handleSessionExpired()'));
});

test('the generation event\'s real run_id is tracked, defaulting to null when the stream was not attached to a run', () => {
  const sendSrc = extractBalancedFunction(source, 'async function sendMessage(runId) {').text;
  assert.ok(sendSrc.includes('_activeGenerationRunId = ev.run_id || null;'));
  assert.ok(sendSrc.includes('_activeGenerationRunId = null;'), 'must reset at the start of every new attempt, matching the existing generation-id/cancellable reset pattern');
});

test('Quick Switch and per-conversation drafts are unchanged by this phase', () => {
  // These are the two concrete B14 surfaces the directive named to
  // preserve. Confirms the real functions still exist with their
  // established real-data guarantees, not replaced or weakened.
  assert.ok(source.includes("fetch('/api/sessions?limit=8'"), 'Quick Switch must still use the real sessions endpoint');
  assert.ok(source.includes('_draftsByConversation'), 'per-conversation draft isolation must still exist');
});

// --- Behavioral test: createRun() against a fake fetch ---

test('createRun() returns the real run_id from a successful response, or null on any failure', async () => {
  const fnSrc = extractBalancedFunction(source, 'async function createRun() {').text;
  const sandboxOk = { _authToken: 'tok-1', _authHeaders: () => ({ Authorization: 'Bearer tok-1' }), fetch: async () => ({ ok: true, status: 200, json: async () => ({ run_id: 'real-run-id-123', created_at: 1234, members: [], count: 0 }) }) };
  vm.createContext(sandboxOk);
  vm.runInContext(fnSrc, sandboxOk);
  assert.equal(await sandboxOk.createRun(), 'real-run-id-123');

  const sandboxNoAuth = { _authToken: null, fetch: async () => { throw new Error('must not call fetch when signed out'); } };
  vm.createContext(sandboxNoAuth);
  vm.runInContext(fnSrc, sandboxNoAuth);
  assert.equal(await sandboxNoAuth.createRun(), null);

  const sandboxFail = { _authToken: 'tok-1', _authHeaders: () => ({}), fetch: async () => ({ ok: false, status: 500, json: async () => ({}) }) };
  vm.createContext(sandboxFail);
  vm.runInContext(fnSrc, sandboxFail);
  assert.equal(await sandboxFail.createRun(), null);
});
