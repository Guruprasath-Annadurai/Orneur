// DEF-CP1-03 hardening regression test. Imports the EXACT shipped file --
// orca/serve/web/sse_diagnostics.js, served to the browser at
// /static/sse_diagnostics.js -- not a reimplementation, so there is no
// drift between what is tested and what ships.
//
// Run with: node tests/frontend/test_sse_diagnostics.mjs
// (Node's built-in test runner; no new dependency. Not wired into the
// Python-based CI pipeline -- see the PR description for why that's an
// explicit, disclosed limitation rather than a silent gap.)
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
// A classic (non-module) script: loading it with require() runs its
// top-level code once, in its own module scope, but it explicitly attaches
// its API to `globalThis` (see the file) -- which really is the one
// process-wide global object, so this reaches it from here too.
require('../../orca/serve/web/sse_diagnostics.js');
const { createMalformedEventLogger, MALFORMED_LOG_CAP } = globalThis.ORNEUR_SSE_DIAGNOSTICS;

function capture() {
  const lines = [];
  const warn = (...args) => lines.push(args.join(' '));
  return { lines, warn };
}

test('a confidential payload fragment never appears in diagnostic output, even on repeated malformed events', () => {
  const CONFIDENTIAL = 'sk-super-secret-token-ACME-CORP-DO-NOT-LOG-5f3a9c2e';
  const { lines, warn } = capture();
  const logMalformedEvent = createMalformedEventLogger(warn);

  // Simulate a stream of malformed SSE lines that each embed the
  // confidential fragment (e.g. a backend echoing a user's own message
  // text, or an attacker-controlled line, inside something that failed to
  // parse as JSON) -- more than the cap, and with several different parse
  // error shapes.
  const malformedPayloads = [
    `data: {not json, secret="${CONFIDENTIAL}"`,
    `data: ${CONFIDENTIAL}`,
    `data: {"unterminated": "${CONFIDENTIAL}`,
    `data: <xml>${CONFIDENTIAL}</xml>`,
  ];
  for (let i = 0; i < 20; i++) {
    const payload = malformedPayloads[i % malformedPayloads.length];
    try {
      JSON.parse(payload.slice('data: '.length));
      assert.fail('fixture payload unexpectedly parsed as valid JSON');
    } catch (err) {
      logMalformedEvent(err);
    }
  }

  const allOutput = lines.join('\n');
  assert.ok(!allOutput.includes(CONFIDENTIAL), 'confidential fragment leaked into diagnostic output');
  assert.ok(!allOutput.includes('secret='), 'even the key name context leaked');
  assert.ok(!allOutput.toLowerCase().includes('acme'), 'an unrelated identifier embedded in the payload leaked');
});

test('logging is bounded to MALFORMED_LOG_CAP regardless of how many malformed events occur', () => {
  const { lines, warn } = capture();
  const logMalformedEvent = createMalformedEventLogger(warn);
  for (let i = 0; i < 50; i++) logMalformedEvent(new SyntaxError('Unexpected token'));
  // cap warnings + exactly one "suppressing further..." notice
  assert.equal(lines.length, MALFORMED_LOG_CAP + 1);
});

test('diagnostic still identifies the parse-error kind, for debuggability without content', () => {
  const { lines, warn } = capture();
  const logMalformedEvent = createMalformedEventLogger(warn);
  logMalformedEvent(new SyntaxError('boom'));
  assert.match(lines[0], /SyntaxError/);
  assert.match(lines[0], /#1/);
});

test('a missing/undefined error is handled without throwing and without leaking anything', () => {
  const { lines, warn } = capture();
  const logMalformedEvent = createMalformedEventLogger(warn);
  assert.doesNotThrow(() => logMalformedEvent(undefined));
  assert.match(lines[0], /\(Error\)/);
});

test('each logger instance has its own independent counter (one per SSE response)', () => {
  const a = createMalformedEventLogger(() => {});
  const b = createMalformedEventLogger(() => {});
  for (let i = 0; i < MALFORMED_LOG_CAP; i++) a(new Error('x'));
  assert.equal(a(new Error('x')), MALFORMED_LOG_CAP + 1); // a is now suppressing
  assert.equal(b(new Error('x')), 1); // b is unaffected
});
