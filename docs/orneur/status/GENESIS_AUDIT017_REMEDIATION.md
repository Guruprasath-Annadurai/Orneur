# GENESIS Foundation — Audit #017 Remediation

Status date: 2026-10-16. Implementation branch: `claude/genesis-sprint2-2026-10-15`
(PR #58 — the originally audited branch, remediated in place, per the same
practice Audit #016 remediation established: fix on the authorized
implementation branch, never on the independent auditor's own branch).

Audited target SHA (the vulnerable commit): `368f7d9acb3de1cffd8996cba98149c160904926`.
Audit report: `docs/orneur/status/INDEPENDENT_GENESIS_SPRINT2_AUDIT_017.md`,
delivered via PR #59 (`antigravity/audit017-genesis-sprint2`,
`732cd04302d4933749842174ff5e55b165ce30dc`). PR #59 itself was not touched —
remediation lives entirely on this branch.

## Independent reproduction before any fix

Per this programme's standing discipline (never trust a prior report's own
narrower test coverage without reproducing against the real code path): the
audit's own adversarial test file
(`tests/test_audit017_adversarial_reproductions.py` on `antigravity/audit017-genesis-sprint2`)
was copied onto this branch and run, unmodified, against the still-vulnerable
code. **All 6 defects (7 test functions) reproduced cleanly** — every
assertion that documents a flaw (e.g. `# Vulnerability: succeeded without
version validation`) passed, confirming the audit's findings were real before
any remediation began. That scratch copy was deleted immediately after
reproduction; it was never meant to be the permanent regression suite (its
assertions describe broken behavior, which would become false once fixed).

## Defect-by-defect remediation

### DEFECT-01 (High) — Checkpoint manifest symlink/file race

`save_verified_training_state()`'s manifest write used a deterministic
temporary filename (`f".{manifest_path.name}.tmp"`) opened via
`Path.write_text()` (`O_CREAT|O_TRUNC`, no `O_EXCL`/`O_NOFOLLOW`) — a
pre-planted symlink at that exact path caused the write to follow it and
overwrite an arbitrary target. This reintroduced the exact vulnerability
class Audit #016 DEFECT-02 already fixed in `save_training_state()` itself,
just in the new, additive manifest-write path that didn't reuse that fix.

**Fix**: reused the identical `tempfile.mkstemp()` (random, `O_EXCL`-created
name) + `os.fdopen` + `f.flush()` + `os.fsync(f.fileno())` + `tmp.chmod(0o600)`
+ `os.replace()` discipline Sprint 1 / Audit #016 established, with cleanup on
any exception. A pre-planted symlink at the *old* predictable path is now
simply never touched (there is nothing left at that name to touch).

Also addressed in this fix (identified while reading section 4.1 of the
report, not covered by the audit's own dedicated test, but a real finding):
the **non-atomicity window** between `save_training_state()`'s internal lock
release and the manifest write — two concurrent `save_verified_training_state()`
callers targeting the same path could interleave (checkpoint A's bytes hashed
into manifest B, or vice versa). Fixed by holding a new, outer
`.{name}.verified.lock` exclusive lock across the entire
save+hash+manifest-write sequence, scoped to this module's own operation
(distinct from, and layered on top of, `save_training_state()`'s own internal
lock — neither lock's scope was narrowed).

Tests: `test_defect01_preexisting_symlink_at_the_old_predictable_manifest_tmp_path_is_not_followed`,
`test_defect01_manifest_has_owner_only_permissions_and_no_symlink_at_final_path`,
`test_concurrent_verified_saves_to_the_same_path_never_produce_a_mismatched_manifest`
(5 real threads, asserts the final on-disk (checkpoint, manifest) pair is
always internally self-consistent and loads cleanly, regardless of which
writer's result ends up on disk).

### DEFECT-02 (Medium) — Manifest format/version enforcement

`load_verified_training_state()` parsed `manifest.format_version` and
`manifest.architecture_version` but never checked them against what the code
actually understands — an incompatible or future format loaded silently.

**Fix**: both fields are now checked against `CHECKPOINT_FORMAT_VERSION` and
`ARCHITECTURE_VERSION` respectively, immediately after parsing the manifest
and *before* the checksum/deserialization steps, raising the new
`UnsupportedManifestVersionError` on any mismatch.

Tests: `test_defect02_unsupported_format_version_is_rejected`,
`test_defect02_unsupported_architecture_version_is_rejected`.

### DEFECT-03 (Medium) — Checkpoint state consistency

A manifest's `step`/`epoch` fields were recorded but never compared against
the actually-deserialized `TrainingState`'s own `step`/`epoch` — a manifest
edited to claim a different step/epoch than its accompanying checkpoint
loaded without any indication of the inconsistency.

**Fix**: after `load_training_state()` returns, `state.step`/`state.epoch`
are compared against `manifest.step`/`manifest.epoch`, raising the new
`ManifestStateMismatchError` on any disagreement. This check deliberately
runs *after* deserialization (it needs the real deserialized state to compare
against) — the format/architecture version check above still runs *before*
deserialization, so an unsupported format is rejected without ever attempting
to deserialize it.

Test: `test_defect03_manifest_step_or_epoch_mismatch_against_real_state_is_rejected`.

### DEFECT-04 (Medium) — Fake checkpoint provenance

`diagnose_adapter()` flipped `is_randomly_initialized` to `False` for ANY
caller-supplied `checkpoint_source` string, including a fabricated,
nonexistent path — a fresh random model could be reported as trained with
zero verification.

**Fix**: `checkpoint_source`, when provided, must now name a file that
actually exists on disk; `FileNotFoundError` is raised otherwise. This is
documented explicitly as a **bounded** fix, not a complete provenance
guarantee: file existence alone does not prove `model`'s weights were
actually loaded from that file (a stronger binding would require threading a
verified checkpoint identity from `load_verified_training_state()` through to
this call — a larger change deliberately out of this remediation's scope).
What it closes is the specific reproduced exploit: an arbitrary, non-existent
string spoofing trained status.

Test: `test_diagnose_adapter_rejects_a_nonexistent_checkpoint_source`
(`test_diagnose_adapter_reports_a_real_checkpoint_source_when_one_is_given`
was also updated to use a real on-disk file, since it would now correctly
fail against the fabricated path it previously used).

### DEFECT-05 (Low) — Memory accounting inaccuracies

`estimate_training_memory()` omitted the vocabulary-logits tensor
(`(batch_size, seq_len, vocab_size)` in fp32, computed before cross-entropy
loss) entirely — for the `10M-smoke` tier at `batch_size=4, seq_len=4096`,
this tensor alone (~4.2 GB) is roughly 37x the entire activation estimate the
function previously produced (~113 MB).

**Fix**: added a new `logits_estimate` field to `MemoryEstimate`
(`batch_size * seq_len * vocab_size * BYTES_PER_PARAM_FP32`), included in
`total`, reported separately rather than folded silently into
`activations_estimate` so a caller can see exactly how much of the total this
one tensor accounts for. The audit's quadratic-attention-scaling point
(`(B, H, S, S)` attention weights under non-FlashAttention backends) is
flagged as a **known, unaddressed limitation** in this remediation — the
existing linear activation formula remains valid only under
FlashAttention/recomputation-style attention backends, which this module does
not itself verify or enforce; expanding the model further to also account for
quadratic attention memory under the `attn_backend="manual"` path was judged
out of this bounded remediation's scope and is carried forward as a residual
risk.

Tests: `test_logits_memory_is_tracked_separately_and_included_in_total`,
`test_logits_memory_can_dominate_at_large_vocab_and_long_sequences`
(reproduces the audit's own 30x+ finding directly as an assertion).
`test_memory_estimate_components_sum_to_total` (pre-existing) was updated to
include the new field in its sum.

### DEFECT-06 (Low) — Evaluation and RNG correctness

Three distinct flaws in `make_inference_backend()`'s generated backend:

1. **Stop token retention**: when generation stopped due to a configured
   `sampling.stop` string, that string remained in the returned `text`.
   **Fix**: `_strip_stop_sequences()` truncates `text` at the earliest
   occurrence of any configured stop string before returning.
2. **Silent empty completion on context overflow**: a prompt tokenizing to
   `>= max_seq_len` tokens returned `text="", error=None` — indistinguishable
   from a genuine zero-token successful completion. **Fix**: this case is now
   detected before the generation loop starts and returns a real, descriptive
   `error`.
3. **Global RNG mutation**: `torch.manual_seed(sampling.seed)` permanently
   mutated the process-wide RNG for every subsequent caller in the process,
   not just this one backend invocation. **Fix**: seeding now happens inside
   a `torch.random.fork_rng()` scope, which saves the RNG state on entry and
   restores it on exit.

Tests: `test_backend_strips_stop_sequence_from_the_returned_text`,
`test_backend_reports_a_real_error_not_a_silent_empty_success_on_context_overflow`,
`test_backend_does_not_permanently_mutate_global_rng_state` (asserts
`torch.get_rng_state()` is bit-identical before and after a seeded backend
call). `test_backend_reports_errors_through_the_result_not_by_raising`
(pre-existing) was strengthened to assert the now-guaranteed error/empty-text
behavior rather than merely `isinstance(result, GenerationResult)`.

## Regression evidence

Full local run (`/Users/ag/orca/.venv`, Python 3.11.15, torch 2.13.0,
sentencepiece 0.2.2):

```
tests/test_genesis_eval_adapter.py ........................... 12 passed
tests/test_genesis_scaling.py .............................. 13 passed
tests/test_genesis_checkpoint_integrity.py ................. 16 passed
tests/test_genesis_model_architecture.py ... (Sprint 1, unchanged)
tests/test_genesis_training_primitives.py ... (Sprint 1, unchanged)
tests/test_genesis_tokenizer.py ... (Sprint 1, unchanged)
tests/test_genesis_audit016_remediation.py ... (Audit #016, unchanged)
tests/test_genesis_eval_v1.py ................................ 150 passed

== 214 passed in 28.66s ==
```

No pre-existing test was weakened, skipped, or deleted to make this pass;
three pre-existing tests (`test_memory_estimate_components_sum_to_total`,
`test_interrupted_manifest_write_leaves_old_manifest_intact`,
`test_backend_reports_errors_through_the_result_not_by_raising`,
`test_diagnose_adapter_reports_a_real_checkpoint_source_when_one_is_given`)
were updated because the remediation changed the exact mechanism they were
asserting against (a new field, a different tmp-file mechanism, a now-real
error, a now-required real file) — each change is narrated above under its
corresponding defect.

A search across `orca/` and `tests/` confirmed no other module imports
`checkpoint_integrity`, `eval_adapter`, or `scaling` — the change surface is
fully contained to the three modified modules and their own tests.

CI run on this exact commit: **pending** at the time of writing — not yet
pushed/observed; will be updated with the real run link once pushed, per this
session's standing practice of never asserting unobserved CI results.

## Governance

No training, GPU provisioning, spend, or external corpus ingestion occurred.
Acceptance ledger unchanged at 0/95. `R65`/`G1`/`AUTH-1` remain
`NOT_VERIFIABLE`. Native-model training remains `NOT_AUTHORIZED`. No merge to
`main` performed or requested.

## Verdict

**`AUDIT017_REMEDIATION_READY_FOR_INDEPENDENT_RETEST`**

All 6 reported defects (DEFECT-01 through DEFECT-06) have documented
dispositions above, each independently reproduced against the real
vulnerable code before being fixed, each with a persistent regression test,
and the full existing Genesis test suite (214 tests) passes without
modification to any assertion's underlying claim. This is a self-report, not
an independent acceptance — only Antigravity's own retest can award that.
