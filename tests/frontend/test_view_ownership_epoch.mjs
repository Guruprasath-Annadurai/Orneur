// AUDIT-P85B regression test for the account-view ownership primitive
// (_viewEpoch / _abandonActiveView / _viewResponseStillOwns), shared by
// loadSessions() (conversation history) and openSession() (conversation
// messages), extracted verbatim from orca/serve/web/conversation.html.
//
// Scope note (honest, disclosed limitation): this covers the ownership
// PRIMITIVE and deterministic simulations of the scenarios the CTO
// directive explicitly listed (rapid conversation switching, logout
// during fetch, Alice-to-Bob, network failure/recovery). The two real,
// non-simulated end-to-end reproductions -- a delayed loadSessions()
// response painting Alice's real conversation into Bob's freshly-
// logged-in sidebar, and a delayed openSession() response painting
// Alice's private message content into Bob's reading pane -- were
// performed against the real running backend with two real signed-up
// accounts in a real browser, BEFORE this fix (both leaked) and AFTER
// (neither did). See the engineering report for the full captured
// evidence; that live reproduction is not something this unit test
// claims to replace.
//
// Run with: node tests/frontend/test_view_ownership_epoch.mjs
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

const abandonFn = extractBalancedFunction(source, 'function _abandonActiveView() {', 0);
const ownsFn = extractBalancedFunction(source, 'function _viewResponseStillOwns(myEpoch, myToken) {', abandonFn.end);

function makeSandbox() {
  const sandbox = { _authToken: 'token-alice' };
  vm.createContext(sandbox);
  vm.runInContext(`var _viewEpoch = 0;\n${abandonFn.text}\n${ownsFn.text}`, sandbox);
  return sandbox;
}

test('_viewEpoch starts at 0 and _abandonActiveView increments it', () => {
  const sandbox = makeSandbox();
  assert.equal(sandbox._viewEpoch, 0);
  sandbox._abandonActiveView();
  assert.equal(sandbox._viewEpoch, 1);
});

test('a response for the current epoch and token owns the view', () => {
  const sandbox = makeSandbox();
  assert.equal(sandbox._viewResponseStillOwns(sandbox._viewEpoch, 'token-alice'), true);
});

// --- Alice-to-Bob (the exact scenario independently reproduced live) ---
test('adversarial reproduction at the primitive level: an account switch invalidates a request captured under the old account', () => {
  const sandbox = makeSandbox();
  const aliceEpoch = sandbox._viewEpoch;
  const aliceToken = sandbox._authToken;

  sandbox._abandonActiveView(); // doLogout() / continueAnonymous()
  sandbox._authToken = 'token-bob'; // onAuthSuccess(bob)

  assert.equal(
    sandbox._viewResponseStillOwns(aliceEpoch, aliceToken),
    false,
    'a loadSessions()/openSession() response captured under Alice must never render after switching to Bob',
  );
});

// --- Rapid conversation switching (same account) ---
test('rapid conversation switching: opening conversation Y invalidates a still-pending request for conversation X', () => {
  const sandbox = makeSandbox();
  // openSession(X) claims an epoch.
  const xEpoch = ++sandbox._viewEpoch;
  const token = sandbox._authToken;
  // Before X's response arrives, the user clicks conversation Y.
  const yEpoch = ++sandbox._viewEpoch; // openSession(Y) claims its own fresh epoch
  assert.equal(sandbox._viewResponseStillOwns(xEpoch, token), false, "X's stale response must not win");
  assert.equal(sandbox._viewResponseStillOwns(yEpoch, token), true, "Y's response, being current, must be allowed to render");
});

// --- Logout during fetch ---
test('logout while a request is in flight invalidates it, even though the token becomes null rather than a different value', () => {
  const sandbox = makeSandbox();
  const myEpoch = sandbox._viewEpoch;
  const myToken = sandbox._authToken;
  sandbox._abandonActiveView(); // doLogout() -> newConversation() -> _abandonActiveView()
  sandbox._authToken = null; // doLogout() clears it
  assert.equal(sandbox._viewResponseStillOwns(myEpoch, myToken), false);
});

// --- Network failure and recovery ---
test('network failure: a stale error-path response is rejected exactly like a stale success-path one', () => {
  // The fix applies the SAME _viewResponseStillOwns() check in the
  // catch block as the success block (see loadSessions()/openSession()
  // in conversation.html) -- this test documents that the primitive
  // itself makes no distinction between "stale success" and "stale
  // failure": both are "not current", and both are rejected identically.
  const sandbox = makeSandbox();
  const myEpoch = sandbox._viewEpoch;
  const myToken = sandbox._authToken;
  sandbox._abandonActiveView();
  // Whether the delayed/raced response resolved or rejected is
  // irrelevant to ownership -- the check doesn't take an outcome
  // parameter, which is exactly why both call sites can reuse it as-is.
  assert.equal(sandbox._viewResponseStillOwns(myEpoch, myToken), false);
});

test('recovery: a genuinely NEW request after a stale one is correctly recognized as current', () => {
  const sandbox = makeSandbox();
  sandbox._abandonActiveView(); // some earlier request is abandoned
  const freshEpoch = ++sandbox._viewEpoch; // a real new loadSessions()/openSession() call
  assert.equal(sandbox._viewResponseStillOwns(freshEpoch, sandbox._authToken), true, 'a fresh, current request must still be able to render normally after an earlier one was abandoned');
});
