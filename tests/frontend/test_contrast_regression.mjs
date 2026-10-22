// AUDIT-B81-A-P1-02 regression test. Parses the real CSS custom
// properties and selector rules straight out of
// orca/serve/web/conversation.html (no hand-copied color values) and
// computes WCAG 2.2 relative-luminance contrast ratios for the actual
// foreground/background pairs each affected element renders with, in
// both themes. This is a reproduction-AND-remediation test: it fails on
// the pre-fix values (.autherr dark 3.84:1, .recents-empty 3.52:1,
// .interrupted-badge ~3.7-4.2:1) and passes on the corrected ones.
//
// Run with: node tests/frontend/test_contrast_regression.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE_PATH = path.join(__dirname, '../../orca/serve/web/conversation.html');
const source = fs.readFileSync(SOURCE_PATH, 'utf8');

function parseVarBlock(selectorRegex) {
  const m = source.match(selectorRegex);
  if (!m) throw new Error(`block not found: ${selectorRegex}`);
  const vars = {};
  for (const decl of m[1].split(';')) {
    const mm = decl.match(/--([a-zA-Z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{3,8}|rgba?\([^)]*\))/);
    if (mm) vars[mm[1]] = mm[2];
  }
  return vars;
}

const rootVars = parseVarBlock(/:root\{([^}]+)\}/);
const darkVars = parseVarBlock(/body\.dark\{([^}]+)\}/);

function resolve(value, vars) {
  const m = value.match(/^var\(--([a-zA-Z0-9-]+)\)$/);
  if (m) return vars[m[1]];
  return value;
}

function extractDeclaration(selector, property) {
  const re = new RegExp(selector.replace(/[.[\]]/g, '\\$&') + '\\{([^}]+)\\}');
  const m = source.match(re);
  if (!m) throw new Error(`selector not found: ${selector}`);
  const propRe = new RegExp(`(?:^|;)${property}\\s*:\\s*([^;]+)`);
  const pm = m[1].match(propRe);
  if (!pm) throw new Error(`property ${property} not found on ${selector}`);
  return pm[1].trim();
}

function hexToRgb(hex) {
  let h = hex.replace('#', '');
  if (h.length === 3) h = [...h].map((c) => c + c).join('');
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function relLum([r, g, b]) {
  const chan = (c) => {
    c /= 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b);
}

function contrast(hex1, hex2) {
  const l1 = relLum(hexToRgb(hex1));
  const l2 = relLum(hexToRgb(hex2));
  const [lighter, darker] = l1 > l2 ? [l1, l2] : [l2, l1];
  return (lighter + 0.05) / (darker + 0.05);
}

function colorFor(selector, property, vars) {
  const raw = extractDeclaration(selector, property);
  const resolved = resolve(raw, vars);
  if (!resolved) throw new Error(`could not resolve ${raw} for ${selector}.${property}`);
  return resolved;
}

const AA_NORMAL_TEXT = 4.5;

test('.autherr meets WCAG AA in light theme (Meridian)', () => {
  const fg = colorFor('.autherr', 'color', rootVars);
  const bg = rootVars['compose'];
  const ratio = contrast(fg, bg);
  assert.ok(ratio >= AA_NORMAL_TEXT, `.autherr light: ${ratio.toFixed(2)}:1, need >= 4.5:1 (fg ${fg} on bg ${bg})`);
});

test('.autherr meets WCAG AA in dark theme (Obsidian) -- the real finding', () => {
  const fg = colorFor('.autherr', 'color', darkVars);
  const bg = darkVars['compose'];
  const ratio = contrast(fg, bg);
  assert.ok(ratio >= AA_NORMAL_TEXT, `.autherr dark: ${ratio.toFixed(2)}:1, need >= 4.5:1 (fg ${fg} on bg ${bg})`);
});

test('.recents-empty meets WCAG AA against the sidebar background in both themes', () => {
  // .sidebar's own background is var(--rail), which differs slightly
  // between themes (#121212 light-mode default vs #101010 in body.dark)
  // even though the sidebar is visually "always dark".
  const fg = extractDeclaration('.recents-empty', 'color');
  for (const [label, vars] of [['light', rootVars], ['dark', darkVars]]) {
    const bg = vars['rail'];
    const ratio = contrast(fg, bg);
    assert.ok(ratio >= AA_NORMAL_TEXT, `.recents-empty ${label}: ${ratio.toFixed(2)}:1, need >= 4.5:1 (fg ${fg} on bg ${bg})`);
  }
});

test('.interrupted-badge text meets WCAG AA against --chip in both themes', () => {
  for (const [label, vars] of [['light', rootVars], ['dark', darkVars]]) {
    const fg = colorFor('.interrupted-badge', 'color', vars);
    const bg = vars['chip'];
    const ratio = contrast(fg, bg);
    assert.ok(ratio >= AA_NORMAL_TEXT, `.interrupted-badge ${label}: ${ratio.toFixed(2)}:1, need >= 4.5:1 (fg ${fg} on bg ${bg})`);
  }
});

test('brand tokens were not globally recolored (Solar Coral / Slate Indigo untouched)', () => {
  assert.equal(rootVars['coral'], '#FF6B57');
  assert.equal(rootVars['accent'], '#3A4B6B');
});

// AUDIT-B81-A-P2-02 -- prefers-reduced-motion coverage.
test('the pulsing thinking-indicator animation is disabled under prefers-reduced-motion: reduce', () => {
  const m = source.match(/@media \(prefers-reduced-motion: reduce\) \{\s*\.dot-pulse\{animation:none/);
  assert.ok(m, 'expected a prefers-reduced-motion block disabling .dot-pulse\'s animation');
});

test('the mobile sidebar slide transition is disabled under reduced motion, and wins the cascade', () => {
  const mobileBlockIdx = source.indexOf('@media (max-width:900px){');
  const reducedMotionSidebarIdx = source.indexOf('@media (max-width:900px) and (prefers-reduced-motion: reduce)');
  assert.ok(mobileBlockIdx !== -1 && reducedMotionSidebarIdx !== -1, 'both rules must be present');
  // Equal-specificity selectors: the LATER one in source order wins the
  // cascade, so the reduced-motion override must come after the base
  // mobile rule that sets transition:transform .2s ease, not before it.
  assert.ok(
    reducedMotionSidebarIdx > mobileBlockIdx,
    'the reduced-motion .sidebar override must appear AFTER the base mobile .sidebar rule in source order, or it will be overridden by it',
  );
  const reducedBlock = source.slice(reducedMotionSidebarIdx, reducedMotionSidebarIdx + 200);
  assert.ok(reducedBlock.includes('.sidebar{transition:none}'), reducedBlock);
});
