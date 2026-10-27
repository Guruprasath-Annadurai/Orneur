// AUDIT-B81-A-P1-01 regression test for the request-ownership primitive
// itself (_streamEpoch / _abandonActiveStream), extracted verbatim from
// orca/serve/web/conversation.html.
//
// Scope note (honest, disclosed limitation): this proves the OWNERSHIP
// PRIMITIVE sendMessage() is built on -- epoch increments monotonically,
// _abandonActiveStream() invalidates the current owner and resets
// isStreaming/_activeStreamController immediately, and an AbortController
// is actually aborted. It does NOT re-run the full sendMessage()/
// newConversation()/openSession() integration end-to-end, because that
// requires mounting the real composer (a <template> + DocumentFragment)
// -- not something a hand-rolled DOM stub can faithfully replicate
// without becoming a second, drift-prone implementation of the browser
// itself.
// The actual end-to-end scenario (send -> new conversation mid-stream ->
// delayed session/chunk events must not mutate sessionId or the DOM) was
// verified directly in a real running browser against the real backend,
// A/B'd against the pre-fix file to confirm it reproduces the defect and
// the fix closes it -- see the engineering report for the exact
// before/after JSON evidence captured from that session.
//
// Run with: node tests/frontend/test_stream_ownership_epoch.mjs
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

const epochDeclIdx = source.indexOf('let _streamEpoch = 0;');
const controllerDeclIdx = source.indexOf('let _activeStreamController = null;', epochDeclIdx);
const abandonFn = extractBalancedFunction(source, 'function _abandonActiveStream() {', controllerDeclIdx);

let abortCalls = 0;
const sandbox = {
  isStreaming: false,
  updateSendEnabled: () => {},
};
vm.createContext(sandbox);
// var (not let/const) so these end up as real properties on the sandbox
// object -- vm.runInContext does not reflect top-level let/const
// bindings onto the context object, only var and function declarations.
vm.runInContext(
  `var _streamEpoch = 0;\nvar _activeStreamController = null;\n${abandonFn.text}`,
  sandbox,
);

test('_streamEpoch starts at 0 and _abandonActiveStream increments it', () => {
  assert.equal(sandbox._streamEpoch, 0);
  sandbox._abandonActiveStream();
  assert.equal(sandbox._streamEpoch, 1);
  sandbox._abandonActiveStream();
  assert.equal(sandbox._streamEpoch, 2);
});

test('_abandonActiveStream aborts the active controller and clears it', () => {
  let aborted = false;
  sandbox._activeStreamController = { abort: () => { aborted = true; } };
  sandbox._abandonActiveStream();
  assert.equal(aborted, true);
  assert.equal(sandbox._activeStreamController, null);
});

test('_abandonActiveStream resets isStreaming to false immediately, even mid-request', () => {
  sandbox.isStreaming = true;
  sandbox._abandonActiveStream();
  assert.equal(sandbox.isStreaming, false);
});

test('_abandonActiveStream is safe to call with no active controller (nothing in flight)', () => {
  sandbox._activeStreamController = null;
  assert.doesNotThrow(() => sandbox._abandonActiveStream());
});

test('ownership pattern: a request that captured an older epoch is no longer the owner after abandonment', () => {
  // Mirrors exactly what sendMessage() does: `const myEpoch = ++_streamEpoch;`
  // then `const isOwner = () => myEpoch === _streamEpoch;`
  sandbox._streamEpoch = 5; // arbitrary starting point
  const myEpoch = ++sandbox._streamEpoch; // 6 -- this "request" claims ownership
  const isOwner = () => myEpoch === sandbox._streamEpoch;
  assert.equal(isOwner(), true);
  sandbox._abandonActiveStream(); // a navigation function invalidates it
  assert.equal(isOwner(), false, 'a request must lose ownership once a newer navigation bumps the epoch');
});
