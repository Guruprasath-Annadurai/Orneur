// Frontend journey remediation, Priority 1 (FE-1): explicit Sign out must revoke the
// server session with the live token before discarding it, clear client state, and
// report only what the server actually confirmed.
//
// Real-browser + real-server proof: tests/journey/test_journey_browser.py (G1) and
// tests/journey/test_journey_api_live.py (G1/G2). This file covers the page logic in isolation.
//
// Run with: node --test tests/frontend/test_logout_revocation.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(__dirname, '../../orca/serve/web/conversation.html'), 'utf8');

function extract(startMarker) {
  const start = source.indexOf(startMarker);
  if (start === -1) throw new Error(`marker not found: ${startMarker}`);
  let depth = 0;
  let i = source.indexOf('{', start);
  for (; i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) break;
  }
  return source.slice(start, i + 1);
}

function build({ responses, token = 'SECRET-TOKEN-1' }) {
  const events = [];
  const errEl = { textContent: '' };
  let call = 0;
  const sandbox = {
    _authToken: token,
    _authUser: { name: 'Alice' },
    events,
    errEl,
    document: { getElementById: (id) => (id === 'si-error' ? errEl : { innerHTML: '', value: '' }) },
    localStorage: { removeItem: (k) => events.push(`localStorage.removeItem:${k}`) },
    _abandonActiveSearch: () => events.push('abandonSearch'),
    _abandonAllViewsForAccountChange: () => events.push('abandonViews'),
    resetModelSelection: () => events.push('resetModel'),
    _draftsByConversation: new Map([['c1', 'secret draft']]),
    _preSearchListHTML: 'x',
    newConversation: () => events.push('newConversation'),
    updateAccountUI: () => events.push('updateAccountUI'),
    openAuthOverlay: () => events.push('openAuthOverlay'),
    AbortController,
    setTimeout: (fn, ms) => (ms === 800 ? setTimeout(fn, 1) : setTimeout(fn, ms)), // keep the retry pause short in tests
    clearTimeout,
    fetch: async (url, opts) => {
      events.push({ fetch: url, method: opts.method, auth: opts.headers.Authorization, tokenInStore: sandbox._authToken });
      const r = responses[Math.min(call++, responses.length - 1)];
      if (r instanceof Error) throw r;
      return { status: r };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext([
    'var _logoutInFlightToken = null;',
    extract('function _clearAuthStateAndShowSignIn(message) {'),
    extract('async function _revokeServerSession(token) {'),
    extract('function _logoutOutcomeMessage(outcome) {'),
    extract('async function doLogout() {'),
  ].join('\n'), sandbox);
  return sandbox;
}

test('revokes THIS session with the live token BEFORE discarding it, using only a bare POST /api/auth/logout', async () => {
  const s = build({ responses: [200] });
  await s.doLogout();
  const fetchEv = s.events.find((e) => e.fetch);
  assert.equal(fetchEv.fetch, '/api/auth/logout', 'no query string or token in the URL');
  assert.equal(fetchEv.method, 'POST');
  assert.equal(fetchEv.auth, 'Bearer SECRET-TOKEN-1');
  assert.ok(s.events.indexOf(fetchEv) < s.events.indexOf('localStorage.removeItem:orneur_token'), 'the revocation request is issued before the stored token is removed');
  assert.equal(s.events.filter((e) => e.fetch).length, 1, 'exactly one request (no logout-all)');
});

test('clears sensitive client state synchronously and reports a confirmed sign-out', async () => {
  const s = build({ responses: [200] });
  const p = s.doLogout();
  // before the server answers, local state is already gone
  assert.equal(s._authToken, null);
  assert.equal(s._authUser, null);
  assert.ok(s.events.includes('abandonViews') && s.events.includes('newConversation') && s.events.includes('resetModel'));
  assert.equal(s._draftsByConversation.size, 0);
  await p;
  assert.equal(s.errEl.textContent, 'You have been signed out.');
});

test('a 401 (token already dead) is reported as already ended, not as a revocation', async () => {
  const s = build({ responses: [401] });
  await s.doLogout();
  assert.equal(s.errEl.textContent, 'This session had already ended.');
  assert.equal(s.events.filter((e) => e.fetch).length, 1, 'no retry on 401');
});

test('network failure: retried once, then honestly reported as unconfirmed; local sign-out still happened', async () => {
  const s = build({ responses: [new Error('network'), new Error('network')] });
  await s.doLogout();
  assert.equal(s.events.filter((e) => e.fetch).length, 2);
  assert.match(s.errEl.textContent, /did not confirm/);
  assert.match(s.errEl.textContent, /may remain valid/);
  assert.equal(s._authToken, null);
});

test('a transient 5xx is retried once and a later 200 is reported as confirmed', async () => {
  const s = build({ responses: [503, 200] });
  await s.doLogout();
  assert.equal(s.errEl.textContent, 'You have been signed out.');
});

test('a 4xx other than 401 (e.g. an API key) is NOT reported as signed out', async () => {
  const s = build({ responses: [400] });
  await s.doLogout();
  assert.match(s.errEl.textContent, /did not confirm/);
});

test('a late outcome never overwrites the overlay after a newer sign-in', async () => {
  const s = build({ responses: [200] });
  const p = s.doLogout();
  s._authToken = 'NEW-LOGIN-TOKEN'; // user signed in again while the revocation was in flight
  await p;
  assert.equal(s.errEl.textContent, '', 'must not write a stale sign-out message over a fresh session');
});

test('a second click while revocation is in flight is ignored; with no token there is no request', async () => {
  const s = build({ responses: [200] });
  const first = s.doLogout();
  await s.doLogout();
  await first;
  assert.equal(s.events.filter((e) => e.fetch).length, 1);
  const none = build({ responses: [200], token: null });
  await none.doLogout();
  assert.equal(none.events.filter((e) => e.fetch).length, 0);
});

test('the page never claims "signed out everywhere" and never logs or echoes the token', () => {
  const code = source.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
  assert.ok(!/signed out everywhere|signed out of all|all devices/i.test(code), 'no everywhere-claim in the page code or copy');
  const fns = [extract('async function _revokeServerSession(token) {'), extract('async function doLogout() {')].join('\n');
  assert.ok(!/console\.|textContent\s*=\s*[^;]*token|innerHTML\s*=\s*[^;]*token/i.test(fns), 'token must not reach console or the DOM');
});

test('another tab signing out ends this tab\'s in-memory session too', () => {
  assert.match(source, /addEventListener\('storage'[\s\S]{0,600}orneur_token[\s\S]{0,700}_clearAuthStateAndShowSignIn/);
});


test('a NEWER sign-in is never blocked by an older logout whose revocation is still pending', async () => {
  const s = build({ responses: [200] });
  s._authToken = 'tokenA';
  const first = s.doLogout();                  // revocation for tokenA is in flight (not awaited)
  s._authToken = 'tokenB';                      // the user signs in again immediately
  const second = s.doLogout();                  // ...and signs out again: must NOT be swallowed by the pending tokenA logout
  await Promise.all([first, second]);
  const posts = s.events.filter((e) => e.fetch === '/api/auth/logout');
  assert.deepEqual(posts.map((e) => e.auth), ['Bearer tokenA', 'Bearer tokenB']);
});

test('a double-click on the SAME session sends one revocation', async () => {
  const s = build({ responses: [200] });
  s._authToken = 'tokenA';
  const first = s.doLogout();
  const second = s.doLogout();
  await Promise.all([first, second]);
  assert.equal(s.events.filter((e) => e.fetch === '/api/auth/logout').length, 1);
});

test('a late storage event about an OLDER token does not sign out a newer session in this tab', () => {
  const handlerSrc = source.slice(source.indexOf("window.addEventListener('storage'"));
  const cleared = [];
  const sandbox = { _authToken: 'tokenB', _clearAuthStateAndShowSignIn: (m) => cleared.push(m), window: { addEventListener: (type, fn) => { sandbox.handler = fn; } } };
  vm.createContext(sandbox);
  vm.runInContext(handlerSrc.slice(0, handlerSrc.indexOf('});') + 3).replace(/^window\./, 'window.'), sandbox);
  sandbox.handler({ key: 'orneur_token', newValue: null, oldValue: 'tokenA' });
  assert.deepEqual(cleared, [], 'an event about tokenA must not clear tokenB');
  sandbox.handler({ key: 'orneur_token', newValue: null, oldValue: 'tokenB' });
  assert.equal(cleared.length, 1, 'removal of THIS tab\'s token signs it out');
  sandbox.handler({ key: 'orneur_token', newValue: null, oldValue: null });
  assert.equal(cleared.length, 2, 'a cleared store signs it out');
});
