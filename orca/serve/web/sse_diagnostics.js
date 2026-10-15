/**
 * Pure, dependency-free SSE malformed-event diagnostics. No DOM access, no
 * closure over page state -- this is the exact file the browser loads AND
 * the exact file the Node regression test in tests/frontend/ imports, so
 * there is no reimplementation drift between what ships and what is tested.
 *
 * DEF-CP1-03 hardening (post-Checkpoint-2-audit finding): a malformed SSE
 * event was previously diagnosed with a truncated EXCERPT of the raw SSE
 * line written to the browser console. That line can carry a user's own
 * message content, or -- since it is server-controlled/attacker-reachable
 * text that failed to parse as JSON -- arbitrary other content with no
 * guarantee of being safe to display. Console output is not a trusted
 * boundary (browser extensions, shared screens, saved HAR/console exports,
 * crash-reporting integrations that scrape console output all read it), so
 * it gets the same treatment as a server log line (see
 * orca/serve/errors.py's DEF-CP1-02 allowlist-over-denylist rationale):
 * metadata only, never the payload. "Metadata" here is an auto-incrementing
 * ordinal and the parse error's name (e.g. "SyntaxError") -- enough to see
 * in devtools that something is wrong and how many times, nothing that
 * could echo message content back out.
 */
(function (global) {
  'use strict';

  var MALFORMED_LOG_CAP = 5;

  function createMalformedEventLogger(warn) {
    warn = warn || (typeof console !== 'undefined' ? console.warn.bind(console) : function () {});
    var count = 0;
    return function logMalformedEvent(err) {
      count += 1;
      if (count > MALFORMED_LOG_CAP) return count;
      var errorName = (err && err.name) || 'Error';
      warn('[stream] could not parse SSE event #' + count + ' (' + errorName + ')');
      if (count === MALFORMED_LOG_CAP) {
        warn('[stream] suppressing further malformed-event warnings for this response (cap=' + MALFORMED_LOG_CAP + ')');
      }
      return count;
    };
  }

  global.ORNEUR_SSE_DIAGNOSTICS = { createMalformedEventLogger: createMalformedEventLogger, MALFORMED_LOG_CAP: MALFORMED_LOG_CAP };
})(typeof window !== 'undefined' ? window : globalThis);
