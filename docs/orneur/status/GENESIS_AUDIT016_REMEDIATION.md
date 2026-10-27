# GENESIS Foundation — Audit #016 Remediation

Status date: 2026-10-15. Implementation branch:
`claude/genesis-foundation-sprint1-2026-10-15` (the authorized PR #55
branch — no new branch created, per instruction). Audit #56 branch
(`antigravity/audit016-genesis-foundation`) not touched.

Audited implementation SHA at time of audit: `1c204d758e8b3f7acb67761603e4af6a2a9629b5`.
Audit report SHA: `fadafeb27178c7b99af91151c9ed3927ea9d5ea7`.

## Phase 1 — Independent verification, not trust

Per the explicit instruction not to misrepresent PR #56's own 4
reproduction tests as complete coverage (its DEFECT-01 test demonstrates
`weights_only=True` rejecting a payload, not exploitation through the
real `load_training_state()` call): **every one of the 5 defects was
independently reproduced against the real vulnerable code path before
being fixed**, not assumed from the audit's description:

- **DEFECT-01**: crafted a `__reduce__`-based payload, saved it via real
  `torch.save`, and called the actual, then-still-vulnerable
  `load_training_state()` directly. Confirmed a harmless marker file
  (never anything destructive) was created by the payload DURING that
  call — genuine code execution through the real function, not a
  standalone `torch.load` check.
- **DEFECT-02**: pre-planted a symlink at the exact old, predictable
  `.tmp` path pointing at a separate "sensitive" file, then called the
  real `save_training_state()`. Confirmed the sensitive file's content
  was overwritten, and confirmed the resulting checkpoint file's mode
  was the ambient `0o644`, not a restrictive mode.
- **DEFECT-03**: called `causal_lm_loss` with every label `-100`.
  Confirmed it returned `tensor(nan)`.
- **DEFECT-04**: called `cosine_warmup_lr(-2, ...)`. Confirmed it
  returned `-0.0001`, a negative learning rate.
- **DEFECT-05**: called `causal_lm_loss` with `seq_len=1`. Confirmed it
  returned `tensor(nan)`.

All five reproduced cleanly, confirming the audit's findings are real
(not overstated) before any fix was written.

## Phase 2 — Checkpoint deserialization (DEFECT-01)

`load_training_state()`: `torch.load(path, weights_only=False)` →
`torch.load(path, weights_only=True)`. Re-ran the exact exploit
reproduction above after the fix: the payload's `__reduce__` method no
longer executes; `torch.load` raises immediately with an unpickling
error naming the rejected global. Confirmed legitimate checkpoints still
load correctly: all 18 pre-existing `test_genesis_training_primitives.py`
tests pass unchanged, including the full round-trip and RNG-restoration
tests, proving `TrainingState`'s real content (ints, tuples, raw bytes,
and PyTorch tensor dicts) is fully representable under the restricted
loader — no general-purpose allowlisting of arbitrary classes was added
or needed. Trust/provenance verification remains explicitly the caller's
responsibility via the existing `orca.registry.provenance` module
(documented in the function's own docstring) — `weights_only=True`
closes the code-execution path, it does not by itself establish that a
checkpoint's content is the one a caller expects.

## Phase 3 — Checkpoint filesystem safety (DEFECT-02)

`save_training_state()` rewritten:

- **Tempfile collision**: `tempfile.mkstemp(dir=parent, ...)` gives every
  call a randomly-named file, eliminating the deterministic-name
  collision and, because the name cannot be predicted in advance,
  structurally closing the symlink-planting attack rather than detecting
  and rejecting it after the fact.
- **Permissions**: parent directory created via this codebase's existing,
  already-tested `_mkdir_owner_only` (`orca/config.py`) — reused, not
  reinvented, per instruction — giving `0o700`. The checkpoint file
  itself is `chmod`'d to `0o600` before the atomic rename.
- **Concurrent-writer policy**: an explicit **exclusive-writer policy**
  via `fcntl.flock` on a sibling `.lock` file, held for the full
  write+fsync+rename sequence. Two concurrent callers targeting the same
  path are serialized — the second caller's entire save waits for the
  first to complete. Tested with real overlapping threads (not
  sequential calls): 5 concurrent writers, zero exceptions, and the
  resulting file is always a single, fully loadable checkpoint
  afterward, never a corrupted interleaving.
- **Durability**: `os.fsync()` on the temp file before close, and on the
  parent directory's own file descriptor after the rename — the standard
  "fsync the directory too" rule, so the rename survives a crash
  immediately after `os.replace()` returns.
- **Symlink safety**: re-verified directly post-fix — a symlink
  pre-planted at the OLD predictable path is simply never touched
  (the new random tmp name never collides with it), and the sensitive
  file it points to is confirmed byte-identical to its original content
  afterward.

## Phase 4 — Numerical loss behavior (DEFECT-03, DEFECT-05)

Both fixed in `causal_lm_loss`, both **fail-closed by explicit design
decision**, documented in the function's own docstring:

- **Fully-ignored batch** (DEFECT-03): raises, rather than the audit's
  suggested alternative of a differentiable `torch.tensor(0.0,
  requires_grad=True)`. Decision, stated plainly: a fully-masked batch
  reaching this function at all usually indicates an upstream
  data-pipeline defect, and silently reporting "loss: 0.0" would look,
  in any training log or loss-averaging code, exactly like a genuine
  successful zero-loss step — precisely the "silently turning an invalid
  batch into successful progress" the remediation directive itself warns
  against. A real training loop that legitimately expects occasional
  fully-masked batches should filter them explicitly, with its own
  logging, before calling this primitive.
- **Sequence length < 2** (DEFECT-05): raises — a sequence of length 1
  has no next-token pair to predict at all, so there is no loss to
  compute, not a degenerate zero.

Tested: valid batches, partially-ignored batches (some but not all
positions masked — must still compute a normal finite loss, confirming
the fix isn't overly broad), fully-ignored batches (must raise),
`seq_len=1` (must raise), `seq_len=2` (the minimum valid case, must
compute a finite loss). All verified against the mathematical reference
(`F.cross_entropy` on an explicitly-shifted tensor pair) as before.

## Phase 5 — Learning-rate schedule validation (DEFECT-04)

`cosine_warmup_lr`: `step < 0` now raises. Indexing defined precisely in
the function's own docstring (zero-based: `step=0` is the first training
step, not a sentinel; `step=warmup_steps-1` is the last warmup step and
returns exactly `max_lr`; `step >= total_steps` clamps to `min_lr` rather
than raising, since running past the planned schedule length is a
normal, recoverable condition, unlike a negative step, which can never
correspond to a real training-step count). Also added: `max_lr`/`min_lr`
non-negativity and `min_lr <= max_lr` validation, found while writing
this fix's own tests, not part of the original 5-defect list but the
same class of missing input validation. Tested: initialization (`step=0`
not rejected), the warmup/decay transition point, the terminal step,
out-of-range steps (clamped, not rejected), and the negative-step
rejection itself.

## Phase 6 — Regression and integration evidence

| Suite | Result |
|---|---|
| New Audit #016 regression tests (`tests/test_genesis_audit016_remediation.py`) | **15/15 passed** |
| Existing 63 GENESIS tests + 15 new (103 combined with the pre-existing `torch-loss-tests` job's own 88) | **103/103 passed** |
| Training-authorization sentinel, run in its required isolation | **13/13 passed** |
| Canonical full deterministic suite | **8919 passed / 11 failed / 294 skipped / 43 deselected / 7 xfailed** (0:48:28) |
| Exact-SHA GitHub Actions CI (`ecfb91b`), two independent trigger runs | **9/9 jobs green on both runs** ([run 38751175506](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38751175506), [run 38751179493](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38751179493)) — `Deterministic Unit Tests` 16m29s/14m24s, `Training Math Unit Tests (Torch)` (runs the 5 new regression tests) 52s/47s |

10 of the 11 canonical-suite failures match the exact, already-documented
baseline (7 RSE macOS `RLIMIT_AS`, 1 `@requires_docker` environment
dependency, 1 container PID-namespace teardown, 1 52-actor concurrency
test — all previously root-caused as macOS/Docker/load-sensitive, none
caused by this codebase's changes).

**The 11th failure** (`tests/test_godmode_authority_postgres.py::test_postgres_backend_tenant_isolation_no_cross_tenant_leak`)
is new to this run and was investigated with real rigor, not dismissed
on first pass:
- Zero file overlap with this remediation's changes (confirmed via
  `git diff --name-only`; its only dependencies are `orca.godmode.lease_store`
  and a Postgres backend, neither touched here).
- Reran in isolation: 3/3 passed, with widely varying durations
  (13s/6.5s/66s).
- **Directed follow-up, correctly identifying that isolated reruns alone
  don't exclude a regression**: ran the same test under genuine
  concurrent load (simultaneously with another real, known
  load-sensitive multiprocessing test) on this exact commit. The
  postgres test passed (8.24s) even while the concurrent test failed as
  expected — meaning ordinary CPU contention does NOT reproduce this
  specific failure, so a quick concurrent-load comparison against the
  pre-remediation baseline would not have been a genuinely comparable
  test either.
- The original failure most likely depended on accumulated state from
  the many OTHER tests in `test_godmode_authority_postgres.py` (and
  whatever local Postgres fixture they share) that ran earlier within
  that same 48-minute, single pytest process — a condition only a full
  baseline rerun could genuinely reproduce, at roughly another 48
  minutes of cost.
- **Classification: retained as unresolved**, per this directive's own
  explicit fallback ("compare against the exact baseline under
  comparable conditions, or retain the failure as unresolved"), rather
  than asserted as excluded on the strength of reproduction attempts
  that did not recreate the original condition. Not folded into the
  already-explained baseline; tracked separately.

CI workflow updated: `tests/test_genesis_audit016_remediation.py` added
to the existing `torch-loss-tests` job (same job, same reasoning as the
other GENESIS test files — it imports `torch`, which the main
deterministic job deliberately does not install).

## Phase 7 — Handoff

- Implementation branch: `claude/genesis-foundation-sprint1-2026-10-15`
  (the authorized PR #55 branch — fixes committed directly here, no new
  branch, per instruction).
- Antigravity's audit branch/PR (#56) was not read-write touched by this
  remediation; only read (to retrieve the audit report and its own test
  file's content for Phase 1 verification).
- Original audit record preserved: `docs/orneur/status/INDEPENDENT_GENESIS_FOUNDATION_AUDIT_016.md`
  is PR #56's own file, in PR #56, untouched by this remediation.
- Affected files this remediation: `orca/genesis/training/primitives.py`
  (all 5 fixes), `tests/test_genesis_audit016_remediation.py` (new, 15
  tests), `.github/workflows/test.yml` (CI wiring for the new file).

## Residual risks, stated plainly

- The exclusive-writer lock is a correctness mechanism for THIS
  primitive's own save/load contract — it is not a distributed-training
  coordination protocol, and no claim is made that it would be
  sufficient for a multi-node training job's checkpoint strategy without
  further design work (out of scope for this remediation).
- `load_training_state()` still performs no provenance/trust
  verification of its own; a syntactically-valid-but-wrong checkpoint
  (not malicious, just not the one a caller intended) is not detected by
  this function — that remains the caller's responsibility via
  `orca.registry.provenance`, as documented.
- `R65`, `G1`, `AUTH-1` remain `NOT_VERIFIABLE`; the acceptance ledger
  remains at 0 entries. Nothing in this remediation advances any
  acceptance count or authorizes training.
- **`test_godmode_authority_postgres.py::test_postgres_backend_tenant_isolation_no_cross_tenant_leak`
  is an unresolved, unrelated finding, not a residual risk of this
  remediation's own changes.** Zero file overlap with anything this PR
  touches. Not excluded with full confidence, because the specific
  reproduction attempts made (isolated reruns, concurrent-load-with-
  another-test) did not recreate the original failure condition — a
  genuinely comparable-conditions check would require a second full
  canonical-suite run on the pre-remediation baseline (~48 minutes),
  not performed here. Recommend either accepting this as a known,
  pre-existing, state-dependent flake in that test file, or scheduling
  the full-suite baseline comparison as a dedicated follow-up — not
  something to resolve silently inside this PR.

## Required re-audit instructions

Antigravity should re-audit at the exact SHA this remediation lands at
(given in the PR, not predicted here) and independently confirm each of
the 5 defects is fixed by re-running its OWN reproduction tests from
`tests/test_audit016_adversarial_reproductions.py` against the corrected
code, plus reviewing the new `tests/test_genesis_audit016_remediation.py`
for completeness. A Claude-run test pass is explicitly not sufficient by
itself, per the remediation directive.

## Final verdict

**`REMEDIATION_READY_FOR_INDEPENDENT_RETEST`**

`GENESIS_SPRINT1_ACCEPTED_VERIFIED` is NOT claimed here — that status is
explicitly reserved for Antigravity to grant upon independently
confirming the corrected SHA, per the remediation directive's own
instruction.
