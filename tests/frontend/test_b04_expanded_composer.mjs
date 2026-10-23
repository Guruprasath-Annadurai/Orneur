// B04 Expanded Composer / Draft Workspace regression tests.
//
// Source-verified against ORNEUR_B04_FINAL_LOCK_AND_HANDOFF.zip (SHA-256
// ad5e1304c096029df337c8d8aee2ecef79d6a3c62ad46a08bf9879dd093fffad,
// confirmed against SHA256_MANIFEST.txt and the archive's own
// verify_assets.py, 26/26 files passing). docs/B04_IMPLEMENTATION_CONTRACT.md
// section 3's state machine is: normal -> FOCUSED_EXPANDED -> DRAFT_WORKSPACE,
// with Return/Close/Escape from the workspace going back to
// FOCUSED_EXPANDED (never all the way to normal in one step).
//
// A real bug was caught during live browser verification before these
// tests were written: the CSS originally read ".composer.focused-expanded"
// and ".workspace-body .composer", but #live-composer (the movable
// wrapper reparented between the composer slots and the workspace) never
// actually carries the ".composer" class -- that class lives on the
// fixed slot elements (#composer-empty-slot/#composer-active-slot) in
// the static markup. Both the FOCUSED_EXPANDED styling and the
// workspace's textarea styling (dark-theme background in particular)
// silently never applied. Fixed by giving composerEl a stable
// "live-composer" id and rewriting the CSS to target it directly. The
// structural test below guards against this exact regression recurring.
//
// Run with: node --test tests/frontend/test_b04_expanded_composer.mjs
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

// --- Structural regression guards (catch the exact live-reproduced bug) ---

test("mountComposer() assigns composerEl a stable id ('live-composer'), not relying on a .composer class it never carries", () => {
  const mountSrc = extractBalancedFunction(source, 'function mountComposer(slotId) {').text;
  assert.ok(mountSrc.includes("composerEl.id = 'live-composer'"), 'composerEl must get a stable id so CSS can target it regardless of which parent (slot or workspace) it currently sits in');
});

test('no CSS rule depends on composerEl itself carrying a stray .composer class (the exact bug reproduced live before the fix)', () => {
  assert.ok(!source.includes('.composer.focused-expanded'), 'must not reintroduce the selector that silently never matched composerEl');
  assert.ok(!source.includes('.workspace-body .composer{') && !source.includes('.workspace-body .composer '), 'must not reintroduce the selector that left the workspace textarea with the browser default white background');
});

test('the workspace textarea styling is keyed off #live-composer, including the base (non-size) properties lost without it', () => {
  const idx = source.indexOf('.workspace-body #live-composer textarea{');
  assert.ok(idx !== -1, 'the workspace textarea rule must target #live-composer directly');
  const rule = source.slice(idx, source.indexOf('}', idx) + 1);
  for (const prop of ['background:none', 'border:none', 'color:var(--ink)']) {
    assert.ok(rule.includes(prop), `workspace textarea rule missing ${prop} -- reproduced live as a white background in dark theme without it`);
  }
});

// --- Behavioral tests against the real functions, with a minimal fake DOM ---

function makeFakeElement(id) {
  const el = {
    id: id || '',
    _classes: new Set(),
    _attrs: {},
    children: [],
    parentElement: null,
    value: '',
    classList: {
      add: (...cls) => cls.forEach((c) => el._classes.add(c)),
      remove: (...cls) => cls.forEach((c) => el._classes.delete(c)),
      contains: (c) => el._classes.has(c),
    },
    get className() { return [...el._classes].join(' '); },
    setAttribute: (k, v) => { el._attrs[k] = v; },
    removeAttribute: (k) => { delete el._attrs[k]; },
    hasAttribute: (k) => k in el._attrs,
    appendChild: (child) => {
      if (child.parentElement) {
        child.parentElement.children = child.parentElement.children.filter((c) => c !== child);
      }
      child.parentElement = el;
      el.children.push(child);
      return child;
    },
    querySelector: (sel) => {
      const wantId = sel.startsWith('#') ? sel.slice(1) : null;
      const stack = [...el.children];
      while (stack.length) {
        const node = stack.shift();
        if (wantId && node.id === wantId) return node;
        stack.push(...(node.children || []));
      }
      return null;
    },
    querySelectorAll: () => {
      // Only used by _workspaceFocusableEls() for 'button, textarea, input, [tabindex]...' --
      // this fake DOM has no tag/role concept, so return every descendant
      // (every fake element created in these tests represents a real
      // focusable control anyway) and let the .filter() in the real
      // function apply offsetParent/disabled as usual.
      const out = [];
      const stack = [...el.children];
      while (stack.length) {
        const node = stack.shift();
        out.push(node);
        stack.push(...(node.children || []));
      }
      return out;
    },
    focus: () => { fakeDoc.activeElement = el; },
    offsetParent: {}, // "visible" for the focusable-els filter
    disabled: false,
    tagName: 'DIV',
  };
  return el;
}

let fakeDoc;

function makeSandbox() {
  const appRoot = makeFakeElement('app-root');
  const emptySlot = makeFakeElement('composer-empty-slot');
  const scrim = makeFakeElement('draft-workspace-scrim');
  const workspaceSlot = makeFakeElement('draft-workspace-slot');
  const closeWorkspaceBtn = makeFakeElement('close-workspace-btn');
  const workspaceDialog = makeFakeElement('draft-workspace');
  workspaceDialog.children = [closeWorkspaceBtn, workspaceSlot];
  scrim.children = [workspaceDialog];
  const openWsBtn = makeFakeElement('open-workspace-btn');

  const registry = { 'app-root': appRoot, 'composer-empty-slot': emptySlot, 'draft-workspace-scrim': scrim, 'draft-workspace-slot': workspaceSlot, 'draft-workspace': workspaceDialog };

  fakeDoc = {
    activeElement: null,
    getElementById: (id) => registry[id] || null,
    body: { contains: (elm) => elm && (elm === appRoot || elm === emptySlot || elm === scrim || elm === workspaceSlot || elm === workspaceDialog || emptySlot.children.includes(elm) || workspaceSlot.children.includes(elm)) },
  };

  const msgInput = makeFakeElement('msg-input');
  const openWorkspaceBtn = openWsBtn;
  const expandBtn = makeFakeElement('expand-btn');
  const composerEl = makeFakeElement('live-composer');
  composerEl.children = [msgInput, openWorkspaceBtn, expandBtn];
  emptySlot.appendChild(composerEl);

  const sandbox = {
    document: fakeDoc,
    composerEl,
    _preWorkspaceFocusEl: null,
    _composerOriginSlot: null,
  };
  vm.createContext(sandbox);
  const expandSrc = extractBalancedFunction(source, 'function expandComposer() {').text;
  const collapseSrc = extractBalancedFunction(source, 'function collapseComposer() {').text;
  const openWsSrc = extractBalancedFunction(source, 'function openDraftWorkspace() {').text;
  const closeWsSrc = extractBalancedFunction(source, 'function closeDraftWorkspace() {').text;
  const focusablesSrc = extractBalancedFunction(source, 'function _workspaceFocusableEls() {').text;
  vm.runInContext(`${expandSrc}\n${collapseSrc}\n${focusablesSrc}\n${openWsSrc}\n${closeWsSrc}`, sandbox);
  return { sandbox, composerEl, msgInput, scrim, appRoot, emptySlot, openWorkspaceBtn };
}

test('expandComposer() adds focused-expanded and focuses the textarea', () => {
  const { sandbox, composerEl, msgInput } = makeSandbox();
  sandbox.expandComposer();
  assert.equal(composerEl.classList.contains('focused-expanded'), true);
  assert.equal(fakeDoc.activeElement, msgInput);
});

test('collapseComposer() removes focused-expanded and is a safe no-op with no composerEl', () => {
  const { sandbox, composerEl } = makeSandbox();
  sandbox.expandComposer();
  sandbox.collapseComposer();
  assert.equal(composerEl.classList.contains('focused-expanded'), false);

  sandbox.composerEl = null;
  assert.doesNotThrow(() => sandbox.collapseComposer());
});

test('openDraftWorkspace() reparents composerEl, preserves its value, and marks the background inert', () => {
  const { sandbox, composerEl, msgInput, scrim, appRoot } = makeSandbox();
  msgInput.value = 'unsent draft text, must survive the move';
  sandbox.openDraftWorkspace();
  assert.equal(scrim.classList.contains('open'), true);
  assert.equal(composerEl.parentElement.id, 'draft-workspace-slot');
  assert.equal(msgInput.value, 'unsent draft text, must survive the move', 'the SAME element is moved, never cloned -- its value must be untouched');
  assert.equal(appRoot.hasAttribute('inert'), true);
  assert.equal(fakeDoc.activeElement, msgInput);
});

test('openDraftWorkspace() is idempotent when already open', () => {
  const { sandbox, composerEl } = makeSandbox();
  sandbox.openDraftWorkspace();
  const parentAfterFirst = composerEl.parentElement;
  sandbox.openDraftWorkspace(); // should be a no-op, not re-capture a new origin slot
  assert.equal(composerEl.parentElement, parentAfterFirst);
});

test('closeDraftWorkspace() returns composerEl to its real origin slot and clears inert', () => {
  const { sandbox, composerEl, scrim, appRoot, emptySlot } = makeSandbox();
  sandbox.openDraftWorkspace();
  sandbox.closeDraftWorkspace();
  assert.equal(scrim.classList.contains('open'), false);
  assert.equal(composerEl.parentElement, emptySlot, 'must return to the slot it actually came from, not a hardcoded one');
  assert.equal(appRoot.hasAttribute('inert'), false);
});

test('closeDraftWorkspace() restores focus to the invoking control when the original focus target is gone', () => {
  const { sandbox, composerEl, openWorkspaceBtn } = makeSandbox();
  sandbox.openDraftWorkspace();
  sandbox.closeDraftWorkspace();
  assert.equal(fakeDoc.activeElement, openWorkspaceBtn, 'falls back to #open-workspace-btn when the pre-open focus target is no longer in the document');
});

test('closeDraftWorkspace() is a safe no-op when already closed', () => {
  const { sandbox, scrim } = makeSandbox();
  assert.doesNotThrow(() => sandbox.closeDraftWorkspace());
  assert.equal(scrim.classList.contains('open'), false);
});

test('_workspaceFocusableEls() returns elements in DOM order for the Tab-trap to wrap correctly', () => {
  const { sandbox } = makeSandbox();
  sandbox.openDraftWorkspace();
  const els = sandbox._workspaceFocusableEls();
  assert.ok(els.length >= 1);
  assert.equal(els[0].id, 'close-workspace-btn');
});

test("newConversation() collapses the composer (and any open workspace) when composerEl exists", () => {
  const newConversationSrc = extractBalancedFunction(source, 'function newConversation() {').text;
  let collapseCalled = false;
  const sandbox = {
    _authToken: 'token-alice',
    _abandonActiveStream: () => {},
    sessionId: 'old-sid',
    composerEl: {}, // truthy -- collapseComposer() must be called
    collapseComposer: () => { collapseCalled = true; },
    closeTempModePanel: () => {},
    document: { getElementById: () => ({ innerHTML: '' }) },
    highlightSelectedRecent: () => {},
    showEmptyView: () => {},
  };
  vm.createContext(sandbox);
  vm.runInContext(
    `var _historyEpoch = 0;\nvar _messageEpoch = 0;\nfunction _abandonActiveMessage(){_messageEpoch++;}\n${newConversationSrc}`,
    sandbox,
  );
  sandbox.newConversation();
  assert.equal(collapseCalled, true, 'a derelict draft-workspace dialog must not survive starting a new conversation / account switch');
});
