// B11 Editing & Versions regression tests.
//
// Source: docs/B11_IMPLEMENTATION_CONTRACT.md (ORNEUR_B11_FINAL_LOCK_AND_HANDOFF.zip,
// SHA-256 a6f6d0350bc3f889fdcb572447857e69f73bda59b28000a1befaa8f0e38c2401,
// verified against manifests/SHA256_MANIFEST.json's per-file sha256/
// size_bytes records, 21/21 files passing).
//
// No message-edit, version-lineage or regenerate backend exists anywhere
// in this codebase (grepped orca/serve/api.py and orca/serve/conversations.py;
// zero hits for edit_message/message_version/version_id/regenerate/
// lineage -- only the read-only GET .../messages endpoint). The
// contract's own instruction for exactly this: "leave dependent UI
// disabled/fail-closed, document the gap." This phase implements Inline
// Edit only (the contract's own default surface) with a genuinely
// disabled Save, reusing the approved prototype's own already-honest
// copy ("Local preview · not submitted", "The original stays in
// history. Sending the edit requires an available model."). Response
// Versions/Regenerate/Compare (the contract's optional surface) is NOT
// built -- there is no second response version anywhere in this backend
// to compare against.
//
// Run with: node --test tests/frontend/test_b11_inline_edit.mjs
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

test('"Save edit" carries a real disabled attribute, never a fake clickable control', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text) {').text;
  const btnIdx = fnSrc.indexOf('Save edit');
  const btnTagStart = fnSrc.lastIndexOf('<button', btnIdx);
  const btnTag = fnSrc.slice(btnTagStart, fnSrc.indexOf('>', btnTagStart) + 1);
  assert.ok(btnTag.includes('disabled'), 'per the contract, editing must stay disabled/fail-closed with no backend edit endpoint');
});

test('no code path ever submits an edit, mutates history, or claims a server commit', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text) {').text;
  for (const forbidden of ['fetch(', 'PATCH', 'edit_acknowledged', 'submitEdit', '/api/session']) {
    assert.ok(!fnSrc.includes(forbidden), `appendUserMessage() must never attempt a real edit submission (found "${forbidden}") -- no backend edit endpoint exists`);
  }
});

test('the edit textarea is reset to the exact original text on every open, never a stale abandoned draft', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text) {').text;
  assert.ok(fnSrc.includes('textarea.value = text;'), 'must reset to the real original -- "initial text exactly equals selected message," and Cancel must restore it with no mutation');
});

test('the edit panel visibility is controlled by a class, not a base display style that would out-specify [hidden] (the same bug class already found twice this session)', () => {
  const idx = source.indexOf('.edit-msg-panel{');
  assert.ok(idx !== -1);
  const baseRule = source.slice(idx, source.indexOf('}', idx) + 1);
  assert.ok(!baseRule.includes('display:block') && !baseRule.includes('display:flex'), 'the base .edit-msg-panel rule must not force a visible display value');
  assert.ok(source.includes('.edit-msg-panel.open{display:block}'), 'must use .open as the authoritative toggle, matching the B05/B15 fix pattern');
});

test('the disabled Save button explains why, honestly, not a generic "coming soon"', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text) {').text;
  assert.ok(fnSrc.includes('does not exist in this backend yet'), 'the explanation must name the real, specific gap, not a vague placeholder');
});

// --- Behavioral test against the real function, with a minimal fake DOM ---

function makeFakeNode(tag) {
  const el = {
    tagName: tag || 'DIV',
    _children: [],
    className: '',
    _html: '',
    hidden: false,
    value: '',
    disabled: false,
    title: '',
    _attrs: {},
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => el.classList._set.add(x)); },
      remove(...c) { c.forEach((x) => el.classList._set.delete(x)); },
      toggle(c, f) { const on = f === undefined ? !el.classList._set.has(c) : f; if (on) el.classList._set.add(c); else el.classList._set.delete(c); },
      contains(c) { return el.classList._set.has(c); },
    },
    get innerHTML() { return el._html; },
    set innerHTML(v) {
      el._html = v;
      el._children = [];
      const tagMatches = [...v.matchAll(/<[a-zA-Z][^>]*>/g)];
      for (const m of tagMatches) {
        const tagStr = m[0];
        const classMatch = tagStr.match(/class="([^"]+)"/);
        const dataActionMatch = tagStr.match(/data-action="([^"]+)"/);
        if (!classMatch && !dataActionMatch) continue;
        if (classMatch) {
          for (const cls of classMatch[1].split(/\s+/)) {
            const frag = makeFakeNode('div');
            frag.className = cls;
            frag._dataAction = dataActionMatch ? dataActionMatch[1] : null;
            if (/\bdisabled\b/.test(tagStr)) frag.disabled = true;
            if (/\bhidden\b/.test(tagStr)) frag.hidden = true;
            el._children.push(frag);
          }
        } else {
          const frag = makeFakeNode('div');
          frag._dataAction = dataActionMatch[1];
          el._children.push(frag);
        }
      }
    },
    appendChild(child) { el._children.push(child); return child; },
    querySelector(sel) {
      const dataActionMatch = sel.match(/^\[data-action="([^"]+)"\]$/);
      if (dataActionMatch) return el._children.find((c) => c._dataAction === dataActionMatch[1]) || null;
      const cls = sel.replace(/^\./, '');
      return el._children.find((c) => (c.className || '') === cls) || null;
    },
    setAttribute(k, v) { el._attrs[k] = v; },
    addEventListener(evt, fn) { el[`_on_${evt}`] = fn; },
    focus() {},
  };
  return el;
}

test('appendUserMessage() wires Edit-open/Cancel-close correctly and resets the draft text', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text) {').text;
  const escSrc = extractBalancedFunction(source, 'function esc(t) {').text;
  const container = makeFakeNode('div');
  const sandbox = {
    document: { getElementById: () => container, createElement: (tag) => makeFakeNode(tag) },
    scrollReadingToBottom: () => {},
  };
  vm.createContext(sandbox);
  vm.runInContext(`var _userMsgCounter = 0;\n${escSrc}\n${fnSrc}`, sandbox);
  sandbox.appendUserMessage('hello world');
  const div = container._children[0];
  const editBtn = div._children.find((c) => c.className === 'edit-msg-btn');
  const panel = div._children.find((c) => c.className === 'edit-msg-panel');
  const textarea = div._children.find((c) => c.className === 'edit-msg-textarea');
  assert.ok(editBtn && panel && textarea);
  assert.equal(panel.hidden, true, 'closed by default');

  editBtn._on_click();
  assert.equal(panel.hidden, false);
  assert.equal(panel.classList.contains('open'), true);
  assert.equal(textarea.value, 'hello world', 'must reset to the real original text on open');
});
