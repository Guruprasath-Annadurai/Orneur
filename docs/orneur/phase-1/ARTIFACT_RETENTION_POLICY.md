# Artifact Retention / Eviction Policy

## The incident this fixes

During Phase 0.5, two Novus-family Ollama artifacts (`orca-core:latest`, `orca-core-dpo:latest`) were deleted via a bare `ollama rm` to free local disk space for an evaluation run. This was a reasonable operational decision at the time, but it happened with **no registry record** of the deletion — the registry (which didn't exist yet) would have had no way to know the artifact was gone, why, or by whom. Phase 1 initially represented this gap with an ad-hoc checksum sentinel string (`"UNVERIFIED_ARTIFACT_REMOVED_FROM_LOCAL_DISK"`), which was honest but not a real, checked mechanism — a caller could still, in principle, try to load that path.

## What changed

### 1. Artifact availability is now a real, distinct field

`orca/registry/checkpoint.py`'s `ArtifactAvailability` enum (`LOCAL`, `REMOTE`, `MISSING`, `CORRUPT`, `ARCHIVED`) replaces the sentinel string. It is a **separate axis from `lifecycle_state`** — a checkpoint can be `RETIRED` (lifecycle) yet still `LOCAL` (availability), or `EXPERIMENTAL` yet `MISSING`. `CheckpointRecord.is_loadable()` / `is_routable()` return `True` only when availability is verified `LOCAL` — metadata existing is never conflated with the weight file being usable. Tested in `tests/test_artifact_availability.py` (8 tests), including the exact real-world case (a checkpoint with a recorded checksum but no local file must not be loadable).

### 2. Recovery, not just accurate absence-tracking

Per this phase's explicit assessment: `orca-core-dpo`'s artifact **was recovered** from its documented Kaggle merge-export kernel (`guruprasathannadurai/orca-core-dpo-merge-export-v1`, status `COMPLETE`), verified by file size (matches every other Llama-3.1-8B Q4_K_M export exactly) and direct GGUF header inspection (architecture=llama, embedding_length=4096, block_count=32, GQA 32/8 heads — the exact expected signature). It is now marked `REMOTE` (verified recoverable, not currently locally loaded) with `recovery_source` pointing at the exact kernel. See `docs/orneur/phase-1/PHASE_1_CLOSURE.md` for the full recovery writeup, including the honest caveat that no prior checksum existed to compare against.

### 3. Eviction now goes through a single, auditable gate

`orca/registry/artifact_retention.py`'s `evict_artifact()` is the only sanctioned path for evicting a checkpoint's local artifact going forward:

- **Always logs** the eviction (`checkpoint_id`, `reason`, `actor`, `timestamp`, the checksum preserved, before/after availability) to an append-only JSONL log (`ORCA_HOME/registry/eviction_log.jsonl`), auditable via `read_eviction_log()`.
- **Refuses** to evict the current `PRODUCTION` checkpoint or the current `rollback_target` for a family, unless `force=True` is explicitly passed — an escape hatch for a deliberate human decision, not a default. Tested: `tests/test_artifact_retention.py::test_eviction_refused_for_production_checkpoint`, `::test_eviction_refused_for_rollback_target`, `::test_eviction_force_overrides_protection`.
- Does **not** delete the file itself — that remains the caller's job (`ollama rm`, `os.remove`, etc.); this function is the bookkeeping gate that must wrap that action.

### What this does NOT do (by design, minimal scope)

This is not a storage platform — no automatic disk-pressure monitoring, no scheduled eviction, no remote artifact store integration. It is the smallest mechanism that prevents the specific recurrence: an eviction happening with no record, or happening to a checkpoint that shouldn't be touched. A future phase can build automated retention policy on top of this gate; this phase only ensures the gate exists and is enforced when used.

## Going forward

Any future disk-pressure cleanup of a registered checkpoint's Ollama artifact **must** call `evict_artifact()` first (or accept the `EvictionRefused` if it's protected). This is a process discipline this document establishes, not something Python can force onto a bare `ollama rm` typed directly into a shell — the registry can only be as accurate as the discipline of routing artifact removal through it.
