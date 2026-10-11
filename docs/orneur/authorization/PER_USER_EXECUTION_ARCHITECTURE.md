# Per-user isolated execution — DESIGN PROPOSAL (NOT IMPLEMENTED, NOT ACTIVATED)

Status: **PROPOSAL.** Nothing in this document is built or enabled. It exists so that re-enabling `shell`, `read_file`, `write_file`
and code execution for web users (disabled by G-020) has a reviewed target, instead of a flag.

## Why the current design cannot be made safe by patching
* The tools run **in the server process's OS identity**: the same user that owns `auth.db`, the signing secret (`/proc/self/environ`),
  every tenant's memory/doc stores and the model weights.
* The "workspace" is one shared directory. A shared directory with a path check is a *namespace convention*, not a tenant boundary:
  symlink races, `git`/`find` flags, and content written by user A and read by user B all cross it.
* The Python "sandbox" (`orca/code/sandbox.py`) is an AST deny-list in the server's environment; allowing `pathlib` was enough to read
  `/proc/self/environ` (reproduced: `docs/orneur/status/g020/BEFORE_original.txt`).

## Required properties before any web tool is re-enabled
1. **Identity**: every execution request carries `(tenant_id, user_id, session_id, request_id)` derived from the verified token, never from model output.
2. **Isolation unit**: one disposable sandbox per *(user, session)* — container with `--network=none`, read-only root, non-root UID, seccomp +
   dropped capabilities, `pids/memory/cpu/time` limits, no inherited environment, no mounts of server paths. gVisor/Firecracker preferred over a shared kernel.
3. **Storage**: a per-user volume mounted only into that user's sandbox, quota-limited, deleted with the account (extends `account_delete`).
4. **No ambient secrets**: the sandbox receives no environment variables and no credentials; outbound network off by default, allow-list egress only per tool.
5. **Authority is separate from model text**: a signed, short-lived *tool grant* (`tool`, `user_id`, `session_id`, `expires`, `max_calls`) issued by the
   server after policy evaluation (`orca.agent.policy`); the sandbox verifies it. Prompt text can request a tool, it can never mint a grant.
6. **Audit**: every call is hash-chain logged (as the training gate does): who, which tool, arguments digest, result digest, exit status.
7. **Kill switch + quotas**: per-user/tenant call budgets; a global off switch that fails closed.
8. **Independent review** of the sandbox and a **red-team suite** (escape, symlink, `/proc`, fork bomb, egress, cross-user read) as a release gate.

## Staged plan (each stage needs founder approval; none is started)
| Stage | Scope | Gate |
|---|---|---|
| X0 | This document + threat model review | independent review |
| X1 | Sandbox runner behind an internal interface, exercised only by tests | red-team suite green in CI |
| X2 | Single-tenant (founder) staging use | audit, founder sign-off |
| X3 | Opt-in per user/tier for read-only tools | audit #2, quota + kill switch verified |
| X4 | Write/exec tools | separate audit |

## What stays true until then
`SERVER_AUTHORITY_TOOLS` (`orca/tools/__init__.py`) are never registered on the web surface; `/api/code/run` returns `403 capability_disabled`.
There is **no environment variable** that re-enables them. The local CLI/TUI keeps its tools (single operator, own machine).
