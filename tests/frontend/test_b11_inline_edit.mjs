// B11 Editing & Versions regression tests.
//
// INTEGRATION Phase C (2026-10-24): Cursor's PR #94 added real message-
// version/edit/regenerate APIs (docs/orneur/cursor/ORNEUR_B11_MESSAGE_VERSIONS_HANDOFF.md
// on the PR #98 integration candidate, confirmed by reading orca/serve/api.py
// directly, not just the doc). The prior honest-disabled-state premise
// ("no backend exists") is now obsolete -- replaced with real wiring:
//
// - Edit (user messages): real POST .../edits with a fresh Idempotency-Key
//   per save, duplicate-submit protection via a real disabled attribute
//   while in flight, loading/success/error states, honest copy that
//   editing does not erase long-term memory and does not regenerate the
//   answer below.
// - Historical version viewing: a real, READ-ONLY panel backed by
//   GET .../versions. Per the CTO addendum's explicit instruction, this
//   never implements a working previous/next version ACTIVATION control
//   -- the backend exposes no such action, only a read of the list.
// - Regenerate (assistant messages): deliberately NOT built. The
//   originally-approved B11 design only ever included Inline Edit as its
//   default surface; Response Versions/Regenerate was explicitly the
//   optional surface not built when no backend existed. Building it now
//   would extend the founder-approved design without approval, which the
//   addendum explicitly forbids ("Do not extend the approved B11 design
//   without founder approval"). Disclosed as a deliberate scope boundary.
// - message_id for a freshly-sent message is NOT available from
//   /api/stream's `done` event (confirmed by reading _persist_turn()
//   directly -- only the assistant's id is echoed back, the user side's
//   id is a separate UUID generated and persisted server-side, never
//   returned). _backfillMessageIds() fetches the real message list after
//   a successful exchange to learn it; until then Save stays honestly
//   disabled with that exact reason.
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

test('Save is honestly disabled until a real message_id is known, not a permanent fake disabled control', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text, meta) {').text;
  assert.ok(fnSrc.includes("div.dataset.messageId = (meta && meta.messageId) || ''"), 'message_id starts empty for a freshly-sent message not yet backfilled');
  assert.ok(fnSrc.includes('refreshSaveEnabled'), 'Save\'s disabled state must be dynamic (re-evaluated once the id arrives), not hardcoded permanently disabled');
  assert.ok(fnSrc.includes("hasn't finished saving yet"), 'the disabled reason must name the real, specific, temporary condition -- not a vague "coming soon" or a false claim that editing is unsupported');
});

test('a real edit POST is sent with a fresh Idempotency-Key, never a fabricated success', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text, meta) {').text;
  assert.ok(fnSrc.includes('/messages/${encodeURIComponent(messageId)}/edits'), 'must call the real edit endpoint');
  assert.ok(fnSrc.includes("'Idempotency-Key': crypto.randomUUID()"), 'must send a fresh idempotency key per save attempt');
  assert.ok(fnSrc.includes('data.active_content'), 'must display the server\'s own confirmed active_content, not merely echo what was typed');
});

test('duplicate-submit protection: Save is really disabled while a save request is in flight', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text, meta) {').text;
  const saveHandlerIdx = fnSrc.indexOf("saveBtn.addEventListener('click'");
  const disableIdx = fnSrc.indexOf('saveBtn.disabled = true;', saveHandlerIdx);
  const fetchIdx = fnSrc.indexOf("fetch(`/api/session/", saveHandlerIdx);
  assert.ok(disableIdx !== -1 && fetchIdx !== -1 && disableIdx < fetchIdx, 'Save must be disabled BEFORE the request starts, not after it resolves, so a second click during the request cannot fire a second request');
});

test('honest copy: editing does not erase long-term memory and does not claim the response below was regenerated', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text, meta) {').text;
  assert.ok(fnSrc.includes('does not remove this content from long-term memory') && fnSrc.includes('does not regenerate the response below'), 'must not imply either false capability -- per the contract, an edit does not rewrite vector memory and regenerate is a completely separate, unbuilt action');
});

test('version history is read-only: fetches the real GET .../versions list, never implements a version-activation control', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text, meta) {').text;
  assert.ok(fnSrc.includes('/messages/${encodeURIComponent(messageId)}/versions'), 'must call the real versions endpoint');
  // Strip comments before scanning for forbidden code -- the surrounding
  // prose legitimately explains what must NOT exist, which would
  // otherwise false-positive against its own words.
  const codeOnly = fnSrc.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const forbidden of ['restoreVersion', 'setActiveVersion', "method: 'PATCH'"]) {
    assert.ok(!codeOnly.includes(forbidden), `must never implement a version-activation action (found "${forbidden}") -- the backend exposes no such route, only a read of the history list`);
  }
});

test('Regenerate is deliberately not built -- no code path calls the real regenerate endpoint', () => {
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text, meta) {').text;
  assert.ok(!fnSrc.includes('/regenerate'), 'extending B11 to a Regenerate control on assistant messages is out of this phase\'s scope -- the originally-approved design never included it, and the addendum requires founder approval before adding it');
});

// --- CORRECTNESS HARDENING (2026-10-24): the original _backfillMessageIds()
// inferred BOTH message ids by re-fetching the list and grabbing "the
// last user/assistant entry" -- a real, reproduced race under
// concurrent requests on the same session (two browser tabs): a third
// request's pair persisting in the window between this request's own
// persist and the fetch resolving means "last in the list" no longer
// refers to this request's own turn. The CTO directive is explicit:
// "Do not guess message identity from text or position." Fixed by
// removing the guess entirely. ---

test('the assistant message_id is assigned directly from the real done event, never inferred by re-fetching and guessing "the last one"', () => {
  const sendSrc = extractBalancedFunction(source, 'async function sendMessage() {').text;
  assert.ok(sendSrc.includes('_assignAssistantMessageId(finalAnswerDiv, ev.message_id)'), 'must use the exact, already-known id from this specific done event -- zero fetch, zero race, zero ambiguity');
  assert.ok(!sendSrc.includes('_backfillMessageIds'), 'the position-guessing function must be fully removed, not left as dead/unused code that could be accidentally re-wired');
});

test('the user message_id is never assigned by client-side inference anywhere in this file', () => {
  assert.ok(!source.includes('.reverse().find((m) => m.role ==='), 'no code path may guess "the last message of role X" to assign an id -- this is exactly the position-based guess the directive forbids');
});

test('_assignAssistantMessageId() is a pure, synchronous assignment -- no fetch, so no window for a race to land in', () => {
  const fnSrc = extractBalancedFunction(source, 'function _assignAssistantMessageId(answerDiv, doneMessageId) {').text;
  assert.ok(!fnSrc.includes('fetch('), 'must not re-fetch anything -- the id is already known with certainty from the event that was just received');
});

test('openSession() passes the real message_id/version_count/edited fields from GET .../messages -- no backfill needed for a reloaded conversation', () => {
  const openSrc = extractBalancedFunction(source, 'async function openSession(sid, title) {').text;
  assert.ok(openSrc.includes('{ messageId: m.message_id, versionCount: m.version_count, edited: !!m.edited }'));
});

test('the edit panel visibility is controlled by a class, not a base display style that would out-specify [hidden] (the same bug class already found twice this session)', () => {
  const idx = source.indexOf('.edit-msg-panel{');
  assert.ok(idx !== -1);
  const baseRule = source.slice(idx, source.indexOf('}', idx) + 1);
  assert.ok(!baseRule.includes('display:block') && !baseRule.includes('display:flex'), 'the base .edit-msg-panel rule must not force a visible display value');
  assert.ok(source.includes('.edit-msg-panel.open{display:block}'), 'must use .open as the authoritative toggle, matching the B05/B15/B13 fix pattern');
});

// --- Behavioral tests against the real functions, with a minimal fake DOM ---

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
    dataset: {},
    textContent: '',
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
    insertAdjacentElement(pos, child) { el._children.push(child); return child; },
    querySelector(sel) {
      const dataActionMatch = sel.match(/^\[data-action="([^"]+)"\]$/);
      if (dataActionMatch) return el._children.find((c) => c._dataAction === dataActionMatch[1]) || null;
      const cls = sel.replace(/^\./, '');
      return el._children.find((c) => (c.className || '') === cls) || null;
    },
    setAttribute(k, v) { el._attrs[k] = v; },
    addEventListener(evt, fn) { el[`_on_${evt}`] = fn; },
    focus() {},
    remove() { el._removed = true; },
  };
  return el;
}

function buildSandbox(fetchImpl) {
  const container = makeFakeNode('div');
  const sandbox = {
    document: { getElementById: () => container, createElement: (tag) => makeFakeNode(tag) },
    scrollReadingToBottom: () => {},
    sessionId: 'sid-1',
    _authToken: 'tok-1',
    _authHeaders: () => ({ Authorization: 'Bearer tok-1' }),
    _handleSessionExpired: () => { sandbox._sessionExpiredCalled = true; },
    crypto: { randomUUID: () => 'fake-uuid-' + Math.random().toString(36).slice(2) },
    fetch: fetchImpl || (async () => { throw new Error('fetch should not be called in this test'); }),
  };
  return { sandbox, container };
}

function loadFns(sandbox) {
  const escSrc = extractBalancedFunction(source, 'function esc(t) {').text;
  const fnSrc = extractBalancedFunction(source, 'function appendUserMessage(text, meta) {').text;
  vm.createContext(sandbox);
  vm.runInContext(`var _userMsgCounter = 0;\n${escSrc}\n${fnSrc}`, sandbox);
}

test('appendUserMessage() wires Edit-open/Cancel-close correctly and resets to the current active text', () => {
  const { sandbox, container } = buildSandbox();
  loadFns(sandbox);
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
  assert.equal(textarea.value, 'hello world', 'must reset to the real current text on open');
});

test('a message with no known message_id (not yet backfilled) has Save genuinely disabled', () => {
  const { sandbox, container } = buildSandbox();
  loadFns(sandbox);
  sandbox.appendUserMessage('fresh message, not backfilled yet');
  const div = container._children[0];
  const saveBtn = div.querySelector('[data-action="save"]');
  assert.ok(saveBtn);
  assert.equal(saveBtn.disabled, true);
});

test('a message loaded with a real message_id (from openSession() or after backfill) has Save enabled', () => {
  const { sandbox, container } = buildSandbox();
  loadFns(sandbox);
  sandbox.appendUserMessage('reloaded message', { messageId: 'real-id-1', versionCount: 1, edited: false });
  const div = container._children[0];
  const saveBtn = div.querySelector('[data-action="save"]');
  assert.equal(saveBtn.disabled, false);
  assert.equal(div.dataset.messageId, 'real-id-1');
});

test('a successful edit updates the displayed text to the server\'s active_content and closes the panel', async () => {
  const calls = [];
  const { sandbox, container } = buildSandbox(async (url, opts) => {
    calls.push({ url, opts });
    return { ok: true, status: 200, json: async () => ({ message_id: 'real-id-1', active_content: 'the server-confirmed new text', version_count: 2 }) };
  });
  loadFns(sandbox);
  sandbox.appendUserMessage('original text', { messageId: 'real-id-1', versionCount: 1, edited: false });
  const div = container._children[0];
  const editBtn = div._children.find((c) => c.className === 'edit-msg-btn');
  const panel = div._children.find((c) => c.className === 'edit-msg-panel');
  const textarea = div._children.find((c) => c.className === 'edit-msg-textarea');
  const saveBtn = div.querySelector('[data-action="save"]');

  editBtn._on_click();
  textarea.value = 'my local draft edit';
  await saveBtn._on_click();

  assert.equal(calls.length, 1);
  assert.ok(calls[0].url.includes('/messages/real-id-1/edits'));
  const sampleQ = div._children.find((c) => c.className === 'sample-q');
  assert.equal(sampleQ.textContent, 'the server-confirmed new text', 'must display the server\'s own confirmed text, not merely the typed draft');
  assert.equal(panel.hidden, true, 'a successful save closes the panel');
});

test('a failed edit shows the real server error and leaves the draft in the textarea for retry', async () => {
  const { sandbox, container } = buildSandbox(async () => ({ ok: false, status: 400, json: async () => ({ error: 'Content is empty or too long.', code: 'message_version_rejected' }) }));
  loadFns(sandbox);
  sandbox.appendUserMessage('original text', { messageId: 'real-id-1', versionCount: 1, edited: false });
  const div = container._children[0];
  const editBtn = div._children.find((c) => c.className === 'edit-msg-btn');
  const panel = div._children.find((c) => c.className === 'edit-msg-panel');
  const textarea = div._children.find((c) => c.className === 'edit-msg-textarea');
  const errorEl = div._children.find((c) => c.className === 'edit-msg-error');
  const saveBtn = div.querySelector('[data-action="save"]');

  editBtn._on_click();
  textarea.value = 'an edit that will be rejected';
  await saveBtn._on_click();

  assert.equal(panel.hidden, false, 'a failed save must keep the panel open, not silently close it');
  assert.equal(textarea.value, 'an edit that will be rejected', 'the user\'s draft must not be lost on failure');
  assert.equal(errorEl.hidden, false);
  assert.equal(errorEl.textContent, 'Content is empty or too long.', 'must show the real server error, not a generic message');
});

test('a 401 during save routes through the real session-expiry handler', async () => {
  const { sandbox, container } = buildSandbox(async () => ({ status: 401, ok: false, json: async () => ({}) }));
  loadFns(sandbox);
  sandbox.appendUserMessage('x', { messageId: 'real-id-1', versionCount: 1, edited: false });
  const div = container._children[0];
  const editBtn = div._children.find((c) => c.className === 'edit-msg-btn');
  const saveBtn = div.querySelector('[data-action="save"]');
  editBtn._on_click();
  await saveBtn._on_click();
  assert.equal(sandbox._sessionExpiredCalled, true);
});

// --- ADVERSARIAL: two concurrent requests on the SAME session, modeling
// two browser tabs sending near-simultaneously. The real backend attack
// surface this test proves is closed: a completed request's bubble must
// receive ONLY its own, genuinely-known assistant message_id, never a
// sibling concurrent request's id -- even when their `done` events
// arrive interleaved. ---

test('ADVERSARIAL: two concurrent sendMessage()-shaped done events never cross-assign each other\'s assistant message_id', () => {
  const fnSrc = extractBalancedFunction(source, 'function _assignAssistantMessageId(answerDiv, doneMessageId) {').text;
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(fnSrc, sandbox);

  // Two independent "requests" -- each has its OWN answer div and its
  // OWN done event, arriving in whatever order a real race could produce.
  const answerDivAlpha = makeFakeNode('div');
  const doneEventAlpha = { message_id: 'assistant-id-ALPHA' };
  const answerDivBeta = makeFakeNode('div');
  const doneEventBeta = { message_id: 'assistant-id-BETA' };

  // Beta's done event arrives FIRST (it was the faster model response),
  // even though alpha's request started first -- the exact interleaving
  // that broke the old "last in the list" approach.
  sandbox._assignAssistantMessageId(answerDivBeta, doneEventBeta.message_id);
  sandbox._assignAssistantMessageId(answerDivAlpha, doneEventAlpha.message_id);

  assert.equal(answerDivAlpha.dataset.messageId, 'assistant-id-ALPHA', 'alpha\'s bubble must carry ALPHA\'s own id, never beta\'s, regardless of arrival order');
  assert.equal(answerDivBeta.dataset.messageId, 'assistant-id-BETA', 'beta\'s bubble must carry BETA\'s own id, never alpha\'s');
});

// --- CORRECTNESS HARDENING: ambiguous save outcome (a thrown network
// error during the edit POST does not prove the server never committed
// it). Reconciles via the real versions endpoint before saying anything
// definitive, and never retries (which would mint a duplicate version)
// when reconciliation already shows the edit landed. ---

test('a network error during save reconciles with the real server state before claiming failure, and reflects success if it actually landed', async () => {
  const calls = [];
  const { sandbox, container } = buildSandbox(async (url, opts) => {
    calls.push(url);
    if (opts && opts.method === 'POST') throw new TypeError('Failed to fetch'); // connection dropped
    // The reconciliation GET: the server DID commit it.
    return { ok: true, status: 200, json: async () => ({ active_content: 'the edit that actually landed', version_count: 2 }) };
  });
  loadFns(sandbox);
  sandbox.appendUserMessage('original text', { messageId: 'real-id-1', versionCount: 1, edited: false });
  const div = container._children[0];
  const editBtn = div._children.find((c) => c.className === 'edit-msg-btn');
  const panel = div._children.find((c) => c.className === 'edit-msg-panel');
  const textarea = div._children.find((c) => c.className === 'edit-msg-textarea');
  const saveBtn = div.querySelector('[data-action="save"]');

  editBtn._on_click();
  textarea.value = 'the edit that actually landed';
  await saveBtn._on_click();

  assert.equal(calls.length, 2, 'must attempt the edit, then reconcile with a real GET -- not just give up');
  assert.ok(calls[1].includes('/versions'), 'the reconciliation call must be to the real versions endpoint');
  const sampleQ = div._children.find((c) => c.className === 'sample-q');
  assert.equal(sampleQ.textContent, 'the edit that actually landed', 'once reconciliation proves it landed, the UI must reflect the real success, not a stale failure claim');
  assert.equal(panel.hidden, true, 'a reconciled success closes the panel exactly like a direct success');
});

test('a network error during save, reconciled as genuinely NOT committed, is reported honestly and allows a real retry', async () => {
  const { sandbox, container } = buildSandbox(async (url, opts) => {
    if (opts && opts.method === 'POST') throw new TypeError('Failed to fetch');
    return { ok: true, status: 200, json: async () => ({ active_content: 'original text', version_count: 1 }) }; // unchanged -- never landed
  });
  loadFns(sandbox);
  sandbox.appendUserMessage('original text', { messageId: 'real-id-1', versionCount: 1, edited: false });
  const div = container._children[0];
  const editBtn = div._children.find((c) => c.className === 'edit-msg-btn');
  const panel = div._children.find((c) => c.className === 'edit-msg-panel');
  const textarea = div._children.find((c) => c.className === 'edit-msg-textarea');
  const errorEl = div._children.find((c) => c.className === 'edit-msg-error');
  const saveBtn = div.querySelector('[data-action="save"]');

  editBtn._on_click();
  textarea.value = 'a genuinely new edit attempt';
  await saveBtn._on_click();

  assert.equal(panel.hidden, false, 'genuinely unconfirmed/failed must keep the panel open for retry');
  assert.ok(errorEl.textContent.includes('was not saved'), 'only reconciliation proving it did NOT land may say this definitively');
  assert.equal(textarea.value, 'a genuinely new edit attempt', 'the draft must survive so the user can retry without retyping');
});

test('when the reconciliation check itself also fails, the message stays genuinely uncertain -- never guesses either way', async () => {
  const { sandbox, container } = buildSandbox(async () => { throw new TypeError('Failed to fetch'); }); // both the edit POST and the reconciliation GET fail
  loadFns(sandbox);
  sandbox.appendUserMessage('original text', { messageId: 'real-id-1', versionCount: 1, edited: false });
  const div = container._children[0];
  const editBtn = div._children.find((c) => c.className === 'edit-msg-btn');
  const textarea = div._children.find((c) => c.className === 'edit-msg-textarea');
  const errorEl = div._children.find((c) => c.className === 'edit-msg-error');
  const saveBtn = div.querySelector('[data-action="save"]');

  editBtn._on_click();
  textarea.value = 'an attempt with total connection loss';
  await saveBtn._on_click();

  assert.ok(!errorEl.textContent.includes('was not saved'), 'must not claim definite failure when reconciliation itself could not be attempted');
  assert.ok(errorEl.textContent.includes('Could not confirm'), 'must honestly state the outcome is unknown');
  assert.ok(errorEl.textContent.includes('duplicate'), 'must warn that retrying now carries a real risk of creating a duplicate version, since the first attempt\'s true outcome is unknown');
});

test('ADVERSARIAL: a concurrent sibling\'s done event never overwrites a different bubble\'s already-assigned id', () => {
  const fnSrc = extractBalancedFunction(source, 'function _assignAssistantMessageId(answerDiv, doneMessageId) {').text;
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(fnSrc, sandbox);
  const answerDivAlpha = makeFakeNode('div');
  sandbox._assignAssistantMessageId(answerDivAlpha, 'assistant-id-ALPHA');
  // A sibling request's done event, if it were EVER (incorrectly) routed
  // at the SAME div, must not happen in the real code (each done handler
  // closure owns its own `finalAnswerDiv`) -- proven here by confirming
  // the function takes the div as an explicit argument, never looks one
  // up globally (e.g. "the last .answer in the DOM"), which is what
  // would make cross-assignment possible in the first place.
  assert.ok(fnSrc.includes('answerDiv.dataset.messageId = doneMessageId'));
  assert.ok(!fnSrc.includes('document.querySelector') && !fnSrc.includes('getElementById'), '_assignAssistantMessageId() must never look up its own target element -- the caller\'s own done-event closure is the only correct source of which div this id belongs to');
});
