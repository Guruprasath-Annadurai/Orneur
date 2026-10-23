// B14 Multi-Conversation Navigation regression tests.
//
// Source: docs/B14_IMPLEMENTATION_CONTRACT.md (ORNEUR_B14_FINAL_LOCK_AND_HANDOFF.zip,
// SHA-256 810f1a472db61360261c678404e40a50c0c3fc79471bef8dc9a740e468e88c14,
// verified via verification/verify_handoff.py: 40 packaged + 31 approved
// source files, zero failures).
//
// Two real, backend-independent pieces are implemented and tested here:
// (1) per-conversation draft isolation -- reproduced live before this fix
// as a genuine bug: switching conversations left the composer's unsent
// text completely untouched, silently attributing conversation A's draft
// to conversation B; (2) Quick Switch, a real keyboard-accessible recent-
// conversations panel built on the already-existing GET /api/sessions
// and the already-hardened openSession() -- never a new switching
// mechanism, never the approved archive's own illustrative example
// titles. Workspace Tabs (B14's other named feature) is NOT built in
// this pass; see docs/orneur/status/ORNEUR_B14_MULTI_CONVERSATION_NAV.md
// for why, disclosed rather than fabricated.
//
// Run with: node --test tests/frontend/test_b14_quick_switch_and_drafts.mjs
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

test('draft clearing is wired into every genuine identity transition (logout/session-expiry, sign-in, anonymous)', () => {
  const clearAuthStateSrc = extractBalancedFunction(source, 'function _clearAuthStateAndShowSignIn(message) {').text;
  const onAuthSuccessSrc = extractBalancedFunction(source, 'function onAuthSuccess(data) {').text;
  const continueAnonymousSrc = extractBalancedFunction(source, 'function continueAnonymous() {').text;
  assert.ok(clearAuthStateSrc.includes('_draftsByConversation.clear()'), 'logout/session-expiry must clear all drafts -- a draft keyed only by conversation id must not survive an account switch');
  assert.ok(onAuthSuccessSrc.includes('_draftsByConversation.clear()'), 'a sign-in that never calls doLogout() must still clear stale drafts');
  assert.ok(continueAnonymousSrc.includes('_draftsByConversation.clear()'), 'going anonymous must not leave a previous principal\'s drafts behind');
});

test('openSession() saves the departing draft and restores the target\'s own draft, never a shared singleton', () => {
  const openSessionSrc = extractBalancedFunction(source, 'async function openSession(sid, title) {').text;
  const saveIdx = openSessionSrc.indexOf('_saveCurrentDraft();');
  const assignIdx = openSessionSrc.indexOf('sessionId = sid;');
  const restoreIdx = openSessionSrc.indexOf('_restoreDraftFor(sid);');
  assert.ok(saveIdx !== -1 && assignIdx !== -1 && restoreIdx !== -1);
  assert.ok(saveIdx < assignIdx, '_saveCurrentDraft() must run BEFORE sessionId changes, so it saves under the DEPARTING conversation\'s own id');
  assert.ok(assignIdx < restoreIdx, '_restoreDraftFor() must run AFTER sessionId changes, so it restores the TARGET conversation\'s own draft');
});

test('Quick Switch lists real conversations from GET /api/sessions, never fabricated/example titles', () => {
  const fnSrc = extractBalancedFunction(source, 'async function openQuickSwitch() {').text;
  assert.ok(fnSrc.includes("fetch('/api/sessions?limit=8'"), 'must call the real, existing sessions endpoint');
  assert.ok(fnSrc.includes('esc(title)'), 'a conversation title is untrusted content and must be escaped before rendering -- the exact "rendered conversation title injection" the contract names');
  assert.ok(!fnSrc.includes("'Infrastructure strategy'") && !fnSrc.includes('Research and reliability'), 'must never hardcode the approved archive\'s own illustrative example conversation titles');
});

test('Quick Switch reuses the real, already-hardened openSession() rather than a new switching mechanism', () => {
  const fnSrc = extractBalancedFunction(source, 'async function openQuickSwitch() {').text;
  assert.ok(fnSrc.includes('openSession(s.id, title)'), 'switching via Quick Switch must go through the same openSession() that already has ownership-epoch and draft-isolation correctness built in');
});

test('openQuickSwitch()/closeQuickSwitch() are idempotent and manage focus correctly', () => {
  const openSrc = extractBalancedFunction(source, 'async function openQuickSwitch() {').text;
  const closeSrc = extractBalancedFunction(source, 'function closeQuickSwitch() {').text;
  assert.ok(openSrc.includes('if (!panel.hidden) return;'), 'opening an already-open panel must be a safe no-op');
  assert.ok(closeSrc.includes('if (panel.hidden) return;'), 'closing an already-closed panel must be a safe no-op');
  assert.ok(openSrc.includes('_preQuickSwitchFocusEl = document.activeElement;'));
  assert.ok(closeSrc.includes('.focus();'));
});

test('newConversation() closes Quick Switch too, matching the same account-transition safety as B04/B13', () => {
  const newConversationSrc = extractBalancedFunction(source, 'function newConversation() {').text;
  assert.ok(newConversationSrc.includes('closeQuickSwitch();'));
});

// --- Behavioral tests: draft save/restore against a minimal fake DOM ---

function makeFakeInput(initialValue) {
  return { value: initialValue || '', style: {}, scrollHeight: 24 };
}

test('_saveCurrentDraft()/_restoreDraftFor() round-trip correctly, including the special "new conversation" slot', () => {
  const saveSrc = extractBalancedFunction(source, 'function _saveCurrentDraft() {').text;
  const restoreSrc = extractBalancedFunction(source, 'function _restoreDraftFor(id) {').text;
  const keySrc = extractBalancedFunction(source, 'function _draftKeyFor(id) {').text;
  const input = makeFakeInput();
  const composerEl = { querySelector: () => input };
  const sandbox = { composerEl, sessionId: 'conv-A', updateSendEnabled: () => {} };
  vm.createContext(sandbox);
  vm.runInContext(`var _draftsByConversation = new Map();\n${keySrc}\n${saveSrc}\n${restoreSrc}`, sandbox);

  input.value = 'typed for conversation A';
  sandbox._saveCurrentDraft();
  sandbox.sessionId = 'conv-B';
  sandbox._restoreDraftFor('conv-B');
  assert.equal(input.value, '', 'conversation B has no saved draft yet -- must not show A\'s text');

  input.value = 'typed for conversation B';
  sandbox._saveCurrentDraft();
  sandbox.sessionId = null;
  sandbox._restoreDraftFor(null);
  assert.equal(input.value, '', 'the "new conversation" slot has no saved draft yet');

  input.value = 'typed for a new conversation';
  sandbox._saveCurrentDraft();
  sandbox.sessionId = 'conv-A';
  sandbox._restoreDraftFor('conv-A');
  assert.equal(input.value, 'typed for conversation A', 'switching back to A must restore A\'s own draft, not B\'s or the new-conversation slot\'s');

  sandbox.sessionId = 'conv-B';
  sandbox._restoreDraftFor('conv-B');
  assert.equal(input.value, 'typed for conversation B');

  sandbox.sessionId = null;
  sandbox._restoreDraftFor(null);
  assert.equal(input.value, 'typed for a new conversation');
});

test('_saveCurrentDraft() clears a conversation\'s saved draft once the input is emptied (e.g. after sending)', () => {
  const saveSrc = extractBalancedFunction(source, 'function _saveCurrentDraft() {').text;
  const keySrc = extractBalancedFunction(source, 'function _draftKeyFor(id) {').text;
  const input = makeFakeInput('will be sent');
  const composerEl = { querySelector: () => input };
  const sandbox = { composerEl, sessionId: 'conv-A' };
  vm.createContext(sandbox);
  vm.runInContext(`var _draftsByConversation = new Map();\n${keySrc}\n${saveSrc}`, sandbox);
  sandbox._saveCurrentDraft();
  assert.equal(sandbox._draftsByConversation.get('conv-A'), 'will be sent');
  input.value = ''; // simulates sendMessage() clearing it after a real send
  sandbox._saveCurrentDraft();
  assert.equal(sandbox._draftsByConversation.has('conv-A'), false, 'an emptied input must clear the stored draft, not leave a stale empty-string entry');
});

test('_saveCurrentDraft()/_restoreDraftFor() are safe no-ops with no composerEl mounted', () => {
  const saveSrc = extractBalancedFunction(source, 'function _saveCurrentDraft() {').text;
  const restoreSrc = extractBalancedFunction(source, 'function _restoreDraftFor(id) {').text;
  const keySrc = extractBalancedFunction(source, 'function _draftKeyFor(id) {').text;
  const sandbox = { composerEl: null, sessionId: null };
  vm.createContext(sandbox);
  vm.runInContext(`var _draftsByConversation = new Map();\n${keySrc}\n${saveSrc}\n${restoreSrc}`, sandbox);
  assert.doesNotThrow(() => sandbox._saveCurrentDraft());
  assert.doesNotThrow(() => sandbox._restoreDraftFor('any'));
});
