// AUDIT-P85-P0 regression test for the search-ownership primitive
// (_searchEpoch / _abandonActiveSearch / _searchResponseStillOwns),
// extracted verbatim from orca/serve/web/conversation.html.
//
// This is the SAME class of defect, and the SAME fix pattern, as
// AUDIT-B81-A-P1-01 (tests/frontend/test_stream_ownership_epoch.mjs):
// a delayed async response must prove it still owns the view before
// it's allowed to repaint it.
//
// Scope note (honest, disclosed limitation): this covers the ownership
// PRIMITIVE in isolation. The full, genuine cross-account vulnerability
// -- a delayed /api/sessions/search response arriving after a real
// account switch -- was independently reproduced and closed in a real
// browser against the real running backend this session: two real
// signed-up users (not mocked), a real artificially-delayed fetch (not
// a simulated promise), a real doLogout()+login() account switch while
// the request was in flight, and a direct comparison of the SAME
// adversarial sequence against the pre-fix file (leaked Alice's private
// "ALICE_SECRET_NIGHTOWL_TWO" conversation into Bob's sidebar) and the
// fixed file (correctly showed Bob's true, empty list). See the
// engineering report for the full captured sequence and network
// evidence. That live reproduction is not something a DOM-stub unit
// test can responsibly claim to replace.
//
// Run with: node tests/frontend/test_search_ownership_epoch.mjs
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

const abandonFn = extractBalancedFunction(source, 'function _abandonActiveSearch() {', 0);
const ownsFn = extractBalancedFunction(source, 'function _searchResponseStillOwns(myEpoch, myToken, myQuery) {', abandonFn.end);

function makeSandbox(initialInputValue) {
  const sandbox = {
    _authToken: 'token-alice',
    document: {
      getElementById(id) {
        if (id === 'conv-search-input') return { value: initialInputValue };
        return null;
      },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(`var _searchEpoch = 0;\n${abandonFn.text}\n${ownsFn.text}`, sandbox);
  return sandbox;
}

test('_searchEpoch starts at 0 and _abandonActiveSearch increments it', () => {
  const sandbox = makeSandbox('x');
  assert.equal(sandbox._searchEpoch, 0);
  sandbox._abandonActiveSearch();
  assert.equal(sandbox._searchEpoch, 1);
});

test('a response for the CURRENT epoch, token, and live query is recognized as owning the view', () => {
  const sandbox = makeSandbox('zebra');
  const myEpoch = sandbox._searchEpoch; // 0, matches
  assert.equal(sandbox._searchResponseStillOwns(myEpoch, 'token-alice', 'zebra'), true);
});

test('a response from a now-stale epoch (a newer search or abandonment happened) is rejected', () => {
  const sandbox = makeSandbox('zebra');
  const myEpoch = sandbox._searchEpoch;
  sandbox._abandonActiveSearch(); // simulates: newer query, clear, logout, or session-history reset
  assert.equal(sandbox._searchResponseStillOwns(myEpoch, 'token-alice', 'zebra'), false);
});

test('adversarial reproduction of the P0 cross-account scenario, at the primitive level: the ownership check alone blocks it', () => {
  // Mirrors the real browser reproduction step by step: Alice's request
  // captures epoch+token+query, the account switches (which calls
  // _abandonActiveSearch(), exactly as doLogout()/onAuthSuccess() now
  // do), and only THEN does the delayed response arrive.
  const sandbox = makeSandbox('NIGHTOWL');
  const aliceEpoch = sandbox._searchEpoch;
  const aliceToken = sandbox._authToken; // 'token-alice', captured at request time

  // Account switch while the request is still "in flight".
  sandbox._abandonActiveSearch(); // doLogout()
  sandbox._authToken = 'token-bob'; // onAuthSuccess(bob)
  sandbox.document.getElementById = (id) => (id === 'conv-search-input' ? { value: '' } : null); // Bob's box is empty

  // Alice's delayed response now resolves.
  assert.equal(
    sandbox._searchResponseStillOwns(aliceEpoch, aliceToken, 'NIGHTOWL'),
    false,
    'a response captured under Alice must never be allowed to render after the account switched to Bob',
  );
});

test('a response whose query no longer matches the live search box is rejected, even with a matching epoch/token', () => {
  const sandbox = makeSandbox('different-live-query');
  const myEpoch = sandbox._searchEpoch;
  assert.equal(sandbox._searchResponseStillOwns(myEpoch, 'token-alice', 'original-query'), false);
});

test('a response with no live search input element at all (box removed/unmounted) is rejected, not thrown', () => {
  const sandbox = makeSandbox('x');
  sandbox.document.getElementById = () => null;
  assert.doesNotThrow(() => sandbox._searchResponseStillOwns(sandbox._searchEpoch, 'token-alice', 'x'));
  assert.equal(sandbox._searchResponseStillOwns(sandbox._searchEpoch, 'token-alice', 'x'), false);
});
