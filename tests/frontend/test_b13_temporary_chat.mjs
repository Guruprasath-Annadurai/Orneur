// B13 Temporary / Private Chat regression tests.
//
// Source: docs/B13_IMPLEMENTATION_CONTRACT.md (ORNEUR_B13_FINAL_LOCK_AND_HANDOFF.zip,
// SHA-256 f0ee3ddc1c44885a8adf3cb88d95cfd9b0a13202bdc8aaeeb78541606a14f9a8,
// verified via verification/verify_handoff.py: 32 package files + 24
// approved source files, zero failures).
//
// No server-owned typed session capability for a temporary/ephemeral
// conversation exists anywhere in this codebase (grepped orca/serve and
// orca/auth for temporary/ephemeral/private_mode/incognito; the one hit
// was an unrelated ExplainStore comment). The contract's own explicit
// guidance for exactly this situation: "If unsupported, show a clearly
// disabled state with a succinct explanation (not a fake toggle)." This
// phase implements that discoverability control and its details dialog
// using the REAL, founder-approved locked copy from
// references/ORNEUR_B13_Unified_Dark.html (itself already an honest
// "concept review, action disabled until verified implementation"
// design) -- not invented wording, and never a real "Start temporary
// chat" action.
//
// A real layout bug was caught by live verification: .expand-action's
// fixed 34px height (sized for B04's short labels) overflowed for the
// longer "Start temporary chat" text at mobile width, visually colliding
// with the "Back" button beside it. Fixed with a scoped override.
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

test('the "Start temporary chat" action carries a real disabled attribute, never a fake clickable toggle', () => {
  const idx = source.indexOf('id="temp-mode-panel"');
  assert.ok(idx !== -1);
  const panelMarkup = source.slice(idx, source.indexOf('</div>\n\n<div class="app"', idx));
  assert.ok(/Start temporary chat<\/button>/.test(panelMarkup) || panelMarkup.includes('Start temporary chat'));
  const btnIdx = panelMarkup.indexOf('Start temporary chat');
  const btnTagStart = panelMarkup.lastIndexOf('<button', btnIdx);
  const btnTag = panelMarkup.slice(btnTagStart, panelMarkup.indexOf('>', btnTagStart) + 1);
  assert.ok(btnTag.includes('disabled'), 'the action must carry a real disabled attribute -- per the contract, "not a fake toggle"');
});

test('no code path ever creates, activates, or claims a temporary session', () => {
  for (const marker of ['function openTempModePanel()', 'function closeTempModePanel()']) {
    const fnSrc = extractBalancedFunction(source, marker + ' {').text;
    for (const forbidden of ['temporary: true', "'temporary'", 'temp_session', 'createTempSession', 'activateTemp']) {
      assert.ok(!fnSrc.includes(forbidden), `${marker} must never attempt to create or claim a temporary session (found "${forbidden}") -- no backend capability exists for this`);
    }
  }
});

test('openTempModePanel()/closeTempModePanel() are idempotent and manage focus correctly', () => {
  const openSrc = extractBalancedFunction(source, 'function openTempModePanel() {').text;
  const closeSrc = extractBalancedFunction(source, 'function closeTempModePanel() {').text;
  assert.ok(openSrc.includes('if (!panel.hidden) return;'), 'opening an already-open panel must be a safe no-op');
  assert.ok(closeSrc.includes('if (panel.hidden) return;'), 'closing an already-closed panel must be a safe no-op');
  assert.ok(openSrc.includes('_preTempModeFocusEl = document.activeElement;'), 'must capture the invoking control to restore focus on close');
  assert.ok(closeSrc.includes('.focus();'), 'must restore focus on close');
});

test('newConversation() closes the temp-mode panel, matching the same account-transition safety established for B04\'s draft workspace', () => {
  const newConversationSrc = extractBalancedFunction(source, 'function newConversation() {').text;
  assert.ok(newConversationSrc.includes('closeTempModePanel();'), 'a derelict dialog must not survive starting a new conversation / account switch');
});

test('the temp-mode-actions button-overflow fix is present (reproduced live before this fix)', () => {
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
    offsetParent: {},
    setAttribute(k, v) { el._attrs[k] = v; },
    focus() { fakeDoc.activeElement = el; },
    querySelectorAll() { return el._children; },
  };
  return el;
}

let fakeDoc;

function makeSandbox() {
  const btn = makeFakeNode('temp-mode-btn');
  const panel = makeFakeNode('temp-mode-panel');
  const backdrop = makeFakeNode('temp-mode-backdrop');
  const closeBtn = makeFakeNode('temp-mode-close');
  panel._children = [closeBtn];
  const registry = { 'temp-mode-btn': btn, 'temp-mode-panel': panel, 'temp-mode-backdrop': backdrop, 'temp-mode-close': closeBtn };
  fakeDoc = {
    activeElement: btn,
    getElementById: (id) => registry[id] || null,
    body: { contains: (el) => Object.values(registry).includes(el) },
  };
  const sandbox = { document: fakeDoc, _preTempModeFocusEl: null };
  vm.createContext(sandbox);
  const openSrc = extractBalancedFunction(source, 'function openTempModePanel() {').text;
  const closeSrc = extractBalancedFunction(source, 'function closeTempModePanel() {').text;
  vm.runInContext(`${openSrc}\n${closeSrc}`, sandbox);
  return { sandbox, btn, panel, backdrop, closeBtn };
}

test('openTempModePanel() shows the panel+backdrop, marks expanded, and focuses the close button', () => {
  const { sandbox, panel, backdrop, btn, closeBtn } = makeSandbox();
  sandbox.openTempModePanel();
  assert.equal(panel.hidden, false);
  assert.equal(backdrop.hidden, false);
  assert.equal(btn._attrs['aria-expanded'], 'true');
  assert.equal(fakeDoc.activeElement, closeBtn);
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
