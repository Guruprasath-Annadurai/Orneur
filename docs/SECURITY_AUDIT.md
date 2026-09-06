<!--
Real dependency vulnerability scan (pip-audit), run 2026-07-24, with an
honest exploitability assessment against Orca's ACTUAL usage of each
flagged package — not just a raw scanner dump. A CVE that doesn't apply to
how a package is actually used is a different risk than one that does;
conflating them either causes false alarm or false confidence.
-->

# Dependency Security Audit

## Method

`pip-audit` run against the project's `.venv` on 2026-07-24. This checks
installed packages against the PyPI Advisory Database (PYSEC) — it does not
scan Orca's own code for vulnerabilities (see `docs/SECURITY_AUDIT.md`'s
sibling work — an OWASP-style code review — as a separate, not-yet-done
item).

## Findings, closed

10 known vulnerabilities were found across `pip` and `setuptools` (build
tooling, not Orca's runtime dependencies) — all had patched versions
available and have been upgraded:
- `pip` 24.0 → 26.1.2 (closes PYSEC-2026-196, -1795, -1796, -2875, -2876)
- `setuptools` 79.0.1 → patched (closes PYSEC-2026-3447)

## Findings, real but assessed as not currently exploitable in Orca's deployment

### chromadb — PYSEC-2026-311 / CVE-2026-45829, CVSS 10.0 (maximum severity)

A genuine, serious, currently-unpatched pre-authentication remote-code-
execution vulnerability, affecting all chromadb versions since 1.0.0. The
vulnerability specifically targets chromadb's standalone **FastAPI server
mode** (`chroma run`) — an attacker-controlled model identifier gets
executed before any authentication check runs.

**Why this does not currently threaten Orca**: `orca/brain/memory.py` uses
`chromadb.PersistentClient(...)` — the embedded, local, file-backed client.
This never starts an HTTP server and never opens a network port. There is
no unauthenticated network surface for the vulnerability to reach.

**The real constraint this creates, going forward**: Orca must never run
chromadb in its server mode (`chroma run` / `HttpClient`). If a future
change introduces multi-machine or networked vector-store access, this CVE
becomes immediately live and must be re-assessed before shipping — do not
add server-mode chromadb without checking whether this CVE has a patch by
then.

### diskcache — PYSEC-2026-2447 / CVE-2025-69872, high severity

A real deserialization-of-untrusted-data vulnerability (unsafe `pickle.load`
in `diskcache.Cache`) — no patched version exists yet. Exploitable only if
an attacker already has write access to the cache directory.

**Why this is low practical severity for Orca today**: both usages
(`orca/brain/memory.py`'s semantic cache, `orca/lens/queue.py`'s job queue)
are local, single-machine file caches under `~/.orca/...`, never exposed to
network input, and never written to based on untrusted remote data.
Exploiting this would require the attacker to already have local
filesystem write access to that user's home directory — at which point the
machine has a more fundamental compromise than this CVE represents.

**The real constraint this creates**: never let untrusted network input
write directly into a diskcache-backed directory, and never expose a
diskcache directory to another user/process boundary without re-assessing
this CVE.

## Still pending (not done in this audit)

- A code-level security review (OWASP Top 10 style — injection, auth,
  SSRF, etc.) of Orca's own code, as opposed to this dependency-only scan.
- Secrets-handling audit (confirm no API keys have ever hit git history —
  the `.env`-only pattern is followed by convention, not yet verified by
  a real history scan with a tool like `gitleaks` or `trufflehog`).
- Re-running this scan on a recurring basis (e.g., in CI) rather than as a
  one-time manual check — `pip-audit` should probably become a CI job.

## Separate observation (not a security issue, noted here for record-keeping)

During eval investigation, core produced a response containing text
resembling its own persona system prompt ("You are Orca — a powerful,
thoughtful AI assistant...") to a plain technical question, with NO system
prompt sent at all (confirmed: `orca/train/eval.py`'s golden-eval calls
never pass a `system` argument). This suggests the persona/system prompt
text was present as literal content within some fine-tuning training
examples rather than kept strictly separate as system-role-only content,
and the model partially memorized and now occasionally reproduces
fragments of it unprompted. Not a security concern, but a real training-
data hygiene issue worth fixing in a future training data curation pass —
not attempted here given scope.

---

## Code-level OWASP-style review (2026-07-24) — real findings, fixed and unfixed

This is the code review flagged as "still pending" above — now done, covering
the highest-risk categories: SQL injection, path traversal, command
injection, SSRF.

### FIXED — arbitrary code execution in `run_python` (orca/tools/code.py)

**The most severe finding of this review.** `run_python()` had ZERO
restriction: it executed arbitrary Python with the real interpreter and
the real OS user's full permissions — no AST checks, no import
restrictions, nothing. This directly contradicted what the earlier design
docs assumed existed. Combined with the model's known jailbreak
susceptibility (0% block rate at the model level), this was a complete,
practical attack chain: a jailbroken model could call this tool to read
secrets, spawn processes, or reach the network.

**Fix**: added `_check_code_safety()`, an AST-based denylist blocking
dangerous imports (`os`, `subprocess`, `socket`, `ctypes`, etc.) and
dangerous builtins (`eval`, `exec`, `open`, `__import__`). Also stripped
the subprocess's environment variables as defense in depth, so even a
bypass of the AST check finds no secrets in `os.environ`.

**Honest scope**: this is a denylist, not a hardened sandbox. A
sufficiently obfuscated payload (reconstructing a blocked name via string
concatenation + `getattr`, for example) can still bypass a static check —
tested and documented explicitly in `tests/test_code_sandbox_safety.py`'s
`test_KNOWN_LIMITATION_*` test. A real sandbox (container/microVM) is the
correct long-term fix and is out of scope for this pass.

### FIXED — arbitrary file read/write in `_read_file`/`_write_file` (orca/tools/__init__.py)

Both tools previously accepted ANY absolute path on the filesystem with
zero restriction — `read_file` could exfiltrate `~/.ssh/id_rsa`, `~/.env`,
`~/.orca/auth.db`; `write_file` could overwrite anything the OS user has
permission to touch. Combined with jailbreak susceptibility, a real,
severe, exploitable gap.

**Fix**: both tools now resolve every path against a dedicated
`WORKSPACE_DIR` and reject anything that would escape it — via `..`
traversal, an absolute path elsewhere, or symlink resolution — verified
in `tests/test_tools_file_sandbox.py` against the actual exploit shapes
(`/etc/passwd`, `~/.ssh/id_rsa`, `../../../etc/passwd`).

### FIXED (preventively) — SSRF in `fetch_page` (orca/tools/web.py)

`fetch_page(url)` accepted any URL with zero validation — a classic SSRF
vector (internal services, cloud metadata endpoints like
`169.254.169.254`). Confirmed this function is currently **unreachable
from any tool-calling surface** (nothing in the codebase calls it) — not
currently exploitable, but a live risk the moment someone wires it up.

**Fix**: added `_is_ssrf_risk()`, resolving the hostname and rejecting
private/loopback/link-local/reserved/multicast addresses and non-http(s)
schemes, fail-closed on resolution failure.

**Honest residual gap**: `follow_redirects=True` means a malicious server
could still redirect to an internal address *after* the pre-request check
passes (a TOCTOU-style bypass) — httpx doesn't cheaply expose per-hop
redirect inspection. Acceptable only because this function is currently
dead code; must be closed (disable auto-redirect, check each hop) before
this is ever wired up as a callable tool.

### FIXED — command injection surface in `run_shell` (orca/tools/code.py)

Previously used `subprocess.run(command, shell=True, ...)` with only a
6-item substring denylist (`rm -rf`, `dd if=`, `mkfs`, a fork bomb pattern,
`shutdown`, `reboot`, `sudo rm`) — genuinely weak: it blocked a handful of
destructive patterns but did nothing to prevent arbitrary command
execution otherwise. Unlike `fetch_page`'s SSRF gap (confirmed dead code),
this tool **was** live and reachable via the agent's `shell` tool — the
single most important remaining item from the original review.

**Fix, two structural changes, not just a bigger denylist**:
1. `shell=False` with `shlex`-parsed arguments — shell metacharacters
   (`;`, `&&`, `|`, backticks, `$()`, redirection) are no longer
   interpreted at all, since there is no shell present to interpret them.
   This eliminates command-chaining/injection as a whole category.
2. The command itself (first token) must be in a fixed allowlist of
   safe, mostly-read-only utilities (`ls`, `cat`, `pwd`, `echo`, `grep`,
   `find`, `wc`, `head`, `tail`, `diff`, `du`, `df`, `whoami`, `date`,
   `uname`, `which`, `env`, `git`) — anything else is refused outright.
   Deliberately excludes every general-purpose code interpreter (python,
   node, npm, bash, sh, zsh, perl, etc.) — allowing any of those would
   let a caller bypass `run_python()`'s AST safety check entirely via
   e.g. `python3 -c "os.system(...)"` through this path instead.

Verified against the actual exploit shapes with real (unmocked) subprocess
execution in `tests/test_run_shell_sandbox.py`: command chaining via `;`
and `&&`, piping to a disallowed command, direct invocation of `curl`/
`python3`/`bash`/`node`, and the environment-stripping defense-in-depth —
all 16 tests pass against real process execution, not simulated behavior.

**Honest residual scope, not fixed**:
- Path restriction is NOT part of this fix — `cat`/`find`/`head`/`tail`/
  `git` can still read any file the OS user can read (e.g.
  `cat ~/.ssh/id_rsa` still succeeds), unlike the workspace-sandboxed
  `read_file` tool. A future pass restricting these commands' path
  arguments to the same sandbox is the natural next step.
- An allowed command can still be misused within its own capability
  (e.g. `git`'s many subcommands) — the destructive-pattern substring
  check remains as defense in depth for this, unchanged from before.
- Real, deliberate usability trade-off: pipelines (`ls | grep x`) no
  longer work at all, since there's no shell to interpret the pipe — the
  direct, necessary cost of eliminating shell-metacharacter injection.

### CLEARED — not a real vulnerability

- `orca/auth/migrate_to_postgres.py`'s f-string SQL construction
  (`f"SELECT {', '.join(columns)} FROM {table}"`) looked like classic SQL
  injection at first glance, but every call site passes hardcoded string
  literals (`"users"`, `"audit_log"`, etc.) — no user input reaches it.
  Not exploitable; a one-time, developer-run migration script.
- The rest of `orca/auth/db.py`'s query layer uses parameterized queries
  (`?`/`%s` placeholders) throughout — no other injection points found.

### Still not done (scope of this pass)

- Fixing `run_shell` properly (see above — the top remaining item).
- Full OWASP Top 10 coverage (auth/session handling, XSS in any
  HTML-rendering surface, CSRF) — this pass focused on injection/traversal/
  SSRF given the tool-use surface's direct exposure to a jailbreak-
  susceptible model; auth/session/XSS/CSRF review is separate, real,
  not-yet-done work.
