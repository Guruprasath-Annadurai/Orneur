// B05 Native Model Selection regression tests.
//
// Source: docs/B05_IMPLEMENTATION_CONTRACT.md (from
// ORNEUR_B05_FINAL_LOCK_AND_HANDOFF.zip, SHA-256
// 44fd0d85685c94eff219e73b57745bf1df407fc1ecce56dc9e519dbded637dfc,
// verified against SHA256SUMS.txt, 17/17 files passing). This phase's
// scope: (1) the contract's explicit "clear selected model... on account/
// tenant switch or logout" requirement, which selectedModelVariant never
// honored before this; (2) "Buttons for Details must remain accessible
// even if selection is disabled... Never disable the entire row when it
// would hide reason/details from keyboard users" -- the previous
// `opt.disabled = true` made an unavailable row's reason text completely
// unreachable by Tab; (3) a verified-fields-only Details disclosure per
// model, sourced directly from GET /api/models.
//
// A second real bug was caught by live verification (not just reading
// the code): `.model-details{display:flex}` as the base rule out-
// specified the browser's own `[hidden]` attribute styling, so every
// details panel rendered permanently open regardless of the `hidden`
// property. Fixed by making `.open` (a class, matching this codebase's
// existing .modelmenu-panel.open convention) the authoritative toggle.
// The structural test below guards against this regression recurring.
//
// Run with: node --test tests/frontend/test_b05_model_picker.mjs
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

// --- Structural regression guards ---

test('unavailable model rows are never given the native disabled attribute (would remove them from the Tab order)', () => {
  const renderSrc = extractBalancedFunction(source, 'function renderModelOptions() {').text;
  assert.ok(!renderSrc.includes('opt.disabled = true'), 'must not reintroduce disabled-attribute rows -- they become unreachable by keyboard, hiding the reason text from Tab users entirely');
  assert.ok(renderSrc.includes("opt.setAttribute('aria-disabled', 'true')"), 'unavailable rows must stay focusable via aria-disabled, not the disabled attribute');
  assert.ok(renderSrc.includes('aria-describedby'), 'every row must link its visible reason text for assistive tech, available or not');
});

test('the model-details panel visibility is controlled by a class, not a base display style that would out-specify [hidden]', () => {
  const idx = source.indexOf('.model-details{');
  assert.ok(idx !== -1);
  const baseRule = source.slice(idx, source.indexOf('}', idx) + 1);
  assert.ok(!baseRule.includes('display:flex'), 'the base .model-details rule must not force display:flex -- reproduced live as every details panel rendering open by default, out-specifying [hidden]');
  assert.ok(source.includes('.model-details.open{display:flex}'), 'must have a dedicated .open class as the authoritative visibility toggle, matching this file\'s existing .modelmenu-panel.open convention');
});

test('renderModelOptions() only surfaces fields GET /api/models actually returns -- no fabricated modalities/regions/limits', () => {
  const renderSrc = extractBalancedFunction(source, 'function renderModelOptions() {').text;
  for (const forbidden of ['region', 'Region', 'pricing', 'Pricing', 'benchmark', 'Benchmark']) {
    assert.ok(!renderSrc.includes(forbidden), `must not fabricate a "${forbidden}" field the backend never provides -- the contract requires hiding unverified metrics, not inventing them`);
  }
  for (const real of ['info.model', 'info.lifecycle', 'info.vision_capable', 'info.resolved_model', 'info.disclosure']) {
    assert.ok(renderSrc.includes(real), `must source the Details panel from the real backend field ${real}`);
  }
});

test('resetModelSelection() is wired into every genuine identity transition', () => {
  const clearAuthStateSrc = extractBalancedFunction(source, 'function _clearAuthStateAndShowSignIn(message) {').text;
  const onAuthSuccessSrc = extractBalancedFunction(source, 'function onAuthSuccess(data) {').text;
  const continueAnonymousSrc = extractBalancedFunction(source, 'function continueAnonymous() {').text;
  assert.ok(clearAuthStateSrc.includes('resetModelSelection()'), 'logout/session-expiry (both route through _clearAuthStateAndShowSignIn) must clear the previous principal\'s model choice');
  assert.ok(onAuthSuccessSrc.includes('resetModelSelection()'), 'a sign-in that never calls doLogout() must still clear a stale prior selection');
  assert.ok(continueAnonymousSrc.includes('resetModelSelection()'), 'going anonymous must not leave a previous principal\'s model choice selectable');
});

// --- Behavioral test against the real function, with a minimal fake DOM ---

function makeFakeComposerEl() {
  const nodes = {};
  function makeNode(id) {
    const n = {
      id,
      _classes: new Set(),
      textContent: '',
      style: { display: '' },
      classList: {
        add: (...c) => c.forEach((x) => n._classes.add(x)),
        remove: (...c) => c.forEach((x) => n._classes.delete(x)),
        contains: (c) => n._classes.has(c),
        toggle: (c, force) => {
          const on = force === undefined ? !n._classes.has(c) : force;
          if (on) n._classes.add(c); else n._classes.delete(c);
          return on;
        },
      },
      value: '',
      _attrs: {},
      setAttribute: (k, v) => { n._attrs[k] = v; },
      removeAttribute: (k) => { delete n._attrs[k]; },
      title: '',
    };
    nodes[id] = n;
    return n;
  }
  ['model-label', 'model-dot', 'model-btn', 'model-disclosure', 'msg-input', 'send-btn'].forEach(makeNode);
  return {
    querySelector: (sel) => nodes[sel.replace('#', '')] || null,
    _nodes: nodes,
  };
}

test('resetModelSelection() clears the variant and restores the default "Choose model" UI', () => {
  const resetSrc = extractBalancedFunction(source, 'function resetModelSelection() {').text;
  const updateSendSrc = extractBalancedFunction(source, 'function updateSendEnabled() {').text;
  const composerEl = makeFakeComposerEl();
  composerEl._nodes['model-dot'].classList.add('avail');
  composerEl._nodes['model-label'].textContent = 'Novus';
  composerEl._nodes['model-disclosure'].style.display = '';
  composerEl._nodes['model-disclosure'].textContent = 'Currently serving via Genesis';
  composerEl._nodes['msg-input'].value = 'hello';
  composerEl._nodes['send-btn'].classList.remove('disabled');

  const sandbox = { selectedModelVariant: 'core', composerEl, isStreaming: false };
  vm.createContext(sandbox);
  vm.runInContext(`var SEND_ICON_SVG = '';\nvar STOP_ICON_SVG = '';\n${updateSendSrc}\n${resetSrc}`, sandbox);
  sandbox.resetModelSelection();

  assert.equal(sandbox.selectedModelVariant, null);
  assert.equal(composerEl._nodes['model-label'].textContent, 'Choose model');
  assert.equal(composerEl._nodes['model-dot'].classList.contains('avail'), false);
  assert.equal(composerEl._nodes['model-disclosure'].style.display, 'none');
  assert.equal(composerEl._nodes['send-btn'].classList.contains('disabled'), true, 'send must become disabled again -- no model is selected');
});

test('resetModelSelection() is a safe no-op when composerEl does not exist yet', () => {
  const resetSrc = extractBalancedFunction(source, 'function resetModelSelection() {').text;
  const sandbox = { selectedModelVariant: 'core', composerEl: null };
  vm.createContext(sandbox);
  vm.runInContext(resetSrc, sandbox);
  assert.doesNotThrow(() => sandbox.resetModelSelection());
  assert.equal(sandbox.selectedModelVariant, null, 'the variant itself must still clear even with no composer mounted');
});
