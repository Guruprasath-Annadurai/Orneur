# Orneur Phase 0 — Memory & Agent/Reasoning Status

Verified by direct code audit.

## Memory — real 4-layer engine, blurred taxonomy vs. the Orneur "Memory Continuum" concept

`MemoryEngine` (`orca/brain/memory.py:195-269`) composes:
- **Short-term**: in-process sliding window.
- **Long-term**: ChromaDB vector store per session, JSONL-keyword fallback — genuine vector similarity search, not a stub.
- **Episodic**: structured JSON session logs.
- **Semantic**: a `diskcache`-backed key/value store of LLM-distilled facts (`distill_and_save` asks the LLM to extract goals/decisions/preferences into a summary) — "semantic" here means LLM-summarized facts, not a formal semantic/entity graph.

A separate `KnowledgeGraph` class does real entity/relationship extraction, run as fire-and-forget background enrichment per turn — a genuinely distinct entity-memory mechanism, but (per `TRUTH_RAG_STATUS.md`) **not fused back into RAG retrieval**.

**Absent, not relabeled**: no procedural memory (skills/how-to), no dedicated "failure memory" construct under any name. If Orneur's "Memory Continuum" concept requires these as distinct primitives, they are net-new work, not a renaming of something that already exists.

**Consolidation/decay**: none. `SemanticMemory.store_fact` just appends/overwrites by key with a crude 4000-char truncation cap — not a decay algorithm.

**Deletion/provenance — genuinely real, this is a strength to preserve**: `account_delete.py`'s `delete_account()` walks every session ID for a user and deletes episodic-memory files, DocStore chunks, and KnowledgeGraph entities per session — real cross-store cleanup, not just an account-row delete. Two honestly-documented gaps: audit-log entries are deliberately NOT deleted (tamper-evident hash chain, by design), and anonymous/pre-login sessions with no `user_id` link can't be cascade-deleted. `orca/auth/privacy.py` adds real append-only consent tracking and a GDPR export-request queue (records the request; doesn't itself generate the export file).

**Persistence**: SQLite by default, Postgres for multi-instance (`ORCA_DATABASE_URL`) with RLS policies defined but explicitly documented in the code itself as "not wired into every call site yet" — an honest, real caveat, not overclaimed. Session continuity (cross-restart/cross-instance conversation state) is Redis-backed, opt-in, fails open if Redis is down.

## Agent/reasoning orchestration

`AgentLoop` (`orca/brain/agent.py`) is **not an iterative ReAct loop** — it's a single fixed pipeline: Plan (1 LLM call, falls back to `{"action": "direct"}` on JSON parse failure, no retry) → Act (`for call in calls[:MAX_TOOL_ROUNDS]`, hard slice-capped at 6, no retry-on-failure, each tool result truncated to 3000 chars) → Respond → optional single Reflect pass (only if response exceeds a 150-word threshold, does not loop back into itself). History growth is explicitly bounded (`_compress_history_if_needed`, replacing a documented prior unbounded-growth bug). **No unbounded tool-call or retry loop exists anywhere in this path** — bounded by construction, not by a runtime guard that could be defeated.

## Multi-agent ("ultra"/"god-mode") — real, not a bigger prompt

`orca/variants/ultra.py`: a planner LLM decomposes a goal into up to 6 sub-tasks, each tagged with a distinct role (researcher/coder/analyst/writer/critic/architect) backed by a genuinely distinct system prompt per role. A dependency-graph scheduler bounds iterations by `len(remaining) + 2` (not `while True`) and breaks cleanly if no task becomes ready (defends against a cyclic `depends_on` graph). Ready tasks run in true parallel via `asyncio.gather`, each with its own fresh `AgentLoop` instance. A separate grading LLM call scores output 0–100, and a bounded recursive self-heal retries with `max_retries=2` (hard cap of 3 total attempts, strictly decrementing — confirmed no unbounded recursion path).

**"God-mode" is a naming choice, not a security bypass** — confirmed by grep: every occurrence is a docstring/marketing label for the CLI variant's full feature set. No authorization-bypass logic is tied to the name anywhere in the codebase.

## Tools / MCP — sandboxing mostly holds, one new gap found

- `run_python`: AST denylist blocking dangerous imports/builtins, stripped subprocess env, 30s timeout — real, with an honestly-documented known limitation (string-concat+getattr can bypass the AST check; this is stated in the code's own comments and covered by a test named for the limitation).
- `read_file`/`write_file`: workspace-sandboxed via `.relative_to()` path resolution (correctly rejects `..` traversal, absolute-path escapes, and symlink escapes) — the right implementation pattern.
- `fetch_page` SSRF guard: real hostname/IP-range check exists, but is **dead code** — no caller anywhere in the codebase invokes it.
- `run_shell`: `shell=False` + `shlex.split()` + a fixed command allowlist — no command injection, but **no path restriction**: an allowlisted command like `cat` can still read `~/.ssh/id_rsa` through this tool, unlike the workspace-sandboxed `read_file`. This is a documented, currently-live gap (already known, not new).
- **New finding, not previously documented**: `orca/mcp/fs_server.py`'s `_safe_path()` uses `str(path).startswith(str(allowed_root))` rather than proper path resolution — a classic prefix-confusion bug (e.g. a sibling directory like `~/projects-evil/secret` would pass a check meant to restrict to `~/projects`). This is a separate code path from the properly-hardened `orca/tools/__init__.py` sandbox and should be fixed with the same `.relative_to()` pattern already used there. Severity/reachability not fully assessed — flagged for `SECURITY_BASELINE.md` and Phase 1 follow-up.

## Enterprise connectors / FDE layer

**Confirmed entirely absent.** No GitHub/Slack/Google Drive/Notion/email/calendar connector integrations exist anywhere in the codebase. The only "Slack"/"GitHub" string matches are regex *detection* patterns in the secret-scanner tool (looking for token *shapes* in scanned content, not connecting to those services) or incidental doc/comment text. This is genuinely net-new work for Orneur's planned FDE/Enterprise Integration Layer — there is nothing to migrate or rename here.
