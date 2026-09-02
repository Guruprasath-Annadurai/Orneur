# Memory Firewall (Phase 5)

`orca/memory/firewall.py`. No recalled memory reaches `CognitiveContext`
without passing through `check()` or `filter_recall()` first (spec §36)
— `CognitiveKernel._recall_memory_and_enrich()` is the one call site
that injects memory into a prompt, and it always goes through
`filter_recall()` first (see [ARCHITECTURE.md](ARCHITECTURE.md)).

## Check order

1. **Scope** — `record.scope_id` must match the requester's, unless the
   record is `GLOBAL`-scoped (the one deliberate cross-scope exception).
   This is the mechanism behind the "memory from one tenant/user/project
   must not bleed into another" rule (spec §6).
2. **Privacy clearance** — `PrivacyClass` rank comparison
   (STANDARD < SENSITIVE < RESTRICTED); a requester below the record's
   privacy rank is blocked outright.
3. **Epistemic state** — `DISPROVEN` is blocked unconditionally,
   regardless of relevance score.
4. **Staleness** — flagged (`FirewallVerdict.is_stale`), not blocked:
   blocking would make it impossible for a stale-but-relevant memory to
   ever trigger the Truth Fabric refresh flow described in
   [MEMORY_EVIDENCE_LEDGER.md](MEMORY_EVIDENCE_LEDGER.md). The recalled
   text is still tagged "may be stale, verify if load-bearing" when
   injected into the objective (`orca/cognitive/kernel.py::
   _recall_memory_and_enrich`).
5. **Prompt injection / safety** — reuses
   `orca.truth.fetch.sanitize_extracted_text()`'s pattern scan (spec
   §12's "don't rerun an unrelated second verifier" principle applied to
   security scanning: one proven pattern list, not a second parallel
   one). Flagged content is **excluded entirely**, never cleaned in
   place and used anyway — same posture as Truth Fabric's own fetch
   sanitization.

## Every rejection carries a reason, never the rejected content

`FirewallVerdict.reasons` is a list of short labels
(`"scope_mismatch"`, `"disproven"`, `"prompt_injection_pattern_matched"`,
etc.) — safe to log/trace. The rejected record's own claim text is never
included in the verdict object passed back to a caller that might trace
it (spec §45's "safe structured memory metadata" requirement extended to
firewall decisions).

## Tested attack surface (spec §40, §56)

`tests/test_memory_security.py` and
`tests/test_memory_retrieval_consolidation_firewall.py` cover: cross-user
leak, cross-project leak, memory-ID guessing across scopes, deleted-memory
resurrection attempts, scope-manipulation via a forged/path-like
`scope_id` string, prompt-injected memory content, and a
large-memory-volume bounded-latency check. All fail safely (verdict:
not allowed / empty recall), none raise or silently succeed.
