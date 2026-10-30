// LANDMARK-01 Wave 4: a reload puts the user back in the conversation this TAB was reading -- same account only, never a temporary chat, never a
// conversation the server refuses. Real-browser proof: tests/journey/test_journey_browser.py (C1).
//
// Run with: node --test tests/frontend/test_active_conversation.mjs
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

function build({ user = { id: 'u1' }, temporary = false, sid = null } = {}) {
  const store = new Map();
  const opened = [];
  const sandbox = {
    _authUser: user,
    _isTemporarySession: temporary,
    sessionId: sid,
    opened,
    store,
    sessionStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
    openSession: async (s, t) => { opened.push([s, t]); },
  };
  vm.createContext(sandbox);
  vm.runInContext([
    "const _ACTIVE_CONV_KEY = 'orneur_active_conversation';",
    extract('function _rememberActiveConversation(sid, title) {'),
    extract('function _forgetActiveConversation() {'),
    extract('async function _restoreActiveConversation() {'),
  ].join('\n'), sandbox);
  return sandbox;
}

test('remembers the open conversation and restores it for the same account', async () => {
  const s = build();
  s._rememberActiveConversation('sess-1', 'My chat');
  await s._restoreActiveConversation();
  assert.deepEqual(s.opened, [['sess-1', 'My chat']]);
});

test('never restores a temporary chat (and drops any earlier memory)', async () => {
  const s = build();
  s._rememberActiveConversation('sess-1', 'x');
  s._isTemporarySession = true;
  s._rememberActiveConversation('temp-1', 'Temporary');
  await s._restoreActiveConversation();
  assert.deepEqual(s.opened, []);
  assert.equal(s.store.size, 0);
});

test('never restores another account\'s conversation', async () => {
  const s = build();
  s._rememberActiveConversation('alice-sess', 'x');
  s._authUser = { id: 'u2' };                    // a different account signed in on the same tab
  await s._restoreActiveConversation();
  assert.deepEqual(s.opened, []);
});

test('nothing is remembered without a signed-in account, and forgetting is complete', async () => {
  const s = build({ user: null });
  s._rememberActiveConversation('anon-sess', 'x');
  assert.equal(s.store.size, 0);
  const t = build();
  t._rememberActiveConversation('sess-2', 'x');
  t._forgetActiveConversation();
  await t._restoreActiveConversation();
  assert.deepEqual(t.opened, []);
});

test('does not override a conversation that is already open', async () => {
  const s = build({ sid: 'already-open' });
  s._rememberActiveConversation('other', 'x');
  await s._restoreActiveConversation();
  assert.deepEqual(s.opened, []);
});

test('corrupt storage is ignored, not thrown', async () => {
  const s = build();
  s.store.set('orneur_active_conversation', '{not json');
  await s._restoreActiveConversation();
  assert.deepEqual(s.opened, []);
});

test('the page wires it: remember on open/new-session, forget on new conversation / temp chat / refused load, restore after session restore', () => {
  assert.match(source, /sessionId = sid;\s*_rememberActiveConversation\(sid, title\);/);
  assert.match(source, /sessionId = ev\.session_id;\s*_rememberActiveConversation\(sessionId\);/);
  assert.match(source, /sessionId = null;\s*_forgetActiveConversation\(\);/);
  assert.match(source, /_isTemporarySession = true;\s*_forgetActiveConversation\(\)/);
  assert.match(source, /if \(!r\.ok\) \{ _forgetActiveConversation\(\);/);
  assert.match(source, /loadModels\(\);\s*_restoreActiveConversation\(\);/);
});
