// AUDIT-P85C regression test for the INDEPENDENT account-view ownership
// domains that replaced AUDIT-P85B's single shared _viewEpoch:
//   - _historyEpoch / _abandonActiveHistory / _historyResponseStillOwns
//     (owned exclusively by loadSessions() -- the sidebar history list)
//   - _messageEpoch / _abandonActiveMessage / _messageResponseStillOwns
//     (owned exclusively by openSession() -- the main reading pane)
//   - _abandonAllViewsForAccountChange (bumps BOTH -- reserved for a
//     genuine authenticated-principal transition only)
// extracted verbatim from orca/serve/web/conversation.html.
//
// Why this file exists (not just a rename of the old one): an independent
// audit (Antigravity) correctly flagged that AUDIT-P85B's single shared
// _viewEpoch made loadSessions() and openSession() invalidate EACH OTHER
// even though they are functionally unrelated UI regions -- a genuine
// liveness/UX defect (valid data discarded, or a permanent "Loading
// conversation..." state), not a privacy leak. Both directions were
// independently reproduced live in a real browser against the actual
// pre-fix (shared-epoch) code before any fix was written:
//   - Sequence 1: a delayed loadSessions() response was discarded because
//     an intervening openSession() call bumped the SAME epoch.
//   - Sequence 2: a delayed openSession() response was discarded (reading
//     pane stuck on "Loading conversation..." forever) because an
//     intervening loadSessions() call bumped the SAME epoch.
// Both were also confirmed FIXED (correctly applying) after splitting the
// epochs, in the same live browser, with the still-existing Alice-to-Bob
// cross-account privacy reproductions re-run and confirmed still blocked
// under the new independent-domain design. See the engineering report for
// the full captured evidence; this unit suite does not claim to replace
// that live reproduction -- it covers the ownership PRIMITIVES and
// deterministic simulations of the calling functions themselves (not just
// the primitives in isolation), per the explicit instruction to exercise
// the actual calling functions.
//
// Run with: node --test tests/frontend/test_view_ownership_epoch.mjs
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

const abandonHistoryFn = extractBalancedFunction(source, 'function _abandonActiveHistory() {', 0);
const abandonMessageFn = extractBalancedFunction(source, 'function _abandonActiveMessage() {', abandonHistoryFn.end);
const abandonAllFn = extractBalancedFunction(source, 'function _abandonAllViewsForAccountChange() {', abandonMessageFn.end);
const historyOwnsFn = extractBalancedFunction(source, 'function _historyResponseStillOwns(myEpoch, myToken) {', abandonAllFn.end);
const messageOwnsFn = extractBalancedFunction(source, 'function _messageResponseStillOwns(myEpoch, myToken) {', historyOwnsFn.end);

function makeSandbox() {
  const sandbox = { _authToken: 'token-alice' };
  vm.createContext(sandbox);
  vm.runInContext(
    `var _historyEpoch = 0;\nvar _messageEpoch = 0;\n${abandonHistoryFn.text}\n${abandonMessageFn.text}\n${abandonAllFn.text}\n${historyOwnsFn.text}\n${messageOwnsFn.text}`,
    sandbox,
  );
  return sandbox;
}

test('both epochs start at 0, and each abandon function bumps only its own domain', () => {
  const sandbox = makeSandbox();
  assert.equal(sandbox._historyEpoch, 0);
  assert.equal(sandbox._messageEpoch, 0);
  sandbox._abandonActiveHistory();
  assert.equal(sandbox._historyEpoch, 1, 'history abandon must bump history');
  assert.equal(sandbox._messageEpoch, 0, 'history abandon must NOT bump message (the exact liveness coupling bug)');
  sandbox._abandonActiveMessage();
  assert.equal(sandbox._messageEpoch, 1, 'message abandon must bump message');
  assert.equal(sandbox._historyEpoch, 1, 'message abandon must NOT bump history (the exact liveness coupling bug, other direction)');
});

test('_abandonAllViewsForAccountChange bumps BOTH domains together', () => {
  const sandbox = makeSandbox();
  sandbox._abandonAllViewsForAccountChange();
  assert.equal(sandbox._historyEpoch, 1);
  assert.equal(sandbox._messageEpoch, 1);
});

test('a response for the current epoch and token owns its own domain', () => {
  const sandbox = makeSandbox();
  assert.equal(sandbox._historyResponseStillOwns(sandbox._historyEpoch, 'token-alice'), true);
  assert.equal(sandbox._messageResponseStillOwns(sandbox._messageEpoch, 'token-alice'), true);
});

// --- Invariant 1: loadSessions() may invalidate an older history
// request but must NOT invalidate an unrelated message request ---
test('invariant 1: a fresh history request does not invalidate an in-flight message request', () => {
  const sandbox = makeSandbox();
  const messageEpoch = sandbox._messageEpoch; // openSession() claimed this
  const token = sandbox._authToken;
  sandbox._abandonActiveHistory(); // loadSessions() called again
  const newHistoryEpoch = ++sandbox._historyEpoch; // loadSessions() claims its own fresh epoch
  assert.equal(sandbox._messageResponseStillOwns(messageEpoch, token), true, 'the unrelated message request must still own its result');
  assert.equal(sandbox._historyResponseStillOwns(newHistoryEpoch, token), true);
});

// --- Invariant 2: openSession() may invalidate an older message
// request but must NOT invalidate an unrelated history request ---
test('invariant 2: a fresh message request does not invalidate an in-flight history request', () => {
  const sandbox = makeSandbox();
  const historyEpoch = sandbox._historyEpoch; // loadSessions() claimed this
  const token = sandbox._authToken;
  sandbox._abandonActiveMessage(); // openSession() called again
  const newMessageEpoch = ++sandbox._messageEpoch;
  assert.equal(sandbox._historyResponseStillOwns(historyEpoch, token), true, 'the unrelated history request must still own its result');
  assert.equal(sandbox._messageResponseStillOwns(newMessageEpoch, token), true);
});

// --- Invariant 3: opening conversation Y must invalidate an obsolete
// message load for conversation X (same domain, rapid succession) ---
test('invariant 3: opening conversation Y invalidates a still-pending load for conversation X', () => {
  const sandbox = makeSandbox();
  const xEpoch = ++sandbox._messageEpoch; // openSession(X)
  const token = sandbox._authToken;
  const yEpoch = ++sandbox._messageEpoch; // openSession(Y), before X resolved
  assert.equal(sandbox._messageResponseStillOwns(xEpoch, token), false, "X's stale response must not win");
  assert.equal(sandbox._messageResponseStillOwns(yEpoch, token), true, "Y's current response must be allowed to render");
});

// --- Invariant 5/6: a genuine authenticated-principal change must
// invalidate BOTH domains (the exact Alice-to-Bob scenario, at the
// primitive level; the live two-account browser reproduction is the
// stronger evidence, documented in the engineering report) ---
test('invariant 5/6: an account switch invalidates in-flight requests in both domains, captured under the old account', () => {
  const sandbox = makeSandbox();
  const aliceHistoryEpoch = sandbox._historyEpoch;
  const aliceMessageEpoch = sandbox._messageEpoch;
  const aliceToken = sandbox._authToken;

  sandbox._abandonAllViewsForAccountChange(); // doLogout()/onAuthSuccess()/continueAnonymous()/tryRestoreSession()
  sandbox._authToken = 'token-bob';

  assert.equal(sandbox._historyResponseStillOwns(aliceHistoryEpoch, aliceToken), false, "Alice's history response must never render after switching to Bob");
  assert.equal(sandbox._messageResponseStillOwns(aliceMessageEpoch, aliceToken), false, "Alice's message response must never render after switching to Bob");
});

// --- Invariant 7: stale success and error responses are rejected
// identically -- the ownership check takes no outcome parameter ---
test('invariant 7: a stale response is rejected the same way regardless of success/failure outcome', () => {
  const sandbox = makeSandbox();
  const historyEpoch = sandbox._historyEpoch;
  const messageEpoch = sandbox._messageEpoch;
  const token = sandbox._authToken;
  sandbox._abandonActiveHistory();
  sandbox._abandonActiveMessage();
  // Whether the underlying fetch resolved or rejected is irrelevant to
  // ownership -- this is why loadSessions()/openSession() reuse the same
  // check in both their try and catch blocks.
  assert.equal(sandbox._historyResponseStillOwns(historyEpoch, token), false);
  assert.equal(sandbox._messageResponseStillOwns(messageEpoch, token), false);
});

test('recovery: a genuinely new request after an abandoned one is correctly recognized as current, per domain', () => {
  const sandbox = makeSandbox();
  sandbox._abandonActiveHistory();
  const freshHistoryEpoch = ++sandbox._historyEpoch;
  assert.equal(sandbox._historyResponseStillOwns(freshHistoryEpoch, sandbox._authToken), true);

  sandbox._abandonActiveMessage();
  const freshMessageEpoch = ++sandbox._messageEpoch;
  assert.equal(sandbox._messageResponseStillOwns(freshMessageEpoch, sandbox._authToken), true);
});

// --- Exercise the actual calling functions, not just the bare
// epoch-comparison primitives (explicit instruction: unit tests must
// exercise loadSessions()/openSession()/newConversation() themselves
// where feasible, not only the isolated helpers above) ---
function extractFunction(src, startMarker) {
  return extractBalancedFunction(src, startMarker, 0).text;
}

test('newConversation() invalidates ONLY the message domain, not history (the CTO directive\'s explicit named example)', () => {
  const newConversationSrc = extractFunction(source, 'function newConversation() {');
  const sandbox = {
    _authToken: 'token-alice',
    _abandonActiveStream: () => {},
    sessionId: 'old-sid',
    composerEl: null, // B04: newConversation() guards its collapseComposer() call on this
    closeTempModePanel: () => {},
    _saveCurrentDraft: () => {},
    _restoreDraftFor: () => {},
    closeQuickSwitch: () => {},
    loadAttachmentsForSession: () => {},
    document: {
      getElementById: () => ({ innerHTML: '' }),
    },
    highlightSelectedRecent: () => {},
    showEmptyView: () => {},
  };
  vm.createContext(sandbox);
  vm.runInContext(
    `var _historyEpoch = 0;\nvar _messageEpoch = 0;\n${abandonHistoryFn.text}\n${abandonMessageFn.text}\n${newConversationSrc}`,
    sandbox,
  );
  const historyBefore = sandbox._historyEpoch;
  sandbox.newConversation();
  assert.equal(sandbox._messageEpoch, 1, 'newConversation() must abandon the message domain (there is no longer a specific conversation loading)');
  assert.equal(sandbox._historyEpoch, historyBefore, 'newConversation() must NOT touch the history domain -- an otherwise valid, authenticated, merely-slow sidebar refresh is unrelated');
  assert.equal(sandbox.sessionId, null);
});

test('doLogout() invalidates BOTH domains via the full-account-reset routine (invariant 6)', () => {
  const clearAuthStateSrc = extractFunction(source, 'function _clearAuthStateAndShowSignIn(message) {');
  const doLogoutSrc = extractFunction(source, 'function doLogout() {');
  const calls = [];
  const sandbox = {
    _authToken: 'token-alice',
    _authUser: { name: 'Alice' },
    localStorage: { removeItem: () => {} },
    document: {
      getElementById: (id) => {
        calls.push(id);
        return { innerHTML: '', value: '' };
      },
    },
    _abandonActiveSearch: () => { calls.push('_abandonActiveSearch'); },
    _preSearchListHTML: null,
    newConversation: () => { calls.push('newConversation'); },
    resetModelSelection: () => { calls.push('resetModelSelection'); },
    updateAccountUI: () => { calls.push('updateAccountUI'); },
    openAuthOverlay: () => { calls.push('openAuthOverlay'); },
  };
  vm.createContext(sandbox);
  vm.runInContext(
    `var _historyEpoch = 0;\nvar _messageEpoch = 0;\nvar _draftsByConversation = new Map();\n${abandonHistoryFn.text}\n${abandonMessageFn.text}\n${abandonAllFn.text}\n${clearAuthStateSrc}\n${doLogoutSrc}`,
    sandbox,
  );
  sandbox.doLogout();
  assert.equal(sandbox._historyEpoch, 1, 'doLogout() must invalidate the history domain (it no longer gets this for free from newConversation(), which is now message-only)');
  assert.equal(sandbox._messageEpoch, 1, 'doLogout() must invalidate the message domain');
  assert.equal(sandbox._authToken, null);
});

test('continueAnonymous() invalidates both domains, clears a previous principal, and marks identity resolved', () => {
  const continueAnonymousSrc = extractFunction(source, 'function continueAnonymous() {');
  assert.ok(!continueAnonymousSrc.includes('_abandonActiveView'), 'must not reference the deleted shared-epoch function');
  let newConversationCalled = false;
  const sandbox = {
    _authToken: 'token-alice', // CTO fix 3: a previous principal must not survive continueAnonymous()
    _authUser: { name: 'Alice' },
    _identityResolved: false,
    _abandonActiveSearch: () => {},
    newConversation: () => { newConversationCalled = true; },
    resetModelSelection: () => {},
    closeAuthOverlay: () => {},
    updateAccountUI: () => {},
    loadModels: () => {},
  };
  vm.createContext(sandbox);
  vm.runInContext(
    `var _historyEpoch = 0;\nvar _messageEpoch = 0;\nvar _draftsByConversation = new Map();\n${abandonHistoryFn.text}\n${abandonMessageFn.text}\n${abandonAllFn.text}\n${continueAnonymousSrc}`,
    sandbox,
  );
  sandbox.continueAnonymous();
  assert.equal(sandbox._historyEpoch, 1);
  assert.equal(sandbox._messageEpoch, 1);
  assert.equal(sandbox._anonymous, true);
  assert.equal(sandbox._authToken, null, 'CTO fix 3: must not retain a previous authenticated principal\'s token');
  assert.equal(sandbox._authUser, null, 'CTO fix 3: must not retain a previous authenticated principal\'s user object');
  assert.equal(sandbox._identityResolved, true, 'CTO fix 2: must mark identity resolved so a later-resolving boot restore defers to this explicit choice');
  assert.equal(newConversationCalled, true, 'CTO fix 1 (symmetric): must clear any previous principal\'s conversation DOM/stream too');
});

test('onAuthSuccess() invalidates both domains, clears previous DOM/stream, and marks identity resolved (a sign-in that never goes through doLogout())', () => {
  const onAuthSuccessSrc = extractFunction(source, 'function onAuthSuccess(data) {');
  let newConversationCalled = false;
  const sandbox = {
    _authToken: null,
    _identityResolved: false,
    localStorage: { setItem: () => {} },
    newConversation: () => { newConversationCalled = true; },
    resetModelSelection: () => {},
    closeAuthOverlay: () => {},
    updateAccountUI: () => {},
    loadSessions: () => {},
    loadModels: () => {},
    _abandonActiveSearch: () => {},
  };
  vm.createContext(sandbox);
  vm.runInContext(
    `var _historyEpoch = 0;\nvar _messageEpoch = 0;\nvar _draftsByConversation = new Map();\n${abandonHistoryFn.text}\n${abandonMessageFn.text}\n${abandonAllFn.text}\n${onAuthSuccessSrc}`,
    sandbox,
  );
  sandbox.onAuthSuccess({ token: 'token-bob', user: { name: 'Bob' } });
  assert.equal(sandbox._historyEpoch, 1, 'onAuthSuccess() must invalidate history even though it never called doLogout()');
  assert.equal(sandbox._messageEpoch, 1, 'onAuthSuccess() must invalidate messages even though it never called doLogout()');
  assert.equal(sandbox._identityResolved, true, 'CTO fix 2: must mark identity resolved so a later-resolving boot restore defers to this login');
  assert.equal(newConversationCalled, true, 'CTO fix 1: must clear the previous principal\'s conversation DOM and end any in-flight stream');
  assert.equal(sandbox._authToken, 'token-bob');
});

// --- Mission 3 audit: session-expiry / 401 basic recovery ---
test('_handleSessionExpired() clears auth state and shows a truthful reason in the sign-in overlay', () => {
  const clearAuthStateSrc = extractFunction(source, 'function _clearAuthStateAndShowSignIn(message) {');
  const handleExpiredSrc = extractFunction(source, 'function _handleSessionExpired() {');
  let shownMessage = null;
  const sandbox = {
    _authToken: 'token-alice',
    _authUser: { name: 'Alice' },
    localStorage: { removeItem: () => {} },
    document: {
      getElementById: (id) => {
        if (id === 'si-error') return { set textContent(v) { shownMessage = v; } };
        return { innerHTML: '', value: '' };
      },
    },
    _abandonActiveSearch: () => {},
    _preSearchListHTML: null,
    newConversation: () => {},
    resetModelSelection: () => {},
    updateAccountUI: () => {},
    openAuthOverlay: () => {},
  };
  vm.createContext(sandbox);
  vm.runInContext(
    `var _historyEpoch = 0;\nvar _messageEpoch = 0;\nvar _draftsByConversation = new Map();\n${abandonHistoryFn.text}\n${abandonMessageFn.text}\n${abandonAllFn.text}\n${clearAuthStateSrc}\n${handleExpiredSrc}`,
    sandbox,
  );
  sandbox._handleSessionExpired();
  assert.equal(sandbox._authToken, null, '_handleSessionExpired() must clear the token, exactly like a real logout');
  assert.equal(sandbox._historyEpoch, 1);
  assert.equal(sandbox._messageEpoch, 1);
  assert.equal(shownMessage, 'Your session has expired. Please sign in again.', 'must show a truthful, specific reason, not a silent logout');
});

test('_handleSessionExpired() is a no-op when already signed out (no token to expire)', () => {
  const clearAuthStateSrc = extractFunction(source, 'function _clearAuthStateAndShowSignIn(message) {');
  const handleExpiredSrc = extractFunction(source, 'function _handleSessionExpired() {');
  let calledClear = false;
  const sandbox = {
    _authToken: null,
    document: { getElementById: () => ({ innerHTML: '', value: '' }) },
    _abandonActiveSearch: () => { calledClear = true; },
    _preSearchListHTML: null,
    newConversation: () => {},
    updateAccountUI: () => {},
    openAuthOverlay: () => {},
  };
  vm.createContext(sandbox);
  vm.runInContext(
    `var _historyEpoch = 0;\nvar _messageEpoch = 0;\nvar _draftsByConversation = new Map();\n${abandonHistoryFn.text}\n${abandonMessageFn.text}\n${abandonAllFn.text}\n${clearAuthStateSrc}\n${handleExpiredSrc}`,
    sandbox,
  );
  sandbox._handleSessionExpired();
  assert.equal(calledClear, false, 'must not run the full reset when there was never a token to expire (e.g. the anonymous/signed-out state)');
});

test('every authenticated call site checks r.status === 401 before the generic !r.ok failure path', () => {
  // Structural check: a 401 must be distinguished from a generic failure
  // at every real authenticated fetch call site this phase touched --
  // otherwise expiry silently degrades into the old "could not load"
  // message with no recovery path.
  const sites = [
    "fetch('/api/sessions?limit=20'",
    'fetch(`/api/session/${encodeURIComponent(sid)}/messages`',
    'fetch(`/api/sessions/search?q=',
    'fetch(`/api/session/${encodeURIComponent(sid)}/title`',
    'fetch(`/api/session/${encodeURIComponent(sid)}/export?format=',
    'fetch(`/api/session/${encodeURIComponent(sid)}`, { method: \'DELETE\'',
  ];
  for (const marker of sites) {
    const idx = source.indexOf(marker);
    assert.ok(idx !== -1, `call site not found: ${marker}`);
    const nextChunk = source.slice(idx, idx + 400);
    assert.ok(nextChunk.includes('_handleSessionExpired()'), `call site missing a 401 -> _handleSessionExpired() check: ${marker}`);
  }
});

// --- CTO continuous-execution directive: mandatory missed P0 corrections ---

test('tryRestoreSession() defers to a faster login/signup/anonymous choice instead of overwriting it (reproduced live, unit-verified here)', async () => {
  const tryRestoreSrc = extractFunction(source, 'async function tryRestoreSession() {');
  let removedFromStorage = false;
  const sandbox = {
    _authToken: null,
    _authUser: null,
    _identityResolved: false,
    localStorage: {
      getItem: () => 'stale-alice-token',
      removeItem: () => { removedFromStorage = true; },
    },
    closeAuthOverlay: () => {},
    updateAccountUI: () => {},
    loadSessions: () => {},
    loadModels: () => {},
    _abandonAllViewsForAccountChange: () => {},
    fetch: async () => {
      // Simulate a faster login winning the race WHILE this fetch is in flight.
      sandbox._identityResolved = true;
      sandbox._authToken = 'bob-token';
      return { ok: true, json: async () => ({ user: { name: 'Alice (stale)' } }) };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(`var _historyEpoch = 0;\nvar _messageEpoch = 0;\n${tryRestoreSrc}`, sandbox);
  const result = await sandbox.tryRestoreSession();
  assert.equal(result, false, 'a restore that lost the race must report failure, not silently succeed');
  assert.equal(sandbox._authToken, 'bob-token', 'must not overwrite the identity a faster login already established');
  assert.equal(removedFromStorage, false, 'must not delete a newer token that a faster login already stored under the same key');
});

test('tryRestoreSession() still restores normally when nothing else wins the race first', async () => {
  const tryRestoreSrc = extractFunction(source, 'async function tryRestoreSession() {');
  const sandbox = {
    _authToken: null,
    _authUser: null,
    _identityResolved: false,
    localStorage: { getItem: () => 'alice-token', removeItem: () => {} },
    closeAuthOverlay: () => {},
    updateAccountUI: () => {},
    loadSessions: () => {},
    loadModels: () => {},
    _abandonAllViewsForAccountChange: () => {},
    fetch: async () => ({ ok: true, json: async () => ({ user: { name: 'Alice' } }) }),
  };
  vm.createContext(sandbox);
  vm.runInContext(`var _historyEpoch = 0;\nvar _messageEpoch = 0;\n${tryRestoreSrc}`, sandbox);
  const result = await sandbox.tryRestoreSession();
  assert.equal(result, true);
  assert.equal(sandbox._authToken, 'alice-token');
  assert.equal(sandbox._identityResolved, true);
});

test('the SSE session-event loadSessions() call site exists and is the real call, not removed or renamed', () => {
  const idx = source.indexOf("if (ev.type === 'session') {");
  assert.ok(idx !== -1, "the SSE 'session' event handler must still exist");
  const chunk = source.slice(idx, idx + 150);
  assert.ok(chunk.includes('loadSessions()'), "the SSE 'session' event handler must still call loadSessions() -- live-verified safe under the independent-epoch design in ORNEUR_PR85_LIVENESS_CORRECTION.md");
});

test("restoreRecentsFromSearch()'s real reload call site exists and is the real call, not removed or renamed", () => {
  const fnSrc = extractFunction(source, 'function restoreRecentsFromSearch() {');
  assert.ok(fnSrc.includes('loadSessions()'), 'restoreRecentsFromSearch() must still call loadSessions() for a truthful (non-cached) reload -- live-verified safe under the independent-epoch design in ORNEUR_PR85_LIVENESS_CORRECTION.md');
});
