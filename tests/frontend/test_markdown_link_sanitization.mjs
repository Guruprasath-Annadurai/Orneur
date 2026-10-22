// AUDIT-B81-P0-01 regression test. Extracts and runs the EXACT shipped
// functions (esc / _sanitizeLinkHref / mdToHtml) straight out of
// orca/serve/web/conversation.html at test time, via a brace-balanced
// source slice run in a vm context -- not a reimplementation pasted into
// this file, so there is no drift between what is tested and what ships.
// conversation.html as a whole is not require()-able (it's HTML with a
// DOM-dependent inline <script>, unlike sse_diagnostics.js), so this test
// deliberately isolates just the three pure, DOM-free functions that
// render untrusted model text to HTML.
//
// Run with: node tests/frontend/test_markdown_link_sanitization.mjs
// (Node's built-in test runner; no new dependency.)
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE_PATH = path.join(__dirname, '../../orca/serve/web/conversation.html');
const source = fs.readFileSync(SOURCE_PATH, 'utf8');

function extractBalancedFunction(src, startMarker, fromIndex) {
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
  if (depth !== 0) throw new Error(`unbalanced braces extracting ${startMarker}`);
  return { text: src.slice(start, i + 1), end: i + 1 };
}

const escFn = extractBalancedFunction(source, 'function esc(t) {', 0);
const sanitizeFn = extractBalancedFunction(source, 'function _sanitizeLinkHref(', escFn.end);
const mdToHtmlFn = extractBalancedFunction(source, 'function mdToHtml(', sanitizeFn.end);

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(`${escFn.text}\n${sanitizeFn.text}\n${mdToHtmlFn.text}`, sandbox);
const { mdToHtml } = sandbox;

test('CTO payload: javascript: link is neutralized, not rendered as a clickable anchor', () => {
  const out = mdToHtml('[Open result](javascript:alert%281%29)');
  assert.ok(!out.includes('<a '), 'must not render an anchor tag: ' + out);
  assert.ok(!out.toLowerCase().includes('javascript:'), 'scheme must not survive into output: ' + out);
  assert.ok(out.includes('Open result'), 'link text must be preserved as plain text');
});

test('data: URLs are rejected', () => {
  const out = mdToHtml('[x](data:text/html,<script>alert(1)</script>)');
  assert.ok(!out.includes('<a '));
  assert.ok(!out.toLowerCase().includes('data:text/html'));
});

test('vbscript: URLs are rejected', () => {
  const out = mdToHtml('[x](vbscript:msgbox(1))');
  assert.ok(!out.includes('<a '));
});

test('whitespace-obfuscated javascript: (tab) is rejected', () => {
  const out = mdToHtml('[x](java\tscript:alert(1))');
  assert.ok(!out.includes('<a '), 'tab-obfuscated scheme must still be rejected: ' + out);
});

test('leading-space-obfuscated javascript: is rejected', () => {
  const out = mdToHtml('[x]( javascript:alert(1))');
  assert.ok(!out.includes('<a '), out);
});

test('uppercase/mixed-case JaVaScRiPt: is rejected', () => {
  const out = mdToHtml('[x](JaVaScRiPt:alert(1))');
  assert.ok(!out.includes('<a '), out);
});

test('legitimate https:// link renders as a safe anchor with hardened rel', () => {
  const out = mdToHtml('[docs](https://example.com/path?q=1)');
  assert.ok(
    out.includes('<a href="https://example.com/path?q=1" target="_blank" rel="noopener noreferrer">docs</a>'),
    out,
  );
});

test('legitimate http:// link is preserved', () => {
  const out = mdToHtml('[x](http://example.com)');
  assert.ok(out.includes('<a href="http://example.com"'), out);
});

test('mailto: link is preserved', () => {
  const out = mdToHtml('[email me](mailto:a@example.com)');
  assert.ok(out.includes('<a href="mailto:a@example.com"'), out);
});

test('relative/anchor links with no scheme are preserved', () => {
  const out = mdToHtml('[section](#top) and [rel](./foo/bar)');
  assert.ok(out.includes('<a href="#top"'), out);
  assert.ok(out.includes('<a href="./foo/bar"'), out);
});

test('a quote character in the URL cannot break out of the href attribute', () => {
  const out = mdToHtml('[x](https://example.com/"onmouseover="alert(1))');
  assert.ok(out.includes('&quot;onmouseover=&quot;'), 'quote must be entity-encoded: ' + out);
  assert.ok(
    !/href="[^"]*"[^>]*\s+onmouseover=/.test(out),
    'attribute must not actually be broken out of: ' + out,
  );
});

test('code blocks, bold, italic, headings, and lists still render normally', () => {
  const out = mdToHtml(
    '# Title\n\nSome **bold** and *italic* text.\n\n- item one\n- item two\n\n```js\nconst x = 1;\n```',
  );
  assert.ok(out.includes('<h1>Title</h1>'));
  assert.ok(out.includes('<strong>bold</strong>'));
  assert.ok(out.includes('<em>italic</em>'));
  assert.ok(out.includes('<li>item one</li>'));
  assert.ok(out.includes('<pre><code>const x = 1;</code></pre>'));
});
