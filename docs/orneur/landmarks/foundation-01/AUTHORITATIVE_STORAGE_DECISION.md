# Authoritative Storage Decision — FOUNDATION LANDMARK-01

**Status:** `VERIFIED_ENGINEERING` (Cursor engineering proof). Not independent Antigravity qualification.  
**Decision date:** 28 October 2026 (Asia/Calcutta)  
**Selected candidate:** PR #130 architecture — SQLite fencing epochs (`497073d` lineage)  
**Rejected candidate:** PR #131 — SQLite-authoritative commits with Redis lease callback (`040d694`)

## Comparison against independently reproduced failures

| Failure | PR #130 (selected) | PR #131 (rejected for sole authority) |
|---|---|---|
| Stale worker writing after lease expiry | Fence token + **epoch** stored in SQLite `session_authority`; `commit_turn` re-validates fence/epoch/expiry/ownership inside the same SQLite transaction as the insert | Optional `authority_check` callback (Redis `lease_held`) runs inside `BEGIN IMMEDIATE`, but fencing state lives in Redis, not the durable txn |
| Phantom JSONL turns after failed SQLite txn | JSONL rebuilt only after COMMIT; export failure leaves SQLite authoritative | Same intent; JSONL export after commit |
| Uncommitted turns in subsequent prompts | `transcript()` / prompt assembly read SQLite turns only | Same intent via `committed_messages` / SQLite-only reads |

## Why #130

1. **Transactional fencing.** Epoch and fence live in the same SQLite database as `conversation_turns`. A Redis ticket alone cannot authorize a stale write.
2. **CTO constraint.** “Do not confuse Redis ownership verification with a transactionally durable fencing guarantee.”
3. **Single transaction engine.** Redis remains advisory (lease/cache). SQLite owns commit authority.
4. **Compatibility.** Message-edit overlays (`message_versions`) bind via `user_message_id` / `message_id` in turn meta; JSONL is derived export only.

## Why not #131 as sole engine

#131 is a strong SQLite-authoritative design with green exact-head CI and excellent regression packaging. It was not selected as the long-term authority model because its commit-time fence is a Redis callback. Under Redis outage it fails closed (safe), but under Redis/SQLite skew it cannot provide the same epoch fencing as an in-database authority row. Combining #130 epochs with #131’s Redis callback would create **two transaction engines** — explicitly forbidden.

Useful #131 artefacts (tests, handoff docs, reconcile helpers) may be referenced; they do not redefine authority.

## Contract (selected)

1. Acquire Redis advisory lease (optional coordination) **and** SQLite `acquire_authority` (epoch bump on takeover).
2. Generate under the held fence/epoch.
3. `commit_turn(..., fence_token, epoch)` validates authority inside `BEGIN IMMEDIATE`, inserts the turn, advances `committed_revision`, COMMIT.
4. Derived JSONL export runs **after** COMMIT. Failure → SQLite remains SoT; reconcile repairs export.
5. Prompt context, API transcript, search, and export read SQLite (with message-version overlay). Never uncommitted JSONL.
6. Legacy JSONL import only via explicit `reconcile_legacy_session` / migration — never auto-trusted into prompts.

## Failure assumptions

- Redis down: advisory lease/CAS cache unavailable; SQLite authority still governs commits when callers use `acquire_authority`.
- Process crash mid-generation: no turn inserted; successor acquires new epoch.
- Process crash after SQLite COMMIT before export: turn durable; export reconciled later.
- Stale worker resume: `stale_authority` / `authority_expired` — no insert.

## Label

`VERIFIED_ENGINEERING` — proven by Cursor unit/integration tests on this branch. **Not** Antigravity-qualified. Gate G13 remains open.
