// B13 Temporary / Private Chat regression tests.
//
// INTEGRATION Phase D (2026-10-24): Cursor PR #95-98 adds a real
// server-owned temporary-chat backend (docs/orneur/cursor/
// ORNEUR_B13_TEMPORARY_CHAT_HANDOFF.md on the integration candidate,
// confirmed by reading orca/serve/api.py's open_temporary_chat()/
// temporary_chat_status()/close_temporary_chat() directly). The prior
// honest disabled-state implementation ("no backend exists") is
// obsolete -- replaced with real wiring to the same approved dialog
// shell (#temp-mode-prestart is the original "Before you start" content
// with corrected, now-true copy; #temp-mode-active is new, for the one
// state the original design never needed: a real active session).
//
// Honest copy preserved, not weakened: the transcript genuinely exists
// on the server until close/expiry -- this is NOT zero-persistence, and
// the UI says so. Close reports `failed` (a deletion that leaves the
// transcript) honestly, never as `closed`.
//
// Run with: node --test tests/frontend/test_b13_temporary_chat.mjs
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

test('TTL default is always inside the real valid range (60-86400s)', () => {
  const idx = source.indexOf('TEMP_CHAT_DEFAULT_TTL_SECONDS');
  assert.ok(idx !== -1);
  const line = source.slice(idx, source.indexOf(';', idx));
  const value = Number(line.match(/= (\d+)/)[1]);
  assert.ok(value >= 60 && value <= 86400, `default TTL ${value} must be inside the real 60-86400s range or every start request would be rejected`);
});

test('Start temporary chat sends a real POST to /api/sessions/temporary and only treats the backend\'s own state:"active" as success', () => {
  const idx = source.indexOf("document.getElementById('temp-mode-start').addEventListener");
  const fnSrc = source.slice(idx, idx + 2500);
  assert.ok(fnSrc.includes("fetch('/api/sessions/temporary'"));
  assert.ok(fnSrc.includes("data.state !== 'active'"), 'must not treat any 200 response as success -- only a real state:"active" record');
});

test('Close temporary chat only treats real "closed" or "expired" as success -- "failed" is never silently treated as closed', () => {
  const idx = source.indexOf("document.getElementById('temp-mode-close-chat').addEventListener");
  const fnSrc = source.slice(idx, idx + 2500);
  assert.ok(fnSrc.includes("/temporary/close"));
  assert.ok(fnSrc.includes("data.state === 'closed' || data.state === 'expired'"));
  assert.ok(fnSrc.includes('could not be fully closed'), 'a real "failed" cleanup state must show an honest failure message, not claim success');
});

test('honest copy: the transcript genuinely exists until close/expiry -- never claims zero-persistence', () => {
  const idx = source.indexOf('id="temp-mode-prestart"');
  const panelMarkup = source.slice(idx, idx + 2500);
  assert.ok(panelMarkup.includes('still exists on the server until you close it or it expires'), 'must not imply the chat leaves no storage trace -- the real JSONL transcript exists until close/expiry, per the contract');
  assert.ok(!/zero[\s-]?(persistence|storage|trace)/i.test(panelMarkup.replace('is not zero-persistence', '')), 'must never claim a positive zero-persistence/zero-trace guarantee');
});

test('sendMessage() handles a real 409 temporary_expired/temporary_closed refusal honestly, distinct from a generic failure, and resets the active indicator', () => {
  const fnSrc = extractBalancedFunction(source, 'async function sendMessage() {').text;
  assert.ok(fnSrc.includes("resp.status === 409"));
  assert.ok(fnSrc.includes("errData.code === 'temporary_expired' || errData.code === 'temporary_closed'"));
  assert.ok(fnSrc.includes('_isTemporarySession = false'), 'the header indicator must not keep claiming an active temporary session the server has already refused to continue');
});

test('exportConversation() surfaces the real server error (covers 409 temporary_not_exportable honestly) instead of a generic failure', () => {
  const fnSrc = extractBalancedFunction(source, 'async function exportConversation(sid, title, format) {').text;
  assert.ok(fnSrc.includes('errData.error ||'), 'must show the real reason when available, not only the generic fallback');
});

test('newConversation() and openSession() reset the temporary-session indicator -- it must never linger onto an unrelated conversation', () => {
  const newConvSrc = extractBalancedFunction(source, 'function newConversation() {').text;
  const openSessSrc = extractBalancedFunction(source, 'async function openSession(sid, title) {').text;
  assert.ok(newConvSrc.includes('_isTemporarySession = false'));
  assert.ok(openSessSrc.includes('_isTemporarySession = false'));
});

test('openTempModePanel()/closeTempModePanel() are idempotent and manage focus correctly', () => {
  const openSrc = extractBalancedFunction(source, 'function openTempModePanel() {').text;
  const closeSrc = extractBalancedFunction(source, 'function closeTempModePanel() {').text;
  assert.ok(openSrc.includes('if (!panel.hidden) return;'), 'opening an already-open panel must be a safe no-op');
  assert.ok(closeSrc.includes('if (panel.hidden) return;'), 'closing an already-closed panel must be a safe no-op');
  assert.ok(openSrc.includes('_preTempModeFocusEl = document.activeElement;'), 'must capture the invoking control to restore focus on close');
  assert.ok(closeSrc.includes('.focus();'), 'must restore focus on close');
});

test('the temp-mode-actions button-overflow fix is still present (reproduced live before this fix, this session)', () => {
  assert.ok(source.includes('.temp-mode-actions .expand-action{flex:1;height:auto'), 'must override the fixed 34px height for this panel\'s longer button labels -- reproduced live as visual overlap between Back and Start temporary chat');
});

// --- Behavioral tests against the real functions, with a minimal fake DOM ---

function makeFakeNode(id) {
  const el = {
    id: id || '',
    hidden: true,
    _attrs: {},
    _children: [],
    disabled: false,
    classList: { _set: new Set(), add(c) { el.classList._set.add(c); }, remove(c) { el.classList._set.delete(c); }, toggle(c, f) { if (f) el.classList._set.add(c); else el.classList._set.delete(c); }, contains(c) { return el.classList._set.has(c); } },
    textContent: '',
    title: '',
    offsetParent: {},
    setAttribute(k, v) { el._attrs[k] = v; },
    focus() { fakeDoc.activeElement = el; },
    querySelector(sel) { return el._children.find((c) => '.' + c.className === sel) || null; },
    querySelectorAll() { return el._children; },
  };
  return el;
}

let fakeDoc;

function makeSandbox() {
  const btn = makeFakeNode('temp-mode-btn');
  const label = makeFakeNode(''); label.className = 'temp-entry-label';
  btn._children = [label];
  const panel = makeFakeNode('temp-mode-panel');
  const backdrop = makeFakeNode('temp-mode-backdrop');
  const closeBtn = makeFakeNode('temp-mode-close');
  const prestart = makeFakeNode('temp-mode-prestart');
  const active = makeFakeNode('temp-mode-active');
  const startBtn = makeFakeNode('temp-mode-start');
  const tempError = makeFakeNode('temp-mode-error');
  const expiry = makeFakeNode('temp-mode-expiry');
  const closeChatBtn = makeFakeNode('temp-mode-close-chat');
  const closeChatError = makeFakeNode('temp-mode-close-error');
  panel._children = [closeBtn];
  const registry = {
    'temp-mode-btn': btn, 'temp-mode-panel': panel, 'temp-mode-backdrop': backdrop, 'temp-mode-close': closeBtn,
    'temp-mode-prestart': prestart, 'temp-mode-active': active, 'temp-mode-start': startBtn,
    'temp-mode-error': tempError, 'temp-mode-expiry': expiry, 'temp-mode-close-chat': closeChatBtn, 'temp-mode-close-error': closeChatError,
  };
  fakeDoc = {
    activeElement: btn,
    getElementById: (id) => registry[id] || null,
    body: { contains: (el) => Object.values(registry).includes(el) },
  };
  const sandbox = {
    document: fakeDoc,
    _preTempModeFocusEl: null,
    _isTemporarySession: false,
    _tempSessionExpiresAt: null,
    _authToken: 'tok-1',
  };
  vm.createContext(sandbox);
  const openSrc = extractBalancedFunction(source, 'function openTempModePanel() {').text;
  const closeSrc = extractBalancedFunction(source, 'function closeTempModePanel() {').text;
  vm.runInContext(`${openSrc}\n${closeSrc}`, sandbox);
  return { sandbox, btn, panel, backdrop, closeBtn, prestart, active, startBtn, label };
}

test('openTempModePanel() shows the panel+backdrop, marks expanded, and focuses the close button', () => {
  const { sandbox, panel, backdrop, btn, closeBtn } = makeSandbox();
  sandbox.openTempModePanel();
  assert.equal(panel.hidden, false);
  assert.equal(backdrop.hidden, false);
  assert.equal(btn._attrs['aria-expanded'], 'true');
  assert.equal(fakeDoc.activeElement, closeBtn);
});

test('openTempModePanel() shows the prestart view with a signed-in-enabled Start button when no temp session is active', () => {
  const { sandbox, prestart, active, startBtn } = makeSandbox();
  sandbox.openTempModePanel();
  assert.equal(prestart.hidden, false);
  assert.equal(active.hidden, true);
  assert.equal(startBtn.disabled, false, 'signed in (fake _authToken is set) -- Start must be enabled');
});

test('openTempModePanel() shows the active view when _isTemporarySession is true', () => {
  const { sandbox, prestart, active } = makeSandbox();
  sandbox._isTemporarySession = true;
  sandbox._tempSessionExpiresAt = Math.floor(Date.now() / 1000) + 3600;
  sandbox.openTempModePanel();
  assert.equal(prestart.hidden, true);
  assert.equal(active.hidden, false);
});

test('closeTempModePanel() hides the panel+backdrop and restores focus to the invoking control', () => {
  const { sandbox, panel, backdrop, btn } = makeSandbox();
  sandbox.openTempModePanel();
  sandbox.closeTempModePanel();
  assert.equal(panel.hidden, true);
  assert.equal(backdrop.hidden, true);
  assert.equal(btn._attrs['aria-expanded'], 'false');
  assert.equal(fakeDoc.activeElement, btn);
});

test('_updateTempModeIndicator() reflects real state on the header pill, including "· Active"', () => {
  const fnSrc = extractBalancedFunction(source, 'function _updateTempModeIndicator() {').text;
  const { sandbox, btn, label } = makeSandbox();
  vm.runInContext(fnSrc, sandbox);
  sandbox._isTemporarySession = false;
  sandbox._updateTempModeIndicator();
  assert.equal(label.textContent, 'Temporary');
  assert.equal(btn.classList.contains('temp-active'), false);

  sandbox._isTemporarySession = true;
  sandbox._updateTempModeIndicator();
  assert.equal(label.textContent, 'Temporary · Active');
  assert.equal(btn.classList.contains('temp-active'), true);
});
